"""Synthetic oracle mechanism checks; fixtures are never financial truth."""
import copy
import hashlib
import json
from fractions import Fraction
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from phase3_benchmark_v2_oracle import (Reader, digest, expected_facts,
    expected_hypotheses, empty_dataset_checks, rid, select_inputs, write_new)


def record(dataset, period, values, *, available="2026-10-01T00:00:00+00:00", **extra):
    bases = {"market_daily": "unadjusted_daily", "financial_income": "consolidated_cumulative_cny",
             "index_daily": "price_index_daily", "adjustment_factor": "raw_adjustment_factor"}
    unit = "CNY/share" if dataset == "market_daily" else "point" if dataset == "index_daily" else "ratio" if dataset == "adjustment_factor" else "CNY"
    return {"security_id": "CN:index:000300.SH" if dataset == "index_daily" else "CN:equity:SZSE:000001",
        "dataset": dataset, "period": period, "basis": bases[dataset], "provider": "synthetic",
        "metrics": [{"name": name, "value": value, "raw_value": value, "unit": unit, "raw_unit": unit} for name, value in sorted(values.items())],
        "provider_version": "synthetic/1", "source_url": "https://example.invalid/synthetic",
        "source_key": period, "revision_id": digest(values), "provider_call_id": "synthetic-call",
        "available_at": available, "retrieved_at": "2026-10-01T00:00:00+00:00",
        "ingested_at": "2026-10-01T00:00:01+00:00", "availability_basis": "observed_at",
        "artifact_id": "0" * 64, "revision_order": 0, **extra}


