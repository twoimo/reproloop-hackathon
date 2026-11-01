"""Synthetic raw transcripts, with no actual device/network/model calls."""
import dataclasses
import json
from pathlib import Path
import sys
import unittest
from hashlib import sha256
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lab'))
import test_lab
from reproloop.replay import model_free_replay
from reproloop.pair_binding import bind_saved_pair, canonical

class PairTests(unittest.TestCase):
    def setUp(self):
        helper=test_lab.LabTests('test_pair_same_generation_and_persisted_post_frames'); helper.setUp()
        self.addCleanup(helper.doCleanups)
        self.h=helper; self.root=helper.root; self.evidence=helper.cfg.evidence_root
        self.paths=[]
        for mode in ('faulty','fixed'):
            result=model_free_replay(helper.lab,helper.export,helper.spec,mode,'pair-'+mode)
            self.assertTrue(result.complete,result.reason)
            path=self.root/(mode+'.json'); path.write_bytes(canonical(dataclasses.asdict(result))); self.paths.append(path)
    def bind(self,**kwargs):
        args=dict(spec=self.h.spec,export=self.h.export,fixture=self.h.fixture,faulty_result_path=self.paths[0],fixed_result_path=self.paths[1],evidence_root=self.evidence,generation=1)
        args.update(kwargs); return bind_saved_pair(**args)
    def load(self,which=0): return json.loads(self.paths[which].read_bytes())
    def store(self,value,which=0): self.paths[which].write_bytes(canonical(value))
    def replace_artifact(self,saved,suffix,mutation):
        old=next(p for p in saved['evidencepaths'] if p.endswith(suffix)); obj=json.loads(Path(old).read_bytes()); mutation(obj)
        raw=canonical(obj); new=self.evidence/(sha256(raw).hexdigest()+suffix); new.write_bytes(raw)
        saved['evidencepaths']=[str(new) if p==old else p for p in saved['evidencepaths']]
        if suffix=='.trace.json': saved['trace_sha256']=sha256(raw).hexdigest()
        return obj
    def test_normal_raw_pair(self):
        report=self.bind(); self.assertTrue(report.valid,report.reason)
        self.assertTrue(report.collected_pair.row.faulty_complete)
        self.assertEqual(report.collected_pair.decision.verdict.value,'reproduced_oracle_and_control_confirmed')
    def test_hash_corruption(self):
        saved=self.load(); p=Path(next(x for x in saved['evidencepaths'] if x.endswith('.png'))); p.write_bytes(b'corrupt')
        self.assertFalse(self.bind().valid)
    def test_wrong_script(self):
        export=dataclasses.replace(self.h.export,task_sha256='d'*64)
        self.assertFalse(self.bind(export=export).valid)
    def test_missing_reset(self):
        saved=self.load(); (self.evidence/(saved['reset_receipt_sha256']+'.reset.json')).unlink()
        self.assertFalse(self.bind().valid)
    def test_false_complete_and_bool_counter(self):
        saved=self.load(); saved['complete']=False; self.store(saved); self.assertFalse(self.bind().valid)
        saved['complete']=True; saved['model_calls']=False; self.store(saved); self.assertFalse(self.bind().valid)
    def test_unknown_readdressed_journal(self):
        saved=self.load(); self.replace_artifact(saved,'.journal.json',lambda j:j['actions'][0].update(state='UNKNOWN')); self.store(saved)
        self.assertFalse(self.bind().valid)
    def test_forged_saved_oracle(self):
        saved=self.load(); saved['oracle_run']['failure_observed']=False; self.store(saved)
        self.assertFalse(self.bind().valid)
    def test_declared_booleans_without_raw_do_not_bind(self):
        self.paths[0].write_text('{"complete":true,"model_calls":0,"pair_binding_valid":true}')
        self.assertFalse(self.bind().valid)
    def test_malformed_duplicate_json(self):
        self.paths[0].write_text('{"complete":true,"complete":true}')
        self.assertFalse(self.bind().valid)
    def test_different_apk_and_generation(self):
        self.assertFalse(self.bind(spec=dataclasses.replace(self.h.spec,faulty_build_sha256='e'*64)).valid)
        self.assertFalse(self.bind(generation=2).valid)
        self.assertFalse(self.bind(generation=True).valid)
    def test_shared_log_receipt(self):
        saved=self.load(); other=self.load(1); saved['oracle_run']['oracle_log_sha256']=other['oracle_run']['oracle_log_sha256']; self.store(saved)
        self.assertFalse(self.bind().valid)
    def test_wrong_run_in_trace(self):
        saved=self.load(); self.replace_artifact(saved,'.trace.json',lambda t:t.update(run_id='other')); self.store(saved)
        self.assertFalse(self.bind().valid)
    def test_arbitrary_planned_input_not_accepted(self):
        saved=self.load(); self.replace_artifact(saved,'.journal.json',lambda j:j['actions'][0].update(planned_args='["shell","input","tap","1","1"]')); self.store(saved)
        self.assertFalse(self.bind().valid)
    def test_saved_reset_proof_must_match_raw(self):
        saved=self.load(); saved['run_proof']['reset_snapshot']['target_title']='Forged'; self.store(saved)
        self.assertFalse(self.bind().valid)
    def test_trace_false_complete_readdressed(self):
        saved=self.load(); self.replace_artifact(saved,'.trace.json',lambda t:t.update(complete=False)); self.store(saved)
        self.assertFalse(self.bind().valid)
    def test_symlink_and_outside_path_rejected(self):
        saved=self.load(); old=Path(saved['evidencepaths'][0]); alias=self.evidence/'alias'; alias.symlink_to(old)
        saved['evidencepaths'][0]=str(alias); self.store(saved); self.assertFalse(self.bind().valid)
    def test_source_disagreement(self):
        saved=self.load(); self.replace_artifact(saved,'.trace.json',lambda t:t['source_sha256'].update(**{'driver.py':'f'*64})); self.store(saved)
        self.assertFalse(self.bind().valid)

if __name__=='__main__': unittest.main()
