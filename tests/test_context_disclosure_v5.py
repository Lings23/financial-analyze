"""Synthetic v5 audit/projection mechanisms; no live financial validation.

Pinned in-memory fixtures and scripted model decisions exercise the shared Runtime.
No model endpoint, financial Provider, or database server is contacted here.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from helpers import ts
from research_fixtures import fixture
from study_fixtures import study_request
import test_context_verification_decoupling as v4
from test_dynamic import SequenceModel, completed_actions, finish, tool
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.models import digest
from stock_research.research.dynamic_context import (
    build_catalog, build_verification_audit, decode_catalog, expand_view, validate_view,
)
from stock_research.research.dynamic_contracts import (
    AGENT_TOOLS, DYNAMIC_TOOLS, MAX_QUESTION_BYTES, DynamicRequest, ParallelParentSpec, required_checks,
)
from stock_research.research.dynamic_protocol import dynamic_messages, observe_tool
from stock_research.research.verification import verify


VERSION = "dynamic-parent-parallel-v5"
SCHEMA = "dynamic-context-disclosure-view/v2"
CONTRACT = "phase_gated_verification_brief/v1"
RUN = v4.RUN
_AUTO = object()


class DisclosureV5Tests(unittest.TestCase):
    # Reuse pinned fixture construction, not the historical v4 test class identity.
    inputs = v4.VerificationDisclosureTests.inputs
    runtime = v4.VerificationDisclosureTests.runtime
    grant_service = v4.VerificationDisclosureTests.grant_service
    rewrite_history = v4.VerificationDisclosureTests.rewrite_history
    research_signature = staticmethod(v4.VerificationDisclosureTests.research_signature)

    def setUp(self):
        v4.VerificationDisclosureTests.setUp(self)
        self.spec = ParallelParentSpec(version=VERSION)

    def complete(self, *, request=None, service=None, version=VERSION):
        return v4.VerificationDisclosureTests.complete(self, request=request, service=service, version=version)

    def wire(self, *, request=None, observations=None, revisions=None, checks=None,
             version=VERSION, max_bytes=12000, refs=(), plan=(), computed_sources=None,
             dependency_ready=True, verification_inputs=_AUTO, **kwargs):
        request = request or self.request
        if observations is None:
            _, _, _, observations, revisions, checks = self.inputs(request)
        arguments = {}
        if version in {"dynamic-parent-parallel-v2", "dynamic-parent-parallel-v3",
                       "dynamic-parent-parallel-v4", VERSION}:
            arguments["parent_execution_checks"] = checks
        if version in {"dynamic-parent-parallel-v4", VERSION}:
            arguments["parent_execution_revisions"] = revisions
        if version == VERSION:
            if verification_inputs is _AUTO:
                _, datasets, computed, _, _, _ = self.inputs(request)
                verification_inputs = ({"computed_ref": digest(computed), "datasets_ref": digest(datasets)}
                    if any(o["tool"] == "hypotheses" for o in observations) else None)
            arguments.update(parent_computed_sources=(
                sorted(o["tool"] for o in observations if o["kind"] == "source_read")
                if computed_sources is None else computed_sources),
                parent_dependency_ready=dependency_ready, parent_verification_inputs=verification_inputs)
        return dynamic_messages(request, DYNAMIC_TOOLS | AGENT_TOOLS, observations,
            required_checks(request), list(plan), max_bytes, version=version,
            context_scope=self.f.access.scope, context_run_id=RUN, context_refs=refs,
            **arguments, **kwargs)

    def catalog(self, observations):
        return build_catalog(self.request, sorted(observations, key=lambda item: item["tool"]),
            required_checks(self.request), scope=self.f.access.scope, run_id=RUN)

    def test_model_wire_contains_exact_revisions_brief_and_no_complete_manifest(self):
        _, datasets, computed, observations, revisions, _ = self.inputs()
        messages, metadata = self.wire()
        wire = json.loads(messages[1]["content"])["context"]
        view = expand_view(wire)
        self.assertEqual((view["schema"], view["disclosure_contract"]), (SCHEMA, CONTRACT))
        self.assertNotIn("verification_manifest", wire)
        self.assertNotIn("verification_audit", wire)
        self.assertNotIn("manifest_ref", messages[1]["content"])
        self.assertNotIn("complete_state_ref", messages[1]["content"])
        self.assertEqual(view["state_versions"], revisions)
        self.assertEqual(wire["state_versions"]["digests"], [revisions["source"]])
        self.assertEqual(wire["state_versions"]["refs"]["verified"], None)
        self.assertEqual(view["evidence"], [])
        self.assertEqual(view["verification_brief"], {
            "computed_ref": "O:hypotheses", "source_refs": ["O:financial", "O:market"],
            "counts": {"facts": len(computed["facts"]), "evidence": len(computed["evidence"]),
                "hypotheses": len(computed["hypotheses"]), "source_datasets": len(datasets),
                "source_records": sum(len(result["records"]) for result in datasets.values())}})
        catalog = self.catalog(observations)
        self.assertEqual(validate_view(wire, catalog, scope=self.f.access.scope, run_id=RUN,
            execution_revisions=revisions, verification_ready=True), view)
        audit = metadata["verification_audit"]
        self.assertEqual(audit, build_verification_audit(catalog, scope=self.f.access.scope,
            run_id=RUN, execution_revisions=revisions,
            input_refs={"computed_ref": digest(computed), "datasets_ref": digest(datasets)}))
        self.assertEqual(audit["schema"], "dynamic-verification-audit/v1")
        self.assertEqual(audit["input_refs"], {"computed_ref": digest(computed), "datasets_ref": digest(datasets)})
        payload = decode_catalog(catalog, scope=self.f.access.scope, run_id=RUN)
        self.assertEqual(audit["complete_state_ref"], digest({key: payload[key] for key in
            ("request", "observations", "required_checks")}))
        self.assertEqual(audit["request_ref"], digest(self.request.to_dict()))
        self.assertFalse(audit["execution_receipt"])
        self.assertEqual(audit["manifest_ref"], digest({key: value for key, value in audit.items()
                                                     if key != "manifest_ref"}))

    def test_full_audit_stays_paid_checkpoint_only_and_brief_is_present_only_while_ready(self):
        prepared = []
        def action(turn, messages):
            prepared.append(self.f.store.read(self.f.access.scope, RUN))
            return completed_actions()[turn - 1]
        model = SequenceModel([], callback=action)
        report = self.runtime(model).run(self.request, self.f.access, run_id=RUN)
        self.assertEqual(report["status"], "completed")
        self.assertEqual([json.loads(m[1]["content"])["context"]["stage"] for m in model.messages],
                         ["before_sources", "before_sources", "calculation", "hypotheses", "verification", "finish"])
        for turn, (saved, messages) in enumerate(zip(prepared, model.messages), 1):
            with self.subTest(turn=turn):
                payload, metadata = json.loads(messages[1]["content"]), saved["context"]
                self.assertNotIn("verification_manifest", payload["context"])
                self.assertNotIn("verification_audit", payload["context"])
                self.assertEqual("verification_brief" in payload["context"], turn == 5)
                self.assertEqual(metadata["verification_ready"], turn == 5)
                self.assertEqual("verification_audit" in metadata, turn >= 5)
                self.assertEqual(metadata["message_sha256"], digest(messages))
                self.assertEqual(saved["decisions"][-1]["message_sha256"], digest(messages))
                if turn >= 5:
                    audit = metadata["verification_audit"]
                    catalog = saved["context_store"]["catalogs"][metadata["catalog_ref"]]
                    self.assertEqual(audit, build_verification_audit(catalog,
                        scope=self.f.access.scope, run_id=RUN,
                        execution_revisions={"source": self.runtime(None)._current(saved),
                            **{name: saved.get(name + "_revision") for name in ("calculated", "hypotheses", "verified")}},
                        input_refs={"computed_ref": digest(saved["calculated"]),
                                    "datasets_ref": digest(self.runtime(None)._datasets(saved))}))
        self.assertEqual(report["context_archive"]["disclosure_contract"], CONTRACT)
        self.assertEqual(report["context_telemetry"][4]["verification_brief_bytes"],
                         prepared[4]["context"]["verification_brief_bytes"])
        self.assertEqual(report["context_telemetry"][5]["verification_brief_bytes"], 0)

    def test_observation_name_does_not_override_pending_authoritative_checks(self):
        _, _, _, observations, revisions, checks = self.inputs()
        for pending in ("calculation", "hypotheses"):
            changed = deepcopy(checks)
            for check in changed:
                if (check["id"] in {pending, "hypotheses", "verification"}
                        or pending == "calculation" and check["id"].startswith("hypothesis:")):
                    check["status"] = "not_completed"
            current = {**revisions, "hypotheses": None, "verified": None}
            if pending == "calculation":
                current["calculated"] = None
            messages, metadata = self.wire(observations=observations, revisions=current, checks=changed)
            view = json.loads(messages[1]["content"])["context"]
            self.assertEqual(view["stage"], pending)
            self.assertNotIn("verification_brief", view)
            self.assertNotIn("verification_audit", metadata)
            self.assertFalse(metadata["verification_ready"])
            with self.assertRaises(ValidationError):
                self.wire(observations=observations, revisions=current, checks=changed,
                          context_stage="verification")

    def test_stale_null_revisions_missing_checks_and_partial_source_sets_are_rejected(self):
        _, _, _, observations, revisions, checks = self.inputs()
        for field in ("source", "calculated", "hypotheses"):
            for value in (None, "0" * 64):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    self.wire(observations=observations, revisions={**revisions, field: value}, checks=checks)
        for sources in ([], ["financial"], ["market"], ["financial", "financial", "market"],
                        ["market", "financial"], ["financial", "market", "news"]):
            with self.subTest(sources=sources), self.assertRaises(ValidationError):
                self.wire(computed_sources=sources)
        for bad_checks in (None, checks[:-1], [*checks[:-1], {"id": checks[-1]["id"], "status": "failed"}]):
            with self.subTest(checks=bad_checks), self.assertRaises(ValidationError):
                self.wire(observations=observations, revisions=revisions, checks=bad_checks)
        for missing in ("financial", "hypotheses"):
            with self.subTest(missing=missing), self.assertRaises(ValidationError):
                self.wire(observations=[o for o in observations if o["tool"] != missing],
                          revisions=revisions, checks=checks)
        for inputs in (None, {}, {"computed_ref": "0" * 64},
                       {"computed_ref": "bad", "datasets_ref": "0" * 64}):
            with self.subTest(inputs=inputs), self.assertRaises(ValidationError):
                self.wire(verification_inputs=inputs)

    def test_authoritative_dag_readiness_blocks_brief_even_when_all_typed_checks_are_present(self):
        messages, metadata = self.wire(dependency_ready=False)
        self.assertEqual(json.loads(messages[1]["content"])["context"]["stage"], "verification")
        self.assertFalse(metadata["verification_ready"])
        self.assertNotIn("verification_brief", json.loads(messages[1]["content"])["context"])
        self.assertNotIn("verification_audit", metadata)
        report, _ = self.complete()
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        state["parallel_groups"] = [{"nodes": {
            "hypotheses": {"status": "pending", "dependencies": []},
            "verification": {"status": "pending", "dependencies": ["hypotheses"]}}}]
        arguments = self.runtime(None)._context_arguments(state, self.f.access)
        self.assertFalse(arguments["parent_dependency_ready"])

    def test_actual_verification_removes_brief_but_retains_complete_audit(self):
        _, datasets, computed, observations, revisions, checks = self.inputs()
        observations = [*observations, observe_tool("verification", verify(computed, datasets, self.request))]
        checks = [{**check, "status": "passed"} if check["id"] == "verification" else check for check in checks]
        revisions = {**revisions, "verified": revisions["source"]}
        messages, metadata = self.wire(observations=observations, revisions=revisions, checks=checks)
        view = expand_view(json.loads(messages[1]["content"])["context"])
        self.assertEqual(view["stage"], "finish")
        self.assertNotIn("verification_brief", view)
        self.assertFalse(metadata["verification_ready"])
        self.assertIn("verification_audit", metadata)
        self.assertEqual(metadata["verification_audit"]["execution_revisions"], revisions)
        self.assertTrue(json.loads(messages[1]["content"])["control"]["execution"]["can_finish"])

    def test_brief_is_rebuilt_after_early_finish_disclosure_and_schema_feedback(self):
        for intervening in ("finish", "disclose", "invalid"):
            def action(turn, messages):
                if turn < 5:
                    return completed_actions()[turn - 1]
                view = json.loads(messages[1]["content"])["context"]
                if turn == 5:
                    return (finish() if intervening == "finish" else "not JSON" if intervening == "invalid" else
                            {"action": "disclose", "catalog_ref": view["catalog_ref"], "refs": ["E:E1"], "plan": ["Inspect"]})
                if turn == 6:
                    self.assertIn("verification_brief", view)
                    self.assertFalse(json.loads(messages[1]["content"])["control"]["execution"]["can_finish"])
                    return tool("verification", ["hypotheses"])
                return finish()
            with self.subTest(intervening=intervening):
                model = SequenceModel([], callback=action)
                report = self.runtime(model).run(self.request, self.f.access)
                self.assertEqual(report["status"], "completed")
                self.assertEqual(model.calls, 7)
                self.assertEqual(sum(e["event"] == "tool_started" and e["tool"] == "verification"
                                     for e in report["trace"]), 1)

    def test_phase_gated_view_refuses_cross_scope_run_readiness_and_forged_brief(self):
        _, _, _, observations, revisions, _ = self.inputs()
        messages, _ = self.wire()
        view = json.loads(messages[1]["content"])["context"]
        catalog = self.catalog(observations)
        for scope, run in (("foreign", RUN), (self.f.access.scope, "b" * 32)):
            with self.assertRaises(PermissionDenied):
                validate_view(view, catalog, scope=scope, run_id=run,
                              execution_revisions=revisions, verification_ready=True)
        with self.assertRaises(IntegrityError):
            validate_view(view, catalog, scope=self.f.access.scope, run_id=RUN,
                          execution_revisions=revisions, verification_ready=False)
        for field in ("source_records", "facts", "evidence", "hypotheses", "source_datasets"):
            corrupted = deepcopy(view)
            corrupted["verification_brief"]["counts"][field] += 1
            with self.subTest(field=field), self.assertRaises(IntegrityError):
                validate_view(corrupted, catalog, scope=self.f.access.scope, run_id=RUN,
                              execution_revisions=revisions, verification_ready=True)
        for field in ("catalog_ref", "computed_ref", "source_refs"):
            corrupted = deepcopy(view)
            if field == "catalog_ref":
                corrupted[field] = "0" * 64
            elif field == "computed_ref":
                corrupted["verification_brief"][field] = "O:calculation"
            else:
                corrupted["verification_brief"][field] = ["O:financial"]
            with self.subTest(field=field), self.assertRaises((PermissionDenied, IntegrityError, ValidationError)):
                validate_view(corrupted, catalog, scope=self.f.access.scope, run_id=RUN,
                              execution_revisions=revisions, verification_ready=True)

    def test_rehashed_checkpoint_audit_tamper_cannot_restore_or_dispatch(self):
        for alteration in ("manifest_ref", "source_records", "request_ref", "computed_ref", "datasets_ref", "missing", "ready"):
            with self.subTest(alteration=alteration):
                report, _ = self.complete()
                def corrupt(states):
                    for saved in states:
                        metadata = saved.get("context", {})
                        if "verification_audit" not in metadata:
                            continue
                        if alteration == "missing":
                            metadata.pop("verification_audit")
                        elif alteration == "ready":
                            metadata["verification_ready"] = not metadata["verification_ready"]
                        else:
                            audit = metadata["verification_audit"]
                            if alteration in {"computed_ref", "datasets_ref"}:
                                audit["input_refs"][alteration] = "0" * 64
                            else:
                                audit[alteration] = (audit[alteration] + 1 if alteration == "source_records" else "0" * 64)
                            if alteration != "manifest_ref":
                                audit["manifest_ref"] = digest({key: value for key, value in audit.items() if key != "manifest_ref"})
                self.rewrite_history(report["run_id"], corrupt)
                fresh = SequenceModel([])
                with patch.object(self.f.store, "append", wraps=self.f.store.append) as append, self.assertRaises(IntegrityError):
                    self.runtime(fresh).run(self.request, self.f.access, resume=report["run_id"])
                self.assertEqual(fresh.calls, 0)
                append.assert_not_called()

    def test_maximum_legal_plan_and_question_are_preserved_or_stop_before_dispatch(self):
        question = "合成：" + "x" * (MAX_QUESTION_BYTES - len("合成：".encode("utf-8")))
        request = replace(self.request, question=question)
        plan = ["计" * 80, "划" * 80, "核" * 80, "验" * 80, "。" * 80]
        messages, metadata = self.wire(request=request, plan=plan, max_bytes=100000)
        control = json.loads(messages[1]["content"])["control"]
        self.assertEqual(control["question"], question)
        self.assertEqual(control["plan"], plan)
        self.assertEqual(metadata["bytes"], sum(len(m["content"].encode("utf-8")) for m in messages))
        self.assertEqual(self.wire(request=request, plan=plan, max_bytes=metadata["bytes"])[0], messages)
        with self.assertRaises(ValidationError):
            self.wire(request=request, plan=plan, max_bytes=metadata["bytes"] - 1)
        actions = completed_actions()
        for action in actions:
            action["plan"] = plan
        model = SequenceModel(actions)
        report = self.runtime(model).run(request, self.f.access)
        self.assertIn(report["status"], {"completed", "partial"})
        for messages in model.messages:
            self.assertLessEqual(sum(len(m["content"].encode("utf-8")) for m in messages), 12000)
            payload = json.loads(messages[1]["content"])
            self.assertEqual(payload["control"]["question"], question)
            if payload["control"]["plan"]:
                self.assertEqual(payload["control"]["plan"], plan)
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        self.assertTrue(all(p["steps"] == plan for p in state["plans"]))
        if report["status"] == "partial":
            self.assertEqual(report["stop_reason"], "dynamic_context_budget_exceeded")
            self.assertFalse(report["context_telemetry"][-1]["model_dispatched"])
        with self.assertRaises(ValidationError):
            ParallelParentSpec(version=VERSION, context_bytes=12001)

    def test_exact_12000_utf8_boundary_accepts_and_12001_stops_without_trimming(self):
        # Extend the pinned synthetic price source, never manufacture Evidence rows.
        with patch("research_fixtures.ts", return_value=ts("2025-10-01T00:00:00")):
            self.f = fixture(Path(self.temp.name) / "boundary", prices=("100",) * 80)
        base = study_request(self.f, hypotheses=("financial_deterioration",)).to_dict()
        base["as_of"] = "2025-10-02T00:00:00+00:00"
        for binding in base["bindings"]:
            if binding["dataset"] == "market_daily":
                binding["end"] = str(date(2025, 4, 1) + timedelta(days=79))
        self.request = DynamicRequest.from_dict({**base, "question": "Q"})
        plan = ["计" * 80] * 5
        _, minimum = self.wire(plan=plan, max_bytes=100000)
        extra = 12000 - minimum["bytes"]
        self.assertGreaterEqual(extra, 0)
        self.assertLess(extra + 2, MAX_QUESTION_BYTES)
        at_limit = replace(self.request, question="Q" * (extra + 1))
        messages, metadata = self.wire(request=at_limit, plan=plan)
        self.assertEqual(metadata["bytes"], 12000)
        self.assertEqual(json.loads(messages[1]["content"])["control"]["plan"], plan)
        self.assertEqual(json.loads(messages[1]["content"])["control"]["question"], at_limit.question)
        over_limit = replace(at_limit, question=at_limit.question + "Q")
        _, measured = self.wire(request=over_limit, plan=plan, max_bytes=100000)
        self.assertEqual(measured["bytes"], 12001)
        with self.assertRaises(ValidationError):
            self.wire(request=over_limit, plan=plan)

    def test_old_parent_versions_preserve_paid_wire_identity_and_zero_append_replay(self):
        for version in ("dynamic-parent-parallel-v1", "dynamic-parent-parallel-v2",
                        "dynamic-parent-parallel-v3", "dynamic-parent-parallel-v4"):
            with self.subTest(version=version):
                report, model = self.complete(version=version)
                history = self.f.store.history(self.f.access.scope, report["run_id"])
                fresh = SequenceModel([])
                with patch.object(self.f.store, "append", wraps=self.f.store.append) as append:
                    replay = self.runtime(fresh, spec=ParallelParentSpec(version=version)).run(
                        self.request, self.f.access, resume=report["run_id"])
                self.assertEqual(replay, report)
                self.assertEqual(self.f.store.history(self.f.access.scope, report["run_id"]), history)
                self.assertEqual(fresh.calls, 0)
                append.assert_not_called()
                for messages in model.messages:
                    context = json.loads(messages[1]["content"])["context"]
                    self.assertNotIn("state_versions", context)
                    self.assertNotIn("verification_brief", context)
                    self.assertEqual("verification_manifest" in context, version.endswith("v4"))
                self.assertNotEqual(self.spec.identity, ParallelParentSpec(version=version).identity)
        self.assertEqual(ParallelParentSpec().version, "dynamic-parent-parallel-v1")
        self.assertEqual(ParallelParentSpec().identity,
                         "5120ebab68444745152040f21bdf1e21e65a73cc3d8da085ea1c4def453ebf00")


# Exercise the already validated v4 safety mechanisms with the explicit v5 Spec.
# Aliases keep those historical tests and fixtures unmodified and avoid duplicating
# long authorization/PIT/restore implementations in this version's test file.
for _name in (
    "test_reference_counts_and_view_construction_never_complete_verification",
    "test_completed_children_do_not_replace_parent_verification_execution",
    "test_actual_verification_executes_against_all_original_objects_and_final_report_is_unchanged",
    "test_explicit_disclosure_retains_the_original_full_object_closure",
    "test_original_verifier_rejects_rehashed_value_source_reference_time_and_omission",
    "test_lawful_insufficient_requires_actual_verification_and_preserves_all_gaps",
    "test_duplicate_verification_is_not_executed_and_two_duplicates_still_stop",
    "test_every_actual_system_and_user_wire_is_measured_and_exact_cap_remains",
    "test_non_evidence_minimum_inputs_still_stop_without_clipping",
    "test_same_parent_explicit_child_v3_direct_serial_parallel_paths_preserve_quality_and_replay",
    "test_revocation_before_verification_blocks_the_tool_even_with_no_evidence_in_prompt",
    "test_revocation_during_verifier_prevents_a_successful_execution_receipt",
    "test_revocation_after_paid_intent_blocks_disclosure_before_model_dispatch",
    "test_revocation_during_final_revalidation_blocks_report_delivery",
    "test_public_available_time_and_system_ingestion_time_remain_exact_in_candidate_views",
    "test_completed_replay_reauthorizes_scope_provider_grants_and_unchanged_snapshot",
    "test_finished_recovery_rejects_stale_revision_or_changed_verification_receipt",
    "test_hash_valid_history_forgery_cannot_replace_actual_verification_execution",
    "test_current_recovered_calculation_cannot_omit_an_executed_source",
    "test_paid_action_resume_preserves_new_wire_and_never_repeats_the_decision",
    "test_unknown_paid_result_never_replays_or_releases_reserved_usage",
    "test_completed_replay_refuses_underlying_artifact_tamper_without_model_or_append",
):
    setattr(DisclosureV5Tests, _name, getattr(v4.VerificationDisclosureTests, _name))


if __name__ == "__main__":
    unittest.main()
