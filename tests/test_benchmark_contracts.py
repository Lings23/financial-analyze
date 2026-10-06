"""Synthetic pre-freeze safety mechanisms, never financial accuracy evidence."""
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
from stock_research.errors import PermissionDenied, ValidationError
from stock_research.models import AccessContext, PITMode, digest
from stock_research.research.benchmark_contracts import require_freezable, validate_contract, validate_service_contract
from stock_research.research.scoped import ScopedReadService, SourceGrant


class BenchmarkContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))

    def metadata(self, request, binding, access):
        snap = self.f.repo.snapshot(self.f.access.scope, binding.snapshot)
        rows = self.f.repo.read(self.f.access.scope, binding.snapshot)
        for r in rows:
            for aid in r.artifact_ids:
                self.f.artifacts.get(self.f.access.scope, aid)
        return {"trusted": True, "authorized": True, "artifacts_verified": True,
                "scope": access.scope, "owner_scope": self.f.access.scope,
                "snapshot": binding.snapshot, "provider": binding.provider,
                "provider_datasets": ["market_daily", "financial_income", "index_daily", "adjustment_factor",
                                      "financial_cashflow", "announcement", "news_recent"],
                "snapshot_datasets": sorted({r.dataset.value for r in rows if r.provider == binding.provider}),
                "snapshot_record_ids": list(snap.record_ids)}

    def audit(self, request=None, metadata_reader=None):
        return validate_service_contract(request or study_request(self.f, hypotheses=("financial_deterioration",)),
                                         self.f.access, self.f.service, metadata_reader or self.metadata)

    def source_input(self, request):
        rows, metas = {}, {}
        from stock_research.models import QueryContext
        for b in request.bindings:
            query = self.f.service.query(request.data_request(b),
                                        QueryContext(self.f.access, b.snapshot, request.as_of, request.mode))
            rows[b.dataset] = [r.to_dict() for r in query.records]
            metas[b.dataset] = self.metadata(request, b, self.f.access)
        return rows, metas

    def codes(self, result):
        return {i["code"] for i in result["issues"]}

    def test_financial_request_is_valid_and_inputs_are_stably_hashed(self):
        request = study_request(self.f, hypotheses=("financial_deterioration",))
        rows, metas = self.source_input(request)
        before = copy.deepcopy((rows, metas))
        a = validate_contract(request, self.f.access.scope, rows, metas)
        b = validate_contract(request.to_dict(), self.f.access.scope, rows, metas)
        self.assertIs(a["valid"], True)
        self.assertEqual(a, b)
        self.assertEqual((rows, metas), before)
        self.assertEqual(a["problem_class_counts"]["research_agent_implementation_defect"], 0)
        changed = replace(request, as_of=ts("2025-04-17T00:00:00"))
        self.assertNotEqual(a["input_sha256"], validate_contract(changed, self.f.access.scope, rows, metas)["input_sha256"])

    def test_missing_trusted_metadata_is_unknown_and_does_not_pass(self):
        request = study_request(self.f, hypotheses=("financial_deterioration",))
        rows, _ = self.source_input(request)
        result = validate_contract(request, self.f.access.scope, rows, {})
        self.assertIsNone(result["valid"])
        self.assertEqual(result["status"], "not_assessable")
        self.assertIn("trusted_binding_metadata_missing", self.codes(result))
        self.assertTrue(all(i["blocks_freeze"] for i in result["issues"]))

    def test_freeze_assertion_blocks_entire_invalid_or_unknown_batch_without_filtering(self):
        good = self.audit()
        bad = self.audit(study_request(self.f, hypotheses=("event_chronology",)))
        unknown = {**good, "valid": None}
        self.assertEqual(require_freezable([good]), (good,))
        for batch in ([good, bad], [good, unknown], [], [{"schema": "legacy", "valid": True}]):
            with self.subTest(batch=len(batch)), self.assertRaises(ValidationError):
                require_freezable(batch)

    def test_authorization_is_rechecked_on_every_read_including_composed_grants(self):
        request = study_request(self.f, hypotheses=("financial_deterioration",))
        grants = [SourceGrant(self.f.service, self.f.access, b.snapshot, request.data_request(b), b.provider)
                  for b in request.bindings]
        service = ScopedReadService("recipient", lambda: grants)
        access = AccessContext("recipient", frozenset({"fixture"}))
        result = validate_service_contract(request, access, service, self.metadata)
        self.assertIs(result["valid"], True)
        grants.clear()
        with self.assertRaises(PermissionDenied):
            validate_service_contract(request, access, service, self.metadata)
        wrong = AccessContext("recipient", frozenset({"different"}))
        with self.assertRaises(PermissionDenied):
            validate_service_contract(request, wrong, service, self.metadata)

    def test_scope_or_snapshot_substitution_cannot_pass(self):
        request = study_request(self.f, hypotheses=("financial_deterioration",))
        rows, metas = self.source_input(request)
        for key, value, expected in (("scope", "other", "binding_identity_mismatch"),
                                     ("snapshot", "0" * 64, "binding_identity_mismatch"),
                                     ("snapshot_record_ids", ["0" * 64], "snapshot_hash_mismatch"),
                                     ("authorized", False, "source_not_authorized")):
            with self.subTest(key=key):
                changed = copy.deepcopy(metas)
                changed["market_daily"][key] = value
                result = validate_contract(request, self.f.access.scope, rows, changed)
                self.assertIs(result["valid"], False)
                self.assertIn(expected, self.codes(result))

    def test_financial_only_snapshot_cannot_be_bound_as_market(self):
        sid = self.f.repo.commit(self.f.access.scope, (self.f.financial,)).snapshot_id
        request = study_request(self.f, hypotheses=("financial_deterioration",))
        request = replace(request, bindings=tuple(replace(b, snapshot=sid) for b in request.bindings))
        result = self.audit(request)
        self.assertIs(result["valid"], False)
        self.assertIn("market_source_incompatible", self.codes(result))
        issue = next(i for i in result["issues"] if i["code"] == "market_source_incompatible")
        self.assertEqual(issue["category"], "benchmark_or_request_contract_defect")

    def test_provider_capability_must_support_bound_dataset(self):
        def metadata(*args):
            result = self.metadata(*args)
            result["provider_datasets"] = ["financial_income"]
            return result
        result = self.audit(metadata_reader=metadata)
        self.assertIs(result["valid"], False)
        self.assertIn("market_source_incompatible", self.codes(result))

    def empty_capture_input(self):
        request = study_request(self.f, hypotheses=("financial_deterioration",))
        # Synthetic records and synthetic archive bytes test only this boundary.
        rows = self.f.repo.read(self.f.access.scope, request.bindings[0].snapshot)
        sid = self.f.repo.commit(self.f.access.scope, tuple(replace(r, provider="tushare")
                                                         for r in rows if r.dataset.value == "financial_income")).snapshot_id
        self.f.access = AccessContext(self.f.access.scope, frozenset({"tushare"}))
        request = replace(request, bindings=tuple(replace(b, snapshot=sid, provider="tushare") for b in request.bindings))
        source, metas = self.source_input(request)
        binding = next(b for b in request.bindings if b.dataset == "market_daily")
        archive = {"api_name": "daily", "archive_schema": "tushare_requested_response_v2", "business_code": 0,
                   "response_fields": ["ts_code", "trade_date", "close"], "items": [],
                   "response_row_count": 0, "selected_row_count": 0,
                   "params": {"ts_code": request.security.provider_symbol,
                              "start_date": binding.start.strftime("%Y%m%d"), "end_date": binding.end.strftime("%Y%m%d")},
                   "started_at": "2025-04-15T05:00:00+00:00", "finished_at": "2025-04-15T06:00:00+00:00"}
        proof = {"kind": "tushare_requested_response_v2_empty/v1", "source_authorized": True,
                 "source_scope": self.f.access.scope, "bound_snapshot": binding.snapshot,
                 "request_identity": request.data_request(binding).identity(),
                 "archive_artifact_id": digest(archive), "archive": archive}
        metas["market_daily"]["empty_dataset_capture"] = proof
        return request, source, metas

    def test_verified_empty_capture_is_data_shortage_and_remains_in_denominator(self):
        request, rows, metas = self.empty_capture_input()
        result = validate_contract(request, self.f.access.scope, rows, metas)
        self.assertIs(result["valid"], True)
        self.assertIn("missing_dataset", self.codes(result))
        self.assertNotIn("market_source_incompatible", self.codes(result))
        check = result["dataset_compatibility"]["market_daily"]
        self.assertIs(check["snapshot_contains_dataset"], False)
        self.assertIs(check["empty_capture_verified"], True)
        self.assertEqual(require_freezable([result]), (result,))

    def test_empty_capture_proof_requires_exact_hash_scope_window_and_cutoff(self):
        request, rows, metas = self.empty_capture_input()
        for field, value in (("archive_artifact_id", "0" * 64), ("source_authorized", False),
                             ("source_scope", "other"), ("bound_snapshot", "0" * 64),
                             ("request_identity", {})):
            with self.subTest(field=field):
                changed = copy.deepcopy(metas)
                changed["market_daily"]["empty_dataset_capture"][field] = value
                result = validate_contract(request, self.f.access.scope, rows, changed)
                self.assertIs(result["valid"], False)
                self.assertIn("empty_capture_provenance_invalid", self.codes(result))
        for key, value in (("items", [["600000.SH", "20250401", "100"]]),
                           ("business_code", -1), ("finished_at", "2025-04-17T06:00:00+00:00"),
                           ("params", {"ts_code": "000016.SZ", "start_date": "20250401", "end_date": "20250414"})):
            with self.subTest(key=key):
                changed = copy.deepcopy(metas)
                proof = changed["market_daily"]["empty_dataset_capture"]
                proof["archive"][key] = value
                proof["archive_artifact_id"] = digest(proof["archive"])
                result = validate_contract(request, self.f.access.scope, rows, changed)
                self.assertIs(result["valid"], False)
                self.assertIn("empty_capture_provenance_invalid", self.codes(result))

    def test_empty_capture_cannot_make_unsupported_provider_compatible(self):
        request, rows, metas = self.empty_capture_input()
        metas["market_daily"]["provider_datasets"] = ["financial_income"]
        result = validate_contract(request, self.f.access.scope, rows, metas)
        self.assertIs(result["valid"], False)
        self.assertIn("market_source_incompatible", self.codes(result))
        self.assertIs(result["dataset_compatibility"]["market_daily"]["empty_capture_verified"], False)

    def test_unbound_required_dataset_is_contract_defect(self):
        result = self.audit(study_request(self.f, hypotheses=("mechanical_adjustment",)))
        self.assertIs(result["valid"], False)
        issue = next(i for i in result["issues"] if i["code"] == "required_dataset_not_bound")
        self.assertEqual(issue["dataset"], "adjustment_factor")

    def test_legal_binding_with_empty_visible_data_retains_valid_denominator(self):
        request = study_request(self.f, hypotheses=("financial_deterioration",))
        request = replace(request, mode=PITMode.PUBLIC, as_of=ts("2025-03-31T00:00:00"))
        result = self.audit(request)
        self.assertIs(result["valid"], True)
        self.assertIn("missing_dataset", self.codes(result))
        self.assertEqual(next(i for i in result["issues"] if i["code"] == "missing_dataset")["category"],
                         "data_or_evidence_insufficiency")

    def test_forged_or_future_selected_sources_are_rejected(self):
        request = study_request(self.f, hypotheses=("financial_deterioration",))
        rows, metas = self.source_input(request)
        changed = copy.deepcopy(rows)
        changed["market_daily"][0]["metrics"][0]["value"] = "999"
        self.assertIs(validate_contract(request, self.f.access.scope, changed, metas)["valid"], False)
        earlier = replace(request, as_of=ts("2025-04-02T00:00:00"))
        result = validate_contract(earlier, self.f.access.scope, rows, metas)
        self.assertIs(result["valid"], False)
        self.assertIn("source_selection_contract_mismatch", self.codes(result))

    def test_nonpositive_base_is_checkable_intrinsic_limit_not_invalid_input(self):
        request = study_request(self.f, hypotheses=("financial_deterioration",))
        source = self.f.repo.read(self.f.access.scope, request.bindings[0].snapshot)
        changed = tuple(replace(r, metrics=tuple(replace(m, value=Decimal("-1"), raw_value="-1")
                                                if m.name == "net_income_parent" else m for m in r.metrics))
                        if r.dataset.value == "financial_income" and r.period.year == 2023 else r for r in source)
        sid = self.f.repo.commit(self.f.access.scope, changed).snapshot_id
        request = replace(request, bindings=tuple(replace(b, snapshot=sid) for b in request.bindings))
        result = self.audit(request)
        self.assertIs(result["valid"], True)
        self.assertTrue(result["hypothesis_preconditions"]["financial_deterioration"]["checkable"])
        issue = next(i for i in result["issues"] if i["code"] == "positive_base_precondition_failed")
        self.assertEqual(issue["category"], "intrinsic_precondition_or_temporal_impossibility")
        self.assertFalse(issue["blocks_freeze"])

    def test_absent_prior_period_is_data_limitation_not_contract_invalid(self):
        request = study_request(self.f, hypotheses=("financial_deterioration",))
        source = self.f.repo.read(self.f.access.scope, request.bindings[0].snapshot)
        sid = self.f.repo.commit(self.f.access.scope, tuple(r for r in source if r.period.year != 2023)).snapshot_id
        request = replace(request, bindings=tuple(replace(b, snapshot=sid) for b in request.bindings))
        result = self.audit(request)
        self.assertIs(result["valid"], True)
        self.assertIn("missing_report_period", self.codes(result))

    def test_window_excluding_required_prior_period_is_contract_invalid(self):
        request = study_request(self.f, hypotheses=("financial_deterioration",))
        request = replace(request, bindings=tuple(replace(b, start=date(2024, 12, 31))
                                                if b.dataset == "financial_income" else b for b in request.bindings))
        result = self.audit(request)
        self.assertIs(result["valid"], False)
        self.assertIn("required_report_period_outside_window", self.codes(result))

    def test_disjoint_binding_windows_are_contract_invalid(self):
        request = study_request(self.f, hypotheses=("market_direction",))
        request, _ = add_domain(self.f, request, "index_daily", periods=[date(2025, 3, 1), date(2025, 3, 3)],
                                values={"close": ["100", "110"]})
        result = self.audit(request)
        self.assertIs(result["valid"], False)
        self.assertIn("required_windows_disjoint", self.codes(result))

    def test_missing_close_is_not_removed_to_make_full_series_checkable(self):
        self.f = fixture(Path(self.temp.name) / "null-close", prices=("100", None, "120"))
        request = study_request(self.f, hypotheses=("market_direction",))
        request, _ = add_domain(self.f, request, "index_daily", values={"close": ["100", "110", "120"]})
        result = self.audit(request)
        self.assertIs(result["valid"], True)
        self.assertFalse(result["hypothesis_preconditions"]["market_direction"]["checkable"])
        self.assertIn("missing_metric", self.codes(result))

    def test_exact_date_alignment_failure_does_not_filter_case_out(self):
        request = study_request(self.f, hypotheses=("market_direction",))
        request, _ = add_domain(self.f, request, "index_daily", periods=[date(2025, 4, 1), date(2025, 4, 3)],
                                values={"close": ["100", "110"]})
        result = self.audit(request)
        self.assertIs(result["valid"], True)
        self.assertIn("exact_date_alignment_failed", self.codes(result))
        self.assertTrue(result["hypothesis_preconditions"]["market_direction"]["checkable"])

    def test_missing_specific_event_is_invalid_without_selecting_a_replacement(self):
        result = self.audit(study_request(self.f, hypotheses=("event_chronology",)))
        self.assertIs(result["valid"], False)
        self.assertIn("missing_event", self.codes(result))
        self.assertIsNone(result["event_completeness"]["record_id"])

    def test_visible_date_anchor_excludes_disclosure_day_from_before(self):
        request, event = with_event(self.f, date_only=True)
        result = self.audit(request)
        self.assertIs(result["valid"], True)
        self.assertEqual(result["event_completeness"]["record_id"], event.record_id)
        self.assertEqual(result["temporal_feasibility"]["observed_before"], ["2025-04-01"])
        self.assertEqual(result["temporal_feasibility"]["observed_after"], ["2025-04-03"])

    def test_wrong_target_or_superseded_event_cannot_be_an_anchor(self):
        request, event = with_event(self.f)
        for event_id in ("0" * 64, self.f.financial.record_id):
            with self.subTest(event_id=event_id):
                result = self.audit(replace(request, event_record_id=event_id))
                self.assertIs(result["valid"], False)
                self.assertIn("invalid_event_binding", self.codes(result))

    def test_system_cutoff_does_not_reuse_public_event_visibility(self):
        request, _ = with_event(self.f, date_only=True)
        public = replace(request, mode=PITMode.PUBLIC, as_of=ts("2025-04-04T00:00:00"))
        system = replace(public, mode=PITMode.SYSTEM)
        self.assertTrue(self.audit(public)["event_completeness"]["valid"])
        result = self.audit(system)
        self.assertFalse(result["event_completeness"]["valid"])
        self.assertIn("invalid_event_binding", self.codes(result))

    def test_cutoff_before_earliest_post_close_is_temporally_impossible(self):
        request, _ = with_event(self.f, date_only=True)
        request = replace(request, mode=PITMode.PUBLIC, as_of=ts("2025-04-02T16:00:00"))
        result = self.audit(request)
        self.assertIs(result["valid"], False)
        self.assertIs(result["temporal_feasibility"]["possible_under_request"], False)
        issue = next(i for i in result["issues"] if i["code"] == "temporal_condition_impossible")
        self.assertEqual(issue["category"], "intrinsic_precondition_or_temporal_impossibility")

    def test_empty_legal_post_prices_are_data_shortage_not_input_error(self):
        self.f = fixture(Path(self.temp.name) / "few", prices=("100", "120"))
        request, _ = with_event(self.f, date_only=True)
        result = self.audit(request)
        self.assertIs(result["valid"], True)
        self.assertIs(result["temporal_feasibility"]["possible_under_request"], True)
        self.assertIn("no_valid_market_window", self.codes(result))


if __name__ == "__main__":
    unittest.main()
