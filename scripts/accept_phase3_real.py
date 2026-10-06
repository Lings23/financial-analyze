"""Read-only real frozen Phase 3 replay. No external model/provider calls.

Frozen Phase 2 Fraction oracles are reused for unchanged numeric requirements;
new hypothesis status expectations are recorded before Phase 3 execution.
"""
import argparse
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from accept_phase2_real import service, read_inputs, write, RUN, PLAN
from stock_research.errors import PermissionDenied
from stock_research.models import AccessContext, digest
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.context import study_messages
from stock_research.research.report import markdown
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudyRequest, StudySpec


BASE = Path("evaluation/phase2_real_acceptance_20261002.json")


def prepare(path):
    base = json.loads(BASE.read_bytes())
    cases = []
    for item in base["cases"]:
        request = StudyRequest.from_dict(item["request"])
        # These frozen windows contain no previous-year same period, factors,
        # benchmark, cash flow or requested event anchor. Do not invent them.
        assert not {"revenue_yoy", "net_income_parent_yoy"} & set(item["expected"])
        cases.append({**item, "request":request.to_dict(), "expected_status":"partial",
                      "expected_hypotheses":{h:"insufficient" for h in request.hypotheses}})
    write(path, {"kind":"real_frozen_snapshot_bounded_research_offline", "scope":base["scope"],
                 "source_run_sha256":base["source_run_sha256"], "source_plan_sha256":base["source_plan_sha256"],
                 "base_corpus_sha256":hashlib.sha256(BASE.read_bytes()).hexdigest(), "cases":cases,
                 "model":"disabled", "causal_ground_truth":False, "live_model_quality_certified":False})
    print(json.dumps({"prepared_cases":len(cases), "corpus_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}))


def evaluate(path, output):
    corpus = json.loads(path.read_bytes())
    assert hashlib.sha256(BASE.read_bytes()).hexdigest() == corpus["base_corpus_sha256"]
    assert hashlib.sha256(RUN.read_bytes()).hexdigest() == corpus["source_run_sha256"]
    assert hashlib.sha256(PLAN.read_bytes()).hexdigest() == corpus["source_plan_sha256"]
    output.mkdir(parents=True, exist_ok=False)
    svc = service()
    access = AccessContext(corpus["scope"], frozenset({"tushare"}))
    store = CheckpointStore(output/"runs")
    results, numeric_total, evidence_total, hypotheses_total = [], 0, 0, 0
    for case in corpus["cases"]:
        request = StudyRequest.from_dict(case["request"])
        inputs = read_inputs(svc, request, access)
        assert digest({k:[r.to_dict() for r in rows] for k,rows in inputs.items()}) == case["input_hash"]
        report = StudyRuntime(svc, store).run(request, access)
        facts = {c["name"]:c for c in report["facts"]}
        expected = {k:Fraction(*v) for k,v in case["expected"].items()}
        checks = {"numeric_names":set(facts)==set(expected),
                  "numeric_values":all(abs(Fraction(Decimal(facts[k]["value"]))-v)<Fraction(1,10**28) for k,v in expected.items()),
                  "hypotheses":{h["id"]:h["status"] for h in report["hypotheses"]}==case["expected_hypotheses"],
                  "status":report["status"]==case["expected_status"], "verification":report["verification"]["status"]=="verified",
                  "coverage":report["coverage"]=="not_verified", "model_disabled":report["model"]["status"]=="disabled"}
        replay = StudyRuntime(svc, CheckpointStore(output/"runs")).run(request, access, resume=report["run_id"])
        checks["identical_replay"] = replay == report
        try:
            StudyRuntime(svc, store).run(request, AccessContext(access.scope, frozenset({"cninfo"})), resume=report["run_id"])
        except PermissionDenied:
            checks["revocation_denied"] = True
        else:
            checks["revocation_denied"] = False
        records = [r for rows in inputs.values() for r in rows]
        before = min(r.available_at for r in records)-timedelta(microseconds=1)
        early = StudyRuntime(svc, store).run(replace(request, as_of=before), access)
        checks["pre_capture_invisible"] = not early["facts"] and early["status"] == "partial"
        # Preview remains local; preparing it is not a live-model validation.
        messages, view = study_messages(report, request, StudySpec().context_bytes)
        checks["lossless_preview"] = view["facts_included"] == len(facts) and view["omitted_claims"] == 0
        write(output/(case["id"]+".json"), report)
        (output/(case["id"]+".md")).write_text(markdown(report), encoding="utf-8")
        if not results:
            write(output/"example-request.json", request.to_dict())
            write(output/"example-model-messages.json", messages)
        numeric_total += len(expected)
        evidence_total += len(report["evidence"])
        hypotheses_total += len(report["hypotheses"])
        results.append({"case":case["id"], "passed":all(checks.values()), "checks":checks, "report_hash":digest(report)})
    result = {"kind":corpus["kind"], "corpus_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
              "tasks_total":len(results), "tasks_passed":sum(r["passed"] for r in results),
              "numeric_claims_checked":numeric_total, "evidence_checked":evidence_total,
              "hypothesis_status_checks":hypotheses_total, "substantive_supported_hypotheses":0,
              "model_network_calls":0, "financial_provider_network_calls":0,
              "causal_quality_certified":False, "provider_accuracy_certified":False, "live_model_quality_certified":False,
              "cases":results}
    write(output/"result.json", result)
    print(json.dumps({k:v for k,v in result.items() if k != "cases"}))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("evaluation/phase3_real_cases_20261002.json"))
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--output", type=Path, default=Path(".artifacts/phase3/real-20261002"))
    args = parser.parse_args()
    if args.prepare:
        prepare(args.corpus)
    else:
        raise SystemExit(evaluate(args.corpus, args.output))
