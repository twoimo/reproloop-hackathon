from dataclasses import replace
import unittest
from evaluation_metrics import *
class MetricsTests(unittest.TestCase):
 def row(self):return EvaluationRow('P1',True,True,True,True,False,True,Verdict.CONFIRMED)
 def test_correct_pair_is_not_fixed_falsepositive(self):
  s=summarize([self.row()],['P1']);self.assertEqual(s['primary_valid_export_pairs']['count'],1);self.assertEqual(s['fixed_failure_signals']['positive'],0);self.assertEqual(s['invalid_pair_confirmations']['count'],0)
 def test_fixed_positive_and_invalid_confirm_are_separate(self):
  s=summarize([replace(self.row(),fixed_failure=True)],['P1']);self.assertEqual(s['fixed_failure_signals']['positive'],1);self.assertEqual(s['invalid_pair_confirmations']['count'],1);self.assertEqual(s['primary_valid_export_pairs']['count'],0)
 def test_fixed_incomplete_not_negative(self):
  s=summarize([replace(self.row(),fixed_complete=False,fixed_failure=None,pair_verdict=Verdict.INCONCLUSIVE)],['P1']);self.assertEqual(s['fixed_failure_signals']['complete_with_signal'],0);self.assertIsNone(s['fixed_failure_signals']['fraction'])
 def test_missing_export_manualcontrol_does_not_inflate_primary(self):
  s=summarize([replace(self.row(),export_created=False,pair_verdict=Verdict.INCONCLUSIVE)],['P1']);self.assertEqual(s['primary_valid_export_pairs']['count'],0);self.assertEqual(s['fixed_failure_signals']['complete_with_signal'],1)
 def test_missing_script_reset_binding_invalidates_confirm(self):
  s=summarize([replace(self.row(),pair_binding_valid=False)],['P1']);self.assertEqual(s['invalid_pair_confirmations']['count'],1)
 def test_unknown_oracle_does_not_count_known_negative(self):
  s=summarize([replace(self.row(),fixed_failure=None,pair_verdict=Verdict.INCONCLUSIVE)],['P1']);self.assertEqual(s['fixed_failure_signals']['missing_or_unknown'],1)
 def test_synthetic_five_rows(self):
  s=synthetic_worked_example();self.assertEqual(s['primary_valid_export_pairs']['fraction'],'3/5');self.assertEqual(s['fixed_failure_signals']['fraction'],'0/3');self.assertEqual(s['fixed_failure_signals']['missing_or_unknown'],2);self.assertEqual(s['invalid_pair_confirmations']['fraction'],'0/5');self.assertEqual(s['actual_pilot_runs'],0)
 def test_missing_planned_row_rejected(self):
  with self.assertRaises(ValueError):summarize([self.row()],['P1','P2'])
 def test_duplicate_result_rejected(self):
  with self.assertRaises(ValueError):summarize([self.row(),self.row()],['P1'])
 def test_wrong_types_rejected(self):
  with self.assertRaises(ValueError):summarize([replace(self.row(),fixed_complete='false')],['P1'])
 def test_empty_denominator_explicit(self):
  s=summarize([],[]);self.assertIsNone(s['primary_valid_export_pairs']['fraction']);self.assertIsNone(s['invalid_pair_confirmations']['fraction'])
 def test_valid_evidence_but_abstained_is_not_export_success(self):
  s=summarize([replace(self.row(),pair_verdict=Verdict.INCONCLUSIVE)],['P1']);self.assertEqual(s['primary_valid_export_pairs']['count'],0);self.assertEqual(s['invalid_pair_confirmations']['count'],0)
if __name__=='__main__':unittest.main(verbosity=2)
