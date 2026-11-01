import dataclasses,unittest
from hashlib import sha256
from reproloop.runtime.owned import Frame,Node,OwnedTarget,RuntimeStop,PACKAGE
from reproloop.runtime.driver import ActionRequest
from reproloop.explore import review_and_lift,scoped_synthetic_lab_review,GENERIC_CHECK
class Reviews(unittest.TestCase):
 def setUp(self):
  self.t=OwnedTarget('emulator-5554','ReproLoop_Test','owner','boot','a'*64,'run',1)
  self.f=Frame(self.t.binding,1,b'png',b'<xml/>',100,100,(Node(PACKAGE+':id/task_target','Target task: Inbox',True,(10,10,90,90)),))
  self.c={'type':'computer_call','status':'completed','call_id':'call_test','actions':[{'type':'click','button':'left','x':25,'y':30}],'pending_safety_checks':[{'id':'opaque-check','code':GENERIC_CHECK[0],'message':GENERIC_CHECK[1]}]}
 def test_default_denies_and_scoped_developer_review_requires_exact_target(self):
  with self.assertRaises(RuntimeStop):review_and_lift(self.c,self.f,self.t,0)
  a,trace,loc,r=review_and_lift(self.c,self.f,self.t,0,scoped_synthetic_lab_review);self.assertTrue(r.approved);self.assertEqual((a['x'],a['y']),(25,30));self.assertEqual(self.c['pending_safety_checks'][0]['id'],'opaque-check')
 def test_unknown_check_and_wrong_step_do_not_auto_ack(self):
  c=dict(self.c);c['pending_safety_checks']=[dict(self.c['pending_safety_checks'][0],code='malicious_instructions')]
  for call,step in ((c,0),(self.c,1)):
   with self.assertRaises(RuntimeStop):review_and_lift(call,self.f,self.t,step,scoped_synthetic_lab_review)
 def test_outside_target_and_missing_checks_fail(self):
  c=dict(self.c);c['actions']=[dict(self.c['actions'][0],x=95)]
  with self.assertRaises((RuntimeStop,ValueError)):review_and_lift(c,self.f,self.t,0,scoped_synthetic_lab_review)
  c=dict(self.c);c.pop('pending_safety_checks')
  with self.assertRaises(RuntimeStop):review_and_lift(c,self.f,self.t,0,scoped_synthetic_lab_review)
 def test_native_point_must_stay_in_exact_selector(self):
  self.assertEqual(self.f.resolve(PACKAGE+':id/task_target','Target task: Inbox',25,30),(25,30))
  with self.assertRaises(RuntimeStop):self.f.resolve(PACKAGE+':id/task_target','Target task: Inbox',95,30)
  for xy in ((True,1),(1,None),(-1,4)):
   with self.assertRaises(ValueError):ActionRequest('a','r','tap','b'*64,x=xy[0],y=xy[1])

class PhaseReviewRegression(unittest.TestCase):
 setUp=Reviews.setUp
 def test_background_target_under_rename_phase_is_not_approved(self):
  f=dataclasses.replace(self.f,nodes=self.f.nodes+(Node(PACKAGE+':id/cancel_edit','Cancel',True,(90,90,99,99)),))
  with self.assertRaises(RuntimeStop):review_and_lift(self.c,f,self.t,0,scoped_synthetic_lab_review)

class PublicObservationControls(unittest.TestCase):
 def test_visible_candidates_and_geometry_only(self):
  from reproloop.explore import public_ui_observation
  t=OwnedTarget('emulator-5554','ReproLoop_Test','owner','boot','a'*64,'run',1)
  f=Frame(t.binding,1,b'png',b'<xml/>',100,100,(Node(PACKAGE+':id/rename_open','Rename',True,(10,20,90,80)),))
  text=public_ui_observation(f)
  self.assertIn('"center":[50,50]',text);self.assertIn('"width":100',text)
  for hidden in ('build_mode','fixture_id','failure_observed','oracle_log','apk_sha256','reset_receipt'):
   self.assertNotIn(hidden,text)
