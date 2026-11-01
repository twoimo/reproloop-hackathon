import copy
import dataclasses
import json
import pathlib
import sys
import unittest
from reproloop.runtime.app_state import (FixtureSpec, AppExpectation, AppEvidenceError, validate_snapshot, AppStateReader, AppObservation, RunProof, oracle_fields)
from reproloop.runtime.owned import OwnedTarget, RuntimeStop


def encode(obj): return json.dumps(obj,separators=(',',':')).encode()

def sample(mode='faulty', complete=True, target=None):
    fixture=FixtureSpec('DEV01',0,'A')
    target=target or OwnedTarget('emulator-5554','Owned','parent','boot','a'*64,'run-1',1)
    expected=AppExpectation(target,fixture,mode)
    meta=expected.metadata()
    actions=['fixture_loaded','task_open','rename_open','select_preset','cancel_edit'] if complete else ['fixture_loaded']
    events=[]
    for seq,action in enumerate(actions,1):
        after='Today' if mode=='faulty' and seq==5 else 'Inbox'
        before='' if seq==1 else 'Inbox'
        draft='' if seq<=2 else ('Inbox' if seq==3 else 'Today')
        events.append(dict(meta,sequence=seq,timestamp_unix_ms=100+seq,action=action,
                           task_id='' if seq==1 else 'target',before_title=before,draft_title=draft,
                           after_title='' if seq==1 else after,cancel_count=int(seq==5),target_title=after,non_target_title='Archive'))
    last=events[-1]
    state=dict(meta,fixture=fixture.fields(),target_id='target',target_title=last['target_title'],non_target_id='other',non_target_title='Archive',sequence=len(events),cancel_count=int(complete),cancel_order=[5] if complete else [],created_at_unix_ms=100,updated_at_unix_ms=last['timestamp_unix_ms'],last_action=last['action'])
    return expected,state,events

def raw_events(events): return b''.join(encode(event)+b'\n' for event in events)

class SchemaTests(unittest.TestCase):
    def valid(self,mode='faulty',complete=True):
        expected,state,events=sample(mode,complete)
        return validate_snapshot(encode(state),raw_events(events),expected)
    def test_normal_faulty_and_fixed_signals(self):
        self.assertEqual(self.valid().target_title,'Today')
        self.assertEqual(self.valid('fixed').target_title,'Inbox')
        self.assertTrue(self.valid().explicit_cancel_flow)
        self.assertFalse(self.valid(complete=False).explicit_cancel_flow)
    def test_canonical_fixture_escaping_and_digest(self):
        fixture=FixtureSpec('DEV01',0,'A')
        self.assertEqual(json.dumps(fixture.fields(),separators=(',',':')),'{"fixture_id":"DEV01","layout_variant":"A","non_target_id":"other","non_target_title":"Archive","seed":0,"target_id":"target","target_title":"Inbox"}')
        self.assertEqual(FixtureSpec('X',1,'C','A "quote"','Slash\\').fields()['target_title'],'A "quote"')
    def test_binding_mismatch_for_every_metadata_field(self):
        for field in ('schema_version','package','build_mode','fixture_id','fixture_sha256','seed','layout_variant','run_id','generation'):
            expected,state,events=sample()
            state[field]=False if type(state[field]) is int else 'wrong'
            with self.subTest(field=field), self.assertRaises(AppEvidenceError) as ctx:
                validate_snapshot(encode(state),raw_events(events),expected)
            self.assertEqual(ctx.exception.reason_code,'BINDING_'+field.upper())
    def test_event_binding_mismatch_even_when_terminal_matches(self):
        expected,state,events=sample(); events[1]['run_id']='stale'
        with self.assertRaisesRegex(AppEvidenceError,'BINDING_RUN_ID'): validate_snapshot(encode(state),raw_events(events),expected)
    def test_missing_unknown_duplicate_malformed_and_truncated(self):
        expected,state,events=sample()
        candidates=[b'{',b'[]',b'{"x":1,"x":2}',encode(dict(state,extra=1)),encode({k:v for k,v in state.items() if k!='fixture'}),b'{"x":NaN}',b'{"x":'+b'['*10+b'0'+b']'*10+b'}']
        for raw in candidates:
            with self.subTest(raw=raw[:50]), self.assertRaises(AppEvidenceError): validate_snapshot(raw,raw_events(events),expected)
        with self.assertRaisesRegex(AppEvidenceError,'TRUNCATED_EVENTS'): validate_snapshot(encode(state),raw_events(events)[:-1],expected)
    def test_malformed_types_do_not_escape_typed_failure(self):
        for field in ('sequence','cancel_count','last_action','fixture','cancel_order','target_title'):
            expected,state,events=sample(); state[field]=[]
            with self.subTest(field=field), self.assertRaises(AppEvidenceError): validate_snapshot(encode(state),raw_events(events),expected)
    def test_state_event_mutability_and_sequence_windows(self):
        mutations=[('sequence',6),('target_title','Other'),('updated_at_unix_ms',999),('cancel_order',[4]),('non_target_title','Changed')]
        for key,value in mutations:
            expected,state,events=sample(); state[key]=value
            with self.subTest(key=key), self.assertRaises(AppEvidenceError): validate_snapshot(encode(state),raw_events(events),expected)
        expected,state,events=sample(); events[2]['sequence']=2
        with self.assertRaisesRegex(AppEvidenceError,'EVENT_SEQUENCE'): validate_snapshot(encode(state),raw_events(events),expected)
    def test_non_target_changes_are_never_accepted(self):
        expected,state,events=sample(); events[-1]['non_target_title']='Changed'; state['non_target_title']='Changed'
        with self.assertRaises(AppEvidenceError): validate_snapshot(encode(state),raw_events(events),expected)
    def test_cancel_cannot_be_inferred_from_dismiss(self):
        expected,state,events=sample('fixed')
        events[-1]['action']='dismiss_edit'; events[-1]['cancel_count']=0
        state.update(last_action='dismiss_edit',cancel_count=0,cancel_order=[])
        snap=validate_snapshot(encode(state),raw_events(events),expected)
        self.assertFalse(snap.explicit_cancel_flow)
    def test_event_transition_and_clock_negative_cases(self):
        for field,value in [('draft_title','Wrong'),('before_title','Wrong'),('cancel_count',0),('task_id','other'),('timestamp_unix_ms',1)]:
            expected,state,events=sample(); events[-1][field]=value
            with self.subTest(field=field), self.assertRaises(AppEvidenceError): validate_snapshot(encode(state),raw_events(events),expected)
    def test_collection_detects_each_read_window(self):
        expected,state,events=sample(); normal=[encode(state),raw_events(events),encode(state),raw_events(events),encode(state)]
        class FakeTransport:
            target=expected.target
            def discover(self,deadline): pass
            def read_app_state(self,deadline): return self.reads.pop(0)
            def read_app_events(self,deadline): return self.reads.pop(0)
        for index in range(5):
            transport=FakeTransport(); transport.reads=normal.copy(); transport.reads[index]+=b' '
            result=AppStateReader(transport).collect(expected,100)
            self.assertEqual(result.reason_code,'READ_WINDOW_CHANGED'); self.assertFalse(result.atomic)
        transport=FakeTransport(); transport.reads=normal.copy()
        self.assertTrue(AppStateReader(transport).collect(expected,100).coherent)
    def test_read_timeout_and_wrong_transport_binding(self):
        expected,_,_=sample()
        class Transport:
            target=expected.target
            def discover(self,deadline): raise TimeoutError()
        self.assertEqual(AppStateReader(Transport()).collect(expected,100).reason_code,'READ_UNAVAILABLE')
    def test_size_bounds(self):
        expected,state,events=sample()
        with self.assertRaisesRegex(AppEvidenceError,'BYTE_BOUND'): validate_snapshot(b'x'*1_000_001,raw_events(events),expected)
        with self.assertRaisesRegex(AppEvidenceError,'EVENT_BYTE_BOUND'): validate_snapshot(encode(state),b'x'*2_000_001,expected)

class OracleAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'examples'))
        import repro_oracle
        cls.oracle=repro_oracle
    def fields(self,mode='faulty',complete=True):
        target=OwnedTarget('emulator-5554','Owned','parent','boot',('a' if mode=='faulty' else 'b')*64,'run-'+mode,1)
        expected,state,events=sample(mode,complete,target)
        snapshot=validate_snapshot(encode(state),raw_events(events),expected)
        _,reset,reset_events=sample(mode,False,target)
        initial=validate_snapshot(encode(reset),raw_events(reset_events),expected)
        obs=AppObservation('COHERENT',snapshot,(),True)
        proof=RunProof(initial,'c'*64,'d'*64,True,True)
        spec=self.oracle.CaseSpec('case','c'*64,expected.fixture.sha256,'a'*64,'b'*64,'cancel')
        return spec,obs,proof
    def test_existing_oracle_pair_via_fields_not_model_verdict(self):
        spec,obs,proof=self.fields(); faulty=self.oracle.OracleRun(**oracle_fields(spec,obs,proof))
        spec,obs,proof=self.fields('fixed'); fixed=self.oracle.OracleRun(**oracle_fields(spec,obs,proof))
        self.assertEqual(self.oracle.judge(spec,faulty,fixed,1).verdict,self.oracle.Verdict.CONFIRMED)
    def test_missing_independent_trace_stays_unknown(self):
        spec,obs,proof=self.fields()
        result=oracle_fields(spec,obs,dataclasses.replace(proof,trace_completed=False))
        self.assertFalse(result['completed']); self.assertIsNone(result['failure_observed'])
        spec,obs,proof=self.fields(complete=False)
        self.assertIsNone(oracle_fields(spec,obs,proof)['failure_observed'])
    def test_opposite_build_mismatched_case_and_stale_reset(self):
        spec,obs,proof=self.fields()
        cases=[dataclasses.replace(spec,faulty_build_sha256='e'*64),dataclasses.replace(spec,fixture_sha256='e'*64),dataclasses.replace(spec,task_sha256='e'*64)]
        for case in cases:
            with self.assertRaises(AppEvidenceError): oracle_fields(case,obs,proof)
        with self.assertRaisesRegex(AppEvidenceError,'FRESH_RESET_REQUIRED'):
            oracle_fields(spec,obs,dataclasses.replace(proof,reset_snapshot=obs.snapshot))
    def test_broken_cancel_marker_mutant_is_detected_by_flow(self):
        spec,obs,proof=self.fields()
        bad=dataclasses.replace(obs.snapshot,events=obs.snapshot.events[:-1])
        self.assertFalse(oracle_fields(spec,dataclasses.replace(obs,snapshot=bad),proof)['completed'])

if __name__=='__main__': unittest.main()
