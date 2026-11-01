from hashlib import sha256
h=lambda value:sha256(value.encode()).hexdigest()
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import unittest
from repro_oracle import *
class OracleTests(unittest.TestCase):
 def setUp(self):
  self.s=CaseSpec('case',h('task'),h('fixture'),h('bad'),h('good'),'oracle')
  self.bad=OracleRun('r1','case',h('task'),h('fixture'),h('bad'),'oracle',h('log1'),True,True,True,True,1,True)
  self.good=replace(self.bad,run_id='r2',build_sha256=h('good'),oracle_log_sha256=h('log2'),failure_observed=False)
 def test_positive_with_repaired_control(self):self.assertEqual(judge(self.s,self.bad,self.good,1).verdict,Verdict.CONFIRMED)
 def test_repaired_stillfails(self):self.assertEqual(judge(self.s,self.bad,replace(self.good,failure_observed=True),1).verdict,Verdict.INCONCLUSIVE)
 def test_no_oracle_same_visual(self):self.assertEqual(judge(self.s,replace(self.bad,failure_observed=None),self.good,1).verdict,Verdict.VISUAL_ONLY)
 def test_no_positive_signal(self):self.assertEqual(judge(self.s,replace(self.bad,failure_observed=False),self.good,1).verdict,Verdict.NOT_REPRODUCED)
 def test_incomplete_not_negative(self):self.assertEqual(judge(self.s,replace(self.bad,completed=False,failure_observed=False),self.good,1).verdict,Verdict.INCONCLUSIVE)
 def test_missing_control(self):self.assertEqual(judge(self.s,self.bad,None,1).verdict,Verdict.INCONCLUSIVE)
 def test_wrong_fixture(self):self.assertEqual(judge(self.s,self.bad,replace(self.good,fixture_sha256=h('other')),1).verdict,Verdict.INCONCLUSIVE)
 def test_wrong_task(self):self.assertEqual(judge(self.s,replace(self.bad,task_sha256=h('other')),self.good,1).verdict,Verdict.INCONCLUSIVE)
 def test_wrong_build(self):self.assertEqual(judge(self.s,self.bad,replace(self.good,build_sha256=h('bad')),1).verdict,Verdict.INCONCLUSIVE)
 def test_same_build(self):self.assertEqual(judge(replace(self.s,repaired_build_sha256=h('bad')),self.bad,self.good,1).verdict,Verdict.INCONCLUSIVE)
 def test_goalnotreached(self):self.assertEqual(judge(self.s,self.bad,replace(self.good,goal_reached=False),1).verdict,Verdict.INCONCLUSIVE)
 def test_controlunknown(self):self.assertEqual(judge(self.s,self.bad,replace(self.good,failure_observed=None),1).verdict,Verdict.INCONCLUSIVE)
 def test_cancelled(self):self.assertEqual(judge(self.s,self.bad,self.good,2).verdict,Verdict.INCONCLUSIVE)
 def test_missing_positive(self):self.assertEqual(judge(self.s,None,self.good,1).verdict,Verdict.INCONCLUSIVE)
 def test_repeat_runid(self):self.assertEqual(judge(self.s,self.bad,replace(self.good,run_id='r1'),1).verdict,Verdict.INCONCLUSIVE)
 def test_fake_truth_string_notbool(self):self.assertEqual(judge(self.s,replace(self.bad,failure_observed='true'),self.good,1).verdict,Verdict.INCONCLUSIVE)
 def test_idempotent_persist(self):
  store=TerminalReceiptStore();self.addCleanup(store.close);d=judge(self.s,self.bad,self.good,1)
  a=store.save('request',self.s,self.bad,self.good,1,export_created=True,pair_binding_valid=True);b=store.save('request',self.s,self.bad,self.good,1,export_created=True,pair_binding_valid=True);self.assertTrue(a[0]);self.assertFalse(b[0]);self.assertEqual(a[1],b[1])
 def test_receipt_conflict(self):
  store=TerminalReceiptStore();self.addCleanup(store.close);store.save('req',self.s,self.bad,self.good,1,export_created=True,pair_binding_valid=True)
  with self.assertRaises(ValueError):store.save('req',self.s,self.bad,replace(self.good,failure_observed=True),1,export_created=True,pair_binding_valid=True)
 def test_cancel_fences_save(self):
  store=TerminalReceiptStore();self.addCleanup(store.close);store.cancel()
  with self.assertRaises(ValueError):store.save('req',self.s,self.bad,self.good,1,export_created=True,pair_binding_valid=True)
 def test_concurrent_receipt_singleinsert(self):
  store=TerminalReceiptStore();self.addCleanup(store.close);d=judge(self.s,self.bad,self.good,1)
  with ThreadPoolExecutor(max_workers=8) as p:out=list(p.map(lambda _:store.save('same',self.s,self.bad,self.good,1,export_created=True,pair_binding_valid=True)[0],range(40)))
  self.assertEqual(sum(out),1)
 def test_synthetic_demo_label(self):
  d=synthetic_demo();self.assertEqual(d['meta_calls'],0);self.assertEqual(d['android_runs'],0);self.assertEqual(d['evidence_level'],'SYNTHETIC_MOCK_TESTED')

 def test_string_false_flags_rejected(self):
  for field in ('completed','preconditions_verified','goal_reached','visual_match'):
   for value in ('false','true',1,0,[],{},None):
    for side in ('faulty','repaired'):
     with self.subTest(field=field,value=value,side=side):
      a,b=self.bad,self.good
      if side=='faulty':a=replace(a,**{field:value})
      else:b=replace(b,**{field:value})
      self.assertEqual(judge(self.s,a,b,1).verdict,Verdict.INCONCLUSIVE)
 def test_boolean_current_generation_rejected(self):
  with self.assertRaises(ValueError):judge(self.s,self.bad,self.good,True)
 def test_boolean_run_generation_rejected(self):self.assertEqual(judge(self.s,replace(self.bad,generation=True),self.good,1).verdict,Verdict.INCONCLUSIVE)
 def test_receipt_null_and_empty_ids_rejected(self):
  store=TerminalReceiptStore();self.addCleanup(store.close);d=judge(self.s,self.bad,self.good,1)
  for key in (None,'','  ',7,True,b'bytes','x'*121):
   with self.subTest(key=key):
    with self.assertRaises(ValueError):store.save(key,self.s,self.bad,self.good,1)
    self.assertEqual(store.db.execute('SELECT count(*) FROM receipts').fetchone()[0],0)
 def test_cannot_relabel_old_decision_as_new_generation(self):
  store=TerminalReceiptStore();self.addCleanup(store.close);d=judge(self.s,self.bad,self.good,1);store.cancel()
  with self.assertRaises(ValueError):store.save('old',self.s,self.bad,self.good,2)
 def test_decision_case_binding_present(self):self.assertEqual(len(judge(self.s,self.bad,self.good,1).case_manifest_sha256),64)


 def test_generation_invalid_range_and_types(self):
  for value in (True,1.0,'1',0,-1):
   with self.subTest(value=value):
    with self.assertRaises(ValueError):judge(self.s,self.bad,self.good,value)
 def test_fresh_after_cancel_can_save(self):
  store=TerminalReceiptStore();self.addCleanup(store.close);store.cancel()
  d=judge(self.s,replace(self.bad,generation=2),replace(self.good,generation=2),2)
  created,payload=store.save('fresh',self.s,replace(self.bad,generation=2),replace(self.good,generation=2),2,export_created=True,pair_binding_valid=True);self.assertTrue(created);self.assertEqual(payload['generation'],2)
 def test_sql_null_constraint_defense(self):
  import sqlite3
  store=TerminalReceiptStore();self.addCleanup(store.close)
  with self.assertRaises(sqlite3.IntegrityError):store.db.execute('INSERT INTO receipts VALUES(NULL,?,?)',('digest','{}'))


 def test_demo_matches_selected_f01_family(self):
  d=synthetic_demo();self.assertEqual(d['fault_family'],'F01_rename_cancel_persistence')
  self.assertEqual(d['actions'],['open_rename','select_preset_Today','cancel'])
  self.assertEqual(d['decision']['verdict'],Verdict.CONFIRMED)


 def test_strict_case_names_and_digests(self):
  for field,value in [('case_id',' '),('oracle_name',' oracle'),('task_sha256','task'),('fixture_sha256','A'*64),('faulty_build_sha256',' '*64),('case_id','x'*129)]:
   with self.subTest(field=field),self.assertRaises(ValueError):judge(replace(self.s,**{field:value}),self.bad,self.good,1)
 def test_strict_run_names_and_digests(self):
  for field,value in [('run_id','\t'),('case_id',' '),('oracle_name',' oracle'),('task_sha256','task'),('oracle_log_sha256','same-log'),('oracle_log_sha256','A'*64)]:
   with self.subTest(field=field):self.assertEqual(judge(self.s,replace(self.bad,**{field:value}),self.good,1).verdict,Verdict.INCONCLUSIVE)
 def test_shared_valid_digest_rejected(self):
  self.assertEqual(judge(self.s,self.bad,replace(self.good,oracle_log_sha256=self.bad.oracle_log_sha256),1).verdict,Verdict.INCONCLUSIVE)
 def test_wrong_typed_inputs_no_attribute_error(self):
  for bad in ({},1,'bad',True):self.assertEqual(judge(self.s,bad,self.good,1).verdict,Verdict.INCONCLUSIVE)
  with self.assertRaises(ValueError):judge({},self.bad,self.good,1)
 def test_public_save_refuses_caller_decision(self):
  store=TerminalReceiptStore();self.addCleanup(store.close)
  with self.assertRaises((TypeError,ValueError)):store.save('forge',Decision(Verdict.CONFIRMED,'forged','f','r',1,'a'*64),1)
  self.assertEqual(store.db.execute('SELECT count(*) FROM receipts').fetchone()[0],0)
 def test_store_default_release_missing_binding_is_inconclusive(self):
  store=TerminalReceiptStore();self.addCleanup(store.close)
  created,p=store.save('safe-default',self.s,self.bad,self.good,1)
  self.assertTrue(created);self.assertEqual(p['verdict'],Verdict.INCONCLUSIVE)
 def test_store_shared_receipt_cannot_confirm(self):
  store=TerminalReceiptStore();self.addCleanup(store.close)
  _,p=store.save('shared',self.s,self.bad,replace(self.good,oracle_log_sha256=self.bad.oracle_log_sha256),1,export_created=True,pair_binding_valid=True)
  self.assertEqual(p['verdict'],Verdict.INCONCLUSIVE)
 def test_input_evidence_change_conflicts_even_if_same_verdict(self):
  store=TerminalReceiptStore();self.addCleanup(store.close)
  store.save('key',self.s,self.bad,self.good,1,export_created=True,pair_binding_valid=True)
  with self.assertRaises(ValueError):store.save('key',self.s,replace(self.bad,oracle_log_sha256=h('new-log')),self.good,1,export_created=True,pair_binding_valid=True)
 def test_store_bad_types_fail_cleanly(self):
  store=TerminalReceiptStore();self.addCleanup(store.close)
  with self.assertRaises(ValueError):store.save('key',self.s,{},self.good,1)
  with self.assertRaises(ValueError):store.save('key',self.s,self.bad,self.good,1,pair_binding_valid='true')

if __name__=='__main__':unittest.main(verbosity=2)
