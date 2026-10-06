"""Offline check of documented real original/corrected income versions."""

import hashlib
import argparse
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext, Security
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true", help="Recompute and compare with saved evidence")
    args = parser.parse_args()
    root = Path(".artifacts/p17_20260930/revision")
    output = root / "version_check.json"
    if output.exists() and not args.verify_only:
        raise ValueError("revision comparison already exists; refusing overwrite")
    refs = json.loads(Path("evaluation/p17_20260930_revision_values.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    supplement = json.loads((root / "supplement.json").read_text(encoding="utf-8"))
    files = {item["label"]: item for item in manifest["files"]}
    files["300122_correction_before_after"] = supplement
    probe = json.loads((root / "tushare_probe.json").read_text(encoding="utf-8"))
    db = PostgresRepository(Path(".runtime/p17-dsn.txt").read_text(encoding="utf-8").strip())
    rows = db.read(probe["scope"], probe["snapshot_id"])
    by_revision = {row.revision_order: row for row in rows}
    comparisons = []
    for version in refs["versions"]:
        source = files[version["reference_label"]]
        if hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() != version["reference_sha256"]:
            raise AssertionError("revision source PDF changed")
        revision_order = int(version["f_ann_date"].replace("-", ""))
        row = by_revision[revision_order]
        metrics = {m.name: m.value for m in row.metrics}
        for field, printed in version["metric_values_cny"].items():
            expected = Decimal(printed)
            actual = metrics[field]
            comparisons.append({"version": version["label"], "field": field,
                                "reference": str(expected), "actual": str(actual),
                                "difference": str(actual - expected), "match": actual == expected,
                                "reference_pdf_sha256": version["reference_sha256"],
                                "reference_pdf_page_one_based": version["pdf_page_one_based"],
                                "record_id": row.record_id})
    request = DataRequest(Security("300122", "SZSE"), Dataset.FINANCIAL_INCOME,
                          datetime(2024, 12, 31).date(), datetime(2024, 12, 31).date())
    access = AccessContext(probe["scope"], frozenset({"tushare"}))
    captured = max(r.available_at for r in rows)
    ingested = max(r.ingested_at for r in rows)
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(), executor, db, ArtifactStore(root / "artifacts"))
        old_cutoff = service.query(request, QueryContext(access, probe["snapshot_id"],
                                                        captured - timedelta(microseconds=1), PITMode.PUBLIC))
        current = service.query(request, QueryContext(access, probe["snapshot_id"],
                                                     ingested + timedelta(microseconds=1), PITMode.SYSTEM))
    date_only = []
    for item in manifest["official_index"]:
        shown_time = datetime.fromtimestamp(item["announcement_time_ms"] / 1000,
                                            timezone.utc).astimezone(timezone(timedelta(hours=8)))
        date_only.append({"announcement_id": item["announcement_id"],
                          "index_time_local": shown_time.isoformat(),
                          "is_midnight": shown_time.time().isoformat() == "00:00:00"})
    outcome = {"scope": probe["scope"], "snapshot_id": probe["snapshot_id"],
               "comparison_count": len(comparisons),
               "matched_count": sum(x["match"] for x in comparisons),
               "before_capture_visible_count": len(old_cutoff.records),
               "after_ingestion_selected_count": len(current.records),
               "selected_revision_order": current.records[0].revision_order if current.records else None,
               "official_index_times": date_only,
               "historical_intraday_release_verified": False,
               "comparisons": comparisons}
    if args.verify_only:
        saved = json.loads(output.read_text(encoding="utf-8"))
        if saved != outcome:
            raise AssertionError("saved revision evidence does not match current sources")
    else:
        output.write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: outcome[k] for k in ("comparison_count", "matched_count",
                                              "before_capture_visible_count", "after_ingestion_selected_count",
                                              "selected_revision_order", "official_index_times",
                                              "historical_intraday_release_verified")}, ensure_ascii=False))
    return 0 if (outcome["comparison_count"] == outcome["matched_count"] == 4
                 and outcome["before_capture_visible_count"] == 0
                 and outcome["selected_revision_order"] == 20260428) else 2


if __name__ == "__main__":
    raise SystemExit(main())
