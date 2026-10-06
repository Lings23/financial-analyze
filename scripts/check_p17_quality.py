"""Compare frozen real-source P1.7 records to separately transcribed official PDFs."""

import collections
import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository


ROOT = Path(".artifacts/p17_20260930")
REFERENCES = Path("evaluation/p17_20260930_reference_values.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true", help="Recompute and compare with saved evidence")
    args = parser.parse_args()
    run = json.loads((ROOT / "run.json").read_text(encoding="utf-8"))
    references = json.loads(REFERENCES.read_text(encoding="utf-8"))
    manifest = {item["label"]: item for item in json.loads(
        (ROOT / "references/manifest.json").read_text(encoding="utf-8"))}
    db = PostgresRepository(Path(".runtime/p17-dsn.txt").read_text(encoding="utf-8").strip())
    records = db.read(run["scope"], run["results"][-1]["snapshot_id"])
    by_key = {(record.canonical_symbol, record.dataset.value, record.period.isoformat()): record
              for record in records}
    if len(by_key) != len(records):
        raise AssertionError("normalized dataset has duplicate grain")

    comparisons = []

    def checked_reference(label, expected_sha):
        entry = manifest[label]
        actual_sha = hashlib.sha256(Path(entry["path"]).read_bytes()).hexdigest()
        if actual_sha != expected_sha or actual_sha != entry["sha256"]:
            raise AssertionError("official PDF hash does not match locked reference")
        return entry

    market = references["market_daily"]
    market_file = checked_reference(market["reference_label"], market["reference_sha256"])
    for row in market["rows"]:
        record = by_key[(market["security"], "market_daily", row["date"])]
        metrics = {metric.name: metric for metric in record.metrics}
        for field in ("close", "volume", "amount"):
            actual = metrics[field].value
            expected = Decimal(row[field])
            comparisons.append({"dataset": "market_daily", "security": market["security"],
                                "period": row["date"], "field": field, "actual": str(actual),
                                "reference": str(expected), "difference": str(actual - expected),
                                "tolerance": "0", "match": actual == expected,
                                "source_url": market_file["url"], "source_sha256": market_file["sha256"],
                                "pdf_page_one_based": market["pdf_page_one_based"],
                                "record_id": record.record_id})

    unit_multiplier = {"CNY million": Decimal(1_000_000), "CNY thousand": Decimal(1000),
                       "CNY": Decimal(1)}
    for row in references["financial_income"]:
        source = checked_reference(row["reference_label"], row["reference_sha256"])
        record = by_key[(row["security"], "financial_income", row["period"])]
        if record.basis != "consolidated_cumulative_cny":
            raise AssertionError("financial report basis changed")
        metrics = {metric.name: metric for metric in record.metrics}
        multiplier = unit_multiplier[row["printed_unit"]]
        tolerance = multiplier / 2
        for field, printed in row["metric_values"].items():
            expected = Decimal(printed) * multiplier
            actual = metrics[field].value
            difference = actual - expected
            comparisons.append({"dataset": "financial_income", "security": row["security"],
                                "period": row["period"], "field": field, "actual": str(actual),
                                "reference": str(expected), "difference": str(difference),
                                "tolerance": str(tolerance), "match": abs(difference) <= tolerance,
                                "source_url": source["url"], "source_sha256": source["sha256"],
                                "pdf_page_one_based": row["pdf_page_one_based"],
                                "record_id": record.record_id})

    raw_duplicates = []
    artifacts = ArtifactStore(ROOT / "artifacts")
    for entry in run["results"]:
        if entry["dataset"] != "financial_income":
            continue
        for call in run["calls"][entry["audit_call_start_index"]:entry["audit_call_end_index"]]:
            payload = json.loads(artifacts.get(run["scope"], call["raw_response_artifact_id"]))
            rows = [dict(zip(payload["response_fields"], item)) for item in payload["response_items"]]
            window_rows = [r for r in rows if entry["start"].replace("-", "") <= r["end_date"]
                           <= entry["end"].replace("-", "")]
            key = lambda r: (r["end_date"], r["ann_date"], r.get("f_ann_date"), r["report_type"])
            counts = collections.Counter(key(row) for row in window_rows)
            for grain, count in counts.items():
                if count > 1:
                    raw_duplicates.append({"symbol": entry["symbol"], "grain": grain,
                                           "row_count": count,
                                           "identical_requested_fields": len({json.dumps(r, sort_keys=True)
                                            for r in window_rows if key(r) == grain}) == 1})

    issues = []
    nulls = collections.Counter()
    counts = collections.Counter()
    for record in records:
        counts[record.dataset.value] += 1
        if record.available_at < record.retrieved_at or record.ingested_at < record.retrieved_at:
            issues.append({"record_id": record.record_id, "issue": "temporal_order"})
        if record.availability_basis != "observed_at":
            issues.append({"record_id": record.record_id, "issue": "unexpected_release_basis"})
        values = {metric.name: metric.value for metric in record.metrics}
        for metric in record.metrics:
            if metric.value is None:
                nulls[(record.dataset.value, metric.name)] += 1
        if record.dataset.value == "market_daily":
            o, h, l, c = (values[x] for x in ("open", "high", "low", "close"))
            if any(v is None for v in (o, h, l, c)) or not (l <= o <= h and l <= c <= h):
                issues.append({"record_id": record.record_id, "issue": "invalid_ohlc"})
            if values["volume"] is None or values["amount"] is None or values["volume"] < 0 or values["amount"] < 0:
                issues.append({"record_id": record.record_id, "issue": "invalid_volume_amount"})
    failures = [item for item in comparisons if not item["match"]]
    output = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "plan_sha256": run["plan_sha256"],
              "reference_values_sha256": hashlib.sha256(REFERENCES.read_bytes()).hexdigest(),
              "snapshot_id": run["results"][-1]["snapshot_id"],
              "record_counts": dict(counts), "metric_cells": sum(len(r.metrics) for r in records),
              "compared_cells": len(comparisons), "matched_cells": len(comparisons) - len(failures),
              "uncompared_cells": sum(len(r.metrics) for r in records) - len(comparisons),
              "null_counts": [{"dataset": d, "field": f, "count": n} for (d, f), n in sorted(nulls.items())],
              "raw_duplicate_grains": raw_duplicates, "integrity_issues": issues,
              "comparisons": comparisons}
    path = ROOT / "comparison.json"
    if args.verify_only:
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved.pop("checked_at", None)
        output.pop("checked_at", None)
        normalized = json.loads(json.dumps(output, ensure_ascii=False))
        if saved != normalized:
            mismatched = sorted(key for key in normalized.keys() | saved.keys() if saved.get(key) != normalized.get(key))
            raise AssertionError(f"saved comparison evidence differs in: {', '.join(mismatched)}")
    else:
        if path.exists():
            raise ValueError("comparison evidence already exists; refusing to overwrite")
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("record_counts", "metric_cells", "compared_cells",
                                               "matched_cells", "uncompared_cells", "null_counts",
                                               "raw_duplicate_grains", "integrity_issues")}, ensure_ascii=False))
    return 0 if not failures and not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())
