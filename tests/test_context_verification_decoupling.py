"""Synthetic W1 disclosure/execution mechanisms; never financial ground truth.

These tests use pinned in-memory source fixtures and scripted model actions. They
do not call a model endpoint, financial Provider, or a database server.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from helpers import ts
from research_fixtures import fixture
from study_fixtures import study_request
from test_dynamic import SequenceModel, completed_actions, finish, tool
from test_parallel_runtime import parallel_action
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.model_adapters.chat import ChatResult
from stock_research.models import AccessContext, PITMode, canonical_json, digest
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_context import (
    build_catalog, decode_catalog, expand_view, resolve_catalog, validate_view,
)
from stock_research.research.dynamic_context_metadata import decode_metadata_view
from stock_research.research.dynamic_contracts import (
    DYNAMIC_TOOLS, AGENT_TOOLS, DynamicRequest, FinancialChildSpec, MarketChildSpec,
    ParallelParentSpec, required_checks,
)
from stock_research.research.dynamic_protocol import dynamic_messages, observe_tool
from stock_research.research.scoped import ScopedReadService, SourceGrant
from stock_research.research.study import StudyRuntime
from stock_research.research.tools import read_domain
from stock_research.research.verification import verify


VERSION = "dynamic-parent-parallel-v4"
BASELINE = "dynamic-parent-parallel-v3"
RUN = "a" * 32
DISCLOSURE_SCHEMA = "dynamic-context-disclosure-view/v1"


class RoleModel:
    """Thread-safe scripted model supporting existing explicit Child v3 wires."""
    config = SimpleNamespace(model="deepseek-v4-flash-0731")

    def __init__(self, parent_actions):
        self.actions = parent_actions
        self.counts, self.messages, self.lock = Counter(), [], Lock()

    def complete(self, messages, **kwargs):
        version = json.loads(messages[1]["content"]).get("protocol_version", "")
        role = ("financial" if version.startswith("financial-child-") else
                "market" if version.startswith("market-child-") else "parent")
        with self.lock:
            self.counts[role] += 1
            turn = self.counts[role]
            self.messages.append((role, turn, deepcopy(messages)))
        action = (self.actions[turn - 1] if role == "parent" else
                  tool(role) if turn == 1 else finish())
        return ChatResult(self.config.model, self.config.model,
                          json.dumps(action, ensure_ascii=False), "stop",
                          "synthetic-w1-" + role + "-" + str(turn), 100, 20, 120, 1)


class VerificationDisclosureTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.request = DynamicRequest.from_dict({
            **study_request(self.f, hypotheses=("financial_deterioration",)).to_dict(),
            "question": "SYNTHETIC: preserve the full pinned state and actual verification execution.",
        })
        self.spec = ParallelParentSpec(version=VERSION)

    def runtime(self, model, *, service=None, spec=None, **kwargs):
        return DynamicRuntime(service or self.f.service, self.f.store, model, spec or self.spec,
            domain_child_specs={"financial": FinancialChildSpec(version="financial-child-v3"),
                                "market": MarketChildSpec(version="market-child-v3")}, **kwargs)

    def complete(self, *, request=None, service=None, version=VERSION):
        model = SequenceModel(completed_actions())
        report = self.runtime(model, service=service, spec=ParallelParentSpec(version=version)).run(
            request or self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        return report, model

    def inputs(self, request=None):
        request = request or self.request
        outputs = {name: read_domain(self.f.service, request, self.f.access, name)
                   for name in ("financial", "market")}
        datasets = {dataset: result for output in outputs.values() for dataset, result in output.items()}
        computed = StudyRuntime(self.f.service, self.f.store)._calculate(datasets, request)
        calculation = deepcopy(computed)
        calculation["hypotheses"] = []
        observations = [observe_tool(name, output) for name, output in outputs.items()]
        observations += [observe_tool("calculation", calculation), observe_tool("hypotheses", computed)]
        revision = digest(outputs)
        revisions = {"source": revision, "calculated": revision, "hypotheses": revision, "verified": None}
        checks = [{"id": value, "status": "not_completed" if value == "verification" else "passed"}
                  for value in required_checks(request)]
        return outputs, datasets, computed, observations, revisions, checks

    def wire(self, *, request=None, observations=None, revisions=None, checks=None,
             version=VERSION, max_bytes=12000, refs=(), **kwargs):
        request = request or self.request
        if observations is None:
            _, _, _, observations, revisions, checks = self.inputs(request)
        return dynamic_messages(request, DYNAMIC_TOOLS | AGENT_TOOLS, observations,
            required_checks(request), [], max_bytes, version=version,
            context_scope=self.f.access.scope, context_run_id=RUN, context_refs=refs,
            parent_execution_checks=checks,
            **({"parent_execution_revisions": revisions} if version == VERSION else {}), **kwargs)

    def grant_service(self, request=None):
        request = request or self.request
        grants = [SourceGrant(self.f.service, self.f.access, binding.snapshot,
            request.data_request(binding), binding.provider) for binding in request.bindings]
        return ScopedReadService(self.f.access.scope, lambda: tuple(grants)), grants

    def rewrite_history(self, run, mutate):
        """Rehash a malicious local rewrite to exercise semantic recovery checks."""
        states = self.f.store.history(self.f.access.scope, run)
        mutate(states)
        with self.f.store._connection() as db:
            db.execute("DELETE FROM checkpoints WHERE scope=? AND run=?", (self.f.access.scope, run))
            previous = ""
            for sequence, state in enumerate(states):
                checksum = digest({"previous": previous, "state": state})
                db.execute("INSERT INTO checkpoints VALUES (?,?,?,?,?,?)",
                    (self.f.access.scope, run, sequence, previous, checksum, canonical_json(state)))
                previous = checksum

    @staticmethod
    def research_signature(report):
        evidence = {identity: {key: value for key, value in source.items() if key != "tool_call_id"}
                    for identity, source in report["evidence"].items()}
        return {"facts": report["facts"], "evidence": evidence,
                "hypotheses": report["hypotheses"], "gaps": report["gaps"],
                "verification": report["verification"], "event_anchor": report["event_anchor"]}

    def test_new_verification_view_is_a_distinct_contract_without_automatic_evidence_closure(self):
        candidate, metadata = self.wire()
        baseline, _ = self.wire(version=BASELINE)
        new = expand_view(json.loads(candidate[1]["content"])["context"])
        old = expand_view(json.loads(baseline[1]["content"])["context"])
        self.assertEqual(new["schema"], DISCLOSURE_SCHEMA)
        self.assertNotEqual(new["schema"], old["schema"])
        self.assertEqual(new["stage"], "verification")
        self.assertEqual(new["evidence"], [])
        self.assertTrue(old["evidence"])
        for key in ("facts", "hypotheses", "catalog_ids", "range", "required_checks", "event_anchor"):
            self.assertEqual(new[key], old[key], key)
        self.assertIn("disclosure_contract", new)
        self.assertIn("verification_manifest", new)
        self.assertEqual(metadata["evidence_preserved"], len(old["catalog_ids"]["evidence"]))
        self.assertEqual(metadata["evidence_included"], 0)
        with self.assertRaises(ValidationError):
            decode_metadata_view(json.loads(candidate[1]["content"])["context"])

    def test_reference_counts_and_view_construction_never_complete_verification(self):
        _, _, _, observations, revisions, checks = self.inputs()
        messages, _ = self.wire(observations=observations, revisions=revisions, checks=checks)
        execution = json.loads(messages[1]["content"])["control"]["execution"]
        self.assertFalse(execution["can_finish"])
        self.assertEqual(execution["pending_checks"], ["verification"])
        self.assertEqual(execution["next_action"]["tool"], "verification")
        model = SequenceModel([*completed_actions()[:-2], finish(), finish()])
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual((report["status"], report["stop_reason"]), ("partial", "no_progress"))
        self.assertEqual(next(check["status"] for check in report["required_checks"]
                              if check["id"] == "verification"), "not_completed")
        self.assertFalse(any(event["event"] == "tool_started" and event["tool"] == "verification"
                             for event in report["trace"]))
        # Automatic deterministic revalidation can succeed while the required
        # model-selected verification execution remains unperformed.
        self.assertEqual(report["verification"]["status"], "verified")
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        self.assertNotIn("verification_execution", state)

    def test_completed_children_do_not_replace_parent_verification_execution(self):
        model = RoleModel([parallel_action(), tool("calculation", ["financial", "market"]),
                           tool("hypotheses", ["calculation"]), finish(), finish()])
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual((report["status"], report["stop_reason"]), ("partial", "no_progress"))
        self.assertEqual(len(report["child_results"]), 2)
        self.assertTrue(all(child["status"] == "completed" for child in report["child_results"]))
        self.assertEqual(next(check["status"] for check in report["required_checks"]
                              if check["id"] == "verification"), "not_completed")
        self.assertFalse(any(event["event"] == "tool_started" and event["tool"] == "verification"
                             for event in report["trace"]))

    def test_actual_verification_executes_against_all_original_objects_and_final_report_is_unchanged(self):
        baseline, _ = self.complete(version=BASELINE)
        calls = []
        def verified(computed, datasets, request):
            calls.append((deepcopy(computed), deepcopy(datasets)))
            return verify(computed, datasets, request)
        with patch("stock_research.research.dynamic.verify", side_effect=verified):
            candidate, model = self.complete()
        self.assertEqual(self.research_signature(candidate), self.research_signature(baseline))
        state = self.f.store.read(self.f.access.scope, candidate["run_id"])
        self.assertTrue(calls)
        self.assertTrue(all(set(computed["evidence"]) == set(candidate["evidence"])
                            for computed, _ in calls))
        receipt = state["verification_execution"]
        self.assertEqual(receipt["computed_ref"], digest(state["calculated"]))
        self.assertEqual(receipt["datasets_ref"], digest(self.runtime(None)._datasets(state)))
        self.assertEqual(receipt["turn"], 5)
        self.assertEqual(sum(event["event"] == "tool_started" and event["tool"] == "verification"
                             for event in candidate["trace"]), 1)
        self.assertTrue(all(check["status"] == "passed" for check in candidate["required_checks"]))
        for messages in model.messages:
            payload = json.loads(messages[1]["content"])
            if payload["context"]["stage"] == "verification":
                self.assertEqual(payload["context"]["evidence"], [])

    def test_synthetic_preverification_overflow_can_actually_verify_and_finish(self):
        # A larger pinned synthetic source, without made-up Evidence padding.
        with patch("research_fixtures.ts", return_value=ts("2025-10-01T00:00:00")):
            self.f = fixture(Path(self.temp.name) / "large", prices=("100",) * 80)
        base = study_request(self.f, hypotheses=("financial_deterioration",)).to_dict()
        base["as_of"] = "2025-10-02T00:00:00+00:00"
        for binding in base["bindings"]:
            if binding["dataset"] == "market_daily":
                binding["end"] = str(date(2025, 4, 1) + timedelta(days=79))
        self.request = DynamicRequest.from_dict({**base, "question": "SYNTHETIC W1 size mechanism only"})
        baseline_model = SequenceModel(completed_actions())
        baseline = self.runtime(baseline_model, spec=ParallelParentSpec(version=BASELINE)).run(
            self.request, self.f.access)
        self.assertEqual((baseline["status"], baseline["stop_reason"]),
                         ("partial", "dynamic_context_budget_exceeded"))
        self.assertEqual(baseline_model.calls, 4)
        candidate, model = self.complete()
        self.assertEqual(candidate["verification"]["evidence_checked"], len(candidate["evidence"]))
        self.assertEqual(len(candidate["evidence"]), 85)
        self.assertEqual(len(candidate["facts"]), len(baseline["facts"]))
        self.assertEqual(self.research_signature(candidate), self.research_signature(baseline))
        full, full_metadata = self.wire(version=BASELINE, max_bytes=100000)
        reduced, reduced_metadata = self.wire()
        self.assertGreater(full_metadata["bytes"], 12000)
        self.assertLessEqual(reduced_metadata["bytes"], 12000)
        self.assertGreater(full_metadata["bytes"], reduced_metadata["bytes"])
        self.assertEqual(full_metadata["bytes"], sum(len(value["content"].encode("utf-8")) for value in full))
        self.assertEqual(reduced_metadata["bytes"], sum(len(value["content"].encode("utf-8")) for value in reduced))
        self.assertEqual(model.calls, 6)
        self.assertTrue(all(sum(len(value["content"].encode("utf-8")) for value in wire) <= 12000
                            for wire in model.messages))

    def test_explicit_disclosure_retains_the_original_full_object_closure(self):
        _, _, _, observations, revisions, checks = self.inputs()
        messages, _ = self.wire(observations=observations, revisions=revisions, checks=checks,
                                refs=["O:hypotheses"])
        view = expand_view(json.loads(messages[1]["content"])["context"])
        self.assertEqual({row[0][2:] for row in view["evidence"]}, set(observations[-1]["evidence"]))
        self.assertFalse(json.loads(messages[1]["content"])["control"]["execution"]["can_finish"])
        catalog = build_catalog(self.request, sorted(observations, key=lambda item: item["tool"]),
            required_checks(self.request), scope=self.f.access.scope, run_id=RUN)
        resolved = resolve_catalog(catalog, ["O:hypotheses"], scope=self.f.access.scope,
                                  run_id=RUN, catalog_ref=catalog["catalog_ref"])
        self.assertEqual(resolved["O:hypotheses"], observations[-1])

    def test_verification_manifest_counts_and_refs_match_full_authoritative_catalog(self):
        _, datasets, computed, observations, revisions, checks = self.inputs()
        messages, _ = self.wire(observations=observations, revisions=revisions, checks=checks)
        view = expand_view(json.loads(messages[1]["content"])["context"])
        catalog = build_catalog(self.request, sorted(observations, key=lambda item: item["tool"]),
            required_checks(self.request), scope=self.f.access.scope, run_id=RUN)
        payload = decode_catalog(catalog, scope=self.f.access.scope, run_id=RUN)
        manifest = view["verification_manifest"]
        self.assertEqual(manifest["catalog_ref"], catalog["catalog_ref"])
        self.assertEqual(manifest["request_ref"], digest(self.request.to_dict()))
        self.assertEqual(manifest["execution_revisions"], revisions)
        self.assertFalse(manifest["execution_receipt"])
        self.assertEqual(manifest["collections"]["facts"]["count"], len(computed["facts"]))
        self.assertEqual(manifest["collections"]["evidence"]["count"], len(computed["evidence"]))
        self.assertEqual(manifest["collections"]["hypotheses"]["count"], len(computed["hypotheses"]))
        self.assertEqual(manifest["source_records"], sum(len(result["records"]) for result in datasets.values()))
        self.assertEqual(manifest["complete_state_ref"], digest({key: payload[key] for key in
            ("request", "observations", "required_checks")}))
        for field in ("source_records", "complete_state_ref"):
            altered = deepcopy(json.loads(messages[1]["content"])["context"])
            altered["verification_manifest"][field] = (manifest[field] + 1 if field == "source_records" else "0" * 64)
            with self.subTest(field=field), self.assertRaises((IntegrityError, ValidationError)):
                validate_view(altered, catalog, scope=self.f.access.scope, run_id=RUN,
                              execution_revisions=revisions)

    def test_original_verifier_rejects_rehashed_value_source_reference_time_and_omission(self):
        _, datasets, computed, _, _, _ = self.inputs()
        self.assertEqual(verify(computed, datasets, self.request)["status"], "verified")
        for alteration in ("value", "source", "reference", "time", "omission", "snapshot"):
            corrupted, sources = deepcopy(computed), deepcopy(datasets)
            fact = corrupted["facts"][0]
            if alteration == "value":
                fact["value"] = "99999"
                fact["id"] = digest({key: value for key, value in fact.items() if key != "id"})
            elif alteration == "source":
                next(iter(corrupted["evidence"].values()))["provider"] = "forged"
            elif alteration == "reference":
                fact["inputs"] = ["0" * 64]
                fact["id"] = digest({key: value for key, value in fact.items() if key != "id"})
            elif alteration == "time":
                next(iter(corrupted["evidence"].values()))["available_at"] = "2099-01-01T00:00:00+00:00"
            elif alteration == "omission":
                corrupted["facts"].pop()
            else:
                next(iter(sources.values()))["snapshot"] = "0" * 64
            with self.subTest(alteration=alteration), self.assertRaises(IntegrityError):
                verify(corrupted, sources, self.request)

    def test_lawful_insufficient_requires_actual_verification_and_preserves_all_gaps(self):
        request = replace(self.request, bindings=tuple(replace(binding, start=date(2024, 12, 31))
            if binding.dataset == "financial_income" else binding for binding in self.request.bindings))
        actions = completed_actions()
        actions[-1] = finish("insufficient")
        report = self.runtime(SequenceModel(actions)).run(request, self.f.access)
        self.assertEqual(report["status"], "insufficient")
        self.assertEqual(report["verification"]["status"], "verified")
        self.assertEqual(report["hypotheses"][0]["status"], "insufficient")
        self.assertTrue(report["gaps"])
        self.assertEqual(report["required_checks"][-1]["status"], "insufficient")
        self.assertTrue(all(check["status"] == "passed" for check in report["required_checks"][:-1]))
        self.assertIn("verification_execution", self.f.store.read(self.f.access.scope, report["run_id"]))

    def test_duplicate_verification_is_not_executed_and_two_duplicates_still_stop(self):
        model = SequenceModel([*completed_actions()[:-1], tool("verification", ["hypotheses"]),
                               tool("verification", ["hypotheses"])])
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual((report["status"], report["stop_reason"]), ("partial", "no_progress"))
        self.assertEqual(report["usage"]["tool_calls"], 5)
        self.assertEqual(sum(event["event"] == "tool_started" and event["tool"] == "verification"
                             for event in report["trace"]), 1)
        self.assertEqual(sum(event["event"] == "repeated_action" and not event["dispatched"]
                             for event in report["trace"]), 2)

    def test_every_actual_system_and_user_wire_is_measured_and_exact_cap_remains(self):
        report, model = self.complete()
        for messages, record in zip(model.messages, report["context_telemetry"]):
            self.assertEqual([message["role"] for message in messages], ["system", "user"])
            size = sum(len(message["content"].encode("utf-8")) for message in messages)
            self.assertEqual(record["total_context_bytes"], size)
            self.assertEqual(record["message_sha256"], digest(messages))
            self.assertLessEqual(size, 12000)
            self.assertEqual((record["input_tokens"], record["output_tokens"], record["total_tokens"]), (100, 20, 120))
        messages, metadata = self.wire()
        self.assertEqual(self.wire(max_bytes=metadata["bytes"])[0], messages)
        with self.assertRaises(ValidationError):
            self.wire(max_bytes=metadata["bytes"] - 1)
        with self.assertRaises(ValidationError):
            ParallelParentSpec(version=VERSION, context_bytes=12001)

    def test_non_evidence_minimum_inputs_still_stop_without_clipping(self):
        # W1 leaves exact source periods and directories mandatory. Their growth
        # can still exceed the fixed cap; no paging or silent clipping is allowed.
        with patch("research_fixtures.ts", return_value=ts("2026-04-15T00:00:00")):
            self.f = fixture(Path(self.temp.name) / "non-evidence-overflow", prices=("100",) * 300)
        base = study_request(self.f, hypotheses=("financial_deterioration",)).to_dict()
        base["as_of"] = "2026-04-16T00:00:00+00:00"
        for binding in base["bindings"]:
            if binding["dataset"] == "market_daily":
                binding["end"] = str(date(2025, 4, 1) + timedelta(days=299))
        self.request = DynamicRequest.from_dict({**base, "question": "SYNTHETIC " + "x" * 1900})
        model = SequenceModel(completed_actions())
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual((report["status"], report["stop_reason"]),
                         ("partial", "dynamic_context_budget_exceeded"))
        self.assertLess(model.calls, 5)
        self.assertFalse(any(event["event"] == "tool_started" and event["tool"] == "verification"
                             for event in report["trace"]))
        self.assertFalse(report["context_telemetry"][-1]["model_dispatched"])
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        self.assertEqual(len(state["outputs"]["market"]["market_daily"]["records"]), 300)

    def test_same_parent_explicit_child_v3_direct_serial_parallel_paths_preserve_quality_and_replay(self):
        suffix = completed_actions()[2:]
        paths = {"direct": completed_actions(),
                 "serial": [tool("financial_child"), tool("market_child"), *suffix],
                 "parallel": [parallel_action(), *suffix]}
        signatures = []
        for route, actions in paths.items():
            with self.subTest(route=route):
                model = RoleModel(actions)
                report = self.runtime(model).run(self.request, self.f.access)
                self.assertEqual(report["status"], "completed")
                signatures.append(self.research_signature(report))
                self.assertTrue(all(check["status"] == "passed" for check in report["required_checks"]))
                for role, _, messages in model.messages:
                    self.assertLessEqual(sum(len(message["content"].encode("utf-8")) for message in messages), 12000)
                    if role != "parent":
                        self.assertEqual(json.loads(messages[1]["content"])["protocol_version"], role + "-child-v3")
                fresh = RoleModel([])
                with patch.object(self.f.store, "append", wraps=self.f.store.append) as append, \
                        patch.object(self.f.service, "refresh", wraps=self.f.service.refresh) as provider:
                    restored = self.runtime(fresh).run(self.request, self.f.access, resume=report["run_id"])
                self.assertEqual(restored, report)
                self.assertEqual(fresh.counts, {})
                append.assert_not_called()
                provider.assert_not_called()
                self.assertEqual(report["usage"]["financial_provider_network_calls"], 0)
        self.assertTrue(all(signature == signatures[0] for signature in signatures))

    def test_revocation_before_verification_blocks_the_tool_even_with_no_evidence_in_prompt(self):
        service, grants = self.grant_service()
        def callback(turn, messages):
            if turn == 5:
                self.assertEqual(json.loads(messages[1]["content"])["context"]["evidence"], [])
                grants.clear()
            return completed_actions()[turn - 1]
        model = SequenceModel([], callback=callback)
        with self.assertRaises(PermissionDenied):
            self.runtime(model, service=service).run(self.request, self.f.access, run_id=RUN)
        state = self.f.store.read(self.f.access.scope, RUN)
        self.assertEqual(model.calls, 5)
        self.assertFalse("verification_execution" in state)
        self.assertFalse(any(event["event"] == "tool_started" and event["tool"] == "verification"
                             for event in state["trace"]))

    def test_revocation_during_verifier_prevents_a_successful_execution_receipt(self):
        service, grants = self.grant_service()
        runtime = self.runtime(SequenceModel(completed_actions()), service=service)
        original = runtime._verify_computed
        def revoke_after_verify(state, request):
            result = original(state, request)
            if (state.get("pending_tool") or {}).get("tool") == "verification":
                grants.clear()
            return result
        with patch.object(runtime, "_verify_computed", side_effect=revoke_after_verify), self.assertRaises(PermissionDenied):
            runtime.run(self.request, self.f.access, run_id=RUN)
        state = self.f.store.read(self.f.access.scope, RUN)
        self.assertFalse("verification_execution" in state)
        self.assertTrue(any(event["event"] == "tool_started" and event["tool"] == "verification"
                            for event in state["trace"]))
        self.assertFalse(any(event["event"] == "tool_finished" and event["tool"] == "verification"
                             for event in state["trace"]))

    def test_revocation_after_paid_intent_blocks_disclosure_before_model_dispatch(self):
        service, grants = self.grant_service()
        model = SequenceModel(completed_actions())
        append = self.f.store.append
        def revoke_after_intent(scope, run, state):
            append(scope, run, state)
            if state["trace"] and state["trace"][-1]["event"] == "model_started" and state["model_attempts"] == 5:
                grants.clear()
        with patch.object(self.f.store, "append", side_effect=revoke_after_intent), self.assertRaises(PermissionDenied):
            self.runtime(model, service=service).run(self.request, self.f.access, run_id=RUN)
        state = self.f.store.read(self.f.access.scope, RUN)
        self.assertEqual(model.calls, 4)
        self.assertEqual(state["decisions"][-1]["status"], "pending")
        self.assertGreater(state["tokens_accounted"], sum(d.get("total_tokens", 0) for d in state["decisions"]))
        self.assertFalse("verification_execution" in state)

    def test_revocation_during_final_revalidation_blocks_report_delivery(self):
        service, grants = self.grant_service()
        runtime = self.runtime(SequenceModel(completed_actions()), service=service)
        original = runtime._verify_computed
        def revoke_at_final_report(state, request):
            result = original(state, request)
            if state["report"] is not None:
                grants.clear()
            return result
        with patch.object(runtime, "_verify_computed", side_effect=revoke_at_final_report), self.assertRaises(PermissionDenied):
            runtime.run(self.request, self.f.access, run_id=RUN)
        state = self.f.store.read(self.f.access.scope, RUN)
        self.assertTrue(state["security_stopped"])
        self.assertFalse(any(event["event"] == "report_verified" for event in state["trace"]))

    def test_public_available_time_and_system_ingestion_time_remain_exact_in_candidate_views(self):
        released, ingested = ts("2025-04-15T10:00:00"), ts("2025-04-16T10:00:00")
        records = self.f.repo.read(self.f.access.scope, self.request.bindings[0].snapshot)
        financial = [replace(record, available_at=released, published_at=released,
            retrieved_at=released, ingested_at=ingested, announcement_date=released.date())
            for record in records if record.dataset.value == "financial_income"]
        snapshot = self.f.repo.commit(self.f.access.scope, (*self.f.records, *financial))
        cases = ((PITMode.PUBLIC, released - timedelta(microseconds=1), False),
                 (PITMode.PUBLIC, released, True),
                 (PITMode.SYSTEM, ingested - timedelta(microseconds=1), False),
                 (PITMode.SYSTEM, ingested, True))
        for mode, cutoff, visible in cases:
            with self.subTest(mode=mode.value, cutoff=cutoff):
                request = replace(self.request, mode=mode, as_of=cutoff,
                    bindings=tuple(replace(binding, snapshot=snapshot.snapshot_id) for binding in self.request.bindings))
                model = SequenceModel(completed_actions())
                report = self.runtime(model).run(request, self.f.access)
                self.assertEqual(report["verification"]["status"], "verified")
                ids = {record.record_id for record in financial}
                self.assertEqual({source["record_id"] for source in report["evidence"].values()} & ids,
                                 ids if visible else set())
                for source in report["evidence"].values():
                    self.assertLessEqual(ts(source["available_at"]), cutoff)
                    if mode == PITMode.SYSTEM:
                        self.assertLessEqual(ts(source["ingested_at"]), cutoff)
                    self.assertEqual(source["snapshot"], snapshot.snapshot_id)
                for messages in model.messages:
                    view = expand_view(json.loads(messages[1]["content"])["context"])
                    self.assertEqual(view["range"]["cutoff"], cutoff.isoformat())
                    self.assertEqual(view["range"]["pit_mode"], mode.value)
                    if not visible:
                        self.assertFalse(any(row[1] in {"revenue", "net_income_parent"} for row in view["evidence"]))

    def test_completed_replay_reauthorizes_scope_provider_grants_and_unchanged_snapshot(self):
        service, grants = self.grant_service()
        report, _ = self.complete(service=service)
        changed_snapshot = self.f.repo.commit(self.f.access.scope, self.f.records)
        changed_request = replace(self.request, bindings=tuple(
            replace(binding, snapshot=changed_snapshot.snapshot_id) for binding in self.request.bindings))
        for request, access in ((self.request, AccessContext("another-scope", self.f.access.allowed_providers)),
                                (self.request, replace(self.f.access, allowed_providers=frozenset({"revoked"}))),
                                (changed_request, self.f.access)):
            fresh = SequenceModel([])
            with self.subTest(scope=access.scope, request=request), self.assertRaises(PermissionDenied):
                self.runtime(fresh, service=service).run(request, access, resume=report["run_id"])
            self.assertEqual(fresh.calls, 0)
        grants.clear()
        fresh = SequenceModel([])
        with patch.object(self.f.store, "append", wraps=self.f.store.append) as append, self.assertRaises(PermissionDenied):
            self.runtime(fresh, service=service).run(self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(fresh.calls, 0)
        append.assert_not_called()

    def test_v4_view_cannot_cross_scope_run_catalog_or_authoritative_revision(self):
        _, _, _, observations, revisions, checks = self.inputs()
        messages, _ = self.wire(observations=observations, revisions=revisions, checks=checks)
        view = json.loads(messages[1]["content"])["context"]
        catalog = build_catalog(self.request, sorted(observations, key=lambda item: item["tool"]),
            required_checks(self.request), scope=self.f.access.scope, run_id=RUN)
        self.assertEqual(validate_view(view, catalog, scope=self.f.access.scope, run_id=RUN,
                                     execution_revisions=revisions), expand_view(view))
        for scope, run in (("foreign", RUN), (self.f.access.scope, "b" * 32)):
            with self.assertRaises(PermissionDenied):
                validate_view(view, catalog, scope=scope, run_id=run, execution_revisions=revisions)
        forged = deepcopy(view)
        forged["catalog_ref"] = "0" * 64
        with self.assertRaises((PermissionDenied, ValidationError)):
            validate_view(forged, catalog, scope=self.f.access.scope, run_id=RUN, execution_revisions=revisions)
        stale = {**revisions, "calculated": "0" * 64}
        with self.assertRaises((IntegrityError, ValidationError)):
            validate_view(view, catalog, scope=self.f.access.scope, run_id=RUN, execution_revisions=stale)
        with self.assertRaises(ValidationError):
            validate_view(view, catalog, scope=self.f.access.scope, run_id=RUN)

    def test_finished_recovery_rejects_stale_revision_or_changed_verification_receipt(self):
        for tamper in ("revision", "missing_receipt", "turn", "computed", "source", "result"):
            with self.subTest(tamper=tamper):
                report, _ = self.complete()
                state = self.f.store.read(self.f.access.scope, report["run_id"])
                if tamper == "revision":
                    state["calculated_revision"] = "0" * 64
                elif tamper == "missing_receipt":
                    state.pop("verification_execution")
                elif tamper == "turn":
                    state["verification_execution"]["turn"] = 4
                else:
                    key = {"computed": "computed_ref", "source": "source_revision", "result": "result_ref"}[tamper]
                    state["verification_execution"][key] = "0" * 64
                self.f.store.append(self.f.access.scope, report["run_id"], state)
                fresh = SequenceModel([])
                with self.assertRaises((IntegrityError, ValidationError)):
                    self.runtime(fresh).run(self.request, self.f.access, resume=report["run_id"])
                self.assertEqual(fresh.calls, 0)

    def test_hash_valid_history_forgery_cannot_replace_actual_verification_execution(self):
        model = SequenceModel([*completed_actions()[:-2], finish(), finish()])
        report = self.runtime(model).run(self.request, self.f.access)
        def corrupt(states):
            for state in states:
                if "hypotheses_revision" in state:
                    state["verified_revision"] = state["hypotheses_revision"]
        self.rewrite_history(report["run_id"], corrupt)
        fresh = SequenceModel([])
        with self.assertRaises(IntegrityError):
            self.runtime(fresh).run(self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(fresh.calls, 0)

    def test_current_recovered_calculation_cannot_omit_an_executed_source(self):
        from stock_research.research.hypotheses import diagnose_insufficiency, test_hypotheses
        from stock_research.research.study import calculate_study_claims
        report, _ = self.complete()
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        financial = DynamicRuntime._datasets(state, ["financial"])
        partial = calculate_study_claims(financial, self.request)
        partial["hypotheses"] = test_hypotheses(partial, financial, self.request)
        partial["insufficiency_diagnostics"] = diagnose_insufficiency(partial, financial, self.request)
        # This subset is arithmetically valid, so Runtime must enforce the complete
        # executed-source set before passing inputs to the unchanged verifier.
        self.assertEqual(verify(partial, financial, self.request)["status"], "verified")
        self.assertLess(len(partial["facts"]), len(state["calculated"]["facts"]))
        state["calculated"], state["computed_sources"] = partial, ["financial"]
        with self.assertRaises(IntegrityError):
            self.runtime(SequenceModel([]))._verify_computed(state, self.request)

    def test_paid_action_resume_preserves_new_wire_and_never_repeats_the_decision(self):
        original = self.f.store.append
        def crash_after_action(scope, run, state):
            original(scope, run, state)
            if state["trace"] and state["trace"][-1]["event"] == "plan_updated":
                raise KeyboardInterrupt()
        first = SequenceModel([tool("financial")])
        with patch.object(self.f.store, "append", side_effect=crash_after_action), self.assertRaises(KeyboardInterrupt):
            self.runtime(first).run(self.request, self.f.access, run_id=RUN)
        resumed = SequenceModel(completed_actions()[1:])
        report = self.runtime(resumed).run(self.request, self.f.access, resume=RUN)
        self.assertEqual(report["status"], "completed")
        self.assertEqual((first.calls, resumed.calls, report["usage"]["model_attempts"]), (1, 5, 6))
        self.assertEqual(report["context_telemetry"][0]["message_sha256"], digest(first.messages[0]))

    def test_unknown_paid_result_never_replays_or_releases_reserved_usage(self):
        first = SequenceModel([], crash=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.runtime(first).run(self.request, self.f.access, run_id=RUN)
        state = self.f.store.read(self.f.access.scope, RUN)
        fresh = SequenceModel([])
        report = self.runtime(fresh).run(self.request, self.f.access, resume=RUN)
        self.assertEqual(fresh.calls, 0)
        self.assertEqual(report["stop_reason"], "unknown_model_outcome_no_replay")
        self.assertEqual(report["usage"]["tokens_reserved"], state["tokens_reserved"])
        self.assertEqual(report["context_telemetry"][0]["message_sha256"], digest(first.messages[0]))

    def test_completed_replay_refuses_underlying_artifact_tamper_without_model_or_append(self):
        report, _ = self.complete()
        self.f.artifacts._path(self.f.access.scope, self.f.financial.artifact_id).write_bytes(b"corrupt synthetic")
        fresh = SequenceModel([])
        with patch.object(self.f.store, "append", wraps=self.f.store.append) as append, self.assertRaises(IntegrityError):
            self.runtime(fresh).run(self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(fresh.calls, 0)
        append.assert_not_called()

    def test_old_parent_v3_wire_reconstruction_and_default_identity_are_unchanged(self):
        report, model = self.complete(version=BASELINE)
        before = self.f.store.history(self.f.access.scope, report["run_id"])
        fresh = SequenceModel([])
        with patch.object(self.f.store, "append", wraps=self.f.store.append) as append:
            restored = self.runtime(fresh, spec=ParallelParentSpec(version=BASELINE)).run(
                self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(restored, report)
        self.assertEqual(before, self.f.store.history(self.f.access.scope, report["run_id"]))
        self.assertEqual(fresh.calls, 0)
        append.assert_not_called()
        for messages in model.messages:
            view = json.loads(messages[1]["content"])["context"]
            self.assertEqual(expand_view(view), expand_view(decode_metadata_view(view)))
        self.assertEqual(ParallelParentSpec().version, "dynamic-parent-parallel-v1")
        self.assertEqual(ParallelParentSpec().identity,
                         "5120ebab68444745152040f21bdf1e21e65a73cc3d8da085ea1c4def453ebf00")
        self.assertNotEqual(self.spec.identity, ParallelParentSpec(version=BASELINE).identity)


if __name__ == "__main__":
    unittest.main()
