"""Read-only independent Fraction checks on the frozen 601009 Phase 2 example.

Checks arithmetic and authorized lineage, NOT provider accuracy or overall Agent success.
DSN is supplied only through STOCK_RESEARCH_DSN; this script never reads model secrets.
"""
import argparse
import json
import os
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from stock_research.models import AccessContext, DataRecord, digest
from stock_research.providers.base import ProviderRegistry
from stock_research.research.cli import ReadArtifactStores
from stock_research.research.contracts import ResearchRequest
from stock_research.research.tools import read_domain
from stock_research.service import DataService
from stock_research.storage.postgres import PostgresRepository


def verify(report):
    request = ResearchRequest.from_dict(report["request"])
    service = DataService(ProviderRegistry(), None, PostgresRepository(os.environ["STOCK_RESEARCH_DSN"]),
                          ReadArtifactStores([".artifacts/p17_20261001/formal/artifacts"]))
    access = AccessContext("p17-formal-20261001", frozenset({"tushare"}))
    data = {**read_domain(service, request, access, "market"), **read_domain(service, request, access, "financial")}
    records = {DataRecord.from_dict(row).record_id: DataRecord.from_dict(row)
               for result in data.values() for row in result["records"]}
    prices = sorted((r.period, next(m.value for m in r.metrics if m.name == "close"))
                    for r in records.values() if r.dataset.value == "market_daily")
    fractions = [Fraction(price) for _, price in prices]
    expected = {"observed_price_change": fractions[-1] / fractions[0] - 1,
                "observed_max_drawdown": max(1 - value / max(fractions[:i+1]) for i, value in enumerate(fractions))}
    latest = max((r for r in records.values() if r.dataset.value == "financial_income"), key=lambda r: r.period)
    expected.update({"financial_income." + m.name: Fraction(m.value) for m in latest.metrics if m.value is not None})
    checks = {f["name"]: f["name"] in expected and
              abs(Fraction(Decimal(f["value"])) - expected[f["name"]]) < Fraction(1, 10**28) for f in report["facts"]}
    assert set(checks) == set(expected) and all(checks.values()), "numeric mismatch"
    for e in report["evidence"].values():
        record = records[e["record_id"]]
        metric = next(m for m in record.metrics if m.name == e["metric"])
        assert str(metric.value) == e["value"] and metric.unit == e["unit"]
        assert tuple(e["artifact_ids"]) == record.artifact_ids
    assert all(f["inputs"] and all(i in report["evidence"] for i in f["inputs"]) for f in report["facts"])
    return {"kind": "real_snapshot_arithmetic_and_lineage_replay", "run_id": report["run_id"],
            "report_hash": digest(report), "checked_claims": len(checks), "checks": checks,
            "checked_evidence": len(report["evidence"]), "provider_accuracy_certified": False,
            "model_network_calls": 0, "financial_provider_network_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=".artifacts/phase2/real-offline/report.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = verify(json.loads(Path(args.report).read_text(encoding="utf-8")))
    with Path(args.output).open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result))
