"""Synthetic v6 wire/parser mechanisms; no live model or financial validation."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import test_context_verification_decoupling as fixture_v4
import test_domain_agents_cli as fixture_cli
from stock_research.errors import ValidationError
from stock_research.models import digest
from stock_research.research import cli
from stock_research.research.context_telemetry import build_context_telemetry, overflow_context_telemetry
from stock_research.research.dynamic_contracts import (
    AGENT_TOOLS, DYNAMIC_TOOLS, MAX_QUESTION_BYTES, ParallelParentSpec, required_checks,
)
from stock_research.research.dynamic_protocol import (
    SYSTEM_PARENT_PARALLEL_V6, WINDOW_VERSION, dynamic_messages, parse_action,
)


CATALOG = "a" * 64
CURSOR = "b" * 64
TOOLS = DYNAMIC_TOOLS | AGENT_TOOLS


class ContextReadParserTests(unittest.TestCase):
    def parse(self, action, **kwargs):
        return parse_action(json.dumps(action), TOOLS, [], version=WINDOW_VERSION,
            context_catalog_ref=CATALOG, context_known_refs=["E:E1", "C:F1"],
            context_known_cursors=[CURSOR], **kwargs)

    def action(self, **kwargs):
        return {"action": "context_read", "catalog_ref": CATALOG, "plan": ["Inspect"], **kwargs}

    def test_exact_ref_and_cursor_forms_accept_only_registered_members(self):
        self.assertEqual(self.parse(self.action(refs=["E:E1", "C:F1"]))["refs"], ["C:F1", "E:E1"])
        self.assertEqual(self.parse(self.action(cursor=CURSOR))["cursor"], CURSOR)
        invalid = (self.action(), self.action(refs=[]), self.action(refs=["E:hidden"]),
            self.action(refs=["E:E1", "E:E1"]), self.action(refs="E:E1"),
            self.action(cursor="c" * 64), self.action(cursor=CURSOR.upper()),
            self.action(refs=["E:E1"], cursor=CURSOR), self.action(cursor=CURSOR, path="/tmp"),
            {**self.action(refs=["E:E1"]), "catalog_ref": "d" * 64},
            self.action(refs=[1]), self.action(cursor=True), self.action(cursor=CURSOR, plan=[]))
        for action in invalid:
            with self.subTest(action=action), self.assertRaises(ValidationError):
                self.parse(action)

    def test_refs_bound_is_sixteen_and_current_window_not_entire_catalog(self):
        refs = ["E:" + str(index) for index in range(17)]
        for count in (1, 16):
            parsed = parse_action(json.dumps(self.action(refs=refs[:count])), TOOLS, [],
                version=WINDOW_VERSION, context_catalog_ref=CATALOG, context_known_refs=refs)
            self.assertEqual(len(parsed["refs"]), count)
        with self.assertRaises(ValidationError):
            parse_action(json.dumps(self.action(refs=refs)), TOOLS, [], version=WINDOW_VERSION,
                context_catalog_ref=CATALOG, context_known_refs=refs)
        with self.assertRaises(ValidationError):
            self.parse(self.action(refs=["O:in_catalog_but_not_this_window"]))

    def test_disclose_is_legacy_only_and_context_read_is_v6_only(self):
        action = self.action(refs=["E:E1"])
        with self.assertRaises(ValidationError):
            self.parse({**action, "action": "disclose"})
        for version in ("dynamic-parent-domains-v2", *("dynamic-parent-parallel-v" + str(i) for i in range(1, 6))):
            with self.subTest(version=version), self.assertRaises(ValidationError):
                parse_action(json.dumps(action), TOOLS, [], version=version,
                             context_catalog_ref=CATALOG, context_known_refs=["E:E1"])
            self.assertEqual(parse_action(json.dumps({**action, "action": "disclose"}), TOOLS, [],
                version=version, context_catalog_ref=CATALOG, context_known_refs=["E:E1"])["action"], "disclose")

    def test_duplicate_keys_numeric_values_and_extra_trusted_fields_rejected(self):
        raw = '{"action":"context_read","catalog_ref":"' + CATALOG + '","cursor":"' + CURSOR + '",'
        for content in (raw + '"cursor":"' + CURSOR + '","plan":["Inspect"]}',
                        raw + '"plan":[1]}'):
            with self.assertRaises(ValidationError):
                parse_action(content, TOOLS, [], version=WINDOW_VERSION,
                    context_catalog_ref=CATALOG, context_known_cursors=[CURSOR])
        for field in ("window_ref", "scope", "cutoff", "state_versions", "completed_checks"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.parse(self.action(cursor=CURSOR, **{field: "forged"}))


class ContextWindowProtocolTests(unittest.TestCase):
    setUp = fixture_v4.VerificationDisclosureTests.setUp
    inputs = fixture_v4.VerificationDisclosureTests.inputs

    def budget(self, available=True):
        return {"decisions_remaining": 8, "tools_remaining": 12, "tokens_remaining": 48000,
            "root_remaining": {"decisions": 16, "tools": 18, "tokens": 96000},
            "deadline": "2026-10-07T12:00:00+08:00", "required_actions_remaining": 2,
            "context_read_available": available}

    def wire(self, *, budget=None, max_bytes=12000, request=None, plan=None, **kwargs):
        request = request or self.request
        _, datasets, computed, observations, revisions, checks = self.inputs(request)
        return dynamic_messages(request, TOOLS, observations, required_checks(request),
            ["Inspect"] if plan is None else plan, max_bytes, version=WINDOW_VERSION, context_scope=self.f.access.scope,
            context_run_id=fixture_v4.RUN, parent_execution_checks=checks,
            parent_execution_revisions=revisions, parent_computed_sources=["financial", "market"],
            parent_dependency_ready=True,
            parent_verification_inputs={"computed_ref": digest(computed), "datasets_ref": digest(datasets)},
            context_window_budget=self.budget() if budget is None else budget, **kwargs)

    def test_window_builder_binds_exact_wire_authoritative_brief_and_external_audit(self):
        messages, metadata = self.wire()
        context = json.loads(messages[1]["content"])["context"]
        self.assertEqual(messages[0]["content"], SYSTEM_PARENT_PARALLEL_V6)
        self.assertEqual(context["schema"], "dynamic-context-window/v1")
        self.assertEqual(metadata["window"]["window_ref"], context["window_ref"])
        self.assertEqual(metadata["window"]["catalog_ref"], metadata["catalog_ref"])
        self.assertEqual(metadata["message_sha256"], digest(messages))
        self.assertEqual(metadata["bytes"], sum(len(m["content"].encode("utf-8")) for m in messages))
        self.assertLessEqual(metadata["bytes"], 12000)
        self.assertTrue(metadata["verification_ready"])
        self.assertIn("verification_brief", context)
        self.assertIn("verification_audit", metadata)
        self.assertNotIn("verification_audit", messages[1]["content"])
        self.assertNotIn("verification_manifest", messages[1]["content"])

    def test_authoritative_budget_is_preserved_and_invalid_budget_stops_locally(self):
        budget = self.budget(False)
        messages, metadata = self.wire(budget=budget)
        self.assertEqual(json.loads(messages[1]["content"])["control"]["context_budget"], budget)
        self.assertEqual(metadata["window"]["allowed_cursors"], [])
        invalid = ({**budget, "decisions_remaining": True}, {**budget, "deadline": "2026-10-07T12:00:00"},
            {**budget, "root_remaining": {"decisions": -1, "tools": 18, "tokens": 96000}},
            {**budget, "extra": "forged"}, {**budget, "context_read_available": 1})
        for changed in invalid:
            with self.subTest(budget=changed), self.assertRaises(ValidationError):
                self.wire(budget=changed)

    def test_window_inherits_authoritative_complete_sources_and_revision_gates(self):
        _, datasets, computed, observations, revisions, checks = self.inputs()
        arguments = {"version": WINDOW_VERSION, "context_scope": self.f.access.scope,
            "context_run_id": fixture_v4.RUN, "parent_execution_checks": checks,
            "parent_execution_revisions": revisions, "parent_computed_sources": ["financial", "market"],
            "parent_dependency_ready": True,
            "parent_verification_inputs": {"computed_ref": digest(computed), "datasets_ref": digest(datasets)},
            "context_window_budget": self.budget()}
        for altered in ({"parent_computed_sources": ["financial"]},
                        {"parent_execution_revisions": {**revisions, "hypotheses": "c" * 64}},
                        {"parent_verification_inputs": None}, {"context_stage": "finish"}):
            with self.subTest(altered=altered), self.assertRaises(ValidationError):
                dynamic_messages(self.request, TOOLS, observations, required_checks(self.request), [], 12000,
                                 **{**arguments, **altered})

    def test_legacy_versions_reject_window_budget_without_changing_existing_inputs(self):
        for version in ("single-dynamic-v2", "dynamic-parent-parallel-v5"):
            with self.subTest(version=version), self.assertRaises(ValidationError):
                dynamic_messages(self.request, TOOLS, [], required_checks(self.request), [], 12000,
                    version=version, context_window_budget=self.budget())

    def test_long_question_plan_preserved_or_minimum_view_failure(self):
        from stock_research.research.context_window import ContextMinimumViewExceeded
        question = "合成：" + "x" * (MAX_QUESTION_BYTES - len("合成：".encode("utf-8")))
        request = replace(self.request, question=question)
        plan = ["计" * 80, "划" * 80, "核" * 80, "验" * 80, "。" * 80]
        try:
            messages, metadata = self.wire(request=request, plan=plan)
        except ContextMinimumViewExceeded:
            return  # Explicit bounded failure preserves the immutable control input.
        control = json.loads(messages[1]["content"])["control"]
        self.assertEqual(control["question"], question)
        self.assertEqual(control["plan"], plan)
        with self.assertRaises(ContextMinimumViewExceeded):
            self.wire(max_bytes=100)
        self.assertEqual(metadata["bytes"], sum(len(m["content"].encode("utf-8")) for m in messages))

    def test_telemetry_measures_exact_window_and_preserves_full_fact_denominator(self):
        messages, metadata = self.wire()
        _, _, computed, observations, _, _ = self.inputs()
        with patch("stock_research.research.dynamic_context.expand_view", side_effect=AssertionError("legacy expansion")):
            telemetry = build_context_telemetry(messages, metadata, observations, self.request,
                run_id=fixture_v4.RUN, turn_id=1, route_type="dynamic_parallel")
        self.assertEqual(telemetry["window_ref"], metadata["window"]["window_ref"])
        self.assertEqual(telemetry["total_fact_count"], len(computed["facts"]))
        self.assertEqual(telemetry["total_evidence_count"], len(computed["evidence"]))
        self.assertEqual(telemetry["total_context_bytes"], metadata["bytes"])
        self.assertFalse(telemetry["verification_tool_execution_implied"])
        self.assertIsNone(telemetry["lazy_disclosure_saved_bytes"])
        corrupted = deepcopy(metadata)
        corrupted["visible_fact_count"] = 0
        if corrupted["visible_fact_count"] != metadata["visible_fact_count"]:
            with self.assertRaises(ValidationError):
                build_context_telemetry(messages, corrupted, observations, self.request,
                    run_id=fixture_v4.RUN, turn_id=1, route_type="dynamic_parallel")

    def test_window_overflow_measurement_cannot_raise_cap_and_reselect_pages(self):
        with patch("stock_research.research.dynamic_protocol.dynamic_messages") as builder:
            with self.assertRaises(ValidationError):
                overflow_context_telemetry(self.request, TOOLS, [], required_checks(self.request), [],
                    run_id=fixture_v4.RUN, turn_id=1, message_kwargs={"version": WINDOW_VERSION})
            builder.assert_not_called()

    def test_explicit_v6_identity_preserves_parent_default_and_limits(self):
        spec = ParallelParentSpec(version=WINDOW_VERSION)
        baseline = ParallelParentSpec()
        self.assertEqual(baseline.version, "dynamic-parent-parallel-v1")
        self.assertNotEqual(spec.identity, baseline.identity)
        for field in ("context_bytes", "max_decisions", "max_tools", "max_tokens", "max_seconds",
                      "root_max_decisions", "root_max_tools", "root_max_tokens", "no_progress_limit"):
            self.assertEqual(getattr(spec, field), getattr(baseline, field))


class ContextWindowCLITests(unittest.TestCase):
    setUp = fixture_cli.DomainAgentsCLITests.setUp
    args = fixture_cli.DomainAgentsCLITests.args

    def test_v6_option_requires_explicit_parallel_mode_before_credentials(self):
        args = self.args("--parallel-version", WINDOW_VERSION, "--with-model")
        with patch.object(cli, "load_model_config") as config, self.assertRaises(ValidationError):
            cli.run(args, self.f.repo)
        config.assert_not_called()

    def test_v6_preview_uses_same_parent_without_creating_paid_state(self):
        args = self.args("--parallel-domains", "--parallel-version", WINDOW_VERSION, "--preview-model")
        with patch.object(cli, "load_model_config") as config, patch.object(cli, "CheckpointStore") as store:
            result = cli.run(args, self.f.repo)
        self.assertEqual(result["status"], "preview")
        config.assert_not_called()
        store.assert_not_called()


if __name__ == "__main__":
    unittest.main()
