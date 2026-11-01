import hashlib
import json,unittest
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from meta_protocol import *
class ContractTests(unittest.TestCase):
 def frame(self):return FrameBinding(hashlib.sha256(b'frame').hexdigest(),1080,1920,1)
 def call(self):return {'type':'computer_call','status':'completed','call_id':'call_1','pending_safety_checks':[],'actions':[{'type':'click','button':'left','x':20,'y':30}]}
 def test_video_documented_minimal_fields(self):
  p=video_request('file-example','Describe visible actions, not hidden state');self.assertEqual(p['model'],'muse-spark-1.3');self.assertIn('text',p);self.assertNotIn('response_format',p);self.assertFalse(p['store']);self.assertEqual(p['input'][0]['content'][1],{'type':'input_file','file_id':'file-example'});self.assertEqual(p['text']['format']['type'],'json_schema')
 def test_invalid_video_id(self):
  with self.assertRaises(ValueError):video_request('https://untrusted','prompt')
 def test_bad_output_budget(self):
  with self.assertRaises(ValueError):video_request('file-x','prompt',True)
 def test_strict_schema(self):
  s=strict_result_schema();self.assertFalse(s['additionalProperties']);self.assertEqual(set(s['required']),set(s['properties']))
 def test_computer_payload_no_invented_display_fields(self):
  p=computer_initial_request(b'\x89PNG\r\n\x1a\n','test-only bytes');self.assertEqual(p['tools'],[{'type':'computer'}])
 def test_mime_mismatch(self):
  with self.assertRaises(ValueError):computer_initial_request(b'JPEG','x')
 def test_valid_action(self):self.assertEqual(len(validate_computer_call(self.call(),self.frame(),self.frame())),1)
 def test_stale_generation(self):
  with self.assertRaises(ValueError):validate_computer_call(self.call(),self.frame(),FrameBinding(hashlib.sha256(b'frame').hexdigest(),1080,1920,2))
 def test_pending_safety(self):
  c=self.call();c['pending_safety_checks']=[{'id':'safety','code':'malicious','message':'stop'}]
  with self.assertRaises(ValueError):validate_computer_call(c,self.frame(),self.frame())
 def test_nonfinite_coordinates(self):
  c=self.call();c['actions'][0]['x']=float('nan')
  with self.assertRaises(ValueError):validate_computer_call(c,self.frame(),self.frame())
 def test_outside_coordinates(self):
  c=self.call();c['actions'][0]['x']=1080
  with self.assertRaises(ValueError):validate_computer_call(c,self.frame(),self.frame())
 def test_unknown_action(self):
  c=self.call();c['actions']=[{'type':'run_shell','text':'not allowed'}]
  with self.assertRaises(ValueError):validate_computer_call(c,self.frame(),self.frame())
 def test_unknown_fields(self):
  with self.assertRaises(ValueError):parse_candidate('{"status":"candidate","summary":"x","evidence_ids":[],"authorized":true}')
 def test_duplicate_keys(self):
  with self.assertRaises(ValueError):parse_candidate('{"status":"candidate","status":"uncertain","summary":"x","evidence_ids":[]}')
 def test_candidate_is_not_confirmed(self):self.assertEqual(parse_candidate('{"status":"candidate","summary":"visible symptom only","evidence_ids":["frame1"]}')['status'],'candidate')
 def test_cost_exact(self):self.assertEqual(estimate_usd(12000,0,2000),Decimal('.0235'))
 def test_invalid_cache_count(self):
  with self.assertRaises(ValueError):estimate_usd(1,2,1)
 def test_no_live_call_before_credit(self):
  with self.assertRaises(PermissionError):CreditAdmission().reserve('x',{'model':MODEL},Decimal('.1'))
 def test_budget_exhaustion(self):
  g=CreditAdmission(True,Decimal('.1'));g.reserve('x',{},Decimal('.1'))
  with self.assertRaises(PermissionError):g.reserve('y',{},Decimal('.01'))
 def test_idempotency_concurrent(self):
  g=CreditAdmission(True,Decimal('1'))
  with ThreadPoolExecutor(max_workers=8) as p:r=list(p.map(lambda _:g.reserve('same',{'p':1},Decimal('.1')),range(30)))
  self.assertEqual(sum(r),1);self.assertEqual(g.reserved,Decimal('.1'))
 def test_conflicting_retry(self):
  g=CreditAdmission(True,Decimal('1'));g.reserve('x',{'p':1},Decimal('.1'))
  with self.assertRaises(ValueError):g.reserve('x',{'p':2},Decimal('.1'))

 def test_unhashable_status_rejected(self):
  for status in ([],{}):
   with self.subTest(status=status):
    with self.assertRaises(ValueError):parse_candidate(json.dumps({'status':status,'summary':'x','evidence_ids':[]}))
 def test_unhashable_action_rejected(self):
  c=self.call();c['actions']=[{'type':[]}]
  with self.assertRaises(ValueError):validate_computer_call(c,self.frame(),self.frame())
 def test_huge_integer_coordinate_rejected_cleanly(self):
  c=self.call();c['actions'][0]['x']=10**400
  with self.assertRaises(ValueError):validate_computer_call(c,self.frame(),self.frame())
 def test_boolean_frame_generation_rejected(self):
  f=FrameBinding(hashlib.sha256(b'frame').hexdigest(),1080,1920,True)
  with self.assertRaises(ValueError):validate_computer_call(self.call(),f,f)
 def test_nested_json_rejected_cleanly(self):
  with self.assertRaises(ValueError):parse_candidate('['*1500+']'*1500)

 def test_fractional_pixels_rejected_but_integral_copy_normalized(self):
  for x in (.5,10.9):
   c=self.call();c['actions'][0]['x']=x
   with self.assertRaises(ValueError):validate_computer_call(c,self.frame(),self.frame())
  c=self.call();c['actions'][0]['x']=20.0
  out=validate_computer_call(c,self.frame(),self.frame())
  self.assertIs(type(out[0]['x']),int);self.assertIs(type(c['actions'][0]['x']),float)
 def test_current_frame_bool_fields_and_bad_type(self):
  from dataclasses import replace
  f=self.frame()
  for current in (replace(f,generation=True),replace(f,width=True),None,{},replace(f,digest='hash')):
   with self.subTest(current=current),self.assertRaises(ValueError):validate_computer_call(self.call(),f,current)
 def test_both_frame_strict_digest_and_types(self):
  from dataclasses import replace
  for f in (replace(self.frame(),digest=' '*64),replace(self.frame(),digest='A'*64),replace(self.frame(),generation=1.0)):
   with self.assertRaises(ValueError):validate_computer_call(self.call(),f,f)
 def test_bool_current_dimension_equal_one_rejected(self):
  from dataclasses import replace
  f=replace(self.frame(),width=1);c=self.call();c['actions'][0]['x']=0
  with self.assertRaises(ValueError):validate_computer_call(c,f,replace(f,width=True))
 def test_call_id_nonblank_canonical(self):
  for cid in (' ','\t',' call','call ',True,[]):
   c=self.call();c['call_id']=cid
   with self.assertRaises(ValueError):validate_computer_call(c,self.frame(),self.frame())
 def test_whitespace_evidence_ids_rejected(self):
  with self.assertRaises(ValueError):parse_candidate('{"status":"candidate","summary":"x","evidence_ids":[" "]}')

if __name__=='__main__':unittest.main(verbosity=2)
