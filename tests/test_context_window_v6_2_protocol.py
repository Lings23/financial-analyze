"""Synthetic v6.2 requested-capacity/compatibility; no external financial validation."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_context_verification_decoupling as v4
import test_context_window_optimized_protocol as v61
import test_domain_agents_cli as fixture_cli
from test_dynamic import SequenceModel, completed_actions
from stock_research.errors import PermissionDenied, ValidationError
from stock_research.models import digest
from stock_research.research import cli
from stock_research.research.context_telemetry import build_context_telemetry, overflow_context_telemetry
from stock_research.research.context_window import ContextMinimumViewExceeded, rebuild_window, select_next
from stock_research.research.dynamic_contracts import ParallelParentSpec
from stock_research.research.dynamic_protocol import (
    OPTIMIZED_WINDOW_VERSION, REQUESTED_WINDOW_ADMISSION_POLICY, REQUESTED_WINDOW_VERSION,
    SYSTEM_PARENT_PARALLEL_V6_1, SYSTEM_PARENT_PARALLEL_V6_2, parse_action,
)


VERSION = REQUESTED_WINDOW_VERSION
RUN = "d" * 32


class RequestedCapacityParserTests(unittest.TestCase):
    action = v61.OptimizedWindowParserTests.action
    test_read_parser_preserves_literal_registered_refs_and_cursors = v61.OptimizedWindowParserTests.test_read_parser_preserves_literal_registered_refs_and_cursors
    test_metadata_tags_or_indexes_cannot_become_model_action_references = v61.OptimizedWindowParserTests.test_metadata_tags_or_indexes_cannot_become_model_action_references

    def parse(self, action):
        return parse_action(json.dumps(action), v61.TOOLS, [], version=VERSION,
            context_catalog_ref="a" * 64, context_known_refs=["O:financial", "E:E1"],
            context_known_cursors=["b" * 64])


class RequestedCapacityProtocolTests(unittest.TestCase):
    setUp = v4.VerificationDisclosureTests.setUp
    inputs = v4.VerificationDisclosureTests.inputs
    budget = v61.OptimizedWindowProtocolTests.budget
    catalog = v61.OptimizedWindowProtocolTests.catalog
    raw = v61.OptimizedWindowProtocolTests.raw

    def wire(self, *, version=VERSION, **kwargs):
        return v61.OptimizedWindowProtocolTests.wire(self, version=version, **kwargs)

    def pending_selection(self):
        _, metadata = self.wire()
        return select_next(self.catalog(), {"action": "context_read", "catalog_ref": metadata["catalog_ref"],
            "refs": ["O:hypotheses"], "plan": ["Inspect"]}, metadata["window"],
            scope=self.f.access.scope, run_id=v4.RUN)

    def test_v6_1_wire_metadata_spec_and_prompt_are_still_exact(self):
        messages, metadata = self.wire(version=OPTIMIZED_WINDOW_VERSION)
        self.assertEqual(digest(messages), "670a10cf7477782db6f8187e2f0cb99805668c6be57fe610c694d8f4f85e23f2")
        self.assertEqual(digest(metadata), "fdc8185140b12913bf397e7bdbe6fa561f2cd6edb3e400e035891ccc351581b4")
        self.assertEqual(metadata["bytes"], 9956)
        self.assertEqual(ParallelParentSpec(version=OPTIMIZED_WINDOW_VERSION).identity,
                         "9532afb24400da93f8951b200a24b3eca6f48522e5257ec76517ceab39b5afd5")
        self.assertEqual(SYSTEM_PARENT_PARALLEL_V6_2, SYSTEM_PARENT_PARALLEL_V6_1)

    def test_unrequested_previews_keep_v6_1_envelope_and_exact_codec(self):
        _, old = self.wire(version=OPTIMIZED_WINDOW_VERSION)
        messages, metadata = self.wire()
        self.assertEqual(metadata["window"]["pages"], old["window"]["pages"])
        self.assertEqual(metadata["window_admission_mode"], REQUESTED_WINDOW_ADMISSION_POLICY)
        self.assertEqual(self.raw(messages), rebuild_window(self.catalog(), metadata["window"],
            scope=self.f.access.scope, run_id=v4.RUN))
        self.assertEqual(metadata["bytes"], sum(len(m["content"].encode("utf-8")) for m in messages))

    def test_explicit_requested_page_uses_actual_capacity_without_claim_or_source_changes(self):
        selected = self.pending_selection()
        _, old = self.wire(version=OPTIMIZED_WINDOW_VERSION, selection=selected)
        messages, metadata = self.wire(selection=selected)
        new = metadata["window_selection"]
        self.assertGreater(new["end"], old["window_selection"]["end"])
        for key, value in selected.items():
            if key != "end":
                self.assertEqual(new[key], value)
        self.assertEqual(metadata["claims_preserved"], old["claims_preserved"])
        self.assertEqual(metadata["evidence_preserved"], old["evidence_preserved"])
        self.assertEqual(metadata["verification_audit"], old["verification_audit"])
        self.assertLessEqual(metadata["bytes"], 12000)
        self.assertEqual(self.raw(messages), rebuild_window(self.catalog(), metadata["window"],
            scope=self.f.access.scope, run_id=v4.RUN))

    def test_committed_page_end_is_not_reselected_after_header_change(self):
        _, metadata = self.wire(selection=self.pending_selection())
        selected = deepcopy(metadata["window_selection"])
        _, rebuilt = self.wire(selection=selected)
        self.assertEqual(rebuilt["window_selection"], selected)
        with self.assertRaises(ContextMinimumViewExceeded):
            self.wire(selection=selected, max_bytes=100)

    def test_new_builder_passes_explicit_capacity_and_has_no_legacy_retry_on_failure(self):
        from stock_research.research import context_window as core
        with patch.object(core, "compile_window", wraps=core.compile_window) as compiler:
            self.wire(selection=self.pending_selection())
        self.assertTrue(all(call.kwargs["requested_capacity"] == "actual" for call in compiler.call_args_list))
        self.assertTrue(all(call.kwargs.get("admission_render") is not None for call in compiler.call_args_list))
        with patch.object(core, "compile_window", side_effect=ContextMinimumViewExceeded("synthetic minimum")) as compiler:
            with self.assertRaises(ContextMinimumViewExceeded):
                self.wire()
            self.assertEqual(compiler.call_count, 1)

    def test_telemetry_records_actual_wire_and_separate_new_admission_policy(self):
        messages, metadata = self.wire(selection=self.pending_selection())
        observations = self.inputs()[3]
        record = build_context_telemetry(messages, metadata, observations, self.request,
            run_id=v4.RUN, turn_id=1, route_type="dynamic_parallel")
        self.assertEqual(record["window_admission_mode"], REQUESTED_WINDOW_ADMISSION_POLICY)
        self.assertEqual(record["total_context_bytes"], metadata["bytes"])
        self.assertEqual(record["window_ref"], metadata["window"]["window_ref"])
        self.assertFalse(record["verification_tool_execution_implied"])
        self.assertIsNone(record["total_tokens"])
        with patch("stock_research.research.dynamic_protocol.dynamic_messages") as builder:
            with self.assertRaises(ValidationError):
                overflow_context_telemetry(self.request, v61.TOOLS, [], [], [],
                    run_id=v4.RUN, turn_id=1, message_kwargs={"version": VERSION})
            builder.assert_not_called()

    def test_new_identity_is_additive_and_all_limits_defaults_are_preserved(self):
        spec, old = ParallelParentSpec(version=VERSION), ParallelParentSpec(version=OPTIMIZED_WINDOW_VERSION)
        self.assertNotEqual(spec.identity, old.identity)
        self.assertEqual(ParallelParentSpec().version, "dynamic-parent-parallel-v1")
        self.assertEqual(ParallelParentSpec().identity, "5120ebab68444745152040f21bdf1e21e65a73cc3d8da085ea1c4def453ebf00")
        for field in ("context_bytes", "max_decisions", "max_tools", "max_tokens", "max_seconds",
                      "root_max_decisions", "root_max_tools", "root_max_tokens", "no_progress_limit"):
            self.assertEqual(getattr(spec, field), getattr(old, field))


class RequestedCapacityRuntimeTests(unittest.TestCase):
    runtime = v4.VerificationDisclosureTests.runtime

    def setUp(self):
        v4.VerificationDisclosureTests.setUp(self)
        self.spec = ParallelParentSpec(version=VERSION)

    def test_complete_zero_append_replay_and_cross_version_restore_rejection(self):
        model = SequenceModel(completed_actions())
        report = self.runtime(model).run(self.request, self.f.access, run_id=RUN)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["context_archive"]["window_admission_policy"], REQUESTED_WINDOW_ADMISSION_POLICY)
        fresh = SequenceModel([])
        with patch.object(self.f.store, "append", wraps=self.f.store.append) as append:
            self.assertEqual(self.runtime(fresh).run(self.request, self.f.access, resume=RUN), report)
            append.assert_not_called()
        self.assertEqual(fresh.calls, 0)
        with patch.object(self.f.store, "append", wraps=self.f.store.append) as append, self.assertRaises(PermissionDenied):
            self.runtime(fresh, spec=ParallelParentSpec(version=OPTIMIZED_WINDOW_VERSION)).run(
                self.request, self.f.access, resume=RUN)
        append.assert_not_called()

    def test_committed_read_resumes_same_paid_pages_and_deadline_without_repeating_action(self):
        original = self.f.store.append
        def stop(scope, run, state):
            original(scope, run, state)
            last = state["trace"][-1] if state["trace"] else {}
            if last.get("event") == "tool_finished" and last.get("tool") == "context_read":
                raise KeyboardInterrupt()
        def decide(turn, messages):
            if turn <= 4:
                return completed_actions()[turn - 1]
            context = v61.OptimizedWindowProtocolTests.raw(self, messages)
            return {"action": "context_read", "catalog_ref": context["catalog_ref"],
                "refs": ["O:financial"], "plan": ["Inspect"]}
        first = SequenceModel([], callback=decide)
        with patch.object(self.f.store, "append", side_effect=stop), self.assertRaises(KeyboardInterrupt):
            self.runtime(first).run(self.request, self.f.access, run_id=RUN)
        saved = self.f.store.read(self.f.access.scope, RUN)
        self.assertEqual(first.calls, 5)
        remaining = SequenceModel(completed_actions()[4:])
        report = self.runtime(remaining).run(self.request, self.f.access, resume=RUN)
        restored = self.f.store.read(self.f.access.scope, RUN)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(remaining.calls, 2)
        self.assertEqual(restored["deadline"], saved["deadline"])
        self.assertEqual(restored["window_store"]["receipts"], saved["window_store"]["receipts"])
        self.assertEqual(restored["window_store"]["windows"][:5], saved["window_store"]["windows"])
        self.assertEqual(report["usage"]["model_attempts"], 7)


class RequestedCapacityCLITests(unittest.TestCase):
    setUp = fixture_cli.DomainAgentsCLITests.setUp
    args = fixture_cli.DomainAgentsCLITests.args

    def test_explicit_v6_2_requires_parallel_mode_before_credentials(self):
        args = self.args("--parallel-version", VERSION, "--with-model")
        with patch.object(cli, "load_model_config") as config, self.assertRaises(ValidationError):
            cli.run(args, self.f.repo)
        config.assert_not_called()

    def test_explicit_v6_2_preview_uses_unchanged_codec_and_short_system(self):
        args = self.args("--parallel-domains", "--parallel-version", VERSION, "--preview-model")
        with patch.object(cli, "load_model_config") as config, patch.object(cli, "CheckpointStore") as store:
            report = cli.run(args, self.f.repo)
        messages = json.loads((Path(args.output) / "model-messages.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "preview")
        self.assertEqual(messages[0]["content"], SYSTEM_PARENT_PARALLEL_V6_1)
        self.assertEqual(json.loads(messages[1]["content"])["protocol_version"], VERSION)
        config.assert_not_called()
        store.assert_not_called()


if __name__ == "__main__":
    unittest.main()
