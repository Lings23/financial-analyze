"""Frozen acceptance-envelope QA; no live model/provider calls or financial truth."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import phase4_p45_demo as demo
from stock_research.errors import IntegrityError


class ParallelDemoTests(unittest.TestCase):
    def test_prepare_freezes_new_task_two_required_domains_and_unchanged_cap(self):
        with TemporaryDirectory() as directory, patch.object(demo, "OUT", Path(directory)), \
                patch.object(demo, "load_model_config", return_value=SimpleNamespace(
                    model=demo.SPEC.model, endpoint="https://example.invalid/configured-test")):
            result = demo.prepare()
            plan = demo.old.read(Path(directory) / "plan.json")
            self.assertTrue(result["prepared"])
            self.assertEqual(result["model_calls"], 0)
            self.assertEqual(plan["context_limit_bytes"], 12000)
            self.assertEqual(plan["independent_new_task_count"], 1)
            self.assertFalse(plan["blind"])
            self.assertTrue(plan["underlying_sources_known_validation"])
            self.assertEqual({b["dataset"] for b in plan["item"]["request"]["bindings"]},
                             {"market_daily", "financial_income"})
            self.assertNotIn("api_key", json.dumps(plan))
            demo.checked(result["plan_sha256"])

    def intervals(self, directory, *, start_b="2026-10-05T00:00:01+00:00"):
        intents = []
        for number, role, start in ((1, "financial-child-v1", "2026-10-05T00:00:00+00:00"),
                                    (2, "market-child-v1", start_b)):
            prefix = f"{number:02d}"
            demo.old.write_new(directory / (prefix + "-dispatch.json"), {"role": role, "started_at": start})
            demo.old.write_new(directory / (prefix + "-interval.json"), {
                "role": role, "started_at": start, "finished_at": start[:17] + "05+00:00"})
            intents.append({"number": number, "task_id": demo.CASE_ID + "/" + role})
        return intents

    def test_actual_overlap_requires_overlapping_paid_domain_intervals(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            intents = self.intervals(root)
            self.assertTrue(demo.dispatch_overlap(root, intents))
            self.assertFalse(demo.dispatch_overlap(root, intents[:1]))

    def test_interval_identity_tamper_and_sequential_sections_are_detected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            intents = self.intervals(root, start_b="2026-10-05T00:01:00+00:00")
            self.assertFalse(demo.dispatch_overlap(root, intents))
            intents[0]["task_id"] = demo.CASE_ID + "/market-child-v1"
            with self.assertRaises(IntegrityError):
                demo.dispatch_overlap(root, intents)
