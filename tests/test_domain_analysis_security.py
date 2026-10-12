"""Actual synthetic Runtime/checkpoint security evidence; no financial truth.

These tests exercise persisted source/calculation/review receipts and the real
root verifier. Scripted model actions are mechanism fixtures, never live model
quality or provider validation evidence.
"""
from collections import Counter
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from time import monotonic
import unittest
from unittest.mock import patch
import uuid

from helpers import ts
from research_fixtures import fixture
from study_fixtures import study_request
from test_domain_analysis_runtime import AnalysisModel
from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.models import digest
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest
from stock_research.research.domain_analysis_contracts import DomainAnalysisParentSpec
from stock_research.research.domain_analysis_execution import import_result, execution_receipts, _coverage
from stock_research.research.scoped import ScopedReadService, SourceGrant
from stock_research.research.verification import verify_domain


class DomainAnalysisSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name), scope="synthetic-domain-security")
        self.request = DynamicRequest.from_dict({**study_request(self.f,
            hypotheses=("financial_deterioration",)).to_dict(),
            "question": "SYNTHETIC: preserve the frozen Financial and Market target"})

    def runtime(self, model, *, mode="child", execution="serial", **kwargs):
        return DynamicRuntime(self.f.service, self.f.store, model,
            DomainAnalysisParentSpec(mode=mode, execution=execution), **kwargs)

    def complete(self, *, mode="child", execution="serial"):
        runtime = self.runtime(AnalysisModel(), mode=mode, execution=execution)
        report = runtime.run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed", report.get("stop_reason"))
        return runtime, report, self.f.store.read(self.f.access.scope, report["run_id"])

    def latest_parent(self):
        with self.f.store._connection() as db:
            row = db.execute("SELECT payload FROM checkpoints WHERE payload LIKE ? ORDER BY rowid DESC LIMIT 1",
                ('%"spec_version":"dynamic-parent-domain-analysis-v1"%',)).fetchone()
        self.assertIsNotNone(row)
        return json.loads(row[0])

    @staticmethod
    def rehash_report(report):
        report["result_digest"] = digest({key: value for key, value in report.items() if key != "result_digest"})

    @staticmethod
    def reservation_counts(state):
        return Counter(event["child_run_id"] for event in state["root_budget"]["events"]
                       if event["kind"] == "child_reserved")

    def test_child_review_only_fraction_parent_join_composition_and_replay_zero_local_oracle(self):
        import stock_research.research.domain_operators as operators
        counts = Counter()
        def counted(computed, datasets, request, domain, **kwargs):
            counts[(request.objective, domain)] += 1
            self.assertEqual(request.objective, domain + "_analysis")
            return verify_domain(computed, datasets, request, domain, **kwargs)
        runtime = self.runtime(AnalysisModel())
        with patch.object(operators, "verify_domain", side_effect=counted), \
                patch.object(operators, "expected_claims", side_effect=AssertionError("Parent must not run its extra Fraction projection")):
            report = runtime.run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed", report.get("stop_reason"))
        self.assertEqual(counts, {("financial_analysis", "financial"): 1, ("market_analysis", "market"): 1})
        self.assertEqual(runtime.analysis_metrics["root_full_execution"]["calls"], 1)
        self.assertGreater(runtime.analysis_metrics["root_full_integrity"]["calls"], 0)
        self.assertEqual(len([event for event in report["trace"] if event["event"] == "final_verification"]), 1)
        self.assertEqual(report["verification"]["status"], "verified")
        joins = [event for event in report["trace"] if event["event"] == "domain_join"]
        self.assertEqual({event["domain"] for event in joins}, {"financial", "market"})
        self.assertTrue(all(event["fraction_verifications"] == 0 for event in joins))
        history = {state["run_id"]: len(self.f.store.history(self.f.access.scope, state["run_id"]))
                   for state in [self.f.store.read(self.f.access.scope, report["run_id"]),
                   *[self.f.store.read(self.f.access.scope, child["child_run_id"]) for child in report["child_results"]]]}
        replay = self.runtime(AnalysisModel())
        with patch.object(operators, "verify_domain", side_effect=AssertionError("replay repeats Child Fraction")), \
                patch.object(operators, "expected_claims", side_effect=AssertionError("replay repeats Parent extra oracle")):
            self.assertEqual(replay.run(self.request, self.f.access, resume=report["run_id"]), report)
        self.assertEqual(replay.model.counts, {})
        self.assertEqual(replay.analysis_metrics["root_full_execution"]["calls"], 0)
        self.assertGreater(replay.analysis_metrics["root_full_integrity"]["calls"], 0)
        for run, count in history.items():
            self.assertEqual(len(self.f.store.history(self.f.access.scope, run)), count)

    def test_composite_tools_have_two_real_local_reviews_and_no_parent_local_reverification(self):
        import stock_research.research.domain_operators as operators
        counts = Counter()
        def counted(computed, datasets, request, domain, **kwargs):
            counts[domain] += 1
            return verify_domain(computed, datasets, request, domain, **kwargs)
        with patch.object(operators, "verify_domain", side_effect=counted):
            runtime, report, _ = self.complete(mode="tool")
        self.assertEqual(counts, {"financial": 1, "market": 1})
        self.assertEqual(runtime.analysis_metrics["root_full_execution"]["calls"], 1)
        with patch.object(operators, "verify_domain", side_effect=AssertionError("tool replay repeats local oracle")):
            self.assertEqual(self.runtime(AnalysisModel(), mode="tool").run(self.request, self.f.access,
                resume=report["run_id"]), report)

    def test_join_rejects_coordinated_report_tampering_against_actual_child_checkpoint(self):
        runtime, _, state = self.complete()
        original = state["domain_results"]["financial"]
        mutations = []
        for name in ("claim", "omission", "verification", "spec", "task", "source", "input", "receipt", "ownership", "source_call"):
            changed = deepcopy(original)
            if name == "claim":
                fact = changed["computed"]["facts"][0]
                fact["value"] = "999999"
                fact["id"] = digest({key: value for key, value in fact.items() if key != "id"})
                changed["coverage"]["fact_ids"] = [item["id"] for item in changed["computed"]["facts"]]
            elif name == "omission":
                changed["computed"]["facts"].pop()
                changed["computed"]["local_verification"]["numeric_claims"] -= 1
                changed["local_verification"]["numeric_claims"] -= 1
                changed["coverage"]["fact_ids"] = [item["id"] for item in changed["computed"]["facts"]]
            elif name == "verification":
                changed["local_verification"]["status"] = "verified"
                changed["local_verification"]["method"] = "self_declared"
                changed["computed"]["local_verification"] = deepcopy(changed["local_verification"])
            elif name == "spec":
                changed["spec_ref"] = "0" * 64
            elif name == "task":
                changed["task"]["required_operators"] = ["financial_snapshot"]
                changed["task"]["task_ref"] = digest({key: value for key, value in changed["task"].items() if key != "task_ref"})
                changed["task_ref"] = changed["task"]["task_ref"]
            elif name == "source":
                changed["source_results"]["financial_income"]["snapshot"] = "0" * 64
                changed["source_result_ref"] = digest(changed["source_results"])
            elif name == "input":
                changed["input_revision"] = "0" * 64
            elif name == "receipt":
                changed["receipts"][-1]["output_revision"] = "0" * 64
            elif name == "ownership":
                changed["local_attestation"]["ownership_ref"] = "0" * 64
            else:
                changed["source_tool_call_id"] = changed["receipts"][-1]["call_id"]
            self.rehash_report(changed)
            mutations.append((name, changed))
        import stock_research.research.domain_operators as operators
        for name, changed in mutations:
            with self.subTest(tamper=name), patch.object(operators, "verify_domain", side_effect=AssertionError("Join cannot use numeric fallback")):
                with self.assertRaises(IntegrityError):
                    import_result(runtime, deepcopy(state), self.request, changed, "financial", self.f.access)

    def test_cached_parent_result_coordinated_rehash_is_rejected_before_model_dispatch(self):
        _, report, state = self.complete()
        changed = state["domain_results"]["financial"]
        changed["computed"]["facts"][0]["value"] = "999999"
        changed["computed"]["facts"][0]["id"] = digest({key: value for key, value in changed["computed"]["facts"][0].items() if key != "id"})
        self.rehash_report(changed)
        summary = next(item for item in state["child_results"] if item["domain"] == "financial")
        summary["result_ref"] = digest(changed)
        state["report"]["domain_analysis"]["results"]["financial"] = deepcopy(changed)
        self.f.store.append(self.f.access.scope, report["run_id"], state)
        model = AnalysisModel()
        with self.assertRaises(IntegrityError):
            self.runtime(model).run(self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(model.counts, {})

    def test_join_rejects_rehashed_actual_child_checkpoint_rewriting_old_review_receipt(self):
        runtime, _, parent = self.complete()
        domain = parent["domain_results"]["financial"]
        run = domain["run_id"]
        child = self.f.store.read(self.f.access.scope, run)
        fact = child["calculated"]["facts"][0]
        fact["value"] = "999999"
        fact["id"] = digest({key: value for key, value in fact.items() if key != "id"})
        review = next(event for event in child["trace"] if event["event"] == "tool_finished" and event.get("tool") == "domain_review")
        review["result_hash"] = digest(child["calculated"])
        receipt = next(item for item in execution_receipts(child) if item["call_id"] == review["tool_call_id"])
        attestation = child["local_attestation"]
        attestation.update(computed_ref=digest(child["calculated"]), result_ref=digest(child["calculated"]),
                           review_receipt_ref=digest(receipt), coverage=_coverage(child["calculated"]))
        attestation["attestation_ref"] = digest({key: value for key, value in attestation.items() if key != "attestation_ref"})
        report = child["report"]
        report.update(computed=deepcopy(child["calculated"]), coverage=_coverage(child["calculated"]),
                      receipts=execution_receipts(child), local_attestation=deepcopy(attestation),
                      local_attestation_ref=attestation["attestation_ref"], trace=deepcopy(child["trace"]))
        self.rehash_report(report)
        self.f.store.append(self.f.access.scope, run, child)
        # The SQLite append/checksum chain is valid; historical real execution is
        # still authoritative and must reject a coordinated replacement receipt.
        self.assertEqual(self.f.store.read(self.f.access.scope, run), child)
        with self.assertRaisesRegex(IntegrityError, "history was rewritten"):
            import_result(runtime, parent, self.request, report, "financial", self.f.access)

    def test_join_reauthorizes_real_sources_and_replay_rejects_changed_ownership(self):
        runtime, report, state = self.complete()
        grants = [SourceGrant(self.f.service, self.f.access, binding.snapshot,
            self.request.data_request(binding), binding.provider) for binding in self.request.bindings]
        runtime.service = ScopedReadService(self.f.access.scope, lambda: [grant for grant in grants
            if grant.request.dataset.value != "financial_income"])
        with self.assertRaises(PermissionDenied):
            import_result(runtime, deepcopy(state), self.request, state["domain_results"]["financial"], "financial", self.f.access)
        state["analysis_ownership"]["check_ownership"]["financial_deterioration"] = "parent"
        state["report"]["domain_analysis"]["ownership"] = deepcopy(state["analysis_ownership"])
        self.f.store.append(self.f.access.scope, report["run_id"], state)
        model = AnalysisModel()
        with self.assertRaises(IntegrityError):
            self.runtime(model).run(self.request, self.f.access, resume=report["run_id"])
        self.assertEqual(model.counts, {})

    def test_child_review_receipt_crash_recovers_without_fraction_reexecution(self):
        import stock_research.research.domain_operators as operators
        parent = self.runtime(AnalysisModel())
        root_run, child_run = uuid.uuid4().hex, uuid.uuid4().hex
        deadline = (parent.now() + timedelta(seconds=240)).isoformat()
        child, request, access = parent._child_context(self.request, self.f.access, root_run, deadline, "financial")
        original = self.f.store.append
        fired = [False]
        def crash(scope, run, state):
            original(scope, run, state)
            if not fired[0] and run == child_run and state["trace"] and state["trace"][-1]["event"] == "tool_finished" \
                    and state["trace"][-1].get("tool") == "domain_review":
                fired[0] = True
                raise KeyboardInterrupt()
        with patch.object(self.f.store, "append", side_effect=crash), self.assertRaises(KeyboardInterrupt):
            child.run(request, access, run_id=child_run)
        state = self.f.store.read(access.scope, child_run)
        self.assertEqual(state["hypotheses_revision"], state["calculated_revision"])
        self.assertEqual(state["trace"][-1]["tool"], "domain_review")
        resumed, _, _ = parent._child_context(self.request, self.f.access, root_run, deadline, "financial")
        resumed.model = AnalysisModel()
        with patch.object(operators, "verify_domain", side_effect=AssertionError("known review repeated")):
            report = resumed.run(request, access, resume=child_run)
        self.assertEqual(report["status"], "completed", report.get("stop_reason"))
        self.assertEqual(resumed.model.counts, {"financial": 1})
        self.assertEqual(report["usage"]["tool_calls"], 3)
        self.assertTrue(report["local_attestation_ref"])

    def test_parent_crash_after_child_persisted_before_join_resumes_same_allocation(self):
        original = DynamicRuntime.run
        fired = [False]
        def crash(runtime, request, access, **kwargs):
            report = original(runtime, request, access, **kwargs)
            if not fired[0] and runtime.spec.version == "financial-analysis-child-v1" and report["status"] == "completed":
                fired[0] = True
                raise KeyboardInterrupt()
            return report
        with patch.object(DynamicRuntime, "run", new=crash), self.assertRaises(KeyboardInterrupt):
            self.runtime(AnalysisModel()).run(self.request, self.f.access)
        before = self.latest_parent()
        pending = before["pending_child"]
        child = self.f.store.read(self.f.access.scope, pending["run_id"])
        self.assertEqual(child["report"]["status"], "completed")
        self.assertEqual(self.reservation_counts(before)[pending["run_id"]], 1)
        self._assert_parent_known_child_resume(before, pending["run_id"])

    def test_parent_crash_after_join_before_source_import_resumes_without_rejoining_or_reserving(self):
        original = self.f.store.append
        fired = [False]
        def crash(scope, run, state):
            original(scope, run, state)
            if not fired[0] and state["spec_version"] == "dynamic-parent-domain-analysis-v1" and state["trace"] \
                    and state["trace"][-1]["event"] == "domain_join" and state["trace"][-1]["domain"] == "financial":
                fired[0] = True
                raise KeyboardInterrupt()
        with patch.object(self.f.store, "append", side_effect=crash), self.assertRaises(KeyboardInterrupt):
            self.runtime(AnalysisModel()).run(self.request, self.f.access)
        before = self.latest_parent()
        child_run = before["domain_results"]["financial"]["run_id"]
        self._assert_parent_known_child_resume(before, child_run)

    def _assert_parent_known_child_resume(self, before, child_run):
        import stock_research.research.domain_operators as operators
        original = operators.calculate_domain
        productions = Counter()
        def produce(datasets, request, domain, *args, **kwargs):
            productions[domain] += 1
            return original(datasets, request, domain, *args, **kwargs)
        model = AnalysisModel()
        with patch.object(operators, "calculate_domain", side_effect=produce):
            report = self.runtime(model).run(self.request, self.f.access, resume=before["run_id"])
        self.assertEqual(report["status"], "completed", report.get("stop_reason"))
        self.assertEqual(model.counts.get("financial", 0), 0)
        self.assertEqual(productions.get("financial", 0), 0)
        after = self.f.store.read(self.f.access.scope, before["run_id"])
        self.assertEqual(self.reservation_counts(after)[child_run], 1)
        self.assertEqual(len([result for result in after["child_results"] if result["domain"] == "financial"]), 1)
        self.assertEqual(after["domain_results"]["financial"]["run_id"], child_run)
        self.assertEqual(report["root_budget"]["model_attempts"], 14)

    def test_parallel_unknown_paid_child_stops_root_and_sibling_new_paid_and_preserves_reservation(self):
        rendezvous = Barrier(2, timeout=5)
        children = {}
        runtime = self.runtime(None, execution="parallel")
        original_context = runtime._child_context
        def capture_context(*args, **kwargs):
            result = original_context(*args, **kwargs)
            children[args[4] if len(args) > 4 else kwargs.get("domain", "financial")] = result[0]
            return result
        def unknown(role, turn, payload, action):
            if role in {"financial", "market"} and turn == 1:
                rendezvous.wait()
                if role == "financial":
                    raise RuntimeError("synthetic unknown model result")
                until = monotonic() + 5
                while not children["market"].cancelled() and monotonic() < until:
                    Event().wait(0.005)
                self.assertTrue(children["market"].cancelled())
        model = AnalysisModel(unknown)
        runtime.model = model
        with patch.object(runtime, "_child_context", side_effect=capture_context):
            report = runtime.run(self.request, self.f.access)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(model.counts["parent"], 1)
        self.assertEqual(model.counts["financial"], 1)
        self.assertEqual(model.counts["market"], 1)
        self.assertGreater(report["root_budget"]["unknown_usage_calls"], 0)
        self.assertGreater(report["root_budget"]["tokens_accounted"], report["root_budget"]["total_tokens"])
        self.assertEqual(report["facts"], [])
        replay_model = AnalysisModel()
        self.assertEqual(self.runtime(replay_model, execution="parallel").run(self.request, self.f.access,
            resume=report["run_id"]), report)
        self.assertEqual(replay_model.counts, {})

    def test_parallel_cancellation_discards_both_late_results_and_replays_without_dispatch(self):
        rendezvous, cancelled = Barrier(2, timeout=5), Event()
        def cancel(role, turn, payload, action):
            if role in {"financial", "market"} and turn == 1:
                rendezvous.wait()
                cancelled.set()
        model = AnalysisModel(cancel)
        report = self.runtime(model, execution="parallel", cancelled=cancelled.is_set).run(self.request, self.f.access)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["stop_reason"], "cancelled")
        self.assertEqual(model.counts, {"parent": 1, "financial": 1, "market": 1})
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["evidence"], {})
        state = self.f.store.read(self.f.access.scope, report["run_id"])
        self.assertEqual(state["domain_results"], {})
        self.assertEqual(state["outputs"], {})
        cancelled.clear()
        replay = AnalysisModel()
        self.assertEqual(self.runtime(replay, execution="parallel").run(self.request, self.f.access,
            resume=report["run_id"]), report)
        self.assertEqual(replay.counts, {})

    def test_parallel_absolute_deadline_discards_children_without_changing_cutoff(self):
        clock = [ts("2026-10-09T00:00:00")]
        rendezvous = Barrier(2, timeout=5)
        def late(role, turn, payload, action):
            if role in {"financial", "market"} and turn == 1:
                rendezvous.wait()
                clock[0] = ts("2026-10-09T00:04:01")
        report = self.runtime(AnalysisModel(late), execution="parallel", now=lambda: clock[0], monotonic=lambda: 0).run(
            self.request, self.f.access)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["stop_reason"], "deadline_exceeded")
        self.assertEqual(report["facts"], [])
        self.assertEqual(self.f.store.read(self.f.access.scope, report["run_id"])["request"], self.request.to_dict())

    def test_duplicate_child_operator_consumes_no_progress_and_cannot_mint_review_receipt(self):
        def repeat(role, turn, payload, action):
            if role == "financial" and turn in {3, 4}:
                return {"action": "tool", "tool": "calculation", "refs": ["financial", "operator:income_yoy"],
                        "plan": ["Repeat the already completed synthetic operator"]}
        report = self.runtime(AnalysisModel(repeat)).run(self.request, self.f.access)
        self.assertEqual(report["status"], "partial")
        financial = next(result for result in report["child_results"] if result["domain"] == "financial")
        self.assertEqual(financial["stop_reason"], "no_progress")
        child = self.f.store.read(self.f.access.scope, financial["child_run_id"])
        self.assertEqual(len([event for event in child["trace"] if event["event"] == "domain_production"]), 1)
        self.assertFalse(any(event["event"] == "domain_review_executed" for event in child["trace"]))
        self.assertFalse(child.get("local_attestation"))
        self.assertEqual(child["no_progress"], 2)

    def test_parent_early_finish_cannot_use_child_reviews_as_final_verification(self):
        def early(role, turn, payload, action):
            if role == "parent" and turn >= 3:
                return {"action": "finish", "reason": "completed", "plan": ["Request premature final completion"]}
        runtime = self.runtime(AnalysisModel(early))
        report = runtime.run(self.request, self.f.access)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["stop_reason"], "no_progress")
        self.assertEqual(runtime.analysis_metrics["root_full_execution"]["calls"], 0)
        self.assertTrue(all(result["local_verification"]["status"] == "verified"
                            for result in report["domain_analysis"]["results"].values()))
        checks = {check["id"]: check["status"] for check in report["required_checks"]}
        self.assertEqual(checks["verification"], "not_completed")
        self.assertFalse(any(event["event"] == "final_verification" for event in report["trace"]))


if __name__ == "__main__":
    unittest.main()
