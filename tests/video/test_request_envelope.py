import dataclasses,hashlib,json,tempfile,unittest
from pathlib import Path
from reproloop.video import ACTION_IDS,UploadedVideoReceipt,build_video_intent_request,decode_video_intent_response
from reproloop.video_frames import FrameObservation
from reproloop.lab import canonical
class RequestEnvelopeTests(unittest.TestCase):
 def setUp(self):
  capture={'fixture_sha256':'b'*64,'video_input_contract':'visible_native_input_markers','native_marker_restore_status':'VERIFIED','native_marker_receipts':[{'key':k,'phase':'enable','wanted':'1','observed':'1'}for k in('show_touches','pointer_location')]}
  self.upload=UploadedVideoReceipt('up','file-test','a'*64,100,30000,capture,'/private/upload.json',1,86401,'REPORTED_86400_SECONDS')
  self.frames=tuple(FrameObservation(timestamp_ms=(i+1)*1000,png_sha256='c'*64,width=720,height=1280,source_media_sha256='a'*64,data_url='data:image/png;base64,cG5n',pointer_candidate=None,pointer_status='ABSENT',ocr_regions=({'text':label,'confidence':1,'bounds':[1,2,3,4]},),prior_pointer_text_candidates=({'text':label,'confidence':1,'bounds':[1,2,3,4],'source_png_sha256':'c'*64,'timestamp_ms':i*1000},),pointer_location_changed=True,ocr_observer='macOS Vision')for i,label in enumerate(('Target task: Inbox','Rename','Today','Cancel')))
  payload,binding,self.mode=build_video_intent_request(self.upload,supplemental_frames=self.frames,frame_protocol='native_pointer_temporal_ocr_v3')
  self.envelope={'request_id':'req','payload_sha256':hashlib.sha256(canonical(payload)).hexdigest(),'source_binding':binding}
  value={'status':'candidate','initial_target_title':'Inbox','preset_label':'Today','summary':'Visible sequence','actions':[{'operation':op,'timestamp_ms':(i+1)*1000}for i,op in enumerate(ACTION_IDS)]}
  self.response={'model':'muse-spark-1.3','status':'completed','id':'resp_test','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(value)}]}],'usage':{'input_tokens':10,'output_tokens':10,'total_tokens':20}}
 def decode(self,**changes):
  values=dict(supplemental_frames=self.frames,frame_protocol='native_pointer_temporal_ocr_v3',mode=self.mode,request_envelope=self.envelope,persist=False);values.update(changes)
  return decode_video_intent_response(self.response,self.upload,'req','/private','/private/response.json',**values)
 def test_same_original_envelope_reconstructs_without_file_or_http_write(self):
  result=self.decode();self.assertEqual(result.input_grounding['matched_labels'],4);self.assertEqual(result.request_payload_sha256,self.envelope['payload_sha256'])
 def test_other_media_frames_rejected_on_preserved_path_too(self):
  other=tuple(dataclasses.replace(f,source_media_sha256='f'*64)for f in self.frames)
  with self.assertRaises(ValueError):self.decode(supplemental_frames=other)
 def test_unknown_protocol_mode_or_missing_envelope_never_gets_candidate(self):
  for change in({'frame_protocol':'typo'},{'frame_protocol':'candidates_v1'},{'mode':'typo'},{'request_envelope':None}):
   with self.assertRaises(ValueError):self.decode(**change)
 def test_request_hash_identity_and_source_binding_cannot_drift(self):
  for field,value in(('request_id','other'),('payload_sha256','f'*64),('source_binding',{})):
   bad=dict(self.envelope);bad[field]=value
   with self.assertRaises(ValueError):self.decode(request_envelope=bad)
