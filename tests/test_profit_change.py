"""Synthetic mechanism fixtures; never financial ground truth or provider QA."""
import copy
from dataclasses import replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from research_fixtures import fixture
from stock_research.errors import IntegrityError
from stock_research.models import DataRecord, digest
from stock_research.research.calculation import calculate
from stock_research.research.profit_change import (
    PROFIT_CLAIM_NAME, PROFIT_FORMULA, PROFIT_HYPOTHESIS_ID,
    add_profit_change_claim, expected_profit_change_claims, profit_change_diagnostics,
    profit_change_hypothesis, verify_profit_change,
)
from stock_research.research.tools import read_domain


class ProfitChangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name), scope="synthetic-profit-change")

    def inputs(self, prior="-100", current="-60", *, unit="CNY", prior_period=date(2023, 12, 31)):
        records = []
        for period, value in ((prior_period, prior), (date(2024, 12, 31), current)):
            artifact = self.f.artifacts.put(self.f.access.scope,
                                           {"synthetic": True, "period": str(period), "profit": value})
            metrics = tuple(replace(m, value=None if value is None else Decimal(value),
                                    raw_value=value, unit=unit, raw_unit=unit)
                            if m.name == "net_income_parent" else m for m in self.f.financial.metrics)
            records.append(replace(self.f.financial, period=period, metrics=metrics,
                                   artifact_id=artifact, revision_id=artifact))
        snapshot = self.f.repo.commit(self.f.access.scope, records)
        base = replace(self.f.request, bindings=tuple(
            replace(b, snapshot=snapshot.snapshot_id) if b.dataset == "financial_income" else b
            for b in self.f.request.bindings))
        # This test double is only the future opt-in request surface, keeping the
        # legacy StudyRequest schema untouched while its v5 integration is separate.
        request = SimpleNamespace(**base.__dict__, hypotheses=(PROFIT_HYPOTHESIS_ID,),
                                  data_request=base.data_request)
        datasets = {key: value for domain in ("market", "financial")
                    for key, value in read_domain(self.f.service, base, self.f.access, domain).items()}
        return request, datasets

    def compute(self, request, datasets):
        computed = calculate(datasets)
        add_profit_change_claim(computed, datasets, request)
        computed["hypotheses"] = [profit_change_hypothesis(computed, datasets, request)]
        return computed

    def test_negative_base_loss_narrowing_is_signed_amount_not_percentage(self):
        request, datasets = self.inputs("-100", "-60")
        old = calculate(datasets)
        self.assertNotIn("net_income_parent_yoy", {f["name"] for f in old["facts"]})
        computed = self.compute(request, datasets)
        fact = next(f for f in computed["facts"] if f["name"] == PROFIT_CLAIM_NAME)
        self.assertEqual((fact["value"], fact["unit"], fact["formula"]), ("40", "CNY", PROFIT_FORMULA))
        self.assertEqual(computed["hypotheses"][0]["status"], "supported")
        self.assertFalse(computed["hypotheses"][0]["causal_claim"])
        self.assertEqual([f for f in computed["facts"] if f["name"] != PROFIT_CLAIM_NAME], old["facts"])
        self.assertEqual(computed["evidence"], old["evidence"])
        self.assertEqual(verify_profit_change(computed, datasets, request)["numeric_claims"], 1)

    def test_improvement_definition_handles_losses_zero_positive_and_unchanged(self):
        for prior, current, value, status, reason in (
            ("-100", "-160", "-60", "unsupported", "same_period_profit_amount_decreased"),
            ("0", "10", "10", "supported", "same_period_profit_amount_increased"),
            ("10", "20", "10", "supported", "same_period_profit_amount_increased"),
            ("-10", "20", "30", "supported", "same_period_profit_amount_increased"),
            ("20", "-10", "-30", "unsupported", "same_period_profit_amount_decreased"),
            ("-10", "-10", "0", "unsupported", "same_period_profit_amount_unchanged"),
        ):
            with self.subTest(prior=prior, current=current):
                request, datasets = self.inputs(prior, current)
                computed = self.compute(request, datasets)
                fact = next(f for f in computed["facts"] if f["name"] == PROFIT_CLAIM_NAME)
                h = computed["hypotheses"][0]
                self.assertEqual((fact["value"], h["status"], h["reason"]), (value, status, reason))
                self.assertEqual(h["counterevidence_claim_ids"], [fact["id"]] if status == "unsupported" else [])
                verify_profit_change(computed, datasets, request)

    def test_missing_prior_and_missing_metric_are_insufficient_not_zero(self):
        for prior, current, period, reason, diagnostic in (
            ("-100", "-60", date(2023, 9, 30), "prior_year_same_period_not_visible", "missing_report_period"),
            (None, "-60", date(2023, 12, 31), "net_income_parent_missing", "missing_metric"),
            ("-100", None, date(2023, 12, 31), "net_income_parent_missing", "missing_metric"),
        ):
            with self.subTest(reason=reason, prior=prior):
                request, datasets = self.inputs(prior, current, prior_period=period)
                computed = self.compute(request, datasets)
                self.assertNotIn(PROFIT_CLAIM_NAME, {f["name"] for f in computed["facts"]})
                self.assertEqual(computed["hypotheses"][0]["status"], "insufficient")
                self.assertEqual(computed["hypotheses"][0]["reason"], reason)
                self.assertEqual(profit_change_diagnostics(computed, datasets, request)[0]
                                 ["insufficiency_reasons"][0]["code"], diagnostic)
                verify_profit_change(computed, datasets, request)

    def test_no_visible_income_is_explicit_missing_dataset(self):
        request, datasets = self.inputs()
        datasets["financial_income"]["records"] = []
        computed = self.compute(request, datasets)
        self.assertEqual(computed["hypotheses"][0]["reason"], "no_visible_financial_period")
        self.assertEqual(profit_change_diagnostics(computed, datasets, request)[0]
                         ["insufficiency_reasons"][0]["code"], "missing_dataset")
        verify_profit_change(computed, datasets, request)

    def test_non_cny_input_is_not_a_signed_cny_claim(self):
        request, datasets = self.inputs(unit="USD")
        computed = self.compute(request, datasets)
        self.assertEqual(computed["hypotheses"][0]["reason"], "financial_unit_or_basis_mismatch")
        self.assertEqual(computed["hypotheses"][0]["status"], "insufficient")
        self.assertEqual(profit_change_diagnostics(computed, datasets, request)[0]
                         ["insufficiency_reasons"][0]["failure_category"], "benchmark_or_request_contract_defect")
        verify_profit_change(computed, datasets, request)

    def test_independent_fraction_oracle_does_not_call_production_arithmetic_or_hypothesis(self):
        request, datasets = self.inputs("-123456789.12345", "-123456789.02345")
        computed = self.compute(request, datasets)
        with patch("stock_research.research.profit_change._production_inputs", side_effect=AssertionError), \
                patch("stock_research.research.profit_change.add_profit_change_claim", side_effect=AssertionError), \
                patch("stock_research.research.profit_change.profit_change_hypothesis", side_effect=AssertionError):
            expected, reason = expected_profit_change_claims(datasets, request)
            self.assertIsNone(reason)
            self.assertEqual(expected[PROFIT_CLAIM_NAME][0], Fraction(1, 10))
            verify_profit_change(computed, datasets, request)

    def test_large_signed_amount_subtraction_is_exact(self):
        request, datasets = self.inputs("-12345678901234567890123456789012345.00001",
                                       "-12345678901234567890123456789012345.00002")
        computed = self.compute(request, datasets)
        fact = next(f for f in computed["facts"] if f["name"] == PROFIT_CLAIM_NAME)
        self.assertEqual(Fraction(fact["value"]), -Fraction(1, 100000))
        verify_profit_change(computed, datasets, request)

    def test_verifier_rejects_numeric_unit_formula_window_hash_and_missing_claim(self):
        request, datasets = self.inputs()
        computed = self.compute(request, datasets)
        for field, value in (("value", "41"), ("unit", "ratio"), ("formula", "made up"),
                             ("window", ["2023-01-01", "2024-12-31"]), ("id", "0" * 64)):
            with self.subTest(field=field):
                forged = copy.deepcopy(computed)
                fact = next(f for f in forged["facts"] if f["name"] == PROFIT_CLAIM_NAME)
                fact[field] = value
                if field != "id":
                    fact["id"] = digest({k: v for k, v in fact.items() if k != "id"})
                    forged["hypotheses"][0]["claim_ids"] = [fact["id"]]
                with self.assertRaises(IntegrityError):
                    verify_profit_change(forged, datasets, request)
        forged = copy.deepcopy(computed)
        forged["facts"] = [f for f in forged["facts"] if f["name"] != PROFIT_CLAIM_NAME]
        with self.assertRaises(IntegrityError):
            verify_profit_change(forged, datasets, request)

    def test_verifier_rejects_wrong_status_missing_counterfacts_and_causal_overclaim(self):
        request, datasets = self.inputs("-100", "-160")
        computed = self.compute(request, datasets)
        for field, value in (("status", "supported"), ("counterevidence_claim_ids", []),
                             ("causal_claim", True), ("reason", "stock_price_caused_profit_loss")):
            with self.subTest(field=field):
                forged = copy.deepcopy(computed)
                forged["hypotheses"][0][field] = value
                with self.assertRaises(IntegrityError):
                    verify_profit_change(forged, datasets, request)

    def test_verifier_rejects_changed_evidence_raw_value_version_and_snapshot(self):
        request, datasets = self.inputs()
        computed = self.compute(request, datasets)
        key = next(f for f in computed["facts"] if f["name"] == PROFIT_CLAIM_NAME)["inputs"][0]
        for field, value in (("raw_value", "-999"), ("provider_version", "unexpected"),
                             ("snapshot", "0" * 64), ("record_id", "0" * 64)):
            with self.subTest(field=field):
                forged = copy.deepcopy(computed)
                forged["evidence"][key][field] = value
                with self.assertRaises(IntegrityError):
                    verify_profit_change(forged, datasets, request)

    def test_extension_checks_cutoff_security_and_snapshot_read_boundary(self):
        request, datasets = self.inputs()
        computed = self.compute(request, datasets)
        future = copy.deepcopy(datasets)
        future["financial_income"]["records"][0]["available_at"] = "2025-04-17T10:00:00+00:00"
        wrong_security = copy.deepcopy(datasets)
        wrong_security["financial_income"]["records"][0]["security_id"] = "equity:000001.SZSE"
        wrong_snapshot = copy.deepcopy(datasets)
        wrong_snapshot["financial_income"]["snapshot"] = "0" * 64
        for source in (future, wrong_security, wrong_snapshot):
            with self.assertRaises(IntegrityError):
                verify_profit_change(computed, source, request)

    def test_unrequested_extension_is_noop_and_smuggled_claim_is_rejected(self):
        request, datasets = self.inputs()
        request.hypotheses = ("financial_deterioration",)
        computed = calculate(datasets)
        before = copy.deepcopy(computed)
        self.assertIs(add_profit_change_claim(computed, datasets, request), computed)
        self.assertEqual(computed, before)
        self.assertIsNone(profit_change_hypothesis(computed, datasets, request))
        computed["hypotheses"] = []
        self.assertEqual(verify_profit_change(computed, datasets, request)["numeric_claims"], 0)
        computed["facts"].append({"name": PROFIT_CLAIM_NAME})
        with self.assertRaises(IntegrityError):
            verify_profit_change(computed, datasets, request)

    def test_duplicate_extension_claim_is_rejected(self):
        request, datasets = self.inputs()
        computed = self.compute(request, datasets)
        with self.assertRaises(IntegrityError):
            add_profit_change_claim(computed, datasets, request)


if __name__ == "__main__":
    unittest.main()
