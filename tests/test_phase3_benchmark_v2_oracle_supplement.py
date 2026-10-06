"""Synthetic transparent-QA correction checks, never financial source truth."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from phase3_benchmark_v2_oracle_supplement import recompute_task, wrapped_row


class SupplementMechanisms(unittest.TestCase):
    def task(self, *, numerical=True, source_metadata=True):
        return {"evidence_checks": [{"evidence_id": "synthetic-e", "supported": False,
            "checks": {"exact_original_source_revision": False, "expected_evidence_present": True,
                       "exact_source_evidence_fields": source_metadata}, "failure_category": ["exact_original_source_revision"]}],
            "units": [{"unit_type": "numeric_claim", "name": "synthetic-f", "supported": False,
                "checks": {"all_original_source_inputs_supported": False, "fraction_numeric_value": numerical},
                "oracle": {"inputs": ["synthetic-e"]}, "failure_category": ["all_original_source_inputs_supported"]},
                {"unit_type": "hypothesis_state", "supported": False, "checks": {"all_claims_independently_supported": False,
                    "exact_status": True}, "expected_hypothesis": {"claim_names": ["synthetic-f"], "status": "supported"},
                    "failure_category": ["all_claims_independently_supported"]}],
            "expected_hypotheses": {"synthetic-h": {}}, "required_completion": {"missing_computable_fact_names": [],
                "checks": {"complete_independent_fact_set": False, "complete_independent_evidence_set": False,
                    "all_required_hypotheses_correct": False}, "required_checks": 1, "decisive_required_checks": 1}}

    def test_duplicate_proof_resolves_only_source_count_defect_and_preserves_baseline(self):
        task = self.task()
        result = recompute_task(task, {"synthetic-e": {"supported": True, "copies": 2}})
        self.assertTrue(result["evidence_checks"][0]["supported"])
        self.assertTrue(result["required_completion"]["completed"])
        self.assertFalse(task["evidence_checks"][0]["supported"])
        self.assertFalse(result["units"][0]["baseline_supported"])

    def test_duplicate_proof_cannot_bless_wrong_numeric_value_or_source_metadata(self):
        for kwargs in ({"numerical": False}, {"source_metadata": False}):
            with self.subTest(kwargs=kwargs):
                result = recompute_task(self.task(**kwargs), {"synthetic-e": {"supported": True}})
                self.assertFalse(result["required_completion"]["completed"])

    def test_wrapped_full_label_excludes_same_prefix_other_fields(self):
        text = "归属于母公司所有\n497,245,760.73 495,377,653.13\n者权益合计\n归属于母公司所有\n18,331,861.78 17,710,539.94\n者的净利润\n营业收入增长率 -9.50 15.50"
        row, values = wrapped_row(text, "归属于母公司所有者的净利润", 2)
        self.assertEqual(str(values[0]), "916593089/50")
        self.assertIn("净利润", row)
        self.assertNotIn("权益合计", row)
        with self.assertRaises(ValueError):
            wrapped_row(text + "\n归属于母公司所有者的净利润 1.00 2.00", "归属于母公司所有者的净利润", 2)


if __name__ == "__main__":
    unittest.main()
