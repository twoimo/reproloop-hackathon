import dataclasses,unittest
from types import SimpleNamespace
from reproloop.explore import validated_video_goal
from reproloop.video import VideoIntent,UploadedVideoReceipt,ACTION_IDS
from reproloop.runtime.owned import Frame,Node,PACKAGE,RuntimeStop
class VideoGoalTests(unittest.TestCase):
 def setUp(self):
  self.spec=SimpleNamespace(fixture_sha256='b'*64)
  receipt=UploadedVideoReceipt('req','file-test','a'*64,100,30000,{'fixture_sha256':'b'*64},'/private/response.json',1,86401,'REPORTED_86400_SECONDS')
  self.intent=VideoIntent('a'*64,receipt,'model-request','resp_test','c'*64,'Inbox','Today',tuple({'operation':op,'timestamp_ms':(i+1)*1000}for i,op in enumerate(ACTION_IDS)),'Visible sequence','Select Target task: Inbox, open Rename, choose Today, then press Cancel.',{},'/private/intent.json',request_payload_sha256='d'*64)
  self.frame=Frame('binding',1,b'png',b'xml',100,100,(Node(PACKAGE+':id/task_target','Target task: Inbox',True,(10,10,90,90)),))
 def test_candidate_data_matches_current_public_target(self):
  self.assertIn('Inbox',validated_video_goal(self.intent,self.frame,self.spec))
 def test_uncertain_or_missing_action_does_not_get_text_fallback(self):
  for value in (dataclasses.replace(self.intent,status='uncertain'),dataclasses.replace(self.intent,actions=self.intent.actions[:3])):
   with self.assertRaises(RuntimeStop):validated_video_goal(value,self.frame,self.spec)
 def test_media_fixture_target_and_derived_goal_must_match(self):
  bad=[dataclasses.replace(self.intent,media_sha256='f'*64),dataclasses.replace(self.intent,candidate_goal_text='Click Save'),dataclasses.replace(self.intent,initial_target_title='Other')]
  for value in bad:
   with self.assertRaises(RuntimeStop):validated_video_goal(value,self.frame,self.spec)
  with self.assertRaises(RuntimeStop):validated_video_goal(self.intent,self.frame,SimpleNamespace(fixture_sha256='f'*64))

 def test_v4_sampled_context_and_media_required(self):
  from reproloop.video import OBSERVATION_MODE_V4
  grounding=dict(type='SAMPLED_PRIOR_OCR_POINT_SCENE_AGREEMENT_V4',matched_labels=4,attestation=False,source_media_sha256=self.intent.media_sha256)
  value=dataclasses.replace(self.intent,input_observation_mode=OBSERVATION_MODE_V4,input_grounding=grounding)
  self.assertIn('Inbox',validated_video_goal(value,self.frame,self.spec))
  for change in (dict(type='unknown'),dict(matched_labels=3),dict(attestation=True),dict(source_media_sha256='f'*64)):
   with self.assertRaises(RuntimeStop):validated_video_goal(dataclasses.replace(value,input_grounding={**grounding,**change}),self.frame,self.spec)
 def test_unknown_observation_mode_never_admitted(self):
  with self.assertRaises(RuntimeStop):validated_video_goal(dataclasses.replace(self.intent,input_observation_mode='typo'),self.frame,self.spec)
