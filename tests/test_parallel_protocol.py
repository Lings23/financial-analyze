"""Synthetic M3 contract/protocol boundaries; no financial ground truth."""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research_fixtures import fixture
from study_fixtures import study_request
from stock_research.errors import PermissionDenied, ValidationError
from stock_research.research.dynamic_contracts import (
    AGENT_TOOLS, PARALLEL_VERSION, DomainParentSpec, DynamicRequest,
    FinancialChildSpec, MarketChildSpec, ParallelParentSpec, required_checks,
)
from stock_research.research.dynamic_protocol import (
    SYSTEM_PARENT_CONTEXT, SYSTEM_PARENT_PARALLEL, dynamic_messages, parse_action,
)


def parallel_action(**changes):
    return {"action": "parallel", "tools": ["market_child", "financial_child"],
            "plan": ["Read independent original bound sources"], **changes}


class ParallelProtocolTests(unittest.TestCase):
    def parse(self, action, available=AGENT_TOOLS, completed=(), version=PARALLEL_VERSION):
        return parse_action(json.dumps(action), available, completed, version=version)

    def test_new_parent_keeps_old_root_local_and_child_limits(self):
        spec = ParallelParentSpec()
        self.assertIsInstance(spec, DomainParentSpec)
        self.assertEqual(spec.version, PARALLEL_VERSION)
        self.assertEqual((spec.max_decisions, spec.max_tools, spec.max_tokens, spec.max_seconds),
                         (8, 12, 48000, 240))
        self.assertEqual((spec.root_max_decisions, spec.root_max_tools, spec.root_max_tokens), (16, 18, 96000))
        self.assertEqual(spec.max_children, 2)
        self.assertEqual(FinancialChildSpec().version, "financial-child-v1")
        self.assertEqual(MarketChildSpec().version, "market-child-v1")
        self.assertNotEqual(spec.identity, DomainParentSpec(version="dynamic-parent-domains-v2").identity)
        self.assertEqual(DomainParentSpec().version, "dynamic-parent-domains-v1")

    def test_context_cap_is_exactly_frozen_for_parallel(self):
        for limit in (11999, 12001, 14000, 16000, True):
            with self.subTest(limit=limit), self.assertRaises(ValidationError):
                ParallelParentSpec(context_bytes=limit)
        with self.assertRaises(ValidationError):
            replace(ParallelParentSpec(), max_children=3)

    def test_parallel_action_canonicalizes_only_two_independent_domain_branches(self):
        result = self.parse(parallel_action())
        self.assertEqual(result["tools"], ["financial_child", "market_child"])
        self.assertEqual(result["action"], "parallel")
        self.assertEqual(result, self.parse(parallel_action(tools=list(reversed(result["tools"])))))

    def test_parallel_is_not_a_model_defined_dag_or_scope_grant(self):
        for changes in ({"dependencies": []}, {"refs": []}, {"scope": "another"},
                        {"budget": "999999"}, {"deadline": "future"}, {"nodes": []},
                        {"tools": ["financial_child"]}, {"tools": ["financial_child", "financial_child"]},
                        {"tools": ["financial", "market"]}, {"tools": ["financial_child", "calculation"]},
                        {"tools": ["financial_child", True]}, {"tools": "financial_child"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.parse(parallel_action(**changes))

    def test_partial_authorization_rejects_before_any_child_can_start(self):
        for tools in ({"financial_child"}, {"market_child"}, set()):
            with self.subTest(tools=tools), self.assertRaises(PermissionDenied):
                self.parse(parallel_action(), available=tools)

    def test_completed_branch_cannot_be_restarted_via_group_action(self):
        for completed in ({"financial"}, {"market"}, {"financial_child"}, {"market_child"}):
            with self.subTest(completed=completed), self.assertRaises(ValidationError):
                self.parse(parallel_action(), completed=completed)

    def test_old_versions_and_leaf_children_cannot_request_parallel(self):
        for version in ("single-dynamic-v1", "single-dynamic-v2", "dynamic-parent-financial-v1",
                        "dynamic-parent-domains-v1", "dynamic-parent-domains-v2",
                        "financial-child-v1", "market-child-v1"):
            with self.subTest(version=version), self.assertRaises(ValidationError):
                self.parse(parallel_action(), available={"financial"}, version=version)

    def test_new_parallel_parent_reuses_identical_catalog_view(self):
        with TemporaryDirectory() as directory:
            f = fixture(Path(directory))
            request = DynamicRequest.from_dict({**study_request(f).to_dict(), "question": "SYNTHETIC bounded task"})
            kwargs = {"context_scope": f.access.scope, "context_run_id": "a" * 32}
            old_messages, old_meta = dynamic_messages(request, AGENT_TOOLS, [], required_checks(request), [],
                12000, version="dynamic-parent-domains-v2", **kwargs)
            new_messages, new_meta = dynamic_messages(request, AGENT_TOOLS, [], required_checks(request), [],
                12000, version=PARALLEL_VERSION, **kwargs)
            old_payload, new_payload = (json.loads(messages[1]["content"]) for messages in (old_messages, new_messages))
            self.assertEqual(new_payload["context"], old_payload["context"])
            self.assertEqual(new_payload["control"], old_payload["control"])
            self.assertEqual(new_payload["delegation_results"], old_payload["delegation_results"])
            self.assertEqual(old_messages[0]["content"], SYSTEM_PARENT_CONTEXT)
            self.assertEqual(new_messages[0]["content"], SYSTEM_PARENT_PARALLEL)
            self.assertIn("two serial Children", SYSTEM_PARENT_CONTEXT)
            self.assertNotIn("two serial Children", SYSTEM_PARENT_PARALLEL)
            self.assertEqual(new_meta["catalog_ref"], old_meta["catalog_ref"])

    def test_existing_direct_and_disclose_actions_continue_in_parallel_version(self):
        source = {"action": "tool", "tool": "financial", "refs": [], "plan": ["Read"]}
        self.assertEqual(self.parse(source, available={"financial"})["tool"], "financial")
        disclose = {"action": "disclose", "catalog_ref": "a" * 64, "refs": ["E:E1"], "plan": ["Inspect"]}
        result = parse_action(json.dumps(disclose), {"financial"}, (), version=PARALLEL_VERSION,
                              context_catalog_ref="a" * 64, context_known_refs=["E:E1"])
        self.assertEqual(result, disclose)


if __name__ == "__main__":
    unittest.main()
