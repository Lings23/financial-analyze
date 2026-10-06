"""Verify immutable independent review coherence and exact numeric-input coverage."""
from collections import Counter
from fractions import Fraction as F
import hashlib
from pathlib import Path
import argparse
import json

import phase3_benchmark_v2_oracle as oracle


def run(directory):
    reader = oracle.Reader()
    directory = reader.path(directory)
    outputs = [directory / name for name in ("verification.json", "official-claim-input-coverage.json")]
    if any(path.exists() for path in outputs):
        raise FileExistsError("refusing to overwrite independent review verification")
    review = reader.json(directory / "deterministic-review.json")
    coverage = reader.json(directory / "official-coverage.json")
    proof = reader.json(directory / "source-duplicate-proofs.json")
    protocol = reader.json(directory / "ORACLE_CORRECTION_PROTOCOL.json")
    baseline_dir = reader.root / review["baseline_directory_preserved"]
    baseline = reader.json(baseline_dir / "deterministic-review.json")
    baseline_coverage = reader.json(baseline_dir / "official-coverage.json")
    checks = {"frozen_baseline_oracle_unchanged": hashlib.sha256(Path(oracle.__file__).read_bytes()).hexdigest() == protocol["frozen_baseline_oracle_sha256"],
        "baseline_same_manifest": baseline["manifest_sha256"] == review["manifest_sha256"] == coverage["manifest_sha256"],
        "baseline_summary_retained": review["baseline_summary"] == baseline["summary"],
        "only_existing_official_cell_keys": {(r["security"], r["exchange"], r["period"], r["metric"], r["source_revision"]) for r in coverage["checks"]}
            == {(r["security"], r["exchange"], r["period"], r["metric"], r["source_revision"]) for r in baseline_coverage["checks"]},
        "all_duplicate_proofs_supported": all(p["supported"] and all(p["checks"].values()) for p in proof["proofs"])}
    for path, sha in {**review["source_hashes"], **review["supplemental_input_sha256"]}.items():
        reader.bytes(path, sha)
    official = {(r["security"], r["exchange"], r["period"], r["metric"], r["source_revision"]): r for r in coverage["checks"]}
    baseline_tasks = {t["case_id"]: t for t in baseline["tasks"]}
    input_coverage = []
    task_checks = []
    for task in review["tasks"]:
        original = baseline_tasks[task["case_id"]]
        checks["expected_facts_unchanged_" + task["case_id"]] = task["expected_facts"] == original["expected_facts"]
        checks["expected_hypotheses_unchanged_" + task["case_id"]] = task["expected_hypotheses"] == original["expected_hypotheses"]
        checks["same_unit_occurrences_" + task["case_id"]] = [u["unit_id"] for u in task["units"]] == [u["unit_id"] for u in original["units"]]
        checks["input_checks_unchanged_" + task["case_id"]] = task["input_checks"] == original["input_checks"]
        evs = {ev["evidence_id"]: ev for ev in task["evidence_checks"]}
        source = next(iter(evs.values()))["expected_evidence"]
        request_path = next(path for path in review["source_hashes"] if path.endswith("/inputs/" + task["case_id"] + ".json"))
        frozen = reader.json(request_path, review["source_hashes"][request_path])
        request = frozen["request"]
        supported_facts = {}
        for unit in task["units"]:
            checks["unit_support_equals_all_checks_" + task["case_id"] + "_" + unit["unit_id"]] = unit["supported"] == all(unit["checks"].values())
            if unit["unit_type"] != "numeric_claim":
                continue
            supported_facts[unit["name"]] = unit["supported"] is True
            inputs = []
            for eid in unit["oracle"]["inputs"]:
                ev = evs[eid]["expected_evidence"]
                ref = official.get((request["symbol"], request["exchange"], ev["period"], ev["metric"], ev["revision_id"]))
                inputs.append({"evidence_id": eid, "period": ev["period"], "metric": ev["metric"],
                    "source_revision": ev["revision_id"], "official_assessable": ref is not None and ref["assessable"] is True,
                    "official_supported": None if ref is None else ref["supported"],
                    "reason": "no_independent_official_cell_for_this_exact_source_input" if ref is None else ref["reason"]})
            assessable = all(item["official_assessable"] for item in inputs)
            supported = all(item["official_supported"] is True for item in inputs) if assessable else False if any(item["official_supported"] is False for item in inputs) else None
            input_coverage.append({"case_id": task["case_id"], "claim_id": unit["claim_id"], "name": unit["name"],
                "all_numeric_input_accuracy_assessable": assessable, "all_numeric_input_accuracy_supported": supported,
                "numeric_inputs": inputs})
        for unit in task["units"]:
            if unit["unit_type"] == "hypothesis_state":
                h = unit["expected_hypothesis"]
                checks["hypothesis_claim_support_coherent_" + task["case_id"] + "_" + unit["hypothesis_id"]] = unit["checks"]["all_claims_independently_supported"] == all(supported_facts.get(name, False) for name in h["claim_names"])
        checks["completion_equals_checks_" + task["case_id"]] = task["deterministic_success_candidate"] == task["required_completion"]["completed"] == all(task["required_completion"]["checks"].values())
    units = [u for task in review["tasks"] for u in task["units"]]
    checks["summary_counts_coherent"] = (review["summary"]["units"] == len(units)
        and review["summary"]["supported_units"] == sum(u["supported"] is True for u in units)
        and review["summary"]["deterministic_success_candidates"] == sum(t["deterministic_success_candidate"] for t in review["tasks"]))
    summary = {"claim_occurrences": len(input_coverage), "all_numeric_input_accuracy_assessable": sum(row["all_numeric_input_accuracy_assessable"] for row in input_coverage),
        "all_numeric_input_accuracy_supported": sum(row["all_numeric_input_accuracy_supported"] is True for row in input_coverage),
        "partially_or_fully_not_assessable": sum(row["all_numeric_input_accuracy_assessable"] is False for row in input_coverage),
        "contradicted": sum(row["all_numeric_input_accuracy_supported"] is False for row in input_coverage)}
    oracle.write_new(outputs[0], {"schema": "independent-oracle-coherence-verification/v1", "verified": all(checks.values()),
        "checks": checks, "failures": [name for name, passed in checks.items() if not passed],
        "source_file_hashes_reverified": len({**review["source_hashes"], **review["supplemental_input_sha256"]}),
        "generation_model_calls": 0, "provider_network_calls": 0, "production_imports": 0,
        "verification_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    oracle.write_new(outputs[1], {"schema": "independent-complete-official-numeric-input-coverage/v1", "summary": summary, "claims": input_coverage,
        "source_qualified_transformation_is_not_full_official_accuracy": True})
    return all(checks.values()), summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    args = parser.parse_args()
    verified, summary = run(args.directory)
    print(json.dumps({"verified": verified, "official_claim_input_coverage": summary}, ensure_ascii=False))
