"""Real qualified date-release Phase 3 anchors. Read-only; no market fill or network."""
import argparse
from dataclasses import replace
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path

from accept_phase2_real import write
from stock_research.errors import PermissionDenied
from stock_research.models import AccessContext, PITMode, QueryContext, Security, digest
from stock_research.providers.base import ProviderRegistry
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.contracts import Binding
from stock_research.research.report import markdown
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudyRequest
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository


ROOT = Path(".artifacts/p17_20261001/release_date")
PLAN = Path("evaluation/p17_20261001_release_date_plan.json")


def inputs():
    plan, run = json.loads(PLAN.read_bytes()), json.loads((ROOT/"run.json").read_bytes())
    assert hashlib.sha256(PLAN.read_bytes()).hexdigest() == run["plan_sha256"]
    assert hashlib.sha256(Path(plan["qualification_path"]).read_bytes()).hexdigest() == plan["qualification_sha256"]
    svc = DataService(ProviderRegistry(), None, PostgresRepository(Path(".runtime/p17-dsn.txt").read_text().strip()), ArtifactStore(ROOT/"artifacts"))
    access = AccessContext(plan["scope"], frozenset({"cninfo"}))
    return plan, run, svc, access


def make_request(plan, run, cutoff, mode):
    return StudyRequest(Security(plan["symbol"], plan["exchange"]), cutoff, mode,
                        (Binding("market_daily", run["final_snapshot"], "cninfo", date(2025,4,18), date(2025,4,30)),
                         Binding("financial_income", run["final_snapshot"], "cninfo", date.fromisoformat(plan["period"]), date.fromisoformat(plan["period"]))),
                        hypotheses=("event_chronology",))


def prepare(path):
    plan, run, svc, access = inputs()
    cases = []
    for i, cutoff in enumerate(plan["public_cutoffs_local"]):
        request = make_request(plan, run, datetime.fromisoformat(cutoff), PITMode.PUBLIC)
        binding = request.bindings[1]
        rows = svc.query(request.data_request(binding), QueryContext(access, binding.snapshot, request.as_of, request.mode)).records
        # A valid-shaped placeholder stays unresolvable when no record is visible.
        rid = rows[0].record_id if rows else "0"*64
        request = replace(request, objective="event_review", event_record_id=rid)
        cases.append({"id":"public-boundary-"+str(i+1), "request":request.to_dict(),
                      "expected_anchor":"verified" if rows else "insufficient",
                      "expected_values":{m.name:str(m.value) for m in rows[0].metrics if m.value is not None} if rows else {},
                      "expected_release_date":rows[0].release_date.isoformat() if rows else None})
    for label, cutoff in (("historical", datetime.fromisoformat(plan["public_cutoffs_local"][-1])),
                          ("ingested", datetime.fromisoformat(run["finished_at"])+timedelta(seconds=1))):
        request = make_request(plan, run, cutoff, PITMode.SYSTEM)
        binding = request.bindings[1]
        rows = svc.query(request.data_request(binding), QueryContext(access, binding.snapshot, request.as_of, request.mode)).records
        request = replace(request, objective="event_review", event_record_id=rows[0].record_id if rows else "0"*64)
        cases.append({"id":"system-"+label, "request":request.to_dict(),
                      "expected_anchor":"verified" if rows else "insufficient",
                      "expected_values":{m.name:str(m.value) for m in rows[0].metrics if m.value is not None} if rows else {},
                      "expected_release_date":rows[0].release_date.isoformat() if rows else None})
    write(path, {"kind":"real_qualified_date_anchor_offline", "scope":access.scope, "cases":cases,
                 "source_run_sha256":hashlib.sha256((ROOT/"run.json").read_bytes()).hexdigest(),
                 "qualification_sha256":plan["qualification_sha256"], "provider_network_calls":0,
                 "market_records_available":False, "causal_truth_certified":False})
    print(json.dumps({"prepared_event_cases":len(cases)}))


def evaluate(path, output):
    corpus = json.loads(path.read_bytes())
    plan, run, svc, access = inputs()
    assert hashlib.sha256((ROOT/"run.json").read_bytes()).hexdigest() == corpus["source_run_sha256"]
    assert plan["qualification_sha256"] == corpus["qualification_sha256"]
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for case in corpus["cases"]:
        request = StudyRequest.from_dict(case["request"])
        runtime = StudyRuntime(svc, CheckpointStore(output/"runs"))
        report = runtime.run(request, access)
        actual = {c["name"].removeprefix("financial_income."):c["value"] for c in report["facts"]}
        checks = {"values":actual==case["expected_values"], "anchor_status":report["event_anchor"]["status"]==case["expected_anchor"],
                  "missing_prices_not_invented":not any(c["name"].startswith("event_") for c in report["facts"]),
                  "chronology_insufficient":report["hypotheses"][0]["status"]=="insufficient",
                  "partial":report["status"]=="partial", "verified":report["verification"]["status"]=="verified"}
        if case["expected_release_date"]:
            checks["release_date"] = report["event_anchor"]["release_date"] == case["expected_release_date"]
            checks["precision"] = report["event_anchor"]["precision"] == "date_conservative_next_day"
        checks["identical_replay"] = runtime.run(request, access, resume=report["run_id"]) == report
        try:
            runtime.run(request, AccessContext(access.scope, frozenset({"tushare"})), resume=report["run_id"])
        except PermissionDenied:
            checks["revoked_source_denied"] = True
        else:
            checks["revoked_source_denied"] = False
        write(output/(case["id"]+".json"), report)
        (output/(case["id"]+".md")).write_text(markdown(report), encoding="utf-8")
        results.append({"case":case["id"], "passed":all(checks.values()), "checks":checks,
                        "report_hash":digest(report), "numeric_claims":len(report["facts"]),
                        "evidence":len(report["evidence"]), "qualified_anchor":report["event_anchor"]["status"]=="verified"})
    result = {"kind":corpus["kind"], "corpus_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
              "tasks_total":len(results), "tasks_passed":sum(r["passed"] for r in results),
              "qualified_anchor_checks":sum(r["qualified_anchor"] for r in results),
              "numeric_claims":sum(r["numeric_claims"] for r in results), "evidence":sum(r["evidence"] for r in results),
              "event_price_series_missing":True, "causal_truth_certified":False,
              "model_network_calls":0, "financial_provider_network_calls":0, "cases":results}
    write(output/"result.json", result)
    print(json.dumps({k:v for k,v in result.items() if k != "cases"}))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("evaluation/phase3_event_cases_20261002.json"))
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--output", type=Path, default=Path(".artifacts/phase3/event-20261002"))
    args = parser.parse_args()
    if args.prepare:
        prepare(args.corpus)
    else:
        raise SystemExit(evaluate(args.corpus, args.output))
