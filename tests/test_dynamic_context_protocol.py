"""Strict context-reference actions; synthetic protocol checks, no financial truth."""
import json
import unittest

from stock_research.errors import ValidationError
from stock_research.research.dynamic_protocol import parse_action


class ContextActionTests(unittest.TestCase):
    def parse(self, action, **kwargs):
        return parse_action(json.dumps(action), ["financial", "calculation", "hypotheses", "verification"], [],
            version="dynamic-parent-domains-v2", context_catalog_ref="a" * 64,
            context_known_refs=["E:E1", "C:F1", "O:financial"], **kwargs)

    def action(self, **changes):
        return {"action": "disclose", "catalog_ref": "a" * 64, "refs": ["E:E1"],
                "plan": ["Inspect the existing authorized reference"], **changes}

    def test_current_references_are_canonical_and_cannot_request_new_authority(self):
        self.assertEqual(self.parse(self.action(refs=["O:financial", "E:E1"]))["refs"], ["E:E1", "O:financial"])
        for extra in ({"scope": "another-owner"}, {"cutoff": "2030-01-01T00:00:00+00:00"},
                      {"snapshot": "b" * 64}, {"value": "123"}, {"tool": "financial_child"}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                self.parse(self.action(**extra))

    def test_stale_unknown_duplicate_empty_and_oversized_references_reject(self):
        for changes in ({"catalog_ref": "b" * 64}, {"refs": ["E:guessed"]}, {"refs": []},
                        {"refs": ["E:E1", "E:E1"]}, {"refs": [True]}, {"refs": ["E:E1"] * 17}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.parse(self.action(**changes))

    def test_disclosure_action_does_not_exist_in_legacy_parent_or_child_protocols(self):
        for version in ("single-dynamic-v1", "single-dynamic-v2", "dynamic-parent-domains-v1",
                        "dynamic-parent-financial-v1", "financial-child-v1", "market-child-v1"):
            with self.subTest(version=version), self.assertRaises(ValidationError):
                parse_action(json.dumps(self.action()), ["financial"], [], version=version)


if __name__ == "__main__":
    unittest.main()
