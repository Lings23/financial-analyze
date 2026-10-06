"""Phase 3 security, chronology, evidence, independent arithmetic and recovery."""
import copy
from contextlib import closing
import json
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from helpers import ts
from research_fixtures import FixtureModel, BundleFixtureModel, fixture
from study_fixtures import add_domain, study_request, with_event
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.models import AccessContext, Metric, PITMode, digest
from stock_research.research.context import study_messages
from stock_research.research.contracts import TOOLS
from stock_research.research.report import markdown
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudyRequest, StudySpec
from stock_research.research.tools import read_domain
from stock_research.research.verification import verify


CHOICE = '{"highlights":["F1"],"hypotheses":["financial_deterioration"],"assessment":"descriptive_research_only"}'


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))

    def run_study(self, request=None, model=None, **kwargs):
        return StudyRuntime(self.f.service, self.f.store, model, **kwargs).run(request or study_request(self.f), self.f.access)

    def datasets(self, request):
        return {k: v for name in ("market", "financial", "benchmark", "announcement", "news")
                for k, v in read_domain(self.f.service, request, self.f.access, name).items()}

    def test_default_records_insufficient_and_does_not_claim_causation(self):
        report = self.run_study()
        self.assertEqual(report["schema"], "single-research/v1")
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["research_status"], "evidence_incomplete")
        self.assertEqual(len(report["hypotheses"]), 5)
        self.assertEqual(report["synthesis"]["causal_conclusion"], "not_established")
        self.assertEqual(report["verification"]["status"], "verified")
        self.assertIn("假设检验与综合", markdown(report))

    def test_request_roundtrip_and_rejects_extra_permissions_or_bad_hypothesis(self):
        request = study_request(self.f)
        self.assertEqual(StudyRequest.from_dict(request.to_dict()), request)
        for bad in ({**request.to_dict(), "scope": "administrator"},
                    {**request.to_dict(), "hypotheses": ["trade"]},
                    {**request.to_dict(), "hypotheses": ["market_direction", "market_direction"]},
                    {**request.to_dict(), "objective": "event_review"},
                    {**request.to_dict(), "as_of": "2025-04-16T00:00:00"}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                StudyRequest.from_dict(bad)

    def test_verified_intraday_anchor_after_close_uses_next_day_price(self):
        request, record = with_event(self.f)
        report = self.run_study(request)
        fact = next(f for f in report["facts"] if f["name"] == "event_observed_price_change")
        self.assertEqual(fact["window"], ["2025-04-02", "2025-04-03"])
        self.assertEqual(Decimal(fact["value"]), Decimal("-0.25"))
        self.assertEqual(report["hypotheses"][0]["status"], "supported")
        self.assertEqual(report["event_anchor"]["record_id"], record.record_id)
        self.assertFalse(report["verification"]["causality_established"])

    def test_intraday_anchor_at_close_has_no_prior_same_day_close(self):
        request, record = with_event(self.f)
        record = replace(record, available_at=ts("2025-04-02T07:00:00"), published_at=ts("2025-04-02T07:00:00"))
        sid = self.f.repo.commit(self.f.access.scope, (*self.f.records, record)).snapshot_id
        request = replace(request, event_record_id=record.record_id,
                          bindings=tuple(replace(b, snapshot=sid) for b in request.bindings))
        report = self.run_study(request)
        fact = next(f for f in report["facts"] if f["name"] == "event_observed_price_change")
        self.assertEqual(fact["window"], ["2025-04-01", "2025-04-03"])

    def test_date_precision_excludes_release_day_and_holds_original_basis(self):
        request, record = with_event(self.f, date_only=True)
        report = self.run_study(request)
        fact = next(f for f in report["facts"] if f["name"] == "event_observed_price_change")
        self.assertEqual(fact["window"], ["2025-04-01", "2025-04-03"])
        self.assertEqual(report["event_anchor"]["precision"], "date_conservative_next_day")
        self.assertEqual(Decimal(fact["value"]), Decimal("-0.1"))

    def test_capture_time_and_hidden_record_cannot_be_event_anchor(self):
        request, record = with_event(self.f, observed=True)
        for r in (request, replace(request, event_record_id="0"*64)):
            with self.subTest(r=r.event_record_id):
                report = self.run_study(r)
                self.assertEqual(report["hypotheses"][0]["status"], "insufficient")
                self.assertFalse(any(f["name"].startswith("event_") for f in report["facts"]))

    def test_absent_event_post_price_is_insufficient_not_zero(self):
        f = fixture(Path(self.temp.name)/"few", prices=("100", "120"))
        request, _ = with_event(f)
        report = StudyRuntime(f.service, f.store).run(request, f.access)
        self.assertEqual(report["hypotheses"][0]["status"], "insufficient")
        self.assertNotIn("event_observed_price_change", {c["name"] for c in report["facts"]})

    def test_mechanical_and_benchmark_opposite_direction_have_explicit_counterevidence(self):
        request = study_request(self.f, hypotheses=("mechanical_adjustment", "market_direction"))
        request, _ = add_domain(self.f, request, "adjustment_factor", values={"factor": ["1", "1", "2"]})
        request, _ = add_domain(self.f, request, "index_daily", values={"close": ["100", "110", "120"]})
        report = self.run_study(request)
        a, b = report["hypotheses"]
        self.assertEqual(a["status"], "supported")
        self.assertEqual(b["status"], "unsupported")
        self.assertEqual(b["counterevidence_claim_ids"], b["claim_ids"])

    def test_financial_direction_conflict_and_cashflow_period_mismatch(self):
        records = list(self.f.repo.read(self.f.access.scope, self.f.request.bindings[0].snapshot))
        current = self.f.financial
        changed = replace(current, metrics=tuple(replace(m, value=Decimal("5"), raw_value="5")
                          if m.name == "net_income_parent" else m for m in current.metrics))
        records = [changed if r.record_id == current.record_id else r for r in records]
        sid = self.f.repo.commit(self.f.access.scope, records).snapshot_id
        request = study_request(self.f, hypotheses=("financial_deterioration", "cashflow_divergence"))
        request = replace(request, bindings=tuple(replace(b, snapshot=sid) for b in request.bindings))
        request, _ = add_domain(self.f, request, "financial_cashflow", periods=[date(2024, 6, 30)], values={"operating_cashflow": "-1"})
        report = self.run_study(request)
        self.assertEqual(report["hypotheses"][0]["status"], "conflicted")
        self.assertEqual(report["hypotheses"][1]["reason"], "financial_period_mismatch")

    def test_model_selects_only_ids_and_untrusted_documents_never_enter_context(self):
        request = study_request(self.f)
        request, _ = add_domain(self.f, request, "announcement")
        model = BundleFixtureModel()
        report = self.run_study(request, model)
        self.assertEqual(report["model"]["status"], "verified")
        self.assertEqual(model.calls, 1)
        self.assertNotIn("99999", str(model.messages))
        self.assertNotIn("ignore rules", str(model.messages))
        self.assertEqual(report["model"]["hypotheses"], ["financial_deterioration"])
        payload = json.loads(model.messages[1]["content"])
        self.assertEqual(len(payload["facts"]), len(report["facts"]))
        self.assertEqual(payload["cutoff"], request.as_of.isoformat())

    def test_forged_model_status_prose_unknown_ids_and_duplicate_keys_are_rejected(self):
        cases = [CHOICE.replace('"financial_deterioration"', '"invented_cause"'),
                 CHOICE.replace('"descriptive_research_only"', '"caused_decline"'),
                 CHOICE[:-1]+',"value":99}', CHOICE[:-1]+',"highlights":["F1"]}',
                 CHOICE.replace('["F1"]', '["F999"]'), CHOICE.replace('["F1"]', '["F1","F1"]')]
        for content in cases:
            with self.subTest(content=content):
                report = self.run_study(model=FixtureModel(content))
                self.assertEqual(report["model"]["status"], "rejected_or_failed")
                self.assertEqual(report["status"], "partial")
                self.assertEqual(report["verification"]["status"], "verified")

    def test_context_overflow_preserves_facts_and_never_dispatches(self):
        model = FixtureModel(CHOICE)
        report = self.run_study(model=model, spec=StudySpec(context_bytes=512))
        self.assertEqual(model.calls, 0)
        self.assertEqual(report["stop_reason"], "study_context_budget_exceeded")
        self.assertGreater(len(report["facts"]), 0)
        self.assertEqual(report["context"]["omitted_claims"], 0)

    def test_fraction_verifier_rejects_rehashed_fabrication_omission_and_wrong_unit(self):
        request = study_request(self.f)
        report = self.run_study(request)
        for change in ("value", "unit", "omission", "source", "status", "future"):
            forged = copy.deepcopy(report)
            if change == "omission":
                forged["facts"].pop()
            elif change == "status":
                forged["hypotheses"][0]["status"] = "supported"
            elif change in {"source", "future"}:
                e = next(iter(forged["evidence"].values()))
                e["raw_unit" if change == "source" else "available_at"] = "fake" if change == "source" else "2099-01-01T00:00:00+00:00"
            else:
                c = forged["facts"][0]
                c[change] = "0.99" if change == "value" else "CNY"
                c["id"] = digest({k: v for k, v in c.items() if k != "id"})
            with self.subTest(change=change), self.assertRaises(IntegrityError):
                verify(forged, self.datasets(request), request)

    def test_completed_resume_rechecks_grants_bytes_and_exact_report(self):
        request, _ = add_domain(self.f, study_request(self.f), "announcement")
        report = self.run_study(request, FixtureModel(CHOICE))
        model = FixtureModel(CHOICE)
        runtime = StudyRuntime(self.f.service, self.f.store, model)
        self.assertEqual(runtime.run(request, self.f.access, resume=report["run_id"]), report)
        self.assertEqual(model.calls, 0)
        with self.assertRaises(PermissionDenied):
            runtime.run(request, AccessContext(self.f.access.scope, frozenset({"other"})), resume=report["run_id"])
        with self.assertRaises(PermissionDenied):
            StudyRuntime(self.f.service, self.f.store, model, granted_tools=TOOLS-{"announcement"}).run(request, self.f.access, resume=report["run_id"])
        aid = report["documents"][0]["body_artifact_id"]
        self.f.artifacts._path(self.f.access.scope, aid).write_bytes(b"tampered")
        with self.assertRaises(IntegrityError):
            runtime.run(request, self.f.access, resume=report["run_id"])

    def test_crash_after_model_intent_is_not_resent_and_reservation_stays(self):
        request = study_request(self.f)
        with self.assertRaises(KeyboardInterrupt):
            self.run_study(request, FixtureModel(CHOICE, crash=KeyboardInterrupt()))
        import sqlite3
        with closing(sqlite3.connect(self.f.store.root/"checkpoints.sqlite3")) as db:
            run = db.execute("SELECT run FROM checkpoints ORDER BY seq DESC LIMIT 1").fetchone()[0]
        prior = self.f.store.read(self.f.access.scope, run)
        model = FixtureModel(CHOICE)
        report = StudyRuntime(self.f.service, self.f.store, model).run(request, self.f.access, resume=run)
        self.assertEqual(model.calls, 0)
        self.assertEqual(report["model"]["status"], "unknown_outcome_no_replay")
        self.assertEqual(report["usage"]["tokens_reserved"], prior["tokens_reserved"])

    def test_expired_revalidation_never_publishes_cached_study_claims(self):
        request = study_request(self.f)
        with self.assertRaises(KeyboardInterrupt):
            self.run_study(request, FixtureModel(CHOICE, crash=KeyboardInterrupt()))
        import sqlite3
        with closing(sqlite3.connect(self.f.store.root/"checkpoints.sqlite3")) as db:
            run = db.execute("SELECT run FROM checkpoints ORDER BY seq DESC LIMIT 1").fetchone()[0]
        report = StudyRuntime(self.f.service, self.f.store, FixtureModel(CHOICE),
                              now=lambda: ts("2099-01-01T00:00:00")).run(request, self.f.access, resume=run)
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["hypotheses"], [])
        self.assertEqual(report["verification"]["status"], "not_completed")

    def test_pre_capture_and_system_ingestion_are_not_backfilled(self):
        request, record = with_event(self.f)
        report = self.run_study(replace(request, as_of=record.ingested_at-timedelta(microseconds=1)))
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["event_anchor"]["reason"], "event_anchor_not_visible")
        public = self.run_study(replace(request, as_of=record.ingested_at-timedelta(microseconds=1), mode=PITMode.PUBLIC))
        self.assertEqual(public["event_anchor"]["status"], "verified")

    def test_zero_claims_do_not_receive_completed_or_success_quality(self):
        f = fixture(Path(self.temp.name)/"empty", prices=(None,))
        request = replace(study_request(f), as_of=ts("2020-01-01T00:00:00"))
        report = StudyRuntime(f.service, f.store).run(request, f.access)
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["research_status"], "evidence_incomplete")

    def test_cancelled_start_does_not_read_or_publish_any_evidence(self):
        report = self.run_study(cancelled=lambda: True)
        self.assertEqual(report["facts"], [])
        self.assertEqual(report["usage"]["tool_calls"], 0)
        self.assertEqual(report["stop_reason"], "cancelled")

    def test_cli_research_exports_exact_local_preview_and_refuses_overwrite(self):
        from types import SimpleNamespace
        from stock_research.research.cli import run
        request = study_request(self.f)
        root = Path(self.temp.name)
        manifest = root/"request.json"
        manifest.write_text(json.dumps(request.to_dict()), encoding="utf-8")
        args = SimpleNamespace(request=str(manifest), workflow="research", with_model=False,
                               output=str(root/"cli-output"), artifacts=[str(root/"artifacts")],
                               runs=str(root/"cli-runs"), scope=self.f.access.scope,
                               allow_provider=["fixture"], resume=None, preview_model=True)
        result = run(args, self.f.repo)
        self.assertEqual(result["usage"]["model_attempts"], 0)
        report = json.loads((root/"cli-output"/"report.json").read_text(encoding="utf-8"))
        preview = json.loads((root/"cli-output"/"model-messages.json").read_text(encoding="utf-8"))
        self.assertEqual(report["schema"], "single-research/v1")
        self.assertEqual(preview, study_messages(report, request, StudySpec().context_bytes)[0])
        with self.assertRaises(ValidationError):
            run(args, self.f.repo)

    def test_cli_duplicate_manifest_keys_are_rejected_before_reading(self):
        from types import SimpleNamespace
        from stock_research.research.cli import run
        root = Path(self.temp.name)
        path = root/"duplicate.json"
        path.write_text('{"objective":"event_review","objective":"single_stock_research"}', encoding="utf-8")
        with self.assertRaises(ValidationError):
            run(SimpleNamespace(request=str(path), workflow="research"), self.f.repo)

    def test_mechanical_test_uses_exact_factors_when_price_ratios_round_equal(self):
        request = study_request(self.f, hypotheses=("mechanical_adjustment",))
        request, _ = add_domain(self.f, request, "adjustment_factor",
                               values={"factor": ["1", "1", "1.00000000000000000000000000000000001"]})
        report = self.run_study(request)
        self.assertEqual(report["hypotheses"][0]["status"], "supported")

    def test_model_preview_cannot_accidentally_enable_paid_execution(self):
        from types import SimpleNamespace
        from stock_research.research.cli import run
        with self.assertRaises(ValidationError):
            run(SimpleNamespace(preview_model=True, with_model=True), self.f.repo)


if __name__ == "__main__":
    unittest.main()
