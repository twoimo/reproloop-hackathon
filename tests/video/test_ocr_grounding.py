import unittest
from types import SimpleNamespace
from reproloop.video import validate_ocr_candidate_labels
class GroundingTests(unittest.TestCase):
 def frames(self,last='Cancel'):
  return tuple(SimpleNamespace(pointer_location_changed=True,prior_pointer_text_candidates=({'text':label,'confidence':1,'bounds':[1,2,3,4],'source_png_sha256':'a'*64,'timestamp_ms':0},))for label in('Target task: Inbox','Rename','Today',last))
 def test_exact_lowlevel_candidates_agree(self):
  self.assertEqual(validate_ocr_candidate_labels('Inbox','Today',self.frames())['matched_labels'],4)
 def test_saved_video_or_missing_or_ambiguous_never_fills_model_action(self):
  for frames in(self.frames('Save'),self.frames()[:3],(SimpleNamespace(pointer_location_changed=True,prior_pointer_text_candidates=({'text':'Target task: Inbox'},{'text':'Other task: Errands'})),)+self.frames()[1:]):
   with self.assertRaises(ValueError):validate_ocr_candidate_labels('Inbox','Today',frames)
