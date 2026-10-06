"""Synthetic Phase 6 metadata codec/security mechanisms; never financial truth."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_parallel_parent_progress as progress_fixture
import test_domain_agents_cli as cli_fixture
from test_dynamic import SequenceModel, tool, finish
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.models import canonical_json, digest
from stock_research.research import cli
from stock_research.research.context_telemetry import build_context_telemetry
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_context import (
    build_catalog, encode_view, expand_view, validate_view, view_catalog,
)
from stock_research.research.dynamic_context_metadata import (
    METADATA_VIEW_SCHEMA, encode_metadata_view, decode_metadata_view,
)
from stock_research.research.dynamic_contracts import ParallelParentSpec, required_checks
from stock_research.research.dynamic_protocol import (
    SYSTEM_PARENT_PARALLEL_V2, SYSTEM_PARENT_PARALLEL_V3, dynamic_messages, parse_action,
)


VERSION = "dynamic-parent-parallel-v3"
RUN = "a" * 32


class MetadataContextTests(unittest.TestCase):
    setUp = progress_fixture.ParallelParentProgressTests.setUp
    observations = progress_fixture.ParallelParentProgressTests.observations
    checks = progress_fixture.ParallelParentProgressTests.checks

    def catalog(self, observations=None):
        return build_catalog(self.request, observations or self.observations(),
                             required_checks(self.request), scope=self.f.access.scope, run_id=RUN)

    def view(self, stage="verification"):
        return view_catalog(self.catalog(), scope=self.f.access.scope, run_id=RUN, current_stage=stage)

    def wire(self, observations=None, version=VERSION):
        observations = self.observations() if observations is None else observations
        return dynamic_messages(self.request, self.tools, observations, required_checks(self.request),
            ["SYNTHETIC preserve every field"], 12000, version=version,
            context_scope=self.f.access.scope, context_run_id=RUN,
            parent_execution_checks=self.checks(observations))

    def test_v2_view_round_trips_all_v1_fields_exactly_across_every_stage(self):
        for stage in ("before_sources", "calculation", "hypotheses", "verification", "finish"):
            with self.subTest(stage=stage):
                original = self.view(stage)
                before = deepcopy(original)
                encoded = encode_metadata_view(original)
                self.assertEqual(encoded["schema"], METADATA_VIEW_SCHEMA)
                self.assertEqual(decode_metadata_view(encoded), original)
                self.assertEqual(expand_view(encoded), expand_view(original))
                self.assertEqual(encoded, encode_metadata_view(deepcopy(original)))
                self.assertEqual(original, before)

    def test_financial_value_cells_and_fact_evidence_row_ids_remain_literal(self):
        original = self.view()
        encoded = encode_metadata_view(original)
        for table in ("facts", "evidence"):
            for left, right in zip(original[table], encoded[table]):
                self.assertEqual((left[0], left[2]), (right[0], right[2]))
                self.assertIs(type(right[0]), str)
                self.assertTrue(right[2] is None or type(right[2]) is str)
        self.assertEqual([row[3] for row in encoded["source_datasets"]],
                         [row[3] for row in original["source_datasets"]])

    def test_exact_decimal_null_unicode_order_and_lists_are_reversible(self):
        original = self.view()
        expanded = expand_view(original)
        expanded["facts"][0][2] = "000.00123000"
        expanded["facts"][0][5] = "精确公式 元数据"
        expanded["facts"][1][5] = "精确公式 元数据"
        expanded["evidence"][0][2] = None
        baseline = encode_view(expanded)
        encoded = encode_metadata_view(baseline)
        self.assertEqual(decode_metadata_view(encoded), baseline)
        self.assertEqual(expand_view(encoded), expanded)
        self.assertEqual(encoded["facts"][0][2], "000.00123000")
        self.assertIsNone(encoded["evidence"][0][2])

    def test_repeated_metadata_is_smaller_without_reducing_evidence_or_disclosure(self):
        original = self.view()
        encoded = encode_metadata_view(original)
        self.assertLess(len(canonical_json(encoded).encode()), len(canonical_json(original).encode()))
        self.assertEqual(len(encoded["evidence"]), len(original["evidence"]))
        self.assertEqual(decode_metadata_view(encoded)["disclosed_refs"], original["disclosed_refs"])
        self.assertTrue(encoded["symbols"])

    def test_nonprofitable_short_lists_remain_literal_and_empty_lists_are_not_interned(self):
        encoded = encode_metadata_view(self.view("before_sources"))
        self.assertEqual(encoded["requested_refs"], [])
        self.assertFalse(any(value == [] for value in encoded["list_table"]))
        # The one-element hypothesis list is short and its exact order survives.
        self.assertEqual(decode_metadata_view(encoded)["range"]["declared_hypotheses"],
                         ["financial_deterioration"])

    def test_lists_retain_every_reference_and_order_when_shared(self):
        original = self.view()
        encoded = encode_metadata_view(original)
        decoded = decode_metadata_view(encoded)
        self.assertEqual(decoded["observations"], original["observations"])
        self.assertEqual(decoded["catalog_ids"], original["catalog_ids"])
        self.assertEqual(decoded["range"]["bound_windows"], original["range"]["bound_windows"])

    def test_unknown_schema_extra_fields_and_missing_fields_are_rejected(self):
        original = encode_metadata_view(self.view())
        invalid = []
        bad = deepcopy(original); bad["schema"] = "dynamic-context-view/v100"; invalid.append(bad)
        bad = deepcopy(original); bad["source_text"] = "forbidden"; invalid.append(bad)
        for field in ("symbols", "list_table", "columns", "range", "source_datasets"):
            bad = deepcopy(original); bad.pop(field); invalid.append(bad)
        for bad in invalid:
            with self.subTest(keys=set(bad)), self.assertRaises(ValidationError):
                decode_metadata_view(bad)

    def test_boolean_negative_and_dangling_symbol_or_list_indices_are_rejected(self):
        original = encode_metadata_view(self.view())
        for value in (True, False, -1, 10**9, {"l": True}, {"l": -1}, {"l": 10**9}, {"l": 0, "s": 0}):
            bad = deepcopy(original)
            bad["range"]["cutoff"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                decode_metadata_view(bad)

    def test_noncanonical_tables_and_literal_substitution_are_rejected(self):
        original = encode_metadata_view(self.view())
        invalid = []
        bad = deepcopy(original); bad["symbols"].append("unused-unused-unused"); bad["symbols"].sort(); invalid.append(bad)
        bad = deepcopy(original); bad["symbols"].append(bad["symbols"][-1]); invalid.append(bad)
        bad = deepcopy(original); bad["list_table"].append(["unused"]); invalid.append(bad)
        bad = deepcopy(original); bad["catalog_ids"]["evidence"] = decode_metadata_view(original)["catalog_ids"]["evidence"]; invalid.append(bad)
        for bad in invalid:
            with self.assertRaises(ValidationError):
                decode_metadata_view(bad)

    def test_structural_depth_cycle_float_and_financial_value_alias_are_rejected(self):
        original = encode_metadata_view(self.view())
        nested = "exact"
        for _ in range(40):
            nested = [nested]
        cycle = []; cycle.append(cycle)
        for value in (nested, cycle, 1.25):
            bad = deepcopy(original); bad["list_table"].append(value)
            with self.assertRaises(ValidationError):
                decode_metadata_view(bad)
        for value in (0, {"l": 0}, {"s": 0}):
            bad = deepcopy(original); bad["facts"][0][2] = value
            with self.assertRaises(ValidationError):
                decode_metadata_view(bad)

    def test_current_catalog_binding_scope_and_run_are_required_for_v2(self):
        catalog = self.catalog()
        view = view_catalog(catalog, scope=self.f.access.scope, run_id=RUN, current_stage="verification")
        encoded = encode_metadata_view(view)
        self.assertEqual(validate_view(encoded, catalog, scope=self.f.access.scope, run_id=RUN), expand_view(view))
        for scope, run in (("SYNTHETIC/revoked", RUN), (self.f.access.scope, "b" * 32)):
            with self.assertRaises(PermissionDenied):
                validate_view(encoded, catalog, scope=scope, run_id=run)
        forged = expand_view(view); forged["facts"][0][2] = "999999"
        with self.assertRaises(IntegrityError):
            validate_view(encode_metadata_view(encode_view(forged)), catalog, scope=self.f.access.scope, run_id=RUN)

    def test_v3_only_representation_preserves_control_checks_and_legacy_v2_system(self):
        baseline, baseline_meta = self.wire(version="dynamic-parent-parallel-v2")
        candidate, candidate_meta = self.wire()
        old, new = json.loads(baseline[1]["content"]), json.loads(candidate[1]["content"])
        self.assertEqual(baseline[0]["content"], SYSTEM_PARENT_PARALLEL_V2)
        self.assertEqual(candidate[0]["content"], SYSTEM_PARENT_PARALLEL_V3)
        self.assertIn("Financial value cells and Fact/Evidence row IDs remain literal", candidate[0]["content"])
        new["protocol_version"] = old["protocol_version"]
        new["context"] = decode_metadata_view(new["context"])
        self.assertEqual(new, old)
        for key in ("catalog_ref", "claims_preserved", "evidence_preserved", "evidence_included", "disclosed_refs"):
            self.assertEqual(candidate_meta[key], baseline_meta[key])
        self.assertEqual(candidate_meta["message_sha256"], digest(candidate))

    def test_new_identity_default_limits_and_action_contracts_remain_explicit(self):
        legacy, v2, v3 = ParallelParentSpec(), ParallelParentSpec(version="dynamic-parent-parallel-v2"), ParallelParentSpec(version=VERSION)
        self.assertEqual(legacy.version, "dynamic-parent-parallel-v1")
        self.assertEqual(len({legacy.identity, v2.identity, v3.identity}), 3)
        for key in ("max_decisions", "max_tools", "max_tokens", "max_seconds", "context_bytes",
                    "root_max_decisions", "root_max_tools", "root_max_tokens", "no_progress_limit"):
            self.assertEqual(getattr(v3, key), getattr(v2, key))
        action = tool("verification", ["hypotheses"])
        self.assertEqual(parse_action(json.dumps(action), self.tools,
            ["financial", "market", "calculation", "hypotheses"], version=VERSION), action)
        with self.assertRaises(ValidationError):
            parse_action(json.dumps(tool("verification", [0])), self.tools,
                         ["hypotheses"], version=VERSION)

    def test_cap_remains_exact_and_telemetry_counts_all_original_objects(self):
        messages, metadata = self.wire()
        observation = self.observations()
        record = build_context_telemetry(messages, metadata, observation, self.request,
                                        run_id=RUN, turn_id=1, agent_role="parent")
        self.assertEqual(record["total_context_bytes"], sum(len(message["content"].encode()) for message in messages))
        self.assertEqual(record["total_fact_count"], len(observation[-1]["facts"]))
        self.assertEqual(record["total_evidence_count"], len(observation[-1]["evidence"]))
        self.assertEqual(record["visible_evidence_count"], len(json.loads(messages[1]["content"])["context"]["evidence"]))
        with self.assertRaises(ValidationError):
            dynamic_messages(self.request, self.tools, observation, required_checks(self.request),
                ["SYNTHETIC preserve every field"], metadata["bytes"] - 1, version=VERSION,
                context_scope=self.f.access.scope, context_run_id=RUN,
                parent_execution_checks=self.checks(observation))

    def test_candidate_requires_authoritative_revision_checks_and_cannot_grant_hidden_tools(self):
        observations = self.observations()
        with self.assertRaises(ValidationError):
            dynamic_messages(self.request, self.tools, observations, required_checks(self.request), [], 12000,
                version=VERSION, context_scope=self.f.access.scope, context_run_id=RUN)
        messages, _ = dynamic_messages(self.request, self.tools - {"verification"}, observations,
            required_checks(self.request), [], 12000, version=VERSION,
            context_scope=self.f.access.scope, context_run_id=RUN,
            parent_execution_checks=self.checks(observations))
        execution = json.loads(messages[1]["content"])["control"]["execution"]
        self.assertFalse(execution["can_finish"])
        self.assertIsNone(execution["next_action"])

    def test_repeated_premature_finish_stops_and_completed_replay_appends_nothing(self):
        actions = [tool("financial"), tool("market"), tool("calculation", ["financial", "market"]),
                   tool("hypotheses", ["calculation"]), finish("insufficient"), finish("insufficient")]
        spec = ParallelParentSpec(version=VERSION)
        model = SequenceModel(actions)
        report = DynamicRuntime(self.f.service, self.f.store, model, spec).run(self.request, self.f.access)
        self.assertEqual((report["status"], report["stop_reason"]), ("partial", "no_progress"))
        self.assertEqual(sum(event["event"] == "finish_rejected" for event in report["trace"]), 2)
        fresh = SequenceModel([])
        with patch.object(self.f.store, "append", wraps=self.f.store.append) as append:
            restored = DynamicRuntime(self.f.service, self.f.store, fresh, spec).run(
                self.request, self.f.access, resume=report["run_id"])
            append.assert_not_called()
        self.assertEqual(restored, report)
        self.assertEqual(fresh.calls, 0)

    def test_resume_reauthorizes_and_rejects_protocol_change(self):
        spec = ParallelParentSpec(version=VERSION)
        actions = [tool("financial"), tool("market"), tool("calculation", ["financial", "market"]),
                   tool("hypotheses", ["calculation"]), tool("verification", ["hypotheses"]), finish()]
        report = DynamicRuntime(self.f.service, self.f.store, SequenceModel(actions), spec).run(self.request, self.f.access)
        fresh = SequenceModel([])
        for changed_spec, access in ((replace(spec, version="dynamic-parent-parallel-v2"), self.f.access),
                                     (spec, replace(self.f.access, allowed_providers=frozenset({"revoked_provider"})))):
            with self.assertRaises(PermissionDenied):
                DynamicRuntime(self.f.service, self.f.store, fresh, changed_spec).run(
                    self.request, access, resume=report["run_id"])
        self.assertEqual(fresh.calls, 0)

    def test_unknown_paid_result_preserves_intent_and_is_never_resent(self):
        spec = ParallelParentSpec(version=VERSION)
        model = SequenceModel([], crash=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            DynamicRuntime(self.f.service, self.f.store, model, spec).run(self.request, self.f.access, run_id=RUN)
        state = self.f.store.read(self.f.access.scope, RUN)
        self.assertGreater(state["tokens_reserved"], 0)
        wire = model.messages[0]
        fresh = SequenceModel([])
        report = DynamicRuntime(self.f.service, self.f.store, fresh, spec).run(self.request, self.f.access, resume=RUN)
        self.assertEqual(fresh.calls, 0)
        self.assertEqual(report["stop_reason"], "unknown_model_outcome_no_replay")
        self.assertEqual(report["usage"]["tokens_reserved"], state["tokens_reserved"])
        self.assertEqual(report["context_telemetry"][0]["message_sha256"], digest(wire))


class MetadataContextCLITests(unittest.TestCase):
    setUp = cli_fixture.DomainAgentsCLITests.setUp
    args = cli_fixture.DomainAgentsCLITests.args

    def test_explicit_v3_preview_needs_no_model_or_checkpoint_and_default_stays_v1(self):
        args = self.args("--parallel-domains", "--parallel-version", VERSION, "--preview-model")
        with patch.object(cli, "load_model_config") as config, patch.object(cli, "CheckpointStore") as store:
            cli.run(args, self.f.repo)
            config.assert_not_called(); store.assert_not_called()
        messages = json.loads((Path(args.output) / "model-messages.json").read_text("utf-8"))
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["protocol_version"], VERSION)
        self.assertEqual(payload["context"]["schema"], METADATA_VIEW_SCHEMA)
        self.assertFalse(payload["control"]["execution"]["can_finish"])
        self.assertEqual(self.args("--parallel-domains").parallel_version, "dynamic-parent-parallel-v1")

    def test_candidate_version_requires_parallel_mode_before_credential_load(self):
        for flags in ((), ("--financial-child",), ("--domain-agents",)):
            args = self.args(*flags, "--parallel-version", VERSION, "--with-model")
            with patch.object(cli, "load_model_config") as config, self.assertRaises(ValidationError):
                cli.run(args, self.f.repo)
            config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
