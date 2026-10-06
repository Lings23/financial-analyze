"""Opt-in v5 runtime mechanisms with synthetic rows; no financial ground truth."""
import copy
from dataclasses import replace
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from helpers import ts
from research_fixtures import BundleFixtureModel, fixture
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.models import AccessContext, PITMode, digest
from stock_research.research.context import study_messages
from stock_research.research.profit_change import PROFIT_CLAIM_NAME
from stock_research.research.scoped import ScopedReadService, SourceGrant
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudyRequest, StudySpec
from stock_research.research.tools import read_domain


class StudyV5Tests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name), scope="synthetic-v5-profit")
        self.records = []
        for period, value in ((date(2023, 12, 31), "-100"), (date(2024, 12, 31), "-60")):
            artifact = self.f.artifacts.put(self.f.access.scope,
                                           {"synthetic": True, "period": str(period), "profit": value})
            metrics = tuple(replace(m, value=Decimal(value), raw_value=value)
                            if m.name == "net_income_parent" else m for m in self.f.financial.metrics)
            self.records.append(replace(self.f.financial, period=period, metrics=metrics,
                                        artifact_id=artifact, revision_id=artifact))
        self.snapshot = self.f.repo.commit(self.f.access.scope, self.records)
        bindings = tuple(replace(b, snapshot=self.snapshot.snapshot_id) if b.dataset == "financial_income" else b
                         for b in self.f.request.bindings)
        base = self.f.request
        self.request = StudyRequest(base.security, base.as_of, base.mode, bindings, base.benchmark,
                                    hypotheses=("absolute_profit_change",), hypothesis_version="profit-change/v1")
        self.spec = StudySpec(version="single-research-v5")

    def runtime(self, **kwargs):
        return StudyRuntime(self.f.service, self.f.store, spec=self.spec, **kwargs)

    def datasets(self, request=None):
        request = request or self.request
        return {key: value for domain in ("market", "financial")
                for key, value in read_domain(self.f.service, request, self.f.access, domain).items()}

    def test_explicit_new_request_roundtrip_and_old_schema_unchanged(self):
        self.assertEqual(StudyRequest.from_dict(self.request.to_dict()), self.request)
        self.assertEqual(self.request.to_dict()["hypothesis_version"], "profit-change/v1")
        legacy = replace(self.request, hypotheses=("financial_deterioration",), hypothesis_version=None)
        self.assertNotIn("hypothesis_version", legacy.to_dict())
        self.assertEqual(StudyRequest.from_dict(legacy.to_dict()).to_dict(), legacy.to_dict())
        unversioned = self.request.to_dict()
        unversioned.pop("hypothesis_version")
        with self.assertRaises(ValidationError):
            StudyRequest.from_dict(unversioned)
        unknown = self.request.to_dict()
        unknown["hypothesis_version"] = "profit-change/v99"
        with self.assertRaises(ValidationError):
            StudyRequest.from_dict(unknown)

    def test_v5_runs_verified_bounded_model_and_preserves_descriptive_result(self):
        model = BundleFixtureModel()
        report = self.runtime(model=model).run(self.request, self.f.access)
        self.assertEqual(report["research_status"], "tests_completed")
        self.assertEqual(report["verification"]["status"], "verified")
        fact = next(f for f in report["facts"] if f["name"] == PROFIT_CLAIM_NAME)
        self.assertEqual((fact["value"], fact["unit"]), ("40", "CNY"))
        self.assertEqual(report["hypotheses"][0]["status"], "supported")
        self.assertEqual(report["model"]["status"], "verified")
        self.assertEqual(report["model"]["hypotheses"], ["absolute_profit_change"])
        self.assertIn(fact["id"], report["model"]["highlights"])
        self.assertEqual(report["synthesis"]["causal_conclusion"], "not_established")
        self.assertEqual(model.calls, 1)
        payload = json.loads(model.messages[1]["content"])
        self.assertIn("absolute_profit_change", payload["hypotheses"])
        self.assertFalse(payload["causal_claim"])

    def test_v1_through_v4_reject_opt_in_request_before_read_or_model(self):
        model = BundleFixtureModel()
        for version in ("single-research-v1", "single-research-v2", "single-research-v3", "single-research-v4"):
            with self.subTest(version=version):
                runtime = StudyRuntime(self.f.service, self.f.store, model=model, spec=StudySpec(version=version))
                with self.assertRaises(ValidationError):
                    runtime.run(self.request, self.f.access)
        self.assertEqual(model.calls, 0)

    def test_old_negative_positive_base_rule_stays_insufficient_alongside_new_test(self):
        request = replace(self.request, hypotheses=("financial_deterioration", "absolute_profit_change"))
        report = self.runtime().run(request, self.f.access)
        self.assertEqual([h["id"] for h in report["hypotheses"]], list(request.hypotheses))
        self.assertEqual([h["status"] for h in report["hypotheses"]], ["insufficient", "supported"])
        self.assertNotIn("net_income_parent_yoy", {f["name"] for f in report["facts"]})
        diagnostics = report["insufficiency_diagnostics"][0]["insufficiency_reasons"]
        self.assertTrue(any(d["code"] == "positive_base_precondition_failed" for d in diagnostics))
        self.assertEqual(report["research_status"], "evidence_incomplete")

    def test_v5_on_legacy_request_keeps_v3_numeric_hypotheses_and_model_messages(self):
        request = replace(self.request, hypotheses=("financial_deterioration",), hypothesis_version=None)
        datasets = self.datasets(request)
        old = StudyRuntime(self.f.service, self.f.store)._calculate(datasets, request)
        new = self.runtime()._calculate(datasets, request)
        diagnostics = new.pop("insufficiency_diagnostics")
        self.assertTrue(diagnostics)
        self.assertEqual(old, new)
        old_messages, old_context = study_messages(old, request, 12000, version="single-research-v3")
        new_messages, new_context = study_messages(new, request, 12000, version="single-research-v5")
        self.assertEqual(old_messages, new_messages)
        self.assertEqual(old_context, new_context)

    def test_v5_missing_prior_retains_structured_reason_and_exact_replay(self):
        request = replace(self.request, bindings=tuple(
            replace(b, start=date(2024, 12, 31)) if b.dataset == "financial_income" else b
            for b in self.request.bindings))
        runtime = self.runtime()
        report = runtime.run(request, self.f.access)
        self.assertEqual(report["hypotheses"][0]["status"], "insufficient")
        self.assertEqual(report["hypotheses"][0]["reason"], "prior_year_same_period_not_visible")
        self.assertEqual(report["insufficiency_diagnostics"][0]["insufficiency_reasons"][0]["code"],
                         "missing_report_period")
        self.assertEqual(runtime.run(request, self.f.access, resume=report["run_id"]), report)

    def test_complete_replay_uses_same_v5_request_and_never_calls_model_again(self):
        model = BundleFixtureModel()
        runtime = self.runtime(model=model)
        report = runtime.run(self.request, self.f.access)
        self.assertEqual(runtime.run(self.request, self.f.access, resume=report["run_id"]), report)
        self.assertEqual(model.calls, 1)
        with self.assertRaises(PermissionDenied):
            StudyRuntime(self.f.service, self.f.store, model=model,
                         spec=StudySpec(version="single-research-v4")).run(
                             replace(self.request, hypotheses=("financial_deterioration",), hypothesis_version=None),
                             self.f.access, resume=report["run_id"])

    def test_replay_rejects_numeric_or_hypothesis_tampering_even_valid_checkpoint_chain(self):
        for kind in ("numeric", "hypothesis"):
            with self.subTest(kind=kind):
                runtime = self.runtime()
                report = runtime.run(self.request, self.f.access)
                forged = self.f.store.read(self.f.access.scope, report["run_id"])
                if kind == "numeric":
                    fact = next(f for f in forged["report"]["facts"] if f["name"] == PROFIT_CLAIM_NAME)
                    fact["value"] = "41"
                    fact["id"] = digest({k: v for k, v in fact.items() if k != "id"})
                    forged["report"]["hypotheses"][0]["claim_ids"] = [fact["id"]]
                else:
                    forged["report"]["hypotheses"][0]["status"] = "unsupported"
                self.f.store.append(self.f.access.scope, report["run_id"], forged)
                with self.assertRaises(IntegrityError):
                    runtime.run(self.request, self.f.access, resume=report["run_id"])

    def test_replay_rejects_new_diagnostic_tampering(self):
        request = replace(self.request, bindings=tuple(
            replace(b, start=date(2024, 12, 31)) if b.dataset == "financial_income" else b
            for b in self.request.bindings))
        runtime = self.runtime()
        report = runtime.run(request, self.f.access)
        forged = self.f.store.read(self.f.access.scope, report["run_id"])
        forged["report"]["insufficiency_diagnostics"][0]["insufficiency_reasons"][0]["code"] = "made_up"
        self.f.store.append(self.f.access.scope, report["run_id"], forged)
        with self.assertRaises(IntegrityError):
            runtime.run(request, self.f.access, resume=report["run_id"])

    def test_replay_rechecks_source_grant_revocation(self):
        grants = [SourceGrant(self.f.service, self.f.access, b.snapshot,
                              self.request.data_request(b), b.provider) for b in self.request.bindings]
        service = ScopedReadService("synthetic-v5-recipient", lambda: tuple(grants))
        access = AccessContext("synthetic-v5-recipient", frozenset({"fixture"}))
        runtime = StudyRuntime(service, self.f.store, spec=self.spec)
        report = runtime.run(self.request, access)
        grants.clear()
        with self.assertRaises(PermissionDenied):
            runtime.run(self.request, access, resume=report["run_id"])

    def test_new_capture_does_not_backfill_cutoff_or_mutate_old_snapshot(self):
        runtime = self.runtime()
        old = runtime.run(self.request, self.f.access)
        current = self.records[-1]
        artifact = self.f.artifacts.put(self.f.access.scope,
                                       {"synthetic": True, "recapture": True, "profit": "-150"})
        captured = ts("2025-04-17T10:00:00")
        revised = replace(current, metrics=tuple(replace(m, value=Decimal("-150"), raw_value="-150")
                                                if m.name == "net_income_parent" else m for m in current.metrics),
                          available_at=captured, retrieved_at=captured, ingested_at=captured,
                          availability_basis="observed_at", published_at=None,
                          artifact_id=artifact, revision_id=artifact, revision_order=1)
        new_snapshot = self.f.repo.commit(self.f.access.scope, (*self.records, revised))
        self.assertNotEqual(new_snapshot.snapshot_id, self.snapshot.snapshot_id)
        new_bindings = tuple(replace(b, snapshot=new_snapshot.snapshot_id)
                             if b.dataset == "financial_income" else b for b in self.request.bindings)
        same_cutoff = runtime.run(replace(self.request, bindings=new_bindings), self.f.access)
        after_capture = runtime.run(replace(self.request, bindings=new_bindings,
                                            as_of=ts("2025-04-18T00:00:00")), self.f.access)
        amount = lambda report: next(f["value"] for f in report["facts"] if f["name"] == PROFIT_CLAIM_NAME)
        self.assertEqual((amount(old), amount(same_cutoff), amount(after_capture)), ("40", "40", "-50"))
        self.assertEqual(after_capture["hypotheses"][0]["status"], "unsupported")
        self.assertEqual(runtime.run(self.request, self.f.access, resume=old["run_id"]), old)


if __name__ == "__main__":
    unittest.main()
