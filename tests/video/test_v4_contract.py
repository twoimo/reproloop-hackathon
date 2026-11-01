"""Synthetic v4 integration. No device, network, provider or source video access."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import test_request_envelope as legacy
from reproloop.lab import canonical
from reproloop.video import (ACTION_IDS, FRAME_PROTOCOL_V4, OBSERVATION_MODE_V4, PROMPT_V4,
    build_video_intent_request, decode_video_intent_response, infer_video_intent)
from reproloop.video_frames import FrameObservation


def region(text, bounds):
    return dict(text=text, confidence=1, bounds=bounds)


def frames():
    scenes = (
        (region('Target task: Inbox', [100,100,500,150]),),
        (region('Rename', [100,100,300,150]), region('Selected: Inbox', [10,200,400,230])),
        (region('Today', [100,280,300,330]), region('Cancel', [100,480,300,530]), region('Draft: Inbox', [10,200,400,230])),
        (region('Today', [100,280,300,330]), region('Cancel', [100,480,300,530]), region('Draft: Today', [10,200,400,230])),
        (region('Target task: Today', [100,100,500,150]), region('Rename', [100,280,300,330])),
    )
    points = (None, (120,120), (120,120), (120,300), (120,500))
    result = []
    for index, (scene, point) in enumerate(zip(scenes, points)):
        digest = sha256(('synthetic-frame-'+str(index)).encode()).hexdigest()
        marker = None if point is None else dict(red_marker_candidate=dict(
            center=list(point), bounds=[point[0],point[1],point[0],point[1]], source_png_sha256=digest))
        result.append(FrameObservation(index*1000, digest, 720, 1280, 'a'*64,
            'data:image/png;base64,cG5n', marker, 'ABSENT' if point is None else 'CANDIDATE',
            ocr_regions=scene, ocr_observer='macOS Vision'))
    return tuple(result)


class V4ContractTests(unittest.TestCase):
    def setUp(self):
        self.base = legacy.RequestEnvelopeTests()
        self.base.setUp()
        self.frames = frames()
        self.response = self.base.response
        value = json.loads(self.response['output'][0]['content'][0]['text'])
        value['actions'] = [dict(operation=operation,timestamp_ms=(i+1)*1000) for i,operation in enumerate(ACTION_IDS)]
        self.response['output'][0]['content'][0]['text'] = json.dumps(value)

    def envelope(self, protocol=FRAME_PROTOCOL_V4):
        payload, binding, mode = build_video_intent_request(self.base.upload,
            supplemental_frames=self.frames, frame_protocol=protocol)
        return payload, dict(request_id='req',payload_sha256=sha256(canonical(payload)).hexdigest(),source_binding=binding), mode

    def decode(self, envelope=None, **changes):
        _, original, mode = self.envelope()
        options = dict(supplemental_frames=self.frames,frame_protocol=FRAME_PROTOCOL_V4,
            mode=mode,request_envelope=original if envelope is None else envelope,persist=False)
        options.update(changes)
        return decode_video_intent_response(self.response,self.base.upload,'req','/private','/private/response.json',**options)

    def test_real_parser_and_context_validator_stationary_point(self):
        result = self.decode()
        self.assertEqual(result.input_observation_mode, OBSERVATION_MODE_V4)
        self.assertEqual(result.input_grounding['matched_labels'], 4)
        self.assertTrue(result.input_grounding['matches'][1]['stationary_or_small_move'])
        self.assertFalse(result.input_grounding['attestation'])
        self.assertEqual(result.prompt_sha256, sha256(PROMPT_V4.encode()).hexdigest())

    def test_inference_and_saved_path_share_envelope_and_validator(self):
        with tempfile.TemporaryDirectory() as out, patch('reproloop.video._post', return_value=(self.response,'/private/response.json')) as post:
            result = infer_video_intent(object(),self.base.upload,'req',out,1,
                supplemental_frames=self.frames,frame_protocol=FRAME_PROTOCOL_V4)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(result.input_grounding['matched_labels'], 4)
            self.assertTrue((Path(out)/'req.video-intent.json').is_file())

    def test_cannot_reinterpret_v3_envelope_as_v4(self):
        _, old, _ = self.envelope('native_pointer_temporal_ocr_v3')
        with self.assertRaisesRegex(ValueError,'original request identity/payload envelope'):
            self.decode(envelope=old)

    def test_explicit_protocol_requires_frames_before_any_post(self):
        for protocol in ('native_pointer_temporal_v2','native_pointer_temporal_ocr_v3',FRAME_PROTOCOL_V4):
            with patch('reproloop.video._post') as post, self.assertRaises(ValueError):
                infer_video_intent(object(),self.base.upload,'req','/private',1,frame_protocol=protocol)
            post.assert_not_called()

    def test_no_three_action_or_uncertain_promotion(self):
        content = self.response['output'][0]['content'][0]
        original = json.loads(content['text'])
        for change in (dict(status='uncertain'), dict(actions=original['actions'][:3])):
            content['text'] = json.dumps({**original, **change})
            with self.assertRaises(ValueError):
                self.decode()

    def test_bad_time_and_scene_still_stop_without_fallback(self):
        value = json.loads(self.response['output'][0]['content'][0]['text'])
        value['actions'][1]['timestamp_ms'] += 1
        self.response['output'][0]['content'][0]['text'] = json.dumps(value)
        with self.assertRaisesRegex(ValueError,'exact supplied after-frame'):
            self.decode()
