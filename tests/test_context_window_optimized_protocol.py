"""Synthetic exact v6.1 metadata/wire contracts; no live model or financial truth."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_context_verification_decoupling as fixture_v4
import test_context_window_protocol as fixture_v6
import test_domain_agents_cli as fixture_cli
from stock_research.errors import ValidationError
from stock_research.models import canonical_json, digest
from stock_research.research import cli
from stock_research.research.context_telemetry import build_context_telemetry, overflow_context_telemetry
from stock_research.research.context_window import ContextMinimumViewExceeded, rebuild_window
from stock_research.research.dynamic_context import build_catalog
from stock_research.research.dynamic_contracts import AGENT_TOOLS, DYNAMIC_TOOLS, ParallelParentSpec, required_checks
from stock_research.research.dynamic_protocol import (
    OPTIMIZED_WINDOW_VERSION, SYSTEM_PARENT_PARALLEL_V6, SYSTEM_PARENT_PARALLEL_V6_1, WINDOW_VERSION,
    dynamic_messages, parse_action,
)


TOOLS = AGENT_TOOLS | DYNAMIC_TOOLS


class OptimizedWindowParserTests(unittest.TestCase):
    def parse(self, action):
        return parse_action(json.dumps(action), TOOLS, [], version=OPTIMIZED_WINDOW_VERSION,
            context_catalog_ref="a" * 64, context_known_refs=["O:financial", "E:E1"],
            context_known_cursors=["b" * 64])

    def action(self, **kwargs):
        return {"action": "context_read", "catalog_ref": "a" * 64, "plan": ["Inspect"], **kwargs}

    def test_read_parser_preserves_literal_registered_refs_and_cursors(self):
        self.assertEqual(self.parse(self.action(refs=["O:financial", "E:E1"]))["refs"], ["E:E1", "O:financial"])
        self.assertEqual(self.parse(self.action(cursor="b" * 64))["cursor"], "b" * 64)
        invalid = (self.action(refs=[]), self.action(refs=["E:unregistered"]),
            self.action(refs=["E:E1", "E:E1"]), self.action(cursor="c" * 64),
            self.action(refs=["E:E1"], cursor="b" * 64), self.action(cursor=True),
            {**self.action(refs=["E:E1"]), "action": "disclose"})
        for action in invalid:
            with self.subTest(action=action), self.assertRaises(ValidationError):
                self.parse(action)

    def test_metadata_tags_or_indexes_cannot_become_model_action_references(self):
        for action in (self.action(refs=[{"s": 0}]), self.action(refs=[0]),
            self.action(cursor={"s": 0}), {**self.action(refs=["E:E1"]), "catalog_ref": {"s": 0}},
            self.action(refs={"l": 0})):
            with self.subTest(action=action), self.assertRaises(ValidationError):
                self.parse(action)


class OptimizedWindowProtocolTests(unittest.TestCase):
    setUp = fixture_v4.VerificationDisclosureTests.setUp
    inputs = fixture_v4.VerificationDisclosureTests.inputs
    budget = fixture_v6.ContextWindowProtocolTests.budget

    def wire(self, *, version=OPTIMIZED_WINDOW_VERSION, max_bytes=12000, selection=None, **kwargs):
        _, datasets, computed, observations, revisions, checks = self.inputs()
        arguments = {"context_scope": self.f.access.scope, "context_run_id": fixture_v4.RUN,
            "parent_execution_checks": checks, "parent_execution_revisions": revisions,
            "parent_computed_sources": ["financial", "market"], "parent_dependency_ready": True,
            "parent_verification_inputs": {"computed_ref": digest(computed), "datasets_ref": digest(datasets)},
            "context_window_budget": self.budget(), "context_window_selection": selection}
        return dynamic_messages(self.request, TOOLS, observations, required_checks(self.request), ["Inspect"],
            max_bytes, version=version, **{**arguments, **kwargs})

    def raw(self, messages):
        from stock_research.research.context_window_metadata import decode_window_metadata_view
        return decode_window_metadata_view(json.loads(messages[1]["content"])["context"])

    def catalog(self):
        observations = self.inputs()[3]
        return build_catalog(self.request, sorted(observations, key=lambda item: item["tool"]),
            required_checks(self.request), scope=self.f.access.scope, run_id=fixture_v4.RUN)

    def test_old_v6_messages_metadata_and_system_keep_their_frozen_hashes(self):
        messages, metadata = self.wire(version=WINDOW_VERSION)
        self.assertEqual(digest(messages), "f7230350368fceac20f43344d5723bfb25703809477006d1d1c3d4902e5f1fce")
        self.assertEqual(digest(messages[0]["content"]), "5604b92d6f4395386c35c027c5a28fc84c3bee9b1144ab8dce8a1a7f92356c8e")
        self.assertEqual(digest(metadata), "bdd3e8891523303679ad8cba0a26146d16aed819d0e9659640eb03e5e723d542")
        self.assertEqual(metadata["bytes"], 11300)

    def test_new_version_round_trips_the_exact_server_window_descriptor(self):
        messages, metadata = self.wire()
        wrapper = json.loads(messages[1]["content"])["context"]
        raw = self.raw(messages)
        self.assertEqual(wrapper["schema"], "dynamic-context-window/v2")
        self.assertEqual(wrapper["metadata_schema"], "exact_window_metadata/v1")
        self.assertEqual(raw, rebuild_window(self.catalog(), metadata["window"],
            scope=self.f.access.scope, run_id=fixture_v4.RUN))
        self.assertEqual(metadata["window_wire_schema"], wrapper["schema"])
        self.assertEqual(metadata["window_metadata_schema"], wrapper["metadata_schema"])
        self.assertEqual(metadata["message_sha256"], digest(messages))
        self.assertEqual(metadata["bytes"], sum(len(message["content"].encode("utf-8")) for message in messages))
        self.assertLessEqual(metadata["bytes"], 12000)
        self.assertEqual(metadata["window_literal_bytes"], len(canonical_json(raw).encode("utf-8")))
        self.assertEqual(metadata["window_encoded_bytes"], len(canonical_json(wrapper).encode("utf-8")))

    def test_compile_measures_encoded_minimum_header_but_final_payload_requires_full_window(self):
        from stock_research.research import context_window_metadata as codec
        original = codec.encode_window_metadata_view
        calls = []
        def record(view, **kwargs):
            calls.append(("window_ref" in view, kwargs.get("header_mode", False)))
            return original(view, **kwargs)
        with patch.object(codec, "encode_window_metadata_view", side_effect=record):
            self.wire()
        self.assertIn((False, True), calls)
        self.assertIn((True, False), calls)
        self.assertFalse(calls[-1][1])

    def test_default_admission_keeps_original_v6_selected_pages_before_encoding(self):
        _, baseline = self.wire(version=WINDOW_VERSION)
        messages, optimized = self.wire()
        self.assertEqual(optimized["window_admission_mode"], "legacy_window_envelope/v1")
        self.assertEqual(optimized["window"]["pages"], baseline["window"]["pages"])
        self.assertEqual(optimized["visible_fact_count"], baseline["visible_fact_count"])
        self.assertEqual(optimized["visible_evidence_count"], baseline["visible_evidence_count"])
        self.assertLess(optimized["bytes"], baseline["bytes"])
        self.assertEqual(optimized["bytes"], sum(len(m["content"].encode("utf-8")) for m in messages))

    def test_only_typed_minimum_failure_uses_compressed_capacity_fallback(self):
        from stock_research.research import context_window as core
        original = core.compile_window
        calls = []
        def first_minimum(catalog, **kwargs):
            calls.append("admission_render" in kwargs)
            if kwargs.get("admission_render") is not None:
                raise ContextMinimumViewExceeded("synthetic literal minimum")
            return original(catalog, **kwargs)
        with patch.object(core, "compile_window", side_effect=first_minimum):
            _, metadata = self.wire()
        self.assertEqual(calls, [True, False])
        self.assertEqual(metadata["window_admission_mode"], "compact_capacity_fallback/v1")
        with patch.object(core, "compile_window", side_effect=ValidationError("synthetic integrity failure")) as compiler:
            with self.assertRaises(ValidationError):
                self.wire()
            self.assertEqual(compiler.call_count, 1)

    def test_authoritative_control_checks_and_verification_audit_survive_encoding(self):
        messages, metadata = self.wire()
        payload, raw = json.loads(messages[1]["content"]), self.raw(messages)
        self.assertEqual(payload["control"]["question"], self.request.question)
        self.assertEqual(payload["control"]["plan"], ["Inspect"])
        self.assertEqual(payload["control"]["context_budget"], self.budget())
        self.assertEqual(raw["required_checks"], required_checks(self.request))
        self.assertTrue(metadata["verification_ready"])
        self.assertIn("verification_brief", raw)
        self.assertIn("verification_audit", metadata)
        self.assertNotIn("verification_audit", messages[1]["content"])
        self.assertEqual(raw["range"]["cutoff"], self.request.as_of.isoformat())
        self.assertEqual(raw["range"]["pit_mode"], self.request.mode.value)

    def test_codec_only_change_retains_committed_fragment_boundaries_members_and_hash(self):
        # Freeze an old v6 exact object page and compile the identical committed
        # selection through v6.1. More capacity cannot rewrite its chosen end.
        from stock_research.research.context_window import select_next
        baseline, before = self.wire(version=WINDOW_VERSION)
        pending = select_next(self.catalog(), {"action": "context_read", "catalog_ref": before["catalog_ref"],
            "refs": ["O:financial"], "plan": ["Inspect"]}, before["window"],
            scope=self.f.access.scope, run_id=fixture_v4.RUN)
        _, original = self.wire(version=WINDOW_VERSION, selection=pending)
        selection = original["window_selection"]
        messages, optimized = self.wire(selection=selection)
        raw = self.raw(messages)
        self.assertEqual(optimized["window_selection"], selection)
        page = next(page for page in raw["pages"] if page["selection"] == selection)
        self.assertEqual(page["content_hash"], original["window"]["pages"][0]["content_hash"])
        self.assertEqual((page["start"], page["end"]), (selection["start"], selection["end"]))

    def test_minimum_view_error_and_original_authoritative_gates_remain(self):
        with self.assertRaises(ContextMinimumViewExceeded):
            self.wire(max_bytes=100)
        for arguments in ({"parent_computed_sources": ["financial"]},
                          {"parent_verification_inputs": None}, {"context_refs": ["O:financial"]},
                          {"context_stage": "finish"}):
            with self.subTest(arguments=arguments), self.assertRaises(ValidationError):
                self.wire(**arguments)

    def test_actual_bytes_and_semantic_fact_denominators_are_measured_separately(self):
        messages, metadata = self.wire()
        raw = self.raw(messages)
        _, _, computed, observations, _, _ = self.inputs()
        record = build_context_telemetry(messages, metadata, observations, self.request,
            run_id=fixture_v4.RUN, turn_id=1, route_type="dynamic_parallel")
        self.assertEqual(record["window_schema"], "dynamic-context-window/v2")
        self.assertEqual(record["total_context_bytes"], metadata["bytes"])
        self.assertEqual(record["total_fact_count"], len(computed["facts"]))
        self.assertEqual(record["total_evidence_count"], len(computed["evidence"]))
        self.assertEqual(record["window_pages"], [{key: page[key] for key in
            ("kind", "total", "start", "end", "has_more", "content_hash")} for page in raw["pages"]])
        self.assertEqual(record["dedup_saved_bytes"], metadata["window_literal_bytes"] - metadata["window_encoded_bytes"])
        self.assertIsNone(record["input_tokens"])
        self.assertIsNone(record["total_tokens"])
        self.assertFalse(record["verification_tool_execution_implied"])
        self.assertIsNone(record["lazy_disclosure_saved_bytes"])

    def test_nonprofitable_literal_fallback_is_measured_without_invented_codec_savings(self):
        from stock_research.research import context_window_metadata as codec
        with patch.object(codec, "encode_window_metadata_view", side_effect=lambda view, **_: deepcopy(view)):
            messages, metadata = self.wire()
        self.assertFalse(metadata["window_codec_applied"])
        self.assertEqual(metadata["window_wire_schema"], "dynamic-context-window/v1")
        self.assertIsNone(metadata["window_metadata_schema"])
        observations = self.inputs()[3]
        record = build_context_telemetry(messages, metadata, observations, self.request,
            run_id=fixture_v4.RUN, turn_id=1, route_type="dynamic_parallel")
        self.assertFalse(record["window_codec_applied"])
        self.assertEqual(record["window_encoded_bytes"], record["window_literal_bytes"])
        self.assertEqual(record["dedup_saved_bytes"], 0)
        self.assertEqual(record["total_context_bytes"], metadata["bytes"])

    def test_window_overflow_measurement_cannot_raise_cap_to_choose_different_pages(self):
        with patch("stock_research.research.dynamic_protocol.dynamic_messages") as builder:
            with self.assertRaises(ValidationError):
                overflow_context_telemetry(self.request, TOOLS, [], required_checks(self.request), [],
                    run_id=fixture_v4.RUN, turn_id=1, message_kwargs={"version": OPTIMIZED_WINDOW_VERSION})
            builder.assert_not_called()

    def test_new_identity_and_codec_prompt_preserve_defaults_limits_and_action_contract(self):
        optimized, baseline = ParallelParentSpec(version=OPTIMIZED_WINDOW_VERSION), ParallelParentSpec(version=WINDOW_VERSION)
        self.assertNotEqual(optimized.identity, baseline.identity)
        self.assertEqual(ParallelParentSpec().version, "dynamic-parent-parallel-v1")
        self.assertEqual(ParallelParentSpec().identity, "5120ebab68444745152040f21bdf1e21e65a73cc3d8da085ea1c4def453ebf00")
        for field in ("context_bytes", "max_decisions", "max_tools", "max_tokens", "max_seconds",
                      "root_max_decisions", "root_max_tools", "root_max_tokens", "no_progress_limit"):
            self.assertEqual(getattr(optimized, field), getattr(baseline, field))
        self.assertIn("Actions must emit decoded literal", SYSTEM_PARENT_PARALLEL_V6_1)
        self.assertIn("Only actual tool success", SYSTEM_PARENT_PARALLEL_V6_1)
        self.assertIn("No disclose", SYSTEM_PARENT_PARALLEL_V6_1)
        self.assertLessEqual(len(SYSTEM_PARENT_PARALLEL_V6_1.encode("utf-8")),
                             len(SYSTEM_PARENT_PARALLEL_V6.encode("utf-8")))
        self.assertEqual(len(SYSTEM_PARENT_PARALLEL_V6_1.encode("utf-8")), 2589)
        self.assertEqual(digest(SYSTEM_PARENT_PARALLEL_V6_1),
                         "e477a4ef6b13d7eb3924932ad52eb32ade05fba5fc7d7b316af1db0e8d3409a2")


class OptimizedWindowCLITests(unittest.TestCase):
    setUp = fixture_cli.DomainAgentsCLITests.setUp
    args = fixture_cli.DomainAgentsCLITests.args

    def test_optimized_option_requires_explicit_parallel_mode_before_credentials(self):
        args = self.args("--parallel-version", OPTIMIZED_WINDOW_VERSION, "--with-model")
        with patch.object(cli, "load_model_config") as config, self.assertRaises(ValidationError):
            cli.run(args, self.f.repo)
        config.assert_not_called()

    def test_optimized_preview_exposes_codec_without_starting_paid_state(self):
        args = self.args("--parallel-domains", "--parallel-version", OPTIMIZED_WINDOW_VERSION, "--preview-model")
        with patch.object(cli, "load_model_config") as config, patch.object(cli, "CheckpointStore") as store:
            result = cli.run(args, self.f.repo)
        self.assertEqual(result["status"], "preview")
        messages = json.loads((Path(args.output) / "model-messages.json").read_text(encoding="utf-8"))
        self.assertIn(json.loads(messages[1]["content"])["context"]["schema"],
                      {"dynamic-context-window/v1", "dynamic-context-window/v2"})
        config.assert_not_called()
        store.assert_not_called()


if __name__ == "__main__":
    unittest.main()
