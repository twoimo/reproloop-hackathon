"""Synthetic/mock exploration tests, not native execution or formal liveness proof.

Only the session and driver are fakes. Frozen public frames, proposal validation,
separate safety review, semantic lifting and export use the actual implementation.
Opaque markers below are unit-only strings, never real provider receipts.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

from reproloop.explore import (
    FLOW, GENERIC_CHECK, deny_review, explore, scoped_synthetic_lab_review,
)
from reproloop.runtime.driver import ActionReceipt, ActionRequest
from reproloop.runtime.owned import Frame, Node, OwnedTarget, PACKAGE, RuntimeStop, png_size


def generic_check():
    return {'id': 'unit-only-check', 'code': GENERIC_CHECK[0], 'message': GENERIC_CHECK[1]}


def response(kind='click', checks=None, actions=None):
    if checks is None:
        checks = [generic_check()] if kind == 'click' else []
    action = {'type': 'click', 'button': 'left', 'x': 50, 'y': 50} if kind == 'click' else {'type': kind}
    return {
        'status': 'completed',
        'output': [
            {'type': 'reasoning', 'id': 'unit-only-reasoning',
             'encrypted_content': 'OPAQUE-UNIT-ONLY-NOT-A-REAL-RECEIPT'},
            {'type': 'computer_call', 'status': 'completed', 'call_id': 'unit-only-call',
             'actions': deepcopy(actions if actions is not None else [action]),
             'pending_safety_checks': deepcopy(checks),
             'unit_only_opaque_receipt': {'nested': ['preserve', {'value': 17}]}},
        ],
    }


def synthetic_png(sequence):
    """A valid 100x100 grayscale PNG, with fresh pixels for every capture."""
    def chunk(kind, value):
        return (struct.pack('>I', len(value)) + kind + value
                + struct.pack('>I', zlib.crc32(kind + value)))
    raw = (b'\x00' + bytes([sequence % 256]) * 100) * 100
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', 100, 100, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


class FakeNativeDriver:
    """Stateful mock: captures never act; only exact reviewed FLOW taps advance."""
    def __init__(self, run, fail_capture=None):
        self.run = run
        self.deadline = time.monotonic() + 60
        self.stage = 0
        self.frames = []
        self.inputs = []
        self.fail_capture = fail_capture
        self.capture_attempts = 0

    def visible_nodes(self):
        def node(kind, text, bounds=(10, 10, 90, 90), clickable=True):
            return Node(PACKAGE + ':id/' + kind, text, clickable, bounds)
        if self.stage == 0:
            return (node('task_target', 'Target task: Inbox'),)
        if self.stage in (1, 4):
            return (node('rename_open', 'Rename'),)
        if self.stage == 2:
            return (node('preset_today', 'Today'),
                    node('cancel_edit', 'Cancel', (90, 10, 100, 90)))
        if self.stage == 3:
            return (node('cancel_edit', 'Cancel'),
                    node('draft', 'Draft: Today', (0, 0, 100, 10), False))
        raise AssertionError('mock state outside declared FLOW')

    def capture(self):
        self.capture_attempts += 1
        if self.capture_attempts == self.fail_capture:
            raise RuntimeStop('synthetic capture failure')
        sequence = self.capture_attempts
        frame = Frame(self.run.target.binding, sequence, synthetic_png(sequence),
                      f'<hierarchy synthetic-stage="{self.stage}" sequence="{sequence}"/>'.encode(),
                      100, 100, self.visible_nodes())
        assert png_size(frame.png) == (100, 100)
        self.frames.append(frame)
        self.run.last_frame = frame
        return frame

    def execute(self, request, frame, visible_after):
        assert type(request) is ActionRequest
        assert request.kind == 'tap' and self.stage < 4
        assert frame is self.run.last_frame and frame.nodes == self.visible_nodes()
        assert frame.binding == self.run.target.binding
        assert request.preframe_hash == frame.evidence_sha256
        assert request.resource_id == PACKAGE + ':id/' + FLOW[self.stage]
        assert request.action_id == f'{self.run.target.run_id}:action:{self.stage}'
        assert request.request_id == f'{self.run.target.run_id}:input:{self.stage}'
        assert frame.resolve(request.resource_id, request.text, request.x, request.y) == (50, 50)
        self.inputs.append(request)
        self.stage += 1
        after = self.capture()
        assert visible_after(after), 'actual acceptance predicate must recognize mock transition'
        return ActionReceipt(request.action_id, 'ACCEPTED', 'synthetic/mock only', after.evidence())


class FakeOwnedRun:
    def __init__(self, fail_capture=None):
        self.target = OwnedTarget('emulator-5554', 'ReproLoop_Test', 'owner', 'boot', 'a'*64, 'run', 1)
        self.expectation = SimpleNamespace(fixture=SimpleNamespace(target_title='Inbox'))
        self.last_frame = None
        self.driver = FakeNativeDriver(self, fail_capture)


class FakeModelSession:
    def __init__(self, responses):
        self.responses = deepcopy(responses)
        for index, item in enumerate(self.responses):
            item['output'][1]['call_id'] = f'unit-only-call-{index+1}'
        self.originals = deepcopy(self.responses)
        self.payloads = []
        self.request_ids = []

    def send(self, payload, request_id, deadline, outfile):
        # Snapshot before the explorer appends to the shared history list.
        self.payloads.append(deepcopy(payload))
        self.request_ids.append(request_id)
        assert deadline > time.monotonic()
        assert Path(outfile).name == f'response-{len(self.payloads):02d}.json'
        if len(self.payloads) > len(self.responses):
            raise AssertionError('unexpected extra model call')
        return self.responses[len(self.payloads)-1], 0.001


class ObservationTurnSyntheticTests(unittest.TestCase):
    def run_case(self, responses, *, allow=True, max_calls=5, reviewer=scoped_synthetic_lab_review,
                 fail_capture=None, omit_flag=False):
        self.run = FakeOwnedRun(fail_capture)
        self.session = FakeModelSession(responses)
        self.reviews = []
        def recording_review(call, frame, target, locator, step):
            self.reviews.append((deepcopy(call), frame, target, locator, step))
            return reviewer(call, frame, target, locator, step)
        with TemporaryDirectory(prefix='synthetic-observation-') as directory:
            kwargs = {} if omit_flag else {'allow_readonly_observation': allow}
            result = explore(self.run, SimpleNamespace(task_sha256='b'*64, fixture_sha256='c'*64),
                             self.session, directory, reviewer=recording_review, max_calls=max_calls,
                             **kwargs)
            self.summary = json.loads((Path(directory)/'exploration-summary.json').read_text())
            export_path = Path(directory)/'semantic-export.json'
            self.export_bytes = export_path.read_bytes() if export_path.exists() else None
        self.assertEqual(self.session.responses, self.session.originals, 'raw model output mutated')
        self.assertEqual(result.model_calls, len(self.session.payloads))
        self.assertEqual(self.session.request_ids, [f'run:model:{i+1}' for i in range(result.model_calls)])
        return result

    def assert_complete(self, result, calls, observations):
        self.assertTrue(result.complete, result.reason)
        self.assertEqual((result.model_calls, result.actions), (calls, 4))
        self.assertEqual(self.run.driver.stage, 4)
        self.assertEqual(len(self.run.driver.inputs), 4)
        self.assertEqual([r.action_id for r in self.run.driver.inputs], [f'run:action:{i}' for i in range(4)])
        self.assertEqual([r.request_id for r in self.run.driver.inputs], [f'run:input:{i}' for i in range(4)])
        self.assertEqual([r[4] for r in self.reviews], list(range(4)))
        self.assertTrue(all(r[0]['pending_safety_checks'] == [generic_check()] for r in self.reviews))
        self.assertEqual(self.summary['read_only_observations'], observations)
        self.assertEqual(self.export_bytes, result.export.to_bytes())
        exported = json.loads(self.export_bytes)
        self.assertEqual([s['resource_id'] for s in exported['steps']], [PACKAGE+':id/'+k for k in FLOW])
        self.assertEqual(len(exported['steps']), 4)
        for forbidden in ('screenshot', 'wait', '"x"', '"y"', 'requested_pixels', 'OPAQUE-UNIT'):
            self.assertNotIn(forbidden, self.export_bytes.decode())
        frames = self.run.driver.frames
        self.assertEqual([f.sequence for f in frames], list(range(1, len(frames)+1)))
        self.assertEqual(len({f.frame_sha256 for f in frames}), len(frames))

    def assert_stopped(self, result, calls, inputs=0, observations=0):
        self.assertFalse(result.complete)
        self.assertIsNone(result.export)
        self.assertIsNone(self.export_bytes)
        self.assertEqual((result.model_calls, result.actions), (calls, inputs))
        self.assertEqual(len(self.run.driver.inputs), inputs)
        self.assertEqual(self.run.driver.stage, inputs)
        self.assertEqual(self.summary['read_only_observations'], observations)

    def test_one_screenshot_then_four_separately_reviewed_clicks(self):
        result = self.run_case([response('screenshot')] + [response() for _ in range(4)])
        self.assert_complete(result, 5, 1)
        self.assertEqual([r['step'] for r in result.attempts], [0, 0, 1, 2, 3])
        self.assertFalse(result.attempts[0]['dispatched'])
        self.assertEqual(result.attempts[0]['observation_evidence'], self.run.driver.frames[1].evidence())
        self.assertEqual(self.run.driver.frames[0].nodes, self.run.driver.frames[1].nodes)
        self.assertEqual(len(self.run.driver.frames), 6)
        self.assertIs(self.reviews[0][1], self.run.driver.frames[1])

    def test_one_wait_has_bounded_delay_and_fresh_capture(self):
        with patch('reproloop.explore.time.sleep') as delay:
            result = self.run_case([response('wait')] + [response() for _ in range(4)])
        delay.assert_called_once_with(0.1)
        self.assert_complete(result, 5, 1)
        self.assertEqual(result.attempts[0]['read_only_observation'], 'wait')
        self.assertEqual(self.run.driver.frames[0].nodes, self.run.driver.frames[1].nodes)
        self.assertIs(self.reviews[0][1], self.run.driver.frames[1])

    def test_default_four_clicks_unchanged(self):
        result = self.run_case([response() for _ in range(4)], omit_flag=True, max_calls=4)
        self.assert_complete(result, 4, 0)
        self.assertEqual(self.summary['read_only_observation_cap'], 0)

    def test_disabled_screenshot_rejected_without_input(self):
        result = self.run_case([response('screenshot')], allow=False)
        self.assert_stopped(result, 1)
        self.assertEqual(len(self.run.driver.frames), 1)
        self.assertEqual(self.reviews, [])

    def test_second_observation_stops_without_another_capture_or_input(self):
        for second in ('screenshot', 'wait'):
            with self.subTest(second=second), patch('reproloop.explore.time.sleep') as delay:
                result = self.run_case([response('screenshot'), response(second)])
                self.assert_stopped(result, 2, observations=1)
                self.assertEqual(len(self.run.driver.frames), 2)
                self.assertEqual(self.reviews, [])
                delay.assert_not_called()

    def test_pending_checks_on_readonly_never_reviewed_or_acknowledged(self):
        unknown = {'id': 'unit-only-unknown', 'code': 'unknown', 'message': 'not approved'}
        for kind in ('screenshot', 'wait'):
            for check in (generic_check(), unknown):
                with self.subTest(kind=kind, check=check['code']):
                    result = self.run_case([response(kind, checks=[check])])
                    self.assert_stopped(result, 1)
                    self.assertEqual(len(self.run.driver.frames), 1)
                    self.assertEqual(self.reviews, [])
                    self.assertFalse(any(i.get('type') == 'computer_call_output'
                                         for i in self.session.payloads[0]['input']))

    def test_batched_observation_and_click_rejected_atomically(self):
        batch = [{'type': 'screenshot'}, {'type': 'click', 'button': 'left', 'x': 50, 'y': 50}]
        result = self.run_case([response(checks=[], actions=batch)])
        self.assert_stopped(result, 1)
        self.assertEqual(len(self.run.driver.frames), 1)
        self.assertEqual(self.reviews, [])

    def test_four_call_budget_after_observation_leaves_three_clicks_incomplete(self):
        result = self.run_case([response('screenshot')] + [response() for _ in range(3)], max_calls=4)
        self.assert_stopped(result, 4, inputs=3, observations=1)
        self.assertIn('model call cap', result.reason)
        self.assertEqual([r[4] for r in self.reviews], [0, 1, 2])

    def test_capture_failure_stops_without_input_or_retry(self):
        for fail_capture, calls in ((1, 0), (2, 1)):
            with self.subTest(fail_capture=fail_capture):
                result = self.run_case([response('screenshot')], fail_capture=fail_capture)
                self.assert_stopped(result, calls)
                self.assertIn('synthetic capture failure', result.reason)
                self.assertEqual(self.run.driver.capture_attempts, fail_capture)
                self.assertEqual(self.reviews, [])

    def test_raw_opaque_outputs_checks_and_ack_history_preserved_exactly(self):
        result = self.run_case([response('screenshot')] + [response() for _ in range(4)])
        self.assert_complete(result, 5, 1)
        history = self.session.payloads[-1]['input']
        # Four completed preceding turns: raw outputs then a bound screenshot ack.
        self.assertEqual(len(history), 1 + 4*3)
        for index in range(4):
            start = 1 + index*3
            self.assertEqual(history[start:start+2], self.session.originals[index]['output'])
            ack = history[start+2]
            self.assertEqual(ack['type'], 'computer_call_output')
            self.assertEqual(ack['call_id'], self.session.originals[index]['output'][1]['call_id'])
            expected = [] if index == 0 else [generic_check()]
            self.assertEqual(ack['acknowledged_safety_checks'], expected)
            self.assertEqual(ack['output']['type'], 'computer_screenshot')
        self.assertNotEqual(history[3]['output']['image_url'], self.session.payloads[0]['input'][0]['content'][1]['image_url'])

    def test_observation_does_not_bypass_default_click_review(self):
        result = self.run_case([response('screenshot'), response()], reviewer=deny_review)
        self.assert_stopped(result, 2, observations=1)
        self.assertEqual(len(self.reviews), 1)
        self.assertEqual(self.reviews[0][4], 0)
        self.assertIn('safety review denied', result.reason)
        # Next request may ack the check-free observation, never the denied click.
        acks = [i for i in self.session.payloads[-1]['input'] if i.get('type') == 'computer_call_output']
        self.assertEqual([a['acknowledged_safety_checks'] for a in acks], [[]])

    def test_unknown_click_safety_check_stops_after_observation(self):
        unknown = {'id': 'unit-only-check', 'code': 'unknown', 'message': 'not approved'}
        result = self.run_case([response('screenshot'), response(checks=[unknown])])
        self.assert_stopped(result, 2, observations=1)
        self.assertEqual(len(self.reviews), 1)
        self.assertIn('safety review denied', result.reason)

    def test_policy_types_and_call_bounds_are_rejected_before_capture(self):
        for kwargs in ({'max_calls': True}, {'max_calls': 1.0}, {'max_calls': 0},
                       {'max_calls': 13}, {'allow_readonly_observation': 1},
                       {'allow_readonly_observation': 'true'}):
            with self.subTest(kwargs=kwargs), TemporaryDirectory(prefix='synthetic-policy-') as directory:
                run, session = FakeOwnedRun(), FakeModelSession([])
                with self.assertRaises(ValueError):
                    explore(run, SimpleNamespace(), session, directory, **kwargs)
                self.assertEqual(run.driver.capture_attempts, 0)
                self.assertEqual(session.payloads, [])


if __name__ == '__main__':
    unittest.main()
