"""Frozen L3/L5 synthetic mechanism benchmark; zero real model/provider calls."""
import argparse
from dataclasses import replace
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tests"))
from research_fixtures import BundleFixtureModel, fixture
from study_fixtures import add_domain, study_request, with_event
from stock_research.models import digest
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.report import markdown
from stock_research.research.study import StudyRuntime


def build(f, case):
    profile = case["profile"]
    request = study_request(f, hypotheses=(case["hypothesis"],))
    if profile in {"decline", "conflict", "zero_base"}:
        records = list(f.repo.read(f.access.scope, request.bindings[0].snapshot))
        changed = []
        for record in records:
            if record.dataset.value == "financial_income":
                current = record.period.year == 2024
                amounts = ({"revenue": "50", "total_revenue": "50", "net_income_parent": "5"}
                           if profile == "decline" and current else
                           {"net_income_parent": "5"} if profile == "conflict" and current else
                           {"revenue": "0", "total_revenue": "0"} if profile == "zero_base" and not current else {})
                record = replace(record, metrics=tuple(replace(m, value=Decimal(amounts[m.name]), raw_value=amounts[m.name])
                                 if m.name in amounts else m for m in record.metrics))
            changed.append(record)
        sid = f.repo.commit(f.access.scope, changed).snapshot_id
        request = replace(request, bindings=tuple(replace(b, snapshot=sid) for b in request.bindings))
    elif profile == "no_prior":
        request = replace(request, bindings=tuple(replace(b, start=date(2024,12,31))
                          if b.dataset == "financial_income" else b for b in request.bindings))
    elif profile.startswith("cash_"):
        request, _ = add_domain(f, request, "financial_cashflow", values={"operating_cashflow": "1" if profile == "cash_positive" else "-1"},
                                periods=[date(2024,6,30)] if profile == "cash_mismatch" else None)
    elif profile.startswith("benchmark_"):
        values = ["100","110","120"] if profile == "benchmark_opposite" else ["100","90","80"]
        if profile == "benchmark_mismatch":
            values = ["100","80"]
        request, _ = add_domain(f, request, "index_daily", values={"close": values},
                               periods=[date(2025,4,1),date(2025,4,3)] if profile == "benchmark_mismatch" else None)
    elif profile.startswith("factor_"):
        request, _ = add_domain(f, request, "adjustment_factor", values={"factor": ["1","1","2"] if profile == "factor_change" else ["2","2","2"]})
    elif profile.startswith("event_"):
        request, _ = with_event(f, date_only=profile == "event_date", observed=profile == "event_observed")
        if profile == "event_hidden":
            request = replace(request, event_record_id="0"*64)
    return request


def evaluate(corpus_path, output):
    raw = corpus_path.read_bytes()
    corpus = json.loads(raw)
    output.mkdir(parents=True, exist_ok=False)
    results, numeric_total, evidence_total, hypothesis_total = [], 0, 0, 0
    for case in corpus["cases"]:
        with TemporaryDirectory() as directory:
            f = fixture(Path(directory), prices=case.get("prices", corpus["default_prices"]))
            request = build(f, case)
            model = BundleFixtureModel()  # Synthetic protocol stub only; not a model-quality score.
            report = StudyRuntime(f.service, f.store, model).run(request, f.access)
            facts = {c["name"]: c for c in report["facts"]}
            checks = {"hypothesis_status": report["hypotheses"][0]["status"] == case["expected"],
                      "verified": report["verification"]["status"] == "verified",
                      "model_fixture_verified": report["model"]["status"] == "verified",
                      "causal_claims_absent": report["synthesis"]["causal_conclusion"] == "not_established",
                      "nonempty_facts": bool(facts), "rendered_hypothesis": "假设检验与综合" in markdown(report)}
            for name, expected in (("observed_price_change", case.get("price_change", corpus["default_price_change"])),
                                   ("observed_max_drawdown", case.get("drawdown", corpus["default_drawdown"]))):
                checks[name] = name not in facts if expected is None else name in facts and Decimal(facts[name]["value"]) == Decimal(expected)
                numeric_total += expected is not None
            if "event_change" in case:
                expected = case["event_change"]
                checks["event_arithmetic"] = "event_observed_price_change" not in facts if expected is None else (
                    "event_observed_price_change" in facts and Decimal(facts["event_observed_price_change"]["value"]) == Decimal(expected))
                numeric_total += expected is not None
            replay = StudyRuntime(f.service, CheckpointStore(f.store.root), model).run(request, f.access, resume=report["run_id"])
            checks["exact_replay"] = replay == report and model.calls == 1
            evidence_total += len(report["evidence"])
            hypothesis_total += len(report["hypotheses"])
            result = {"id":case["id"], "level":case["level"], "passed":all(checks.values()), "checks":checks,
                      "research_status":report["research_status"], "report_hash":digest(report)}
            results.append(result)
            (output/(case["id"]+".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {"kind":corpus["kind"], "corpus_sha256":hashlib.sha256(raw).hexdigest(),
              "tasks_total":len(results), "tasks_passed":sum(r["passed"] for r in results),
              "levels":{level:{"total":sum(r["level"]==level for r in results),
                                "passed":sum(r["level"]==level and r["passed"] for r in results)} for level in ("L3","L5")},
              "preregistered_numeric_checks":numeric_total, "evidence_bound_checks":evidence_total,
              "hypothesis_status_checks":hypothesis_total, "model_network_calls":0, "financial_provider_network_calls":0,
              "real_financial_truth_certified":False, "live_model_quality_certified":False, "cases":results}
    (output/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k != "cases"}))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("evaluation/phase3_cases.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(evaluate(args.corpus, args.output))
