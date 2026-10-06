"""Transparent QA correction without changing the frozen baseline or Agent.

The raw duplicate defect was discovered by source-only preflight before reviewing
Agent outputs. A source revision is a logical complete-row identity, not a unique
physical position in a provider response. Exact identical copies add no ambiguity.
Four official before-restatement cells use the pre-dispatch independent PDF audit
selectors, re-extracting bytes rather than copying its financial values/verdicts.
"""
import argparse
from collections import Counter
import copy
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import re

import phase3_benchmark_v2_oracle as oracle


MONEY = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+\.\d+")


def wrapped_row(text, label, count):
    lines = text.splitlines()
    matches = []
    for pos, line in enumerate(lines):
        if not oracle.compact(line).startswith(label[:8]):
            continue
        block = [line]
        for following in lines[pos + 1:pos + 4]:
            chinese = re.sub(r"[^\u4e00-\u9fff]", "", "".join(block))
            if len(MONEY.findall(" ".join(block))) >= count and label in chinese:
                break
            block.append(following)
        excerpt = " | ".join(block)
        if label in re.sub(r"[^\u4e00-\u9fff]", "", "".join(block)) and len(MONEY.findall(excerpt)) == count:
            matches.append((excerpt, [F(token.replace(",", "")) for token in MONEY.findall(excerpt)]))
    if len(matches) != 1:
        raise ValueError("official wrapped full label and physical money count are not unique")
    return matches[0]


def reextract_bridge(pdf, symbol, field, ref):
    path, sha = ref["path"], ref["sha256"]
    company = "浙江帕瓦新能源股份有限公司" if symbol == "688184" else "安徽佳先功能助剂股份有限公司"
    cover = oracle.compact(pdf.text(path, 1, sha))
    interval = oracle.compact(pdf.text(path, 5, sha))
    summary = pdf.text(path, 8, sha)
    checks = {"official_company_security_identity": company in cover and symbol in cover,
        "official_current_report_2025_h1": "2025年半年度报告" in cover,
        "official_reporting_interval": "报告期指2025年1月1日至2025年6月30日" in interval,
        "official_prior_same_period_label": "上年同期" in oracle.compact(summary),
        "official_unit_yuan": "单位：元" in oracle.compact(summary)}
    summary_label = "营业收入" if field == "revenue" else "归属于上市公司股东的净利润"
    detail_label = "营业收入" if field == "revenue" else "归属于母公司所有者的净利润"
    if symbol == "688184":
        explanation = oracle.compact(pdf.text(path, 177, sha))
        header = pdf.text(path, 178, sha).split("对合并利润表的影响", 1)[1]
        body = header if field == "revenue" else pdf.text(path, 179, sha).split("对母公司利润表的影响", 1)[0]
        summary_row, sv = wrapped_row(summary, summary_label, 4)
        detail_row, dv = wrapped_row(body, detail_label, 3)
        checks.update(official_current_prior_halfyear_columns="（1－6月）调整后调整前" in oracle.compact(summary),
            official_prior_2024_h1_explicit="2024年半年度财务报表" in explanation,
            official_restatement_explicit="追溯重述法" in explanation,
            official_before_delta_after_header="调整前金额调整金额调整后金额" in oracle.compact(header),
            official_adjustment_arithmetic=dv[0] + dv[1] == dv[2],
            official_summary_matches_both_bridge_ends=sv[2] == dv[0] and sv[1] == dv[2])
        detail = {"summary_page": 8, "period_definition_page": 5, "explanation_page": 177,
            "header_page": 178, "pdf_page": 178 if field == "revenue" else 179,
            "column": "first detailed before amount; third summary before amount",
            "before_fraction": oracle.fraction_json(dv[0]), "adjustment_fraction": oracle.fraction_json(dv[1]),
            "after_fraction": oracle.fraction_json(dv[2])}
    else:
        header = oracle.compact(pdf.text(path, 9, sha))
        explanation = oracle.compact(pdf.text(path, 11, sha))
        body = pdf.text(path, 10, sha)
        summary_row, sv = wrapped_row(summary, summary_label, 3)
        detail_row, dv = wrapped_row(body, detail_label, 2)
        checks.update(official_prior_before_after_headers=all(word in header for word in ("单位：元", "上年期末（上年同期）", "调整重述前", "调整重述后")),
            official_same_control_restatement=all(word in explanation for word in ("同一控制下企业合并", "上年同期数", "重述", "纳入合并报表")),
            official_summary_matches_adjusted_prior=sv[1] == dv[1])
        detail = {"summary_page": 8, "period_definition_page": 5, "explanation_page": 11,
            "header_page": 9, "pdf_page": 10, "column": "first before-restatement physical amount; two later columns blank",
            "before_fraction": oracle.fraction_json(dv[0]), "adjustment_fraction": oracle.fraction_json(dv[1] - dv[0]),
            "after_fraction": oracle.fraction_json(dv[1])}
    return checks, {**detail, "source_ref": ref, "summary_row_excerpt": summary_row, "row_excerpt": detail_row,
                    "source_version_basis": "printed_2024H1_before_restatement_version; latest_restated_comparability_not_asserted"}


