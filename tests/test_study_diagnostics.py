"""Synthetic diagnostic mechanisms; these are not financial accuracy fixtures."""
import copy
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from helpers import ts
from research_fixtures import fixture
from study_fixtures import add_domain, study_request, with_event
from stock_research.models import PITMode, Security
from stock_research.research.hypotheses import diagnose_insufficiency
from stock_research.research.report import markdown
from stock_research.research.study import StudyRuntime
from stock_research.research.tools import read_domain


class StudyDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))

    def datasets(self, request):
        return {key: value for domain in ("market", "financial", "benchmark", "announcement", "news")
                for key, value in read_domain(self.f.service, request, self.f.access, domain).items()}

    def diagnose(self, request):
        datasets = self.datasets(request)
        computed = StudyRuntime(self.f.service, self.f.store)._calculate(datasets, request)
        untouched = copy.deepcopy(computed)
        reasons = diagnose_insufficiency(computed, datasets, request)
        self.assertEqual(computed, untouched)
        return computed, reasons

    def reason_codes(self, diagnostics):
        return {reason["code"] for item in diagnostics for reason in item["insufficiency_reasons"]}

    def income_request(self, *, prior_profit=None, drop_prior=False):
        request = study_request(self.f, hypotheses=("financial_deterioration",))
        records = []
        for record in self.f.repo.read(self.f.access.scope, request.bindings[0].snapshot):
            if record.dataset.value == "financial_income" and record.period == date(2023, 12, 31):
                if drop_prior:
                    continue
                record = replace(record, metrics=tuple(
                    replace(m, value=None if prior_profit is None else Decimal(prior_profit),
                            raw_value=prior_profit) if m.name == "net_income_parent" else m
                    for m in record.metrics))
            records.append(record)
        snapshot = self.f.repo.commit(self.f.access.scope, records)
        return replace(request, bindings=tuple(replace(b, snapshot=snapshot.snapshot_id) for b in request.bindings))

    def test_nonpositive_base_is_distinct_from_missing_period_and_null_field(self):
        for value in ("0", "-2"):
            with self.subTest(value=value):
                computed, diagnostic = self.diagnose(self.income_request(prior_profit=value))
                self.assertEqual(computed["hypotheses"][0]["status"], "insufficient")
                self.assertEqual(self.reason_codes(diagnostic), {"positive_base_precondition_failed"})
                reason = diagnostic[0]["insufficiency_reasons"][0]
                self.assertEqual(reason["failure_category"], "intrinsic_precondition_or_temporal_impossibility")
                self.assertTrue(reason["record_refs"])
                self.assertTrue(reason["evidence_refs"])
        _, missing_period = self.diagnose(self.income_request(drop_prior=True))
        self.assertEqual(self.reason_codes(missing_period), {"missing_report_period"})
        _, null_field = self.diagnose(self.income_request(prior_profit=None))
        self.assertEqual(self.reason_codes(null_field), {"missing_metric"})

    def test_missing_binding_and_empty_visible_result_have_different_attribution(self):
        request = study_request(self.f, hypotheses=("mechanical_adjustment",))
        _, no_binding = self.diagnose(request)
        reason = no_binding[0]["insufficiency_reasons"][0]
        self.assertEqual(reason["code"], "missing_dataset")
        self.assertEqual(reason["failure_category"], "benchmark_or_request_contract_defect")
        request, _ = add_domain(self.f, request, "adjustment_factor")
        datasets = self.datasets(request)
        datasets["adjustment_factor"]["records"] = []
        computed = StudyRuntime(self.f.service, self.f.store)._calculate(datasets, request)
        empty = diagnose_insufficiency(computed, datasets, request)
        self.assertEqual(empty[0]["insufficiency_reasons"][0]["failure_category"], "data_or_evidence_insufficiency")
        self.assertNotIn("market_source_incompatible", self.reason_codes(empty))

    def test_exact_alignment_does_not_interpolate_or_change_hypothesis_status(self):
        request = study_request(self.f, hypotheses=("market_direction",))
        request, _ = add_domain(self.f, request, "index_daily", periods=[date(2025, 4, 1), date(2025, 4, 2)],
                                values={"close": ["100", "110"]})
        computed, diagnostic = self.diagnose(request)
        self.assertEqual(self.reason_codes(diagnostic), {"exact_date_alignment_failed"})
        self.assertEqual(computed["hypotheses"][0]["status"], "insufficient")
        self.assertNotIn("benchmark_price_change", {f["name"] for f in computed["facts"]})

    def test_zero_change_is_a_precondition_not_missing_data(self):
        request = study_request(self.f, hypotheses=("market_direction",))
        request, _ = add_domain(self.f, request, "index_daily", values={"close": ["100", "100", "100"]})
        computed, diagnostic = self.diagnose(request)
        self.assertEqual(computed["hypotheses"][0]["reason"], "zero_change_has_no_direction")
        self.assertEqual(self.reason_codes(diagnostic), {"zero_change_has_no_direction"})

    def test_event_cutoff_before_earliest_post_close_is_temporally_impossible(self):
        request, _ = with_event(self.f, date_only=True)
        request = replace(request, as_of=ts("2025-04-03T04:00:00"), mode=PITMode.PUBLIC)
        computed, diagnostic = self.diagnose(request)
        self.assertEqual(computed["event_anchor"]["status"], "verified")
        self.assertEqual(computed["hypotheses"][0]["status"], "insufficient")
        self.assertIn("temporal_condition_impossible", self.reason_codes(diagnostic))
        self.assertNotIn("event_observed_price_change", {f["name"] for f in computed["facts"]})

    def test_feasible_event_with_missing_post_prices_is_data_insufficiency(self):
        f = fixture(Path(self.temp.name) / "few", prices=("100", "120"))
        request, _ = with_event(f)
        datasets = {key: value for domain in ("market", "financial")
                    for key, value in read_domain(f.service, request, f.access, domain).items()}
        computed = StudyRuntime(f.service, f.store)._calculate(datasets, request)
        diagnostic = diagnose_insufficiency(computed, datasets, request)
        self.assertEqual(self.reason_codes(diagnostic), {"no_valid_market_window"})
        self.assertEqual(diagnostic[0]["insufficiency_reasons"][0]["failure_category"],
                         "data_or_evidence_insufficiency")

    def test_event_missing_id_and_wrong_security_are_not_conveniently_replaced(self):
        request = study_request(self.f, hypotheses=("event_chronology",))
        _, missing = self.diagnose(request)
        self.assertEqual(self.reason_codes(missing), {"missing_event"})
        request, record = with_event(self.f)
        other = Security("600001", "SSE")
        wrong = replace(record, security_id=other.security_id, canonical_symbol=other.canonical_symbol)
        request = replace(request, event_record_id=wrong.record_id)
        datasets = self.datasets(request)
        datasets["financial_income"]["records"].append(wrong.to_dict())
        minimal = {"hypotheses": [{"id": "event_chronology", "status": "insufficient"}],
                   "facts": [], "evidence": {}, "event_anchor": {"status": "verified"}}
        invalid = diagnose_insufficiency(minimal, datasets, request)
        self.assertIn("invalid_event_binding", self.reason_codes(invalid))
        self.assertNotIn("temporal_condition_impossible", self.reason_codes(invalid))

    def test_explicit_incompatible_market_result_is_not_inferred_from_empty_query(self):
        request = study_request(self.f, hypotheses=("event_chronology",))
        datasets = self.datasets(request)
        minimal = {"hypotheses": [{"id": "event_chronology", "status": "insufficient"}],
                   "facts": [], "evidence": {}, "event_anchor": {"status": "insufficient"}}
        datasets["market_daily"]["records"] = datasets["financial_income"]["records"]
        self.assertIn("market_source_incompatible", self.reason_codes(diagnose_insufficiency(minimal, datasets, request)))
        datasets["market_daily"]["records"] = []
        self.assertNotIn("market_source_incompatible", self.reason_codes(diagnose_insufficiency(minimal, datasets, request)))

    def test_future_negative_base_cannot_supply_diagnostic_evidence(self):
        request = self.income_request(prior_profit="-2")
        datasets = self.datasets(request)
        request = replace(request, as_of=ts("2020-01-01T00:00:00"))
        minimal = {"hypotheses": [{"id": "financial_deterioration", "status": "insufficient"}],
                   "facts": [], "evidence": {}}
        diagnostic = diagnose_insufficiency(minimal, datasets, request)
        self.assertNotIn("positive_base_precondition_failed", self.reason_codes(diagnostic))
        self.assertTrue(all(not reason["record_refs"] for item in diagnostic for reason in item["insufficiency_reasons"]))

    def test_legacy_markdown_unchanged_and_new_report_exposes_exact_diagnostics(self):
        request = self.income_request(prior_profit="-2")
        report = StudyRuntime(self.f.service, self.f.store).run(request, self.f.access)
        legacy_markdown = markdown(report)
        self.assertNotIn("insufficiency_diagnostics", report)
        report["insufficiency_diagnostics"] = []
        self.assertEqual(markdown(report), legacy_markdown)
        report["insufficiency_diagnostics"] = diagnose_insufficiency(report, self.datasets(request), request)
        rendered = markdown(report)
        self.assertIn("positive_base_precondition_failed", rendered)
        self.assertIn("原正基数同比规则", rendered)
        self.assertIn("intrinsic_precondition_or_temporal_impossibility", rendered)
        self.assertEqual(report["hypotheses"][0]["status"], "insufficient")


if __name__ == "__main__":
    unittest.main()
