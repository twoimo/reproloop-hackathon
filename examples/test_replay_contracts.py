"""Pure local synthetic regression tests. No Android, XML capture or Meta calls."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
import unittest

from evaluation_metrics import summarize
from repro_oracle import CaseSpec, OracleRun, Verdict, judge
from replay_contracts import (AttemptBudget, Hierarchy, Locator, Node,
                              PreActionFrame, SemanticExport, TraceClick,
                              collect_pair, export_trace, lift_click, pixel,
                              resolve, validate_capture)

H = lambda s: sha256(s.encode()).hexdigest()


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.f = PreActionFrame('run', 'emulator-owned', 'boot', 'lab.app',
                                H('build'), 1, 1, H('pixels'), 100, 200, 'editor')
        self.n = Node('button', 'lab.app:id/cancel', 'Cancel', True, (10, 20, 30, 40))
        self.h = Hierarchy(self.f, H('hierarchy'), (self.n,))
        self.c = TraceClick(self.f, self.h, 20, 30)

    def test_integral_adapter(self):
        self.assertEqual(pixel(20.0, 100), 20)
        self.assertIs(type(pixel(20.0, 100)), int)

    def test_bad_coordinates(self):
        for v in (True, False, 1.5, float('nan'), float('inf'), -1, 100, 10**400, '20', None):
            with self.subTest(v=repr(v)), self.assertRaises(ValueError): pixel(v, 100)

    def test_bad_extents(self):
        for e in (True, 0, -1, 100.0, 20000):
            with self.subTest(e=e), self.assertRaises(ValueError): pixel(0, e)

    def test_boundary_points(self):
        self.assertEqual(pixel(0, 100), 0)
        self.assertEqual(pixel(99.0, 100), 99)
        with self.assertRaises(ValueError): lift_click(replace(self.c, x=30), self.f)
        self.assertEqual(lift_click(replace(self.c, x=10, y=20), self.f).visible_text, 'Cancel')

    def test_unique_lifting(self):
        self.assertEqual(lift_click(self.c, self.f), Locator(self.n.resource_id, 'Cancel', 'editor'))

    def test_replay_uses_new_bounds_not_old_pixels(self):
        loc = lift_click(self.c, self.f)
        fresh = replace(self.f, capture_epoch=2, frame_sha256=H('new pixels'))
        h = Hierarchy(fresh, H('new tree'), (replace(self.n, bounds=(50, 100, 70, 120)),))
        self.assertEqual(resolve(loc, fresh, h, fresh), (59, 109))

    def test_epoch_mismatch(self):
        h = replace(self.h, frame=replace(self.f, capture_epoch=2))
        with self.assertRaises(ValueError): validate_capture(self.f, h, self.f)

    def test_generation_mismatch(self):
        with self.assertRaises(ValueError): lift_click(self.c, replace(self.f, generation=2))

    def test_bool_generation_in_current_or_tree(self):
        for field in ('generation', 'capture_epoch', 'width'):
            # True must not pass dataclass equality against integer 1.
            f = replace(self.f, **{field: 1})
            h = replace(self.h, frame=f)
            current = replace(f, **{field: True})
            with self.subTest(field=field), self.assertRaises(ValueError): validate_capture(f, h, current)
            with self.subTest(tree=field), self.assertRaises(ValueError): validate_capture(f, replace(h, frame=current), f)

    def test_identity_mismatch(self):
        for field, value in [('run_id', 'other'), ('serial', 'other'), ('boot_id', 'reboot'),
                             ('package', 'other'), ('build_sha256', H('other'))]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_capture(self.f, self.h, replace(self.f, **{field: value}))

    def test_malformed_digest(self):
        with self.assertRaises(ValueError): validate_capture(self.f, replace(self.h, hierarchy_sha256='hash'), self.f)

    def test_nested_clickable_ambiguity(self):
        parent = Node('parent', 'lab.app:id/container', '', True, (0, 0, 100, 200))
        with self.assertRaises(ValueError): lift_click(replace(self.c, hierarchy=replace(self.h, nodes=(parent, self.n))), self.f)

    def test_duplicate_selector_even_if_pixel_unique(self):
        other = replace(self.n, node_key='other', bounds=(50, 100, 70, 120))
        with self.assertRaises(ValueError): lift_click(replace(self.c, hierarchy=replace(self.h, nodes=(self.n, other))), self.f)

    def test_duplicate_node_key(self):
        with self.assertRaises(ValueError): validate_capture(self.f, replace(self.h, nodes=(self.n, self.n)), self.f)

    def test_zero_match_fails(self):
        with self.assertRaises(ValueError): resolve(Locator('lab.app:id/missing', '', 'editor'), self.f, self.h, self.f)

    def test_screen_mismatch(self):
        with self.assertRaises(ValueError): resolve(Locator(self.n.resource_id, 'Cancel', 'other'), self.f, self.h, self.f)

    def test_foreign_resource(self):
        with self.assertRaises(ValueError): validate_capture(self.f, replace(self.h, nodes=(replace(self.n, resource_id='foreign:id/x'),)), self.f)

    def test_node_bad_types_and_bounds(self):
        for n in (replace(self.n, clickable='true'), replace(self.n, bounds=(True, 0, 30, 40)),
                  replace(self.n, bounds=(30, 20, 10, 40)), replace(self.n, text='x'*257),
                  replace(self.n, resource_id='lab.app:id/')):
            with self.subTest(n=n), self.assertRaises(ValueError): validate_capture(self.f, replace(self.h, nodes=(n,)), self.f)

    def test_immutable_bounded_nodes(self):
        for nodes in ([], (), (self.n,)*129):
            with self.subTest(size=len(nodes)), self.assertRaises(ValueError): validate_capture(self.f, replace(self.h, nodes=nodes), self.f)

    def test_export_fixed_trace_deterministic_no_oracle_fields(self):
        a = export_trace((self.c,), H('task'), H('fixture'))
        self.assertEqual(a.to_bytes(), export_trace((self.c,), H('task'), H('fixture')).to_bytes())
        obj = json.loads(a.to_bytes())
        self.assertEqual(set(obj), {'package', 'task_sha256', 'fixture_sha256', 'steps', 'schema_version', 'resolver_version'})
        self.assertNotIn('oracle', a.to_bytes().decode())
        self.assertNotIn('bounds', a.to_bytes().decode())
        self.assertEqual(a.digest(), sha256(a.to_bytes()).hexdigest())

    def test_no_oracle_argument_accepted(self):
        with self.assertRaises(TypeError): export_trace((self.c,), H('task'), H('fixture'), oracle='secret')

    def test_mixed_run_or_repeated_epoch_fails(self):
        with self.assertRaises(ValueError): export_trace((self.c, self.c), H('t'), H('f'))
        f = replace(self.f, run_id='other', capture_epoch=2)
        c = TraceClick(f, replace(self.h, frame=f), 20, 30)
        with self.assertRaises(ValueError): export_trace((self.c, c), H('t'), H('f'))

    def test_export_bad_shape(self):
        for args in (((), H('t'), H('f')), ((self.c,)*25, H('t'), H('f')), ((self.c,), 'bad', H('f'))):
            with self.assertRaises(ValueError): export_trace(*args)
        a = export_trace((self.c,), H('t'), H('f'))
        with self.assertRaises(ValueError): replace(a, schema_version=True).to_bytes()


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.s = CaseSpec('case', H('task'), H('fixture'), H('bad'), H('fixed'), 'cancel')
        self.b = OracleRun('bad-run', 'case', self.s.task_sha256, self.s.fixture_sha256,
                           self.s.faulty_build_sha256, 'cancel', H('badlog'), True, True, True, True, 1)
        self.g = replace(self.b, run_id='fixed-run', build_sha256=self.s.repaired_build_sha256,
                         oracle_log_sha256=H('fixedlog'), failure_observed=False)

    def collect(self, **kwargs):
        return collect_pair(self.s, self.b, self.g, 1, export_created=kwargs.get('export_created', True),
                            pair_binding_valid=kwargs.get('pair_binding_valid', True))

    def test_actual_judge_and_normal_pair(self):
        result = self.collect()
        self.assertEqual(result.decision, judge(self.s, self.b, self.g, 1))
        self.assertEqual(result.row.pair_verdict, result.decision.verdict)
        self.assertEqual(summarize([result.row], ['case'])['primary_valid_export_pairs']['count'], 1)

    def test_missing_binding_downgrades_preserving_identity(self):
        original = judge(self.s, self.b, self.g, 1)
        d = self.collect(pair_binding_valid=False).decision
        self.assertEqual(d.verdict, Verdict.INCONCLUSIVE)
        self.assertEqual((d.generation, d.case_manifest_sha256), (original.generation, original.case_manifest_sha256))

    def test_missing_export_not_model_success(self):
        result = self.collect(export_created=False)
        self.assertEqual(result.decision.verdict, Verdict.INCONCLUSIVE)
        s = summarize([result.row], ['case'])
        self.assertEqual(s['primary_valid_export_pairs']['count'], 0)
        self.assertEqual(s['fixed_failure_signals']['complete_with_signal'], 1)

    def test_missing_control_or_partial_never_confirms(self):
        for fixed in (None, replace(self.g, completed=False), replace(self.g, failure_observed=None),
                      replace(self.g, build_sha256=H('wrong')), replace(self.g, generation=2)):
            with self.subTest(fixed=fixed):
                r = collect_pair(self.s, self.b, fixed, 1, export_created=True, pair_binding_valid=True)
                self.assertNotEqual(r.decision.verdict, Verdict.CONFIRMED)

    def test_shared_receipt_is_not_usable_control(self):
        r = collect_pair(self.s, self.b, replace(self.g, oracle_log_sha256=self.b.oracle_log_sha256), 1,
                         export_created=True, pair_binding_valid=True)
        self.assertEqual(r.decision.verdict, Verdict.INCONCLUSIVE)
        self.assertFalse(r.row.fixed_complete)
        self.assertIsNone(r.row.fixed_failure)
        self.assertEqual(summarize([r.row], ['case'])['fixed_failure_signals']['complete_with_signal'], 0)

    def test_malformed_digest_is_not_usable_control(self):
        r = collect_pair(self.s, self.b, replace(self.g, oracle_log_sha256='not-a-digest'), 1,
                         export_created=True, pair_binding_valid=True)
        self.assertFalse(r.row.fixed_complete)
        self.assertNotEqual(r.decision.verdict, Verdict.CONFIRMED)

    def test_no_caller_terminal_verdict(self):
        with self.assertRaises(TypeError): collect_pair(self.s, self.b, self.g, 1, export_created=True, pair_binding_valid=True, verdict=Verdict.CONFIRMED)

    def test_bad_flags_and_generation(self):
        with self.assertRaises(ValueError): self.collect(pair_binding_valid='true')
        with self.assertRaises(ValueError): collect_pair(self.s, self.b, self.g, True, export_created=True, pair_binding_valid=True)

    def test_unusable_run_ids_cannot_issue_confirmed(self):
        bad = replace(self.b, oracle_log_sha256='   ')
        r = collect_pair(self.s, bad, self.g, 1, export_created=True, pair_binding_valid=True)
        self.assertEqual(r.decision.verdict, Verdict.INCONCLUSIVE)
        self.assertEqual(summarize([r.row], ['case'])['invalid_pair_confirmations']['count'], 0)

    def test_fixed_signal_not_invalid_pair(self):
        r = collect_pair(self.s, self.b, replace(self.g, failure_observed=True), 1, export_created=True, pair_binding_valid=True)
        s = summarize([r.row], ['case'])
        self.assertEqual(s['fixed_failure_signals']['positive'], 1)
        self.assertEqual(s['invalid_pair_confirmations']['count'], 0)


class BudgetTests(unittest.TestCase):
    def setUp(self): self.now = 0.0
    def budget(self, **kwargs): return AttemptBudget(clock=lambda: self.now, **kwargs)

    def test_separate_pre_attempt_caps(self):
        b = self.budget(max_calls=1, max_actions=2, max_captures=1)
        b.reserve_call(); b.reserve_action(); b.reserve_action(); b.reserve_capture()
        self.assertEqual((b.snapshot().calls, b.snapshot().actions, b.snapshot().captures), (1, 2, 1))
        for fn in (b.reserve_call, b.reserve_action, b.reserve_capture):
            with self.assertRaises(ValueError): fn()

    def test_timeout_unknown_no_refund(self):
        b = self.budget(max_calls=1)
        b.reserve_call()  # Simulated dispatch times out; no refund API.
        with self.assertRaises(ValueError): b.reserve_call()
        self.assertEqual(b.snapshot().calls, 1)

    def test_elapsed_boundary(self):
        b = self.budget(seconds=2)
        self.now = 1.999; b.reserve_action()
        self.now = 2.0
        with self.assertRaises(ValueError): b.reserve_action()
        self.assertEqual(b.snapshot().actions, 1)

    def test_clock_rollback(self):
        b = self.budget(); self.now = 1; b.reserve_call(); self.now = .5
        with self.assertRaises(ValueError): b.reserve_action()

    def test_bad_limits_and_clocks(self):
        for kwargs in ({'max_calls': True}, {'max_actions': 0}, {'seconds': float('nan')}, {'seconds': True}, {'seconds': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): self.budget(**kwargs)
        with self.assertRaises(ValueError): AttemptBudget(clock=lambda: True)
        b = self.budget(); self.now = float('inf')
        with self.assertRaises(ValueError): b.reserve_capture()

    def test_thread_safe_limit(self):
        b = self.budget(max_actions=7)
        def attempt(_):
            try: b.reserve_action(); return 1
            except ValueError: return 0
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt, range(100))), 7)
        self.assertEqual(b.snapshot().actions, 7)


if __name__ == '__main__': unittest.main()