def recompute_task(task, corrected_evidence):
    result = copy.deepcopy(task)
    for ev in result["evidence_checks"]:
        if ev["evidence_id"] in corrected_evidence:
            ev["baseline_strict_physical_occurrence_checks"] = copy.deepcopy(ev["checks"])
            ev["baseline_supported"] = ev["supported"]
            ev["checks"]["exact_original_source_revision"] = True
            ev["supplemental_logical_revision_proof"] = corrected_evidence[ev["evidence_id"]]
            ev["supported"] = all(ev["checks"].values())
            ev["failure_category"] = [name for name, passed in ev["checks"].items() if not passed]
            ev["reasoning_summary"] = "Original strict physical count retained; identical complete-row hashes establish one unambiguous logical source revision."
    ev_supported = {ev["evidence_id"]: ev["supported"] is True for ev in result["evidence_checks"]}
    fact_supported = {}
    for unit in result["units"]:
        if unit["unit_type"] != "numeric_claim":
            continue
        baseline = copy.deepcopy(unit["checks"])
        if "all_original_source_inputs_supported" in unit["checks"]:
            unit["checks"]["all_original_source_inputs_supported"] = all(ev_supported.get(eid, False) for eid in unit["oracle"]["inputs"])
        if baseline != unit["checks"]:
            unit["baseline_checks"] = baseline
            unit["baseline_supported"] = unit["supported"]
        unit["supported"] = all(unit["checks"].values())
        unit["failure_category"] = [name for name, passed in unit["checks"].items() if not passed]
        fact_supported[unit["name"]] = unit["supported"]
    for unit in result["units"]:
        if unit["unit_type"] == "hypothesis_state":
            baseline = copy.deepcopy(unit["checks"])
            if unit.get("expected_hypothesis") is not None and "all_claims_independently_supported" in unit["checks"]:
                unit["checks"]["all_claims_independently_supported"] = all(fact_supported.get(name, False) for name in unit["expected_hypothesis"]["claim_names"])
            if baseline != unit["checks"]:
                unit["baseline_checks"] = baseline
                unit["baseline_supported"] = unit["supported"]
            unit["supported"] = all(unit["checks"].values())
            unit["failure_category"] = [name for name, passed in unit["checks"].items() if not passed]
    hs = [unit for unit in result["units"] if unit["unit_type"] == "hypothesis_state"]
    checks = result["required_completion"]["checks"]
    result["required_completion"]["baseline_checks"] = copy.deepcopy(checks)
    checks["complete_independent_fact_set"] = (not result["required_completion"]["missing_computable_fact_names"]
        and all(fact_supported.values()))
    checks["complete_independent_evidence_set"] = all(ev_supported.values()) and checks["complete_independent_evidence_set"] or (
        all(ev_supported.values()) and all(ev["checks"].get("expected_evidence_present") is True
            and ev["checks"].get("exact_source_evidence_fields") is True for ev in result["evidence_checks"]))
    checks["all_required_hypotheses_correct"] = len(hs) == len(result["expected_hypotheses"]) and all(unit["supported"] is True for unit in hs)
    # Mandatory-name presence remains independently pinned by the frozen case.
    result["required_completion"]["correct_required_checks"] = sum(unit["supported"] is True for unit in hs)
    result["required_completion"]["decisive_correct_checks"] = sum(unit["supported"] is True and unit["expected_hypothesis"]["status"] != "insufficient" for unit in hs if unit["expected_hypothesis"])
    result["required_completion"]["completed"] = all(checks.values())
    result["deterministic_success_candidate"] = all(checks.values())
    for unit in result["units"]:
        if unit["supported"] and unit.get("baseline_supported") is False:
            unit["reasoning_summary"] = "Frozen arithmetic/status checks unchanged; independent identical-copy source proof resolves the baseline physical-occurrence QA defect."
    return result


