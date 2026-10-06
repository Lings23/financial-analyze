"""Synthetic v2 Context runtime security; no live Provider or financial truth."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from helpers import ts
from research_fixtures import fixture
from study_fixtures import study_request
from test_dynamic import SequenceModel, completed_actions, finish, tool
from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.models import canonical_json, digest
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_context import resolve_catalog
from stock_research.research.dynamic_contracts import (DomainParentSpec, DynamicRequest, FinancialChildSpec,
    FinancialRequest, MarketChildSpec, MarketRequest)
from stock_research.research.scoped import ScopedReadService, SourceGrant


def disclose(messages):
    view = json.loads(messages[1]["content"])["context"]
    return {"action": "disclose", "catalog_ref": view["catalog_ref"],
            "refs": [view["catalog_ids"]["observations"][0]], "plan": ["读取已授权目录引用"]}


def scripted(steps):
    def choose(call, messages):
        if call > len(steps):
            raise AssertionError("runtime exceeded the scripted decisions")
        action = steps[call - 1]
        return action(messages) if callable(action) else action
    return SequenceModel([], callback=choose)


class DomainContextRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.request = DynamicRequest.from_dict({
            **study_request(self.f, hypotheses=("financial_deterioration",)).to_dict(),
            "question": "SYNTHETIC: test authorized lossless Context mechanisms",
        })
        self.spec = DomainParentSpec(version="dynamic-parent-domains-v2")

    def runtime(self, model, **kwargs):
        return DynamicRuntime(self.f.service, self.f.store, model, kwargs.pop("spec", self.spec), **kwargs)

    def complete(self, *, service=None):
        model = scripted([tool("financial"), tool("market"), tool("calculation", ["financial", "market"]), disclose,
                          tool("hypotheses", ["calculation"]), tool("verification", ["hypotheses"]), finish()])
        report = DynamicRuntime(service or self.f.service, self.f.store, model, self.spec).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        return report, model

    def latest_run(self):
        with self.f.store._connection() as db:
            return db.execute("SELECT run FROM checkpoints ORDER BY rowid DESC LIMIT 1").fetchone()[0]

    def grant_service(self):
        grants = [SourceGrant(self.f.service, self.f.access, binding.snapshot, self.request.data_request(binding), binding.provider)
                  for binding in self.request.bindings]
        return ScopedReadService(self.f.access.scope, lambda: tuple(grants)), grants

    def assert_resume_rejected_without_model(self, run):
        model = SequenceModel([])
        with self.assertRaises((IntegrityError, PermissionDenied)):
            self.runtime(model).run(self.request, self.f.access, resume=run)
        self.assertEqual(model.calls, 0)

    def rewrite_history(self, run, mutate):
        """A malicious hash-valid local rewrite must still fail semantic recovery."""
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

    def test_disclosure_preserves_full_objects_and_is_charged_as_a_real_tool(self):
        report, model = self.complete()
        baseline = self.runtime(SequenceModel(completed_actions())).run(self.request, self.f.access)
        signature = lambda value: (value["name"], value["value"], value["unit"], tuple(value["window"]))
        self.assertEqual({signature(fact) for fact in report["facts"]}, {signature(fact) for fact in baseline["facts"]})
        self.assertEqual(len(report["evidence"]), len(baseline["evidence"]))
        self.assertEqual(model.calls, 7)
        self.assertEqual(report["usage"]["tool_calls"], 6)
        self.assertEqual(report["root_budget"]["model_attempts"], 7)
        self.assertEqual(report["root_budget"]["tool_attempts"], 6)
        self.assertEqual(report["root_budget"]["tokens_accounted"], 840)
        self.assertEqual(report["root_budget"]["unknown_usage_calls"], 0)
        self.assertEqual(len(report["context_archive"]["disclosures"]), 1)
        self.assertEqual(report["context_archive"]["authoritative_facts_preserved"], len(report["facts"]))
        self.assertEqual(report["context_archive"]["authoritative_evidence_preserved"], len(report["evidence"]))
        for messages in model.messages:
            self.assertLessEqual(sum(len(message["content"].encode("utf-8")) for message in messages), 12000)
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        disclosure = state["context_store"]["disclosures"][0]
        catalog = state["context_store"]["catalogs"][disclosure["catalog_ref"]]
        resolved = resolve_catalog(catalog, disclosure["refs"], scope=self.f.access.scope,
                                   run_id=report["run_id"], catalog_ref=disclosure["catalog_ref"])
        self.assertEqual(digest(resolved), disclosure["result_ref"])
        self.assertTrue(all(check["status"] == "passed" for check in report["required_checks"]))

    def test_duplicate_disclosure_never_dispatches_twice_and_stops_within_original_budget(self):
        model = scripted([tool("financial"), disclose, disclose, disclose])
        with patch("stock_research.research.dynamic_context.resolve_catalog", wraps=resolve_catalog) as resolve:
            report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "no_progress")
        self.assertEqual(model.calls, 4)
        self.assertEqual(report["usage"]["tool_calls"], 2)
        self.assertEqual(len(report["context_archive"]["disclosures"]), 1)
        repeats = [event for event in report["trace"] if event["event"] == "repeated_action"]
        self.assertEqual(len(repeats), 2)
        self.assertTrue(all(event["tool"] == "context_disclosure" and not event["dispatched"] for event in repeats))
        # Subsequent history validation may resolve a committed receipt, but only
        # one actual context tool attempt and one disclosure are committed.
        self.assertGreaterEqual(resolve.call_count, 1)
        self.assertEqual(report["root_budget"]["tokens_accounted"], 480)

    def test_disclosing_context_never_satisfies_pending_research_checks(self):
        report = self.runtime(scripted([tool("financial"), disclose, finish("insufficient"), finish()])).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "no_progress")
        rejections = [decision["rejection"] for decision in report["decisions"] if "rejection" in decision]
        self.assertEqual(len(rejections), 2)
        for rejection in rejections:
            self.assertTrue({"read:market", "calculation", "hypotheses", "verification"} <= set(rejection["pending_checks"]))
        self.assertTrue(all(check["status"] == "not_completed" for check in report["required_checks"]
                            if check["id"] in {"read:market", "calculation", "hypotheses", "verification"}))

    def test_disclosure_obeys_local_and_root_tool_budgets(self):
        for spec, reason in ((DomainParentSpec(version=self.spec.version, max_tools=1), "tool_budget_exceeded"),
                             (DomainParentSpec(version=self.spec.version, root_max_tools=1), "root_budget_exceeded")):
            with self.subTest(reason=reason):
                model = scripted([tool("financial"), disclose])
                report = self.runtime(model, spec=spec).run(self.request, self.f.access)
                self.assertEqual(report["stop_reason"], reason)
                self.assertEqual(model.calls, 2)
                self.assertEqual(report["context_archive"]["disclosures"], [])
                self.assertEqual(report["root_budget"]["tool_attempts"], 1)

    def test_context_decisions_and_tokens_are_bounded_before_extra_dispatch(self):
        model = scripted([tool("financial"), disclose])
        report = self.runtime(model, spec=DomainParentSpec(version=self.spec.version, max_decisions=2)).run(self.request, self.f.access)
        self.assertEqual(model.calls, 2)
        self.assertEqual(report["stop_reason"], "decision_budget_exceeded")
        exhausted = SequenceModel([])
        report = self.runtime(exhausted, spec=DomainParentSpec(version=self.spec.version, root_max_tokens=1)).run(self.request, self.f.access)
        self.assertEqual(exhausted.calls, 0)
        self.assertEqual(report["stop_reason"], "root_budget_exceeded")

    def test_old_financial_and_market_leaves_reject_disclosure_protocol(self):
        action = {"action": "disclose", "catalog_ref": "a" * 64, "refs": ["O:financial"], "plan": ["拒绝未授权披露"]}
        for spec, request_type in ((FinancialChildSpec(), FinancialRequest), (MarketChildSpec(), MarketRequest)):
            with self.subTest(version=spec.version):
                model = SequenceModel([action, action])
                runtime = self.runtime(model, spec=spec, parent_run_id="b" * 32,
                                       inherited_deadline=ts("2099-01-01T00:00:00"))
                report = runtime.run(request_type.from_parent(self.request), self.f.access)
                self.assertEqual(model.calls, 2)
                self.assertEqual(report["stop_reason"], "no_progress")
                self.assertEqual(report["usage"]["tool_calls"], 0)
                self.assertNotIn("context_archive", report)

    def test_completed_catalog_replay_has_zero_model_calls_and_identical_report(self):
        report, _ = self.complete()
        model = SequenceModel([])
        restored = self.runtime(model).run(self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(restored, report)
        self.assertEqual(model.calls, 0)

    def test_live_source_grant_revoked_after_resolve_discards_disclosure(self):
        service, grants = self.grant_service()
        model = scripted([tool("financial"), disclose])
        def revoke(*args, **kwargs):
            result = resolve_catalog(*args, **kwargs)
            grants.clear()
            return result
        with patch("stock_research.research.dynamic_context.resolve_catalog", side_effect=revoke):
            with self.assertRaises(PermissionDenied):
                DynamicRuntime(service, self.f.store, model, self.spec).run(self.request, self.f.access)
        self.assertEqual(model.calls, 2)
        state = self.f.store.read(self.f.access.scope, self.latest_run())
        self.assertEqual(state["context_store"]["disclosures"], [])
        self.assertFalse(any(event["event"] == "context_disclosed" for event in state["trace"]))

    def test_completed_catalog_replay_rechecks_current_source_grants(self):
        service, grants = self.grant_service()
        report, _ = self.complete(service=service)
        grants.clear()
        model = SequenceModel([])
        with self.assertRaises(PermissionDenied):
            DynamicRuntime(service, self.f.store, model, self.spec).run(self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(model.calls, 0)

    def test_rehashed_catalog_removal_mutation_and_unbound_addition_are_rejected(self):
        def remove(state):
            state["context_store"]["catalogs"].pop(next(iter(state["context_store"]["catalogs"])))
        def alter(state):
            next(iter(state["context_store"]["catalogs"].values()))["catalog_ref"] = "a" * 64
        def add(state):
            state["context_store"]["catalogs"]["c" * 64] = deepcopy(next(iter(state["context_store"]["catalogs"].values())))
        for name, mutate in (("removed", remove), ("hash_mutated", alter), ("unbound", add)):
            with self.subTest(corruption=name):
                report, _ = self.complete()
                state = self.f.store.read(self.f.access.scope, report["run_id"])
                mutate(state)
                self.f.store.append(self.f.access.scope, report["run_id"], state)
                self.assert_resume_rejected_without_model(report["run_id"])

    def test_rehashed_disclosure_selection_and_foreign_scope_bindings_are_rejected(self):
        for name in ("selection", "foreign_scope"):
            with self.subTest(corruption=name):
                report, _ = self.complete()
                state = self.f.store.read(self.f.access.scope, report["run_id"])
                if name == "selection":
                    state["context_store"]["requested_refs"] = ["E:unpaid-selection"]
                else:
                    state["context_store"]["binding"] = digest({"scope": "foreign", "run_id": report["run_id"],
                                                               "request": self.request.to_dict()})
                self.f.store.append(self.f.access.scope, report["run_id"], state)
                self.assert_resume_rejected_without_model(report["run_id"])

    def test_hash_valid_history_still_rejects_modified_paid_wire_metadata(self):
        report, _ = self.complete()
        def corrupt(states):
            paid = next(state for state in states if state["trace"] and state["trace"][-1]["event"] == "model_started")
            paid["context"]["bytes"] += 1
        self.rewrite_history(report["run_id"], corrupt)
        self.assert_resume_rejected_without_model(report["run_id"])

    def test_hash_valid_history_still_rejects_forged_context_read_result(self):
        report, _ = self.complete()
        def corrupt(states):
            for state in states:
                for receipt in state["context_store"]["disclosures"]:
                    receipt["result_ref"] = "d" * 64
                for event in state["trace"]:
                    if event["event"] == "context_disclosed":
                        event["result_ref"] = "d" * 64
                    elif event["event"] == "tool_finished" and event["tool"] == "context_disclosure":
                        event["result_hash"] = "d" * 64
        self.rewrite_history(report["run_id"], corrupt)
        self.assert_resume_rejected_without_model(report["run_id"])

    def test_unknown_paid_model_context_intent_is_not_replayed(self):
        def callback(call, messages):
            if call == 2:
                raise KeyboardInterrupt()
            return tool("financial")
        with self.assertRaises(KeyboardInterrupt):
            self.runtime(SequenceModel([], callback=callback)).run(self.request, self.f.access)
        model = SequenceModel([])
        report = self.runtime(model).run(self.request, self.f.access, resume=self.latest_run())
        self.assertEqual(model.calls, 0)
        self.assertEqual(report["stop_reason"], "unknown_model_outcome_no_replay")
        self.assertEqual(report["root_budget"]["unknown_usage_calls"], 1)
        self.assertGreater(report["root_budget"]["tokens_accounted"], report["root_budget"]["total_tokens"])

    def test_unknown_context_tool_intent_is_not_replayed(self):
        model = scripted([tool("financial"), disclose])
        with patch("stock_research.research.dynamic_context.resolve_catalog", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.runtime(model).run(self.request, self.f.access)
        replacement = SequenceModel([])
        with patch("stock_research.research.dynamic_context.resolve_catalog", wraps=resolve_catalog) as resolve:
            report = self.runtime(replacement).run(self.request, self.f.access, resume=self.latest_run())
        self.assertEqual(replacement.calls, 0)
        resolve.assert_not_called()
        self.assertEqual(report["stop_reason"], "unknown_tool_outcome_no_replay")
        self.assertEqual(report["context_archive"]["disclosures"], [])

    def test_cancel_or_deadline_after_resolve_discards_late_disclosure(self):
        for reason in ("cancelled", "deadline_exceeded"):
            with self.subTest(reason=reason):
                cancelled = [False]
                clock = [ts("2026-10-05T00:00:00")]
                def late(*args, **kwargs):
                    result = resolve_catalog(*args, **kwargs)
                    if reason == "cancelled":
                        cancelled[0] = True
                    else:
                        clock[0] += timedelta(seconds=241)
                    return result
                model = scripted([tool("financial"), disclose])
                with patch("stock_research.research.dynamic_context.resolve_catalog", side_effect=late):
                    report = self.runtime(model, cancelled=lambda: cancelled[0], now=lambda: clock[0],
                                          monotonic=lambda: 0).run(self.request, self.f.access)
                self.assertEqual(report["stop_reason"], reason)
                self.assertEqual(model.calls, 2)
                self.assertEqual(report["context_archive"]["disclosures"], [])
                self.assertFalse(any(event["event"] == "context_disclosed" for event in report["trace"]))
                self.assertEqual(report["root_budget"]["tool_attempts"], 2)


if __name__ == "__main__":
    unittest.main()
