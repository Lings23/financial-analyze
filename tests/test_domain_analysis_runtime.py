"""Synthetic analysis execution/safety fixtures, never real financial truth."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from research_fixtures import fixture
from study_fixtures import study_request
from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.model_adapters.chat import ChatResult
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest
from stock_research.research.domain_analysis_contracts import DomainAnalysisParentSpec
from stock_research.research.study import calculate_study_claims
from stock_research.research.hypotheses import test_hypotheses
from stock_research.research.tools import read_domain


class AnalysisModel:
    config = SimpleNamespace(model="deepseek-v4-flash-0731")

    def __init__(self, callback=None, split=False):
        self.counts, self.messages = Counter(), []
        self.callback, self.split, self.lock = callback, split, Lock()

    def complete(self, messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        version = payload["protocol_version"]
        role = "financial" if version == "financial-analysis-child-v1" else "market" if version == "market-analysis-child-v1" else "parent"
        with self.lock:
            self.counts[role] += 1
            turn = self.counts[role]
            self.messages.append((role, deepcopy(messages)))
        actions = payload["control"]["legal_next_actions"]
        action = actions[0] if actions else {"action": "finish", "reason": "completed", "plan": ["Request checked completion"]}
        if self.split and role != "parent" and action.get("tool") == "calculation" and len(actions) > 1:
            action = actions[1]
        if self.callback:
            replacement = self.callback(role, turn, payload, action)
            if replacement is not None:
                action = replacement
        return ChatResult(self.config.model, self.config.model, json.dumps(action), "stop", "synthetic-analysis", 100, 20, 120, 1)


class AnalysisRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.request = DynamicRequest.from_dict({**study_request(self.f, hypotheses=("financial_deterioration",)).to_dict(),
            "question": "SYNTHETIC: analyze the fixed Financial and Market goal"})

    def runtime(self, model, mode="child", execution="serial", **kwargs):
        spec = kwargs.pop("spec", DomainAnalysisParentSpec(mode=mode, execution=execution))
        return DynamicRuntime(self.f.service, self.f.store, model, spec, **kwargs)

    def test_three_routes_equal_canonical_full_result(self):
        datasets = {**read_domain(self.f.service, self.request, self.f.access, "financial"),
                    **read_domain(self.f.service, self.request, self.f.access, "market")}
        expected = calculate_study_claims(datasets, self.request)
        expected_hypotheses = test_hypotheses(expected, datasets, self.request)
        for mode in ("direct", "tool", "child"):
            with self.subTest(mode=mode):
                model = AnalysisModel()
                report = self.runtime(model, mode).run(self.request, self.f.access)
                self.assertEqual(report["status"], "completed", report.get("stop_reason"))
                self.assertEqual(report["facts"], expected["facts"])
                self.assertEqual(report["gaps"], expected["gaps"])
                self.assertEqual(report["hypotheses"], expected_hypotheses)
                self.assertEqual(report["verification"]["status"], "verified")
                self.assertTrue(all(c["status"] == "passed" for c in report["required_checks"]))
                if mode == "tool":
                    self.assertEqual(report["root_budget"]["tool_attempts"], 11)
                elif mode == "child":
                    self.assertEqual(model.counts, {"parent": 6, "financial": 4, "market": 4})
                    self.assertEqual(report["root_budget"]["tool_attempts"], 11)
                    composition = report["domain_analysis"]["production_receipts"][0]
                    self.assertEqual(composition["produced_domains"], [])
                    for domain, result in report["domain_analysis"]["results"].items():
                        self.assertEqual(result["local_verification"]["status"], "verified")
                        self.assertEqual([r["tool"] for r in result["receipts"]], [domain, "calculation", "domain_review"])
                        self.assertTrue(all(e["tool_call_id"] == result["source_tool_call_id"] for e in result["computed"]["evidence"].values()))

    def test_completed_replay_zero_model_and_checkpoint_append(self):
        for mode in ("direct", "tool", "child"):
            with self.subTest(mode=mode):
                report = self.runtime(AnalysisModel(), mode).run(self.request, self.f.access)
                count = len(self.f.store.history(self.f.access.scope, report["run_id"]))
                model = AnalysisModel()
                replay = self.runtime(model, mode).run(self.request, self.f.access, resume=report["run_id"])
                self.assertEqual(replay, report)
                self.assertEqual(model.counts, {})
                self.assertEqual(len(self.f.store.history(self.f.access.scope, report["run_id"])), count)

    def test_parallel_consumes_both_results_and_keeps_parent_headroom(self):
        report = self.runtime(AnalysisModel(), execution="parallel").run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed", report.get("stop_reason"))
        self.assertEqual(report["root_budget"]["model_attempts"], 13)
        group = report["parallel_groups"][0]
        self.assertEqual(group["reservation_headroom"], {"decisions": 5, "tools": 6, "tokens": 47880})
        self.assertEqual(len(group["analysis_dag"]), 12)
        self.assertEqual(group["canonical_merge_order"], ["financial", "market"])
        replay_model = AnalysisModel()
        self.assertEqual(self.runtime(replay_model, execution="parallel").run(self.request, self.f.access, resume=report["run_id"]), report)
        self.assertEqual(replay_model.counts, {})

    def test_parent_does_not_produce_delegated_domain(self):
        import stock_research.research.domain_operators as operators
        original = operators.calculate_domain
        calls = []
        def tracked(datasets, request, domain, *args, **kwargs):
            calls.append((request.objective, domain))
            return original(datasets, request, domain, *args, **kwargs)
        with patch.object(operators, "calculate_domain", side_effect=tracked):
            report = self.runtime(AnalysisModel()).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(calls, [("financial_analysis", "financial"), ("market_analysis", "market")])

    def test_split_operators_complete_within_five_decisions(self):
        model = AnalysisModel(split=True)
        report = self.runtime(model).run(self.request, self.f.access)
        self.assertEqual(report["status"], "completed", report.get("stop_reason"))
        self.assertEqual(model.counts, {"parent": 6, "financial": 5, "market": 5})
        self.assertEqual(report["root_budget"]["model_attempts"], 16)

    def test_premature_child_finish_remains_strict(self):
        def early(role, turn, payload, action):
            if role == "financial" and turn <= 2:
                return {"action": "finish", "reason": "insufficient", "plan": ["Premature request"]}
        report = self.runtime(AnalysisModel(early)).run(self.request, self.f.access)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["child_results"][0]["stop_reason"], "no_progress")
        self.assertEqual(report["child_results"][0]["required_checks"][0]["status"], "not_completed")

    def test_revoked_calculation_after_child_read_stops(self):
        runtime = self.runtime(None)
        def revoke(role, turn, payload, action):
            if role == "financial" and turn == 1:
                runtime.granted -= {"calculation"}
        runtime.model = AnalysisModel(revoke)
        with self.assertRaises(PermissionDenied):
            runtime.run(self.request, self.f.access)

    def test_cancelled_child_results_are_withheld(self):
        cancelled = [False]
        def cancel(role, turn, payload, action):
            if role == "financial" and turn == 2:
                cancelled[0] = True
        report = self.runtime(AnalysisModel(cancel), cancelled=lambda: cancelled[0]).run(self.request, self.f.access)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["facts"], [])

    def test_root_preallocation_denies_workers_atomically(self):
        model = AnalysisModel()
        spec = DomainAnalysisParentSpec(root_max_tools=15)
        report = self.runtime(model, execution="parallel", spec=spec).run(self.request, self.f.access)
        self.assertEqual(report["stop_reason"], "root_budget_exceeded")
        self.assertEqual(model.counts, {"parent": 1})
        self.assertEqual(report["child_results"], [])


if __name__ == "__main__":
    unittest.main()