class OracleMechanisms(unittest.TestCase):
    def sources(self, prior="-10", current="5", hypotheses=("absolute_profit_change",)):
        rows = [record("market_daily", "2026-09-16", {"close": "10"}),
                record("market_daily", "2026-09-24", {"close": "12"}),
                record("financial_income", "2024-06-30", {"revenue": "100", "net_income_parent": prior, "total_revenue": "100"}),
                record("financial_income", "2025-06-30", {"revenue": "80", "net_income_parent": current, "total_revenue": "80"})]
        ids = sorted(rid(row) for row in rows)
        sid = digest({"scope": "synthetic-owner", "record_ids": ids})
        bindings = [{"dataset": "market_daily", "snapshot": sid, "provider": "synthetic", "start": "2026-09-16", "end": "2026-09-24"},
                    {"dataset": "financial_income", "snapshot": sid, "provider": "synthetic", "start": "2024-06-30", "end": "2025-06-30"}]
        request = {"symbol": "000001", "exchange": "SZSE", "as_of": "2026-10-04T00:00:00+08:00", "mode": "system",
                   "hypotheses": list(hypotheses), "bindings": bindings, "benchmark": "000300.SH", "event_record_id": None}
        case = {"scope": "synthetic-recipient", "source_scopes": {b["dataset"]: "synthetic-owner" for b in bindings}, "request": request}
        frozen = {"request": request, "scope": case["scope"], "snapshots": [{"owner_scope": "synthetic-owner", "snapshot": sid, "record_ids": ids, "records": rows}]}
        return case, frozen

    def expected(self, case, frozen):
        selected, bindings, checks = select_inputs(case, frozen)
        self.assertTrue(all(checks.values()))
        facts, evidence, anchor, event, pair = expected_facts(selected, bindings, case["request"])
        hypotheses = expected_hypotheses(facts, evidence, selected, case["request"], anchor)
        return facts, hypotheses, pair

    def test_nonpositive_base_uses_signed_amount_and_never_percent_yoy(self):
        case, frozen = self.sources()
        facts, hypotheses, _ = self.expected(case, frozen)
        self.assertEqual(facts["financial_income.absolute_profit_change"]["fraction"], [15, 1])
        self.assertNotIn("net_income_parent_yoy", facts)
        self.assertEqual(hypotheses["absolute_profit_change"]["status"], "supported")

    def test_negative_or_zero_difference_is_explicit_counterevidence(self):
        for current in ("-12", "-10"):
            with self.subTest(current=current):
                case, frozen = self.sources(current=current)
                _, hypotheses, _ = self.expected(case, frozen)
                h = hypotheses["absolute_profit_change"]
                self.assertEqual(h["status"], "unsupported")
                self.assertEqual(h["claim_names"], h["counterevidence_claim_names"])

    def test_missing_input_does_not_become_zero(self):
        case, frozen = self.sources(prior=None)
        facts, hypotheses, _ = self.expected(case, frozen)
        self.assertNotIn("financial_income.absolute_profit_change", facts)
        self.assertEqual(hypotheses["absolute_profit_change"]["status"], "insufficient")
        self.assertEqual(hypotheses["absolute_profit_change"]["reason"], "net_income_parent_missing")

    def test_full_snapshot_tampering_fails_even_when_selected_subset_unchanged(self):
        case, frozen = self.sources()
        frozen["snapshots"][0]["records"][0]["source_key"] = "tampered"
        _, _, checks = select_inputs(case, frozen)
        self.assertFalse(checks["full_snapshot_membership_hash_0"])

    def test_naive_cutoff_rejected_and_public_system_differ(self):
        case, frozen = self.sources()
        case["request"]["as_of"] = "2026-10-04T00:00:00"
        with self.assertRaises(ValueError):
            select_inputs(case, frozen)
        case, frozen = self.sources()
        case["request"]["as_of"] = "2026-10-01T00:00:00+00:00"
        selected, _, _ = select_inputs(case, frozen)
        self.assertFalse(any(selected.values()))
        case["request"]["mode"] = "public"
        selected, _, _ = select_inputs(case, frozen)
        self.assertTrue(any(selected.values()))

    def test_complete_fraction_fact_set_includes_drawdown_all_observations(self):
        case, frozen = self.sources(prior="20", hypotheses=("financial_deterioration",))
        facts, hypotheses, _ = self.expected(case, frozen)
        self.assertEqual(Fraction(*facts["observed_price_change"]["fraction"]), Fraction(1, 5))
        self.assertEqual(facts["observed_max_drawdown"]["fraction"], [0, 1])
        self.assertEqual(len(facts["observed_max_drawdown"]["inputs"]), 2)
        self.assertEqual(hypotheses["financial_deterioration"]["status"], "supported")

    def test_date_event_excludes_disclosure_day_and_uses_last_sides(self):
        case, frozen = self.sources(hypotheses=("event_chronology",))
        rows = frozen["snapshots"][0]["records"]
        event = rows[-1]
        event.update(availability_basis="verified_release_date", release_date="2026-09-20",
                     available_at="2026-09-20T16:00:00+00:00", published_at=None,
                     release_evidence_artifact_id="1" * 64)
        case["request"]["event_record_id"] = rid(event)
        rows.append(record("market_daily", "2026-09-20", {"close": "100"}))
        ids = sorted(rid(row) for row in rows)
        sid = digest({"scope": "synthetic-owner", "record_ids": ids})
        frozen["snapshots"][0].update(snapshot=sid, record_ids=ids)
        for b in case["request"]["bindings"]:
            b["snapshot"] = sid
        facts, hypotheses, pair = self.expected(case, frozen)
        self.assertEqual([row["period"] for row in pair], ["2026-09-16", "2026-09-24"])
        self.assertEqual(hypotheses["event_chronology"]["status"], "supported")
        self.assertEqual(facts["event_observed_price_change"]["fraction"], [1, 5])

    def test_exclusive_output_and_credential_reads_refused(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.json"
            write_new(path, {"synthetic": True})
            with self.assertRaises(FileExistsError):
                write_new(path, {"synthetic": True})
            reader = Reader(temporary)
            with self.assertRaises(ValueError):
                reader.path(Path(temporary) / "test_api.txt")
            with self.assertRaises(ValueError):
                reader.path(Path(temporary).parent / "outside.json")

    def test_empty_snapshot_needs_exact_successful_original_response(self):
        with TemporaryDirectory() as temporary:
            case, frozen = self.sources()
            binding = case["request"]["bindings"][0]
            binding["provider"] = "tushare"
            archive = {"archive_schema": "tushare_requested_response_v2", "api_name": "daily", "business_code": 0,
                "items": [], "fields": ["ts_code", "trade_date", "close"], "response_fields": ["ts_code", "trade_date", "close"],
                "response_row_count": 0, "selected_row_count": 0, "params": {"ts_code": "000001.SZ", "start_date": "20260916", "end_date": "20260924"},
                "started_at": "2026-10-01T00:00:00+00:00", "finished_at": "2026-10-01T00:00:01+00:00"}
            path = Path(temporary) / "synthetic-empty.json"
            write_new(path, archive)
            aid = hashlib.sha256(path.read_bytes()).hexdigest()
            case["source_hashes"] = {path.name: aid}
            proof = {"kind": "tushare_requested_response_v2_empty/v1", "source_authorized": True,
                "source_scope": "synthetic-owner", "bound_snapshot": binding["snapshot"], "archive_artifact_id": aid, "archive": archive,
                "request_identity": {"security_id": "CN:equity:SZSE:000001", "dataset": "market_daily",
                    "start": binding["start"], "end": binding["end"], "basis": "unadjusted_daily"}}
            frozen["binding_metadata"] = {"market_daily": {"empty_dataset_capture": proof}}
            self.assertTrue(all(empty_dataset_checks(case, frozen, binding, Reader(temporary)).values()))
            proof["archive"]["business_code"] = -1
            self.assertFalse(all(empty_dataset_checks(case, frozen, binding, Reader(temporary)).values()))
            frozen["binding_metadata"]["market_daily"].clear()
            self.assertFalse(all(empty_dataset_checks(case, frozen, binding, Reader(temporary)).values()))


if __name__ == "__main__":
    unittest.main()
