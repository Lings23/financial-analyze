"""Synthetic mechanism and pinned pre-extraction compatibility evidence.

Fixtures are not financial ground truth or live provider validation. The four
full-output hashes were frozen from the unmodified HEAD producer whose source
SHA256 is 0206feeb1d9f67dad934796740ec0d0ae2ced9c7059d5d1ff27fa06a548f356f.
They cover every old field/ID/formula/order/Evidence/gap, not just numeric values.
"""
import copy
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from research_fixtures import fixture
from study_fixtures import add_domain, study_request, with_event
from stock_research.errors import IntegrityError, ValidationError
from stock_research.models import digest
from stock_research.research.calculation import calculate
from stock_research.research.domain_operators import (
    calculate_domain, compose_domains, merge_domain_calculations, review_domain,
    test_remaining_hypotheses, ValidatedDomainResult, _attest_validated_domain,
)
from stock_research.research.domain_analysis_contracts import ownership
from stock_research.research.hypotheses import test_hypotheses
from stock_research.research.study import calculate_study_claims
from stock_research.research.tools import read_domain
from stock_research.research.verification import verify, verify_domain


class DomainOperatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name), scope="synthetic-domain-operators")

    def datasets(self, request, f=None):
        f = f or self.f
        return {key: value for domain in ("market", "financial", "benchmark", "announcement", "news")
                for key, value in read_domain(f.service, request, f.access, domain).items()}

    def rich_request(self):
        request = study_request(self.f)
        for dataset, values in (
                ("adjustment_factor", {"factor": ["1", "1", "2"]}),
                ("index_daily", {"close": ["100", "110", "120"]}),
                ("financial_cashflow", {"operating_cashflow": "-1"}),
                ("financial_balance", {})):
            request, _ = add_domain(self.f, request, dataset, values=values)
        return request

    def reviewed(self, datasets, request):
        return {domain: review_domain(calculate_domain(datasets, request, domain), datasets, request, domain)
                for domain in ("financial", "market")}

    def attest(self, datasets, request, domain, computed):
        # The adapter fixture models trusted Runtime issuance after receipt checks;
        # no synthetic receipt is claimed as a live/checkpoint acceptance proof.
        operators = (["financial_snapshot", "income_yoy"] if domain == "financial" else
                     ["market_price_window", "factor_adjusted_window"])
        if domain == "financial" and "absolute_profit_change" in request.hypotheses:
            operators.append("profit_amount_change")
        checks = ["read:" + domain, "calculation", "domain_review", *["operator:" + operator for operator in operators],
                  *["hypothesis:" + hypothesis["id"] for hypothesis in computed["hypotheses"]]]
        proof = {"root_request_ref": digest(request.to_dict()), "domain_request_ref": digest(["synthetic-domain", domain]),
                 "task_ref": digest(["synthetic-task", domain]), "spec_ref": digest(["synthetic-spec", domain]),
                 "checkpoint_ref": {"synthetic": True, "run_id": domain}, "review_receipt_ref": digest(["synthetic-review", domain]),
                 "ownership_ref": digest(ownership(request)), "required_operators": operators,
                 "check_ids": checks, "result_ref": digest(computed)}
        return _attest_validated_domain(computed, datasets, request, domain, proof)

    def test_legacy_full_wrapper_pinned_all_fields_and_ids(self):
        cases = (
            ("base", ("100", "120", "90"), "938997de0a3288ff4ca435bc55e4543754502cde44528527e7fc4e17a1a88874"),
            ("invalid", ("100", None, "90"), "d4218f7333577864b7708f3b389a81f2821a51095329a2e7a99a3174dbffaca1"),
            ("single", ("100",), "b51598f05b956c3c824a11bfe57b1d188a992bd3e4642487033477ebbd0722e0"),
            ("rich", ("100", "120", "90"), "5326bd1ff7d8c1ea0ac81f2bf92d07dfa8b926738356daf8e8e7fa8c2ed79e9a"),
        )
        for name, prices, expected in cases:
            with self.subTest(case=name):
                self.f = fixture(Path(self.temp.name) / name, prices=prices, scope="synthetic-domain-operators")
                request = self.rich_request() if name == "rich" else study_request(self.f)
                self.assertEqual(digest(calculate(self.datasets(request))), expected)

    def test_financial_has_no_fabricated_market_gap_or_evidence(self):
        request = self.rich_request()
        computed = calculate_domain(self.datasets(request), request, "financial")
        self.assertFalse(any(gap.startswith("market") for gap in computed["gaps"]))
        self.assertFalse(any(source["metric"] == "close" for source in computed["evidence"].values()))
        self.assertTrue(all(fact["name"].startswith("financial") or fact["name"].endswith("_yoy")
                            for fact in computed["facts"]))

    def test_consumed_full_results_equal_original_complete_canonical_output(self):
        request = self.rich_request()
        datasets = self.datasets(request)
        legacy = calculate_study_claims(datasets, request)
        legacy["hypotheses"] = test_hypotheses(legacy, datasets, request)
        domains = self.reviewed(datasets, request)
        for supplied in ({}, {"financial": domains["financial"]}, {"market": domains["market"]}, domains,
                         {"market": domains["market"], "financial": domains["financial"]}):
            with self.subTest(supplied=tuple(supplied)):
                computed = compose_domains(datasets, request, supplied)
                computed["hypotheses"] = test_remaining_hypotheses(computed, datasets, request, supplied)
                self.assertEqual(computed, legacy)
                self.assertEqual(list(computed["evidence"]), list(legacy["evidence"]))
                self.assertEqual(verify(computed, datasets, request), verify(legacy, datasets, request))

    def test_delegated_parent_does_not_reproduce_either_domain(self):
        request = self.rich_request()
        datasets = self.datasets(request)
        domains = self.reviewed(datasets, request)
        with patch("stock_research.research.calculation._Calculation.financial", side_effect=AssertionError("financial repeated")), \
                patch("stock_research.research.calculation._Calculation.market", side_effect=AssertionError("market repeated")):
            computed = compose_domains(datasets, request, domains)
        with patch("stock_research.research.domain_operators.test_hypotheses", wraps=test_hypotheses) as producer:
            computed["hypotheses"] = test_remaining_hypotheses(computed, datasets, request, domains)
            self.assertEqual(producer.call_args.kwargs["hypothesis_ids"], {"market_direction", "event_chronology"})
        verify(computed, datasets, request)

    def test_domain_local_verification_independent_of_all_producers(self):
        request = self.rich_request()
        datasets = self.datasets(request)
        domains = self.reviewed(datasets, request)
        with patch("stock_research.research.calculation.calculate", side_effect=AssertionError("full producer")), \
                patch("stock_research.research.calculation._Calculation.fact", side_effect=AssertionError("fact producer")):
            for domain, computed in domains.items():
                self.assertEqual(verify_domain(computed, datasets, request, domain)["status"], "verified")

    def test_review_executes_one_local_verifier_and_structural_ordering(self):
        request = self.rich_request()
        datasets = self.datasets(request)
        computed = calculate_domain(datasets, request, "financial")
        with patch("stock_research.research.domain_operators.expected_claims", side_effect=AssertionError("ordering cannot recompute expected")), \
                patch("stock_research.research.domain_operators.verify_domain", wraps=verify_domain) as verifier:
            reviewed = review_domain(computed, datasets, request, "financial")
        self.assertEqual(verifier.call_count, 1)
        self.assertEqual(reviewed["local_verification"]["status"], "verified")

    def test_trusted_parent_consumes_without_any_local_oracle_then_original_full_verifies(self):
        request = self.rich_request()
        datasets = self.datasets(request)
        domains = self.reviewed(datasets, request)
        with patch("stock_research.research.domain_operators.expected_claims", side_effect=AssertionError("Parent projection repeated")), \
                patch("stock_research.research.domain_operators.verify_domain", side_effect=AssertionError("Parent local arithmetic repeated")), \
                patch("stock_research.research.verification.expected_domain_projection", side_effect=AssertionError("Parent Fraction repeated")):
            trusted = {domain: self.attest(datasets, request, domain, result) for domain, result in domains.items()}
            computed = compose_domains(datasets, request, trusted_domains=trusted)
            computed["hypotheses"] = test_remaining_hypotheses(computed, datasets, request, trusted_domains=trusted)
        legacy = calculate_study_claims(datasets, request)
        legacy["hypotheses"] = test_hypotheses(legacy, datasets, request)
        self.assertEqual(computed, legacy)
        self.assertEqual(list(computed["evidence"]), list(legacy["evidence"]))
        verify(computed, datasets, request)

    def test_trusted_handle_rejects_plain_dict_direct_construction_mutation_and_cross_request_source(self):
        request = self.rich_request()
        datasets = self.datasets(request)
        domains = self.reviewed(datasets, request)
        trusted = {domain: self.attest(datasets, request, domain, result) for domain, result in domains.items()}
        with self.assertRaises(IntegrityError):
            compose_domains(datasets, request, trusted_domains=domains)
        with self.assertRaises(IntegrityError):
            ValidatedDomainResult(domains["financial"], {})
        with self.assertRaises(IntegrityError):
            trusted["financial"]._content = "{}"
        changed = copy.deepcopy(datasets)
        changed["financial_income"]["warnings"].append("source_changed")
        with self.assertRaises(IntegrityError):
            compose_domains(changed, request, trusted_domains=trusted)
        with self.assertRaises(IntegrityError):
            compose_domains(datasets, replace(request, as_of=request.as_of + timedelta(seconds=1)), trusted_domains=trusted)
        with self.assertRaises(IntegrityError):
            compose_domains(datasets, request, trusted_domains={"financial": trusted["market"]})
        # An object manufactured without the issuer still cannot produce its MAC.
        forged = object.__new__(ValidatedDomainResult)
        object.__setattr__(forged, "_content", trusted["financial"]._content)
        object.__setattr__(forged, "_proof", trusted["financial"]._proof)
        object.__setattr__(forged, "_mac", b"invalid")
        with self.assertRaises(IntegrityError):
            compose_domains(datasets, request, trusted_domains={"financial": forged})

    def test_explicit_empty_trusted_mode_direct_produces_without_extra_parent_oracle(self):
        request = self.rich_request()
        datasets = self.datasets(request)
        with patch("stock_research.research.domain_operators.expected_claims", side_effect=AssertionError("extra Parent oracle")):
            computed = compose_domains(datasets, request, trusted_domains={})
        computed["hypotheses"] = test_remaining_hypotheses(computed, datasets, request, trusted_domains={})
        verify(computed, datasets, request)

    def test_partial_operators_accumulate_without_old_production_and_review_requires_full_coverage(self):
        request = self.rich_request()
        datasets = self.datasets(request)
        for domain, operators in (("financial", ("income_yoy", "financial_snapshot")),
                                  ("market", ("factor_adjusted_window", "market_price_window"))):
            parts = []
            for operator in operators:
                part = calculate_domain(datasets, request, domain, [operator])
                verify_domain(part, datasets, request, domain, operators=[operator], check_hypotheses=False)
                parts.append(part)
            with self.assertRaises(IntegrityError):
                review_domain(parts[0], datasets, request, domain)
            complete = review_domain(merge_domain_calculations(*parts), datasets, request, domain)
            expected = review_domain(calculate_domain(datasets, request, domain), datasets, request, domain)
            self.assertEqual(complete, expected)
            self.assertEqual(list(complete["evidence"]), list(expected["evidence"]))

    def test_missing_or_invalid_market_preserves_original_insufficiency(self):
        for prices in (("100",), ("100", None, "90"), (None, "120", "90")):
            with self.subTest(prices=prices):
                f = fixture(Path(self.temp.name) / digest(prices), prices=prices, scope="synthetic-domain-operators")
                request = study_request(f)
                datasets = self.datasets(request, f)
                domains = self.reviewed(datasets, request)
                actual = compose_domains(datasets, request, domains)
                self.assertEqual(actual, calculate_study_claims(datasets, request))

    def test_local_rejects_omitted_claim_evidence_gap_and_rehashed_fabrication(self):
        request = self.rich_request()
        datasets = self.datasets(request)
        domain = self.reviewed(datasets, request)["financial"]
        mutations = []
        changed = copy.deepcopy(domain)
        changed["facts"].pop()
        mutations.append(changed)
        changed = copy.deepcopy(domain)
        changed["evidence"].pop(next(iter(changed["evidence"])))
        mutations.append(changed)
        changed = copy.deepcopy(domain)
        changed["gaps"].append("fabricated:gap")
        mutations.append(changed)
        changed = copy.deepcopy(domain)
        fact = changed["facts"][0]
        fact["value"] = "999"
        fact["id"] = digest({k: v for k, v in fact.items() if k != "id"})
        mutations.append(changed)
        changed = copy.deepcopy(domain)
        source = next(iter(changed["evidence"].values()))
        source["raw_value"] = "999"
        mutations.append(changed)
        for changed in mutations:
            with self.subTest(changed=digest(changed)), self.assertRaises(IntegrityError):
                verify_domain(changed, datasets, request, "financial")

    def test_local_rejects_snapshot_provider_and_pit_misbinding(self):
        request = self.rich_request()
        datasets = self.datasets(request)
        computed = self.reviewed(datasets, request)["financial"]
        for field, value in (("snapshot", "0" * 64), ("provider", "unauthorized")):
            changed = copy.deepcopy(datasets)
            changed["financial_income"][field] = value
            with self.subTest(field=field), self.assertRaises(IntegrityError):
                verify_domain(computed, changed, request, "financial")
        past = replace(request, as_of=request.as_of - timedelta(days=2))
        with self.assertRaises(IntegrityError):
            verify_domain(computed, datasets, past, "financial")

    def test_source_call_attribution_survives_local_review_and_parent_merge(self):
        request = self.rich_request()
        datasets = self.datasets(request)
        domains = self.reviewed(datasets, request)
        for domain, computed in domains.items():
            for source in computed["evidence"].values():
                source["tool_call_id"] = "source-read:" + domain
        computed = compose_domains(datasets, request, domains)
        for domain in domains:
            for key in domains[domain]["evidence"]:
                self.assertEqual(computed["evidence"][key]["tool_call_id"], "source-read:" + domain)

    def test_domain_hypothesis_tampering_cannot_be_hidden_by_local_self_verification(self):
        request = self.rich_request()
        datasets = self.datasets(request)
        domains = self.reviewed(datasets, request)
        domains["market"]["hypotheses"][0]["status"] = "unsupported"
        domains["market"]["local_verification"]["status"] = "verified"
        with self.assertRaises(IntegrityError):
            compose_domains(datasets, request, domains)

    def test_root_event_only_produced_by_parent_with_original_anchor(self):
        request, _ = with_event(self.f)
        datasets = self.datasets(request)
        domains = self.reviewed(datasets, request)
        self.assertFalse(any(fact["name"].startswith("event_") for result in domains.values() for fact in result["facts"]))
        computed = compose_domains(datasets, request, domains)
        computed["hypotheses"] = test_remaining_hypotheses(computed, datasets, request, domains)
        self.assertEqual(computed["event_anchor"]["status"], "verified")
        verify(computed, datasets, request)

    def test_amount_profile_is_explicit_and_does_not_replace_percentage_insufficiency(self):
        rows = []
        for period, value in ((date(2023, 12, 31), "-100"), (date(2024, 12, 31), "-60")):
            metrics = tuple(replace(metric, value=Decimal(value), raw_value=value)
                            if metric.name == "net_income_parent" else metric for metric in self.f.financial.metrics)
            rows.append(replace(self.f.financial, period=period, metrics=metrics, revision_id=digest([str(period), value])))
        sid = self.f.repo.commit(self.f.access.scope, rows).snapshot_id
        request = study_request(self.f, hypotheses=("financial_deterioration", "absolute_profit_change"),
                                hypothesis_version="profit-change/v1")
        request = replace(request, bindings=tuple(replace(binding, snapshot=sid)
                          if binding.dataset == "financial_income" else binding for binding in request.bindings))
        datasets = self.datasets(request)
        domain = review_domain(calculate_domain(datasets, request, "financial"), datasets, request, "financial")
        self.assertIn("net_income_parent:yoy_missing_or_nonpositive_base", domain["gaps"])
        self.assertEqual(domain["hypotheses"][0]["status"], "insufficient")
        self.assertEqual(domain["hypotheses"][1]["status"], "supported")
        computed = compose_domains(datasets, request, {"financial": domain})
        self.assertEqual(computed, calculate_study_claims(datasets, request, profit_change=True))
        computed["hypotheses"] = test_remaining_hypotheses(computed, datasets, request, {"financial": domain})
        verify(computed, datasets, request)
        plain = study_request(self.f)
        with self.assertRaises(ValidationError):
            calculate_domain(datasets, plain, "financial", ["profit_amount_change"])

    def test_duplicate_identity_conflict_rejected_without_last_writer_wins(self):
        request = study_request(self.f)
        computed = calculate_domain(self.datasets(request), request, "financial")
        same = merge_domain_calculations(computed, computed)
        self.assertEqual(same, computed)
        changed = copy.deepcopy(computed)
        changed["facts"][0]["value"] = "0"
        with self.assertRaises(IntegrityError):
            merge_domain_calculations(computed, changed)


if __name__ == "__main__":
    unittest.main()