def run(manifest_path, baseline_dir, outdir):
    reader = oracle.Reader()
    manifest_path, baseline_dir, outdir = (reader.path(path) for path in (manifest_path, baseline_dir, outdir))
    outputs = [outdir / name for name in ("ORACLE_CORRECTION_PROTOCOL.json", "source-duplicate-proofs.json", "deterministic-review.json", "official-coverage.json")]
    if any(path.exists() for path in outputs):
        raise FileExistsError("refusing to overwrite a transparent correction")
    manifest = reader.json(manifest_path)
    baseline = reader.json(baseline_dir / "deterministic-review.json")
    coverage = reader.json(baseline_dir / "official-coverage.json")
    if baseline["manifest_sha256"] != reader.reads[manifest_path.relative_to(reader.root).as_posix()]:
        raise ValueError("baseline and immutable manifest differ")
    expected_frozen_sha = "ea6181ab3b68d54d0ef65844c74019b58f14231cfaf55c7c8b9517280fe0ef61"
    if hashlib.sha256(Path(oracle.__file__).read_bytes()).hexdigest() != expected_frozen_sha:
        raise ValueError("frozen baseline oracle has changed")
    outdir.mkdir(parents=True, exist_ok=True)
    protocol = {"schema": "independent-oracle-correction-protocol-v2/1", "manifest_sha256": baseline["manifest_sha256"],
        "frozen_baseline_oracle_sha256": expected_frozen_sha,
        "supplement_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_only_discovery": {"path": ".artifacts/phase3/benchmark-v2-20261004/source-oracle-preflight-bundled/source-review.json",
            "sha256": "c62ba778570ec13b1c8fd10e10002bbfcdfd395074fc3629cc6095edac9d14f5",
            "Agent_reports_read": 0, "model_calls": 0},
        "official_locator_audit_before_dispatch": {"script_sha256": "e4ddcc846bb477a77b25504848f1fdfc3fe4a5ac6f13a535836c554c9a74541c",
            "path": ".artifacts/phase3/benchmark-v2-20261004-oracle-planning/official_bridge_audit.py"},
        "correction": "At least one exact complete-row revision match and all matching rows fully identical establish one unambiguous logical revision. Different complete rows, field values, identities or hashes remain unsupported.",
        "official_correction": "Four known printed before-restatement bridges use the pre-dispatch independent wrapped full-label/exact physical-money-count selectors and re-extract original bytes; all other official NAs preserved.",
        "unchanged": ["immutable Agent reports and one-attempt model receipts", "38 frozen cases and expectations", "Fraction formulas and all hypothesis test rules", "cutoff, mode, scopes and full snapshot hashes", "success thresholds and denominators", "baseline strict QA outputs"],
        "no_model_or_provider_calls": True, "original_scores_rewritten": False}
    oracle.write_new(outputs[0], protocol)
    task_map = {task["case_id"]: task for task in baseline["tasks"]}
    pdf = oracle.OfficialPDF(reader)
    proofs, final_tasks = [], []
    official_patches = {}
    try:
        for case in manifest["cases"]:
            frozen = reader.json(case["input_path"], case["input_sha256"])
            selected, bindings, checks = oracle.select_inputs(case, frozen)
            facts, evidence, anchor, event, pair = oracle.expected_facts(selected, bindings, case["request"])
            if not all(checks.values()) or facts != task_map[case["id"]]["expected_facts"]:
                raise ValueError("immutable independent input selection/arithmetic changed")
            records = {oracle.rid(row): row for rows in selected.values() for row in rows}
            corrected = {}
            for old in task_map[case["id"]]["evidence_checks"]:
                if old["checks"].get("exact_original_source_revision") is not False:
                    continue
                eid, ev = old["evidence_id"], evidence[old["evidence_id"]]
                record = records[ev["record_id"]]
                aid = record["artifact_id"]
                path = frozen["artifact_paths"][aid]
                archive = reader.json(path, aid)
                rows = [row if isinstance(row, dict) else dict(zip(archive["fields"], row)) for row in archive["items"]]
                matching = [(index, row) for index, row in enumerate(rows) if oracle.digest(row) == ev["revision_id"]]
                field = oracle.RAW_FIELDS.get(ev["metric"], ev["metric"])
                proof_checks = {"original_archive_hash_checked": True, "matching_logical_revision_present": bool(matching),
                    "all_matching_complete_rows_identical": bool(matching) and all(row == matching[0][1] for _, row in matching),
                    "all_matching_complete_row_hashes_equal_revision": bool(matching) and all(oracle.digest(row) == ev["revision_id"] for _, row in matching),
                    "all_matching_original_fields_equal_expected_raw": bool(matching) and all(field in row and oracle.equivalent(row[field], ev["raw_value"]) for _, row in matching),
                    "remaining_frozen_source_checks_unchanged_and_supported": all(passed for name, passed in old["checks"].items() if name != "exact_original_source_revision")}
                proof = {"case_id": case["id"], "evidence_id": eid, "metric": ev["metric"], "period": ev["period"],
                    "source_revision": ev["revision_id"], "source_ref": {"path": path, "sha256": aid},
                    "physical_matching_row_count": len(matching), "matching_row_indices": [index for index, _ in matching],
                    "logical_complete_row_hashes": sorted({oracle.digest(row) for _, row in matching}),
                    "checks": proof_checks, "supported": all(proof_checks.values())}
                proofs.append(proof)
                if proof["supported"]:
                    corrected[eid] = proof
            final = recompute_task(task_map[case["id"]], corrected)
            completion = final["required_completion"]["checks"]
            fact_ok = {u["name"]: u["supported"] is True for u in final["units"] if u["unit_type"] == "numeric_claim"}
            completion["mandatory_fact_names_present_and_supported"] = all(fact_ok.get(name, False) for name in case["expected_behavior"]["mandatory_fact_names"])
            final["required_completion"]["completed"] = final["deterministic_success_candidate"] = all(completion.values())
            final_tasks.append(final)
            for ev in evidence.values():
                symbol = case["request"]["symbol"]
                field = ev["metric"]
                if symbol not in {"688184", "920489"} or ev["period"] != "2024-06-30" or field not in {"revenue", "net_income_parent"}:
                    continue
                key = symbol, case["request"]["exchange"], ev["period"], field, ev["revision_id"]
                if key in official_patches:
                    continue
                ref = pdf.locators[(symbol, case["request"]["exchange"], "2025-06-30", field)]["source"]
                bridge_checks, detail = reextract_bridge(pdf, symbol, field, {k: ref[k] for k in ("path", "sha256", "source_url")})
                exact = F(*detail["before_fraction"])
                bridge_checks["source_value_equals_printed_before_amount"] = abs(oracle.number(ev["value"]) - exact) <= F(1, 200)
                official_patches[key] = {"security": symbol, "exchange": key[1], "period": ev["period"], "metric": field,
                    "source_revision": ev["revision_id"], "assessable": all(passed for name, passed in bridge_checks.items() if name != "source_value_equals_printed_before_amount"),
                    "supported": all(bridge_checks.values()), "reason": "independent_pre_dispatch_printed_before_restatement_bridge_reextracted",
                    "checks": bridge_checks, "official_fraction": detail["before_fraction"], "tolerance_fraction": [1, 200],
                    "provider_value": ev["value"], **detail}
    finally:
        pdf.close()
    final_coverage = copy.deepcopy(coverage)
    for index, item in enumerate(final_coverage["checks"]):
        key = item["security"], item["exchange"], item["period"], item["metric"], item["source_revision"]
        if key in official_patches:
            final_coverage["checks"][index] = {**official_patches[key], "baseline_not_assessable_reason": item["reason"]}
    cells = final_coverage["checks"]
    final_coverage["schema"] = "independent-official-coverage-v2/1+transparent-supplement"
    final_coverage["summary"] = {"distinct_source_revision_cells": len(cells), "assessable": sum(row["assessable"] is True for row in cells),
        "supported": sum(row["supported"] is True for row in cells), "contradicted": sum(row["supported"] is False for row in cells),
        "not_assessable": sum(row["assessable"] is False for row in cells)}
    final_coverage["supplemental_pdf_page_extractions"] = [{"path": str(Path(path).relative_to(reader.root)), "page": page, "text": text} for (path, page), text in sorted(pdf.pages.items())]
    result = copy.deepcopy(baseline)
    result["schema"] += "+transparent-logical-revision-supplement"
    result["tasks"] = final_tasks
    units = [unit for task in final_tasks for unit in task["units"]]
    result["baseline_summary"] = baseline["summary"]
    result["summary"] = {"tasks": len(final_tasks), "units": len(units), "source_assessable_units": sum(unit["assessable"] is True for unit in units),
        "supported_units": sum(unit["supported"] is True for unit in units), "hallucinated_units": sum(unit["hallucination"] is True for unit in units),
        "deterministic_success_candidates": sum(task["deterministic_success_candidate"] for task in final_tasks),
        "required_checks": sum(task["required_completion"]["required_checks"] for task in final_tasks),
        "correct_required_checks": sum(task["required_completion"]["correct_required_checks"] for task in final_tasks),
        "decisive_required_checks": sum(task["required_completion"]["decisive_required_checks"] for task in final_tasks),
        "decisive_correct_checks": sum(task["required_completion"]["decisive_correct_checks"] for task in final_tasks),
        "failures": dict(Counter(name for unit in units for name in unit["failure_category"]))}
    result["correction_protocol"] = protocol
    result["supplemental_input_sha256"] = reader.reads
    result["baseline_directory_preserved"] = baseline_dir.relative_to(reader.root).as_posix()
    oracle.write_new(outputs[1], {"schema": "independent-identical-raw-copy-proofs/v1", "source_only_rule": True,
        "proofs": proofs, "summary": {"evidence_uses": len(proofs), "supported": sum(proof["supported"] for proof in proofs),
            "distinct_case_ids": len({proof["case_id"] for proof in proofs}),
            "physical_matching_counts": dict(Counter(proof["physical_matching_row_count"] for proof in proofs))}})
    oracle.write_new(outputs[2], result)
    oracle.write_new(outputs[3], final_coverage)
    return result, final_coverage


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("baseline_dir")
    parser.add_argument("outdir")
    args = parser.parse_args()
    result, coverage = run(args.manifest, args.baseline_dir, args.outdir)
    print(json.dumps({"deterministic": result["summary"], "official": coverage["summary"]}, ensure_ascii=False))
