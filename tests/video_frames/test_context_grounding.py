"""Synthetic object-only tests. No native/provider execution or byte attestation."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import unittest
from unittest.mock import patch

from reproloop.video_frames import FrameObservation, validate_temporal_ocr_candidate_labels

MEDIA = 'a'*64
OPS = ('select_target', 'open_rename', 'choose_preset', 'cancel_edit')
TIMES = (0, 731, 1804, 2900, 4107)


def region(text, bounds=None, confidence=0.9):
    return dict(text=text, confidence=confidence, bounds=bounds or [90, 90, 130, 130])


def sample(target='Fresh title', preset='Later', after='arbitrary faulty after-state'):
    frames = []
    # The target and Rename intentionally share a stationary native marker.
    labels = ('Target task: '+target, 'Rename', preset, 'Cancel', after)
    for index, label in enumerate(labels):
        digest = sha256(str(index).encode()).hexdigest()
        marker = {'red_marker_candidate': dict(center=[100, 100], bounds=[99, 99, 101, 101],
                                                source_png_sha256=digest)}
        frames.append(FrameObservation(TIMES[index], digest, 720, 1280, MEDIA,
            'data:image/png;base64,SYNTHETIC', marker, 'CANDIDATE',
            (region(label),), ocr_observer='macOS Vision'))
    actions = tuple(dict(operation=op, timestamp_ms=stamp) for op, stamp in zip(OPS, TIMES[1:]))
    return actions, tuple(frames)


class ContextGroundingTests(unittest.TestCase):
    def setUp(self):
        self.actions, self.frames = sample()

    def validate(self, actions=None, frames=None, target='Fresh title', preset='Later'):
        return validate_temporal_ocr_candidate_labels(target, preset,
            self.actions if actions is None else actions, self.frames if frames is None else frames)

    def altered(self, index, **changes):
        frames = list(self.frames)
        frames[index] = replace(frames[index], **changes)
        return tuple(frames)

    def test_four_stationary_context_brackets_nonuniform_actual_times(self):
        result = self.validate()
        self.assertEqual(result['type'], 'SAMPLED_PRIOR_OCR_POINT_SCENE_AGREEMENT_V4')
        self.assertEqual(result['matched_labels'], 4)
        self.assertIs(result['attestation'], False)
        self.assertEqual(result['source_media_sha256'], MEDIA)
        self.assertTrue(result['assumptions'])
        self.assertTrue(result['limits'])
        for index, match in enumerate(result['matches']):
            self.assertEqual(match['operation'], OPS[index])
            self.assertEqual(match['before_timestamp_ms'], TIMES[index])
            self.assertEqual(match['after_timestamp_ms'], TIMES[index+1])
            self.assertEqual(match['before_png_sha256'], self.frames[index].png_sha256)
            self.assertEqual(match['after_png_sha256'], self.frames[index+1].png_sha256)
            self.assertEqual(match['pointer_center'], [100, 100])
            self.assertIs(match['stationary_or_small_move'], True)

    def test_model_labels_and_faulty_or_fixed_after_states_not_oracle(self):
        for after in ('Target task: Fresh title', 'Target task: Later', 'Unrelated result'):
            actions, frames = sample(after=after)
            self.assertEqual(self.validate(actions, frames)['matched_labels'], 4)
        actions, frames = sample('Different title', 'Evening')
        self.assertEqual(self.validate(actions, frames, 'Different title', 'Evening')['matched_labels'], 4)

    def test_whitespace_casefold_and_identical_duplicate_regions(self):
        regions = (region('TARGET   TASK: fresh TITLE'), region('Target task: Fresh title'))
        result = self.validate(frames=self.altered(0, ocr_regions=regions))
        self.assertEqual(result['matches'][0]['normalized_label'], 'target task: fresh title')

    def test_extra_non_event_samples_are_not_counted_as_operations(self):
        extra = replace(self.frames[0], timestamp_ms=200)
        frames = self.frames[:1]+(extra,)+self.frames[1:]
        result = self.validate(frames=frames)
        self.assertEqual(result['matched_labels'], 4)
        self.assertEqual(result['matches'][0]['before_timestamp_ms'], 200)

    def test_partial_frame_coverage_fails_closed(self):
        for frames in (self.frames[:1], self.frames[:4], self.frames[1:]):
            with self.assertRaises(ValueError): self.validate(frames=frames)

    def test_immediately_adjacent_sample_not_previous_action(self):
        extra = replace(self.frames[1], timestamp_ms=1000, ocr_regions=(region('Not Rename'),))
        with self.assertRaises(ValueError):
            self.validate(frames=self.frames[:2]+(extra,)+self.frames[2:])

    def test_absent_previous_point_is_null_and_small_move_boundary(self):
        result = self.validate(frames=self.altered(0, pointer_candidate=None, pointer_status='ABSENT'))
        self.assertIsNone(result['matches'][0]['stationary_or_small_move'])
        for offset, expected in ((3, True), (4, False)):
            marker = deepcopy(self.frames[0].pointer_candidate)
            marker['red_marker_candidate'].update(center=[100+offset, 100], bounds=[100+offset,100,100+offset,100])
            self.assertIs(self.validate(frames=self.altered(0, pointer_candidate=marker))['matches'][0]['stationary_or_small_move'], expected)

    def test_unchanged_scene_and_overlay_only_jitter_rejected(self):
        for overlay in (False, True):
            frames = list(self.frames)
            for index in (0, 1):
                regions = self.frames[0].ocr_regions
                if overlay:
                    regions += (region('header '+str(index), [0, 0, 100, 32]),)
                frames[index] = replace(frames[index], ocr_regions=regions)
            with self.assertRaises(ValueError): self.validate(frames=tuple(frames))

    def test_low_confidence_changes_do_not_count_but_crossing_overlay_does(self):
        unchanged = self.frames[0].ocr_regions+(region('noise', confidence=0.69),)
        with self.assertRaises(ValueError): self.validate(frames=self.altered(1, ocr_regions=unchanged))
        crossing = self.frames[0].ocr_regions+(region('visible', [0, 31, 30, 33]),)
        # Only the generic first bracket matters here; later label still Rename.
        frames = list(self.frames)
        frames[0] = replace(frames[0], ocr_regions=frames[0].ocr_regions+crossing[-1:])
        self.assertEqual(self.validate(frames=tuple(frames))['matched_labels'], 4)

    def test_distinct_overlap_no_nearest_and_half_open_edges(self):
        for regions in ((region('Target task: Fresh title'), region('Other task: Errands')),
                        (region('Target task: Fresh title', [0, 90, 100, 130]),),
                        (region('Target task: Fresh title', [90, 0, 130, 100]),),
                        (region('Target task: Fresh title', [101, 90, 130, 130]),),
                        (region('Target task: Fresh title', confidence=0.699),)):
            with self.subTest(regions=regions), self.assertRaises(ValueError):
                self.validate(frames=self.altered(0, ocr_regions=regions))
        self.validate(frames=self.altered(0, ocr_regions=(region('Target task: Fresh title', [100,100,130,130],0.7),)))

    def test_absent_ambiguous_and_unrequested_current_point(self):
        for status in ('ABSENT', 'AMBIGUOUS', 'NOT_REQUESTED'):
            with self.assertRaises(ValueError):
                self.validate(frames=self.altered(1, pointer_candidate=None, pointer_status=status))

    def test_malformed_pointer_bounds_center_and_source(self):
        bad_markers = [None, {}, {'extra': 1}]
        base = self.frames[1].pointer_candidate['red_marker_candidate']
        for key, value in (('center', [True,100]), ('center', [100.0,100]), ('center', [720,100]),
                           ('bounds', [99,99,103.0,101]), ('bounds', [99,99,104,101]),
                           ('bounds', [100,31,100,31]), ('bounds', [101,99,102,101]),
                           ('source_png_sha256', 'b'*64), ('source_png_sha256', 'A'*64)):
            bad_markers.append({'red_marker_candidate': dict(base, **{key: value})})
        for marker in bad_markers:
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                self.validate(frames=self.altered(1, pointer_candidate=marker))
        with self.assertRaises(ValueError): self.validate(frames=self.altered(1, pointer_status='AMBIGUOUS'))

    def test_nonexact_fractional_bool_reordered_action_times(self):
        for bad in (0, 732, 731.0, True, -1, float('nan'), 45001):
            actions = deepcopy(self.actions)
            actions[0]['timestamp_ms'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.validate(actions=actions)
        actions = deepcopy(self.actions)
        actions[1]['timestamp_ms'] = 731
        with self.assertRaises(ValueError): self.validate(actions=actions)

    def test_missing_extra_wrong_operations_and_shapes(self):
        for actions in (self.actions[:3], self.actions+self.actions[-1:], list(self.actions), (None,)*4):
            with self.assertRaises(ValueError): self.validate(actions=actions)
        for index, operation in ((0,'open_rename'), (3,'Save'), (3,'cancel_rename'), (3,True)):
            actions = deepcopy(self.actions)
            actions[index]['operation'] = operation
            with self.assertRaises(ValueError): self.validate(actions=actions)
        actions = deepcopy(self.actions)
        actions[0]['expectedAfter'] = 'forbidden'
        with self.assertRaises(ValueError): self.validate(actions=actions)

    def test_frame_media_dimensions_hash_chronology_and_types(self):
        for changes in (dict(source_media_sha256='b'*64), dict(source_media_sha256='Z'*64),
                        dict(png_sha256='a'*63), dict(width=720.0), dict(height=True),
                        dict(width=1280,height=720), dict(timestamp_ms=True),
                        dict(timestamp_ms=731.0), dict(timestamp_ms=0), dict(timestamp_ms=45001),
                        dict(ocr_observer=None)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate(frames=self.altered(1, **changes))
        for frames in ((), list(self.frames), self.frames*4, (object(),), self.frames[::-1]):
            with self.assertRaises(ValueError): self.validate(frames=frames)

    def test_ocr_shape_confidence_text_and_geometry(self):
        for bad in (region('', confidence=0.9), region('x'*257), region('x\n'),
                    region('x', confidence=True), region('x', confidence=float('nan')),
                    region('x', confidence=float('inf')), region('x', confidence=-0.1),
                    region('x', confidence=1.1), region('x', confidence=10**1000),
                    region('x', [0,0,720.0,100]),
                    region('x', [False,0,100,100]), region('x', [0,0,721,100]),
                    region('x', [0,0,100,1281]), region('x', [100,0,0,100]),
                    dict(region('x'), source_png_sha256='b'*64)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.validate(frames=self.altered(4, ocr_regions=(bad,)))
        for bad in ([], (region('x'),)*65, (None,)):
            with self.assertRaises(ValueError): self.validate(frames=self.altered(4, ocr_regions=bad))

    def test_invalid_model_labels(self):
        for label in (None, True, '', ' padded', 'x'*65, 'name\n', 'name/other'):
            with self.subTest(label=label), self.assertRaises(ValueError): self.validate(target=label)
            with self.assertRaises(ValueError): self.validate(preset=label)

    def test_pure_no_io_no_mutation_and_ignores_derived_v3_event_count(self):
        frames = tuple(replace(f, pointer_location_changed=False,
            prior_pointer_text_candidates=({'text':'Do not trust derived candidates'},)) for f in self.frames)
        before = deepcopy((self.actions, frames))
        with patch('builtins.open', side_effect=AssertionError('no IO')):
            result = self.validate(frames=frames)
        self.assertEqual(result['matched_labels'],4)
        self.assertEqual((self.actions, frames), before)


if __name__ == '__main__': unittest.main()
