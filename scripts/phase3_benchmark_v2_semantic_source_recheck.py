"""Read-only reproducible source recheck accompanying the manual semantic Judge.

This has no semantic-pass algorithm, production imports, network or model calls.
It independently rehashes original full rows and frozen bytes, and establishes
whether the disclosed physical-duplicate QA correction changes any test formula.
"""
import hashlib
import json
from fractions import Fraction
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / ".artifacts/phase3/benchmark-v2-20261004"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def equivalent(left, right):
    if left is None or right is None:
        return left is None and right is None
    try:
        return Fraction(str(left)) == Fraction(str(right))
    except (ValueError, ZeroDivisionError):
        return left == right


def run():
    final = read(PACK / "independent-oracle/deterministic-review.json")
    baseline = read(PACK / "independent-oracle-baseline/deterministic-review.json")
    declared = read(PACK / "independent-oracle/source-duplicate-proofs.json")
    inventory = read(PACK / "markdown-audit-inventory.json")
    manifest = read(PACK / "benchmark-manifest.json")
    baseline_tasks = {t["case_id"]: t for t in baseline["tasks"]}
    final_tasks = {t["case_id"]: t for t in final["tasks"]}
    checks = {
        "frozen_manifest_sha256": sha(PACK / "benchmark-manifest.json") ==
            "2080aaff734db11a0b8a027be99a5bd6e36b4b3f36f82c9b283b97a7c369ab7a",
        "preregistered_protocol_sha256": sha(PACK / "SEMANTIC_JUDGE_PROTOCOL.md") ==
            "be04d92724cf0374577b8040cc43df1743a4505b3c78130fa94c1a483186cead",
        "preregistered_markdown_audit_script_sha256": sha(ROOT / "scripts/phase3_benchmark_v2_markdown_audit.py") ==
            "11d04f1164722a0aec3505b99c423492f51473edc389539bdf31a0240bf2410c",
        "same_38_case_set": set(baseline_tasks) == set(final_tasks) ==
            {c["case_id"] for c in manifest["cases"]} == {t["case_id"] for t in inventory["tasks"]}
            and len(final_tasks) == 38,
        "same_complete_unit_set": all({u["unit_id"] for u in t["units"]} ==
            {u["unit_id"] for u in baseline_tasks[cid]["units"]} for cid, t in final_tasks.items()),
        "same_expected_fact_values_formulas_and_inputs": all(t["expected_facts"] ==
            baseline_tasks[cid]["expected_facts"] for cid, t in final_tasks.items()),
        "same_expected_hypotheses_rules_states_and_counterevidence": all(t["expected_hypotheses"] ==
            baseline_tasks[cid]["expected_hypotheses"] for cid, t in final_tasks.items()),
        "all_declared_original_bytes_still_match": all(sha(ROOT / name) == expected
            for name, expected in final["source_hashes"].items()),
        "all_case_input_hashes_match": all(sha(ROOT / c["input_path"]) == c["input_sha256"]
            for c in manifest["cases"]),
        "all_38_original_markdowns_and_reports_match": all(
            sha(ROOT / t["markdown_path"]) == t["markdown_sha256"] and
            sha(ROOT / t["report_path"]) == t["report_sha256"] and
            len((ROOT / t["markdown_path"]).read_text(encoding="utf-8").splitlines()) == t["line_count"]
            for t in inventory["tasks"]),
        "all_lines_preserved_in_inventory": all(
            (ROOT / t["markdown_path"]).read_text(encoding="utf-8").splitlines() ==
            [line["text"] for line in t["lines"]] for t in inventory["tasks"]),
    }
    raw_fields = {"net_income_parent": "n_income_attr_p", "revenue": "revenue", "total_revenue": "total_revenue"}
    proofs = []
    for proof in declared["proofs"]:
        src = proof["source_ref"]
        archive = read(ROOT / src["path"])
        fields = archive["fields"]
        rows = [row if isinstance(row, dict) else dict(zip(fields, row)) for row in archive["items"]]
        matches = [(i, row) for i, row in enumerate(rows) if canonical_sha(row) == proof["source_revision"]]
        ev = next(e for e in final_tasks[proof["case_id"]]["evidence_checks"] if e["evidence_id"] == proof["evidence_id"])
        expected = ev["expected_evidence"]
        raw_field = raw_fields[proof["metric"]]
        row_checks = {
            "original_archive_bytes_match_sha": sha(ROOT / src["path"]) == src["sha256"],
            "physical_matches_are_exactly_declared_indices": [i for i, row in matches] == proof["matching_row_indices"],
            "physical_matches_more_than_one": len(matches) > 1,
            "full_rows_all_identical": bool(matches) and all(row == matches[0][1] for i, row in matches),
            "full_row_hash_equals_original_evidence_revision": proof["source_revision"] == expected["revision_id"],
            "all_original_security_and_periods_match": bool(matches) and all(
                row["ts_code"].split(".")[0] in proof["case_id"] and
                row["end_date"] == proof["period"].replace("-", "") for i, row in matches),
            "all_original_raw_field_values_match": bool(matches) and all(
                equivalent(row[raw_field], expected["raw_value"]) for i, row in matches),
        }
        proofs.append({"case_id": proof["case_id"], "evidence_id": proof["evidence_id"],
            "source_ref": src, "raw_field": raw_field, "physical_indices": [i for i, row in matches],
            "source_revision": proof["source_revision"], "checks": row_checks,
            "verified": all(row_checks.values())})
    checks["all_25_duplicate_evidence_uses_independently_verified"] = len(proofs) == 25 and all(p["verified"] for p in proofs)
    result = {"schema": "semantic-source-recheck-v2/1", "method": "Independent stdlib-only bytes/full-row verification; no semantic pass inference.",
        "model_calls": 0, "provider_calls": 0, "production_imports": 0,
        "semantic_pass": None, "checks": checks, "duplicate_proofs": proofs,
        "source_cells_note": "Official source not_assessable cells remain unknown; this recheck does not turn source transformation support into official accuracy.",
        "case_count": len(final_tasks), "markdown_line_count": sum(t["line_count"] for t in inventory["tasks"]),
        "all_checks_satisfied": all(checks.values())}
    output = PACK / "semantic-source-recheck.json"
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"checks": checks, "case_count": len(final_tasks),
        "markdown_line_count": result["markdown_line_count"]}, ensure_ascii=False))
    return result


if __name__ == "__main__":
    if not run()["all_checks_satisfied"]:
        raise SystemExit(1)
