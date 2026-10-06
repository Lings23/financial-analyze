"""Frozen synthetic L1/L2 mechanisms; no financial API calls and no live-model claims."""
import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from research_fixtures import FixtureModel, fixture
from stock_research.research.runtime import ResearchRuntime


def evaluate():
    path = Path(__file__).resolve().parents[1] / "evaluation/phase2_cases.json"
    raw = path.read_bytes()
    corpus = json.loads(raw)
    results = []
    calculations, correct, claims, supported = 0, 0, 0, 0
    for case in corpus["cases"]:
        with TemporaryDirectory() as directory:
            f = fixture(Path(directory), prices=case["prices"])
            model = FixtureModel()
            report = ResearchRuntime(f.service, f.store, model).run(f.request, f.access)
            facts = {v["name"]: v for v in report["facts"]}
            checks = []
            for name, expected in (("observed_price_change", case["change"]),
                                   ("observed_max_drawdown", case["drawdown"]),
                                   ("revenue_yoy", "0.25"), ("financial_income.revenue", "100")):
                ok = name not in facts if expected is None else (name in facts and
                     abs(Decimal(facts[name]["value"]) - Decimal(expected)) <= Decimal(corpus["tolerance"]))
                calculations += expected is not None
                correct += expected is not None and ok
                checks.append(ok)
            expected_status = "partial" if case["change"] is None else "completed"
            checks.extend((report["status"] == expected_status, report["model"]["status"] == "verified"))
            for claim in report["facts"]:
                claims += 1
                supported += bool(claim["inputs"]) and all(i in report["evidence"] and
                              report["evidence"][i]["value"] is not None and report["evidence"][i]["artifact_ids"]
                              for i in claim["inputs"])
            results.append({"case": case["id"], "passed": all(checks), "status": report["status"]})
    return {"suite": corpus["version"], "case_file_sha256": hashlib.sha256(raw).hexdigest(),
            "kind": "synthetic_mechanism", "model": "fixture; no live LLM", "real_financial_validation": False,
            "tasks_passed": sum(r["passed"] for r in results), "tasks_total": len(results),
            "numeric_checks_correct": correct, "numeric_checks_total": calculations,
            "claims_with_lineage": supported, "numeric_claims_total": claims, "cases": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = evaluate()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}))
    raise SystemExit(0 if result["tasks_passed"] == result["tasks_total"] and result["numeric_checks_correct"] == result["numeric_checks_total"] and result["claims_with_lineage"] == result["numeric_claims_total"] else 1)
