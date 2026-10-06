"""Offline source-only preflight; never reads an Agent report or scores ability.

This wrapper calls the already frozen independent Source/Fraction oracle. It does
not alter the oracle, cases, expected behavior, Agent, or model dispatch protocol.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import phase3_benchmark_v2_oracle as oracle


def run(manifest_path, outdir):
    reader = oracle.Reader()
    manifest_path = reader.path(manifest_path)
    outdir = reader.path(outdir)
    outputs = [outdir / name for name in ("source-review.json", "official-coverage.json")]
    if any(path.exists() for path in outputs):
        raise FileExistsError("refusing to overwrite independent source-only preflight")
    manifest = reader.json(manifest_path)
    if (manifest["schema"] != "phase3-contract-gated-benchmark-v2"
            or oracle.digest(manifest["cases"]) != manifest["candidate_sha256"]
            or oracle.digest(manifest["contract_validation"]) != manifest["contract_validation_sha256"]
            or manifest["contract_validation"]["all_cases_contract_valid"] is not True):
        raise ValueError("whole-batch preregistration freeze required")
    pdf = oracle.OfficialPDF(reader)
    cases = []
    try:
        for case in manifest["cases"]:
            frozen = reader.json(case["input_path"], case["input_sha256"])
            for path, sha in case["source_hashes"].items():
                reader.bytes(path, sha)
            selected, bindings, checks = oracle.select_inputs(case, frozen)
            facts, evidence, anchor, event_record, pair = oracle.expected_facts(selected, bindings, case["request"])
            expected_hypotheses = oracle.expected_hypotheses(facts, evidence, selected, case["request"], anchor)
            paths = frozen["artifact_paths"]
            raw = {}
            for aid, path in paths.items():
                data = reader.bytes(path, aid)
                if not data.startswith(b"%PDF"):
                    try:
                        raw[aid] = json.loads(data, object_pairs_hook=oracle.unique_object)
                    except (ValueError, UnicodeDecodeError):
                        pass
            for binding in case["request"]["bindings"]:
                owner = case["source_scopes"][binding["dataset"]]
                snapshot = next((item for item in frozen["snapshots"] if item["owner_scope"] == owner and item["snapshot"] == binding["snapshot"]), None)
                if snapshot is not None and not any(row["dataset"] == binding["dataset"] and row["provider"] == binding["provider"] for row in snapshot["records"]):
                    checks.update(oracle.empty_dataset_checks(case, frozen, binding, reader))
            records = {oracle.rid(row): row for rows in selected.values() for row in rows}
            source_units = []
            official_by_evidence = {}
            for eid, ev in sorted(evidence.items()):
                record = records[ev["record_id"]]
                try:
                    source_checks, refs = oracle.raw_source_checks(ev, record, case["request"], raw, paths, pdf)
                    source_units.append({"evidence_id": eid, "record_id": ev["record_id"], "metric": ev["metric"],
                        "assessable": True, "supported": all(source_checks.values()), "checks": source_checks,
                        "source_refs": refs, "source_evidence": ev,
                        "reason": "independent_original_bytes_field_contract" if all(source_checks.values()) else ", ".join(name for name, passed in source_checks.items() if not passed)})
                except (ValueError, KeyError, IndexError, AssertionError, ImportError) as exc:
                    source_units.append({"evidence_id": eid, "record_id": ev["record_id"], "metric": ev["metric"],
                        "assessable": False, "supported": None, "checks": {}, "source_refs": [],
                        "source_evidence": ev, "reason": "not_assessable: " + str(exc)})
                if ev["provider"] == "tushare" and ev["metric"] in {"revenue", "total_revenue", "net_income_parent", "operating_cashflow"}:
                    official_by_evidence[eid] = pdf.check(ev, case["request"])
                elif ev["provider"] == "cninfo" and ev["value"] is not None:
                    result = {"security": case["request"]["symbol"], "exchange": case["request"]["exchange"],
                        "period": ev["period"], "metric": ev["metric"], "source_revision": ev["revision_id"],
                        "assessable": False, "supported": None}
                    try:
                        pc, pr = pdf.qualified_cell(raw[record["artifact_id"]], ev, raw, paths)
                        result.update(assessable=True, supported=all(pc.values()), checks=pc, source_ref=pr,
                                      reason="qualified_exact_official_version_cell_reextracted")
                    except (ValueError, KeyError, IndexError, AssertionError, ImportError) as exc:
                        result["reason"] = "not_assessable: " + str(exc)
                    cache_key = case["request"]["symbol"], case["request"]["exchange"], ev["period"], ev["metric"], ev["revision_id"], str(ev["value"])
                    pdf.results[cache_key] = result
                    official_by_evidence[eid] = result
            qualification = None
            if event_record is not None:
                try:
                    ec, refs = oracle.qualification_checks(event_record, raw, paths, pdf)
                    qualification = {"assessable": True, "supported": all(ec.values()), "checks": ec, "source_refs": refs,
                                     "reason": "independent_raw_official_index_and_PDF_identity_date_only_qualification"}
                except (ValueError, KeyError, IndexError, AssertionError, ImportError) as exc:
                    qualification = {"assessable": False, "supported": None, "reason": "not_assessable: " + str(exc)}
            claim_coverage = []
            for name, fact in sorted(facts.items()):
                refs = [official_by_evidence.get(eid) for eid in fact["inputs"]]
                all_assessable = all(ref is not None and ref["assessable"] is True for ref in refs)
                supported = (all(ref["supported"] is True for ref in refs) if all_assessable else
                             False if any(ref is not None and ref["supported"] is False for ref in refs) else None)
                claim_coverage.append({"name": name, "evidence_ids": fact["inputs"],
                    "all_numeric_input_accuracy_assessable": all_assessable,
                    "all_numeric_input_accuracy_supported": supported,
                    "reason": "all_exact_source_revision_official_cells_checked" if all_assessable else "one_or_more_official_source_revision_inputs_not_assessable"})
            cases.append({"case_id": case["id"], "level": case["level"], "scope": case["scope"],
                "input_checks": checks, "source_checks": source_units,
                "source_input_supported": all(checks.values()) and all(row["supported"] is True for row in source_units)
                    and (qualification is None or qualification["supported"] is True),
                "selected_record_ids": {dataset: [oracle.rid(row) for row in rows] for dataset, rows in selected.items()},
                "expected_facts": facts, "expected_hypotheses": expected_hypotheses,
                "event_qualification": qualification, "expected_event_anchor": anchor,
                "expected_event_endpoints": [] if pair is None else [row["period"] for row in pair],
                "official_claim_input_coverage": claim_coverage,
                "source_only_not_agent_capability_score": True})
    finally:
        pdf.close()
    units = [row for case in cases for row in case["source_checks"]]
    official = list(pdf.results.values())
    summary = {"cases": len(cases), "source_input_supported_cases": sum(case["source_input_supported"] for case in cases),
        "source_evidence_checks": len(units), "source_supported": sum(row["supported"] is True for row in units),
        "source_not_assessable": sum(row["assessable"] is False for row in units),
        "source_failed": sum(row["supported"] is False for row in units),
        "input_failure_categories": dict(Counter(name for case in cases for name, passed in case["input_checks"].items() if not passed)),
        "source_failure_categories": dict(Counter(name for row in units for name, passed in row["checks"].items() if not passed))}
    result = {"schema": "independent-source-only-preflight-v2/1", "source_only_not_agent_capability_score": True,
        "Agent_reports_read": 0, "Agent_execution_calls": 0, "model_calls": 0, "network_calls": 0,
        "production_imports": 0, "prior_scores_or_verdicts_used_as_truth": False,
        "manifest_sha256": reader.reads[manifest_path.relative_to(reader.root).as_posix()],
        "frozen_oracle_sha256": hashlib.sha256(Path(oracle.__file__).read_bytes()).hexdigest(),
        "preflight_wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "summary": summary, "cases": cases, "input_sha256": reader.reads,
        "limits": ["Expected values and states are independent source deductions, not Agent outputs or capability scores.",
            "Official accuracy is limited to assessable exact-version printed cells; unknowns remain unknown.",
            "Snapshot authorization comes from the pinned trusted application capture and current source-read authorization probes, not from a model self-report."]}
    coverage = {"schema": "independent-official-source-preflight-v2/1", "source_only_not_agent_capability_score": True,
        "manifest_sha256": result["manifest_sha256"], "checks": official,
        "summary": {"distinct_source_revision_cells": len(official), "assessable": sum(row["assessable"] is True for row in official),
            "supported": sum(row["supported"] is True for row in official), "contradicted": sum(row["supported"] is False for row in official),
            "not_assessable": sum(row["assessable"] is False for row in official)},
        "pdf_page_extractions": [{"path": str(Path(path).relative_to(reader.root)), "page": page, "text": text}
            for (path, page), text in sorted(pdf.pages.items())]}
    outdir.mkdir(parents=True, exist_ok=True)
    oracle.write_new(outputs[0], result)
    oracle.write_new(outputs[1], coverage)
    return result, coverage


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("outdir")
    args = parser.parse_args()
    result, coverage = run(args.manifest, args.outdir)
    print(json.dumps({"source_only_not_agent_capability_score": True, "source": result["summary"],
                      "official": coverage["summary"]}, ensure_ascii=False))
