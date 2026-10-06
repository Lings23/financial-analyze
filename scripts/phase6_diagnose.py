"""Read-only Phase 6 diagnosis of frozen, locally authorized Phase 5 exports.

No model/provider adapter, source store, credential file, or CheckpointStore is
opened. SQLite is read with mode=ro and immutable=1; all chains and exported paid
wires are checked before statistics. This does not replace current source-grant
authorization during Runtime replay, which must be run separately.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from stock_research.models import canonical_json, digest
from stock_research.research.dynamic_context import expand_view


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / ".artifacts/phase5/targeted-20261006/live"
REPAIR = ROOT / ".artifacts/phase5/parent-progress-v2-20261006/live"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def size(value):
    return len(canonical_json(value).encode("utf-8"))


def frozen_hashes():
    return {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path)
            for root in (ORIGINAL, REPAIR) for path in sorted(root.rglob("*")) if path.is_file()}


def span_ms(start, finish):
    return round((datetime.fromisoformat(finish) - datetime.fromisoformat(start)).total_seconds() * 1000, 3)


def describe(values):
    values = sorted(values)
    return {"count": len(values), "sum": round(sum(values), 3),
            "min": values[0] if values else None,
            "median": (values[(len(values) - 1) // 2] + values[len(values) // 2]) / 2 if values else None,
            "max": values[-1] if values else None}


def exploratory_representation(view):
    """One counterfactual residual-metadata encoding, never a new model call.

    Existing Fact/Evidence numbers and object-ID cells remain literal. Shared
    exact list contents retain their literal refs in a new table. The prototype
    is only a size probe; acceptance uses the eventual production codec.
    """
    expanded = expand_view(view)
    counts, list_counts = Counter(), Counter()
    eligible = [expanded["range"]]
    eligible += [cell for table in ("facts", "evidence") for row in expanded[table]
                 for index, cell in enumerate(row) if index not in (0, 2)]
    eligible += [cell for row in expanded["source_datasets"]
                 for index, cell in enumerate(row) if index != 0]
    eligible += [cell for row in expanded["observations"]
                 for index, cell in enumerate(row) if index in (2, 4, 5, 6)]

    def scan(item):
        if type(item) is str and len(item.encode("utf-8")) >= 10 and not re.fullmatch(
                r"(?:[CEHO]:.*|[FE][1-9][0-9]*)", item):
            counts[item] += 1
        elif type(item) is list:
            if item and all(type(child) is str for child in item):
                list_counts[canonical_json(item)] += 1
            for child in item:
                scan(child)
        elif type(item) is dict:
            for child in item.values():
                scan(child)

    for item in eligible:
        scan(item)
    strings = sorted(text for text, count in counts.items() if count >= 2
                     and count * size(text) > count * size({"s": 0}) + size(text) + 1)
    # Remove entries whose actual alias width makes them unprofitable.
    while True:
        selected = [text for index, text in enumerate(strings)
                    if counts[text] * size(text) > counts[text] * size({"s": index}) + size(text) + 1]
        if selected == strings:
            break
        strings = selected
    symbols = {text: index for index, text in enumerate(strings)}
    lists = sorted((json.loads(text) for text, count in list_counts.items() if count >= 2
                    and count * len(text.encode("utf-8")) > count * size({"l": 0}) + len(text.encode("utf-8")) + 1),
                   key=canonical_json)
    list_ids = {canonical_json(item): index for index, item in enumerate(lists)}

    def pack(item):
        if type(item) is str and item in symbols:
            return {"s": symbols[item]}
        if type(item) is list:
            if canonical_json(item) in list_ids:
                return {"l": list_ids[canonical_json(item)]}
            return [pack(child) for child in item]
        if type(item) is dict:
            return {key: pack(child) for key, child in item.items()}
        return item

    candidate = deepcopy(view)
    candidate["range"] = pack(expanded["range"])
    for table in ("facts", "evidence"):
        candidate[table] = [[cell if index in (0, 2) else pack(cell)
                             for index, cell in enumerate(row)] for row in expanded[table]]
    candidate["source_datasets"] = [[cell if index == 0 else pack(cell)
                                     for index, cell in enumerate(row)] for row in expanded["source_datasets"]]
    candidate["observations"] = [[pack(cell) if index in (2, 4, 5, 6) else cell
                                  for index, cell in enumerate(row)] for row in expanded["observations"]]
    candidate["symbols"] = strings
    candidate["list_table"] = [[pack(child) for child in item] for item in lists]
    candidate["schema"] = "dynamic-context-view/v2"

    def unpack(item):
        if type(item) is dict and set(item) == {"s"}:
            return strings[item["s"]]
        if type(item) is dict and set(item) == {"l"}:
            return [unpack(child) for child in candidate["list_table"][item["l"]]]
        if type(item) is list:
            return [unpack(child) for child in item]
        if type(item) is dict:
            return {key: unpack(child) for key, child in item.items()}
        return item

    recovered = deepcopy(expanded)
    recovered["range"] = unpack(candidate["range"])
    for table in ("facts", "evidence", "source_datasets", "observations"):
        recovered[table] = unpack(candidate[table])
    assert recovered == expanded
    return {"baseline_view_bytes": size(view), "counterfactual_view_bytes": size(candidate),
            "saved_bytes": size(view) - size(candidate), "symbol_count": len(strings),
            "exact_list_count": len(lists), "full_expanded_v1_equal": True,
            "system_and_control_changed": False, "new_model_token_measurement": None}


def check_sqlite(path):
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        rows = connection.execute("SELECT scope,run,seq,previous,hash,payload FROM checkpoints "
                                  "ORDER BY scope,run,seq").fetchall()
    previous, sequences, reports = {}, {}, {}
    for scope, run, seq, parent, checksum, payload in rows:
        key = (scope, run)
        state = json.loads(payload)
        assert seq == sequences.get(key, 0) and parent == previous.get(key, "")
        assert digest({"previous": parent, "state": state}) == checksum
        previous[key], sequences[key] = checksum, seq + 1
        if state.get("report"):
            reports[run] = state["report"]
    return {"rows": len(rows), "runs": len(sequences), "chain_verified": True}, reports


def check_exports(dataset, base):
    count = 0
    for row in dataset["rows"]:
        if row["sample_kind"] != "new_validation":
            continue
        for subdir, hashes in row["hashes"].items():
            directory = base / row["run_id"] if subdir == "run_files" else base / "dispatch"
            for relative, expected in hashes.items():
                assert sha(directory / relative) == expected
                count += 1
    return count


def tool_spans(reports):
    result = []
    for report in reports:
        starts = {}
        for event in report["trace"]:
            if event["event"] == "tool_started":
                starts[event["tool_call_id"]] = event
            elif event["event"] == "tool_finished":
                start = starts.get(event["tool_call_id"])
                if start:
                    result.append({"run_id": report["run_id"], "tool": event["tool"],
                                   "elapsed_ms": span_ms(start["time"], event["time"]),
                                   "dedup": event.get("dedup"),
                                   "nested_child_model_and_source_cost": event["tool"].endswith("_child")})
    return result


def campaign(base, label, rows):
    summary = load(base / "summary.json")
    final_ledger = summary["ledger"]
    reports = [row["report"] for row in rows]
    children = [child for row in rows for child in row["child_reports"]]
    all_reports = reports + children
    telemetry = {entry["message_sha256"]: entry for report in all_reports
                 for entry in report["context_telemetry"]}
    intents = {entry["number"]: entry for entry in final_ledger["intents"]}
    wires, intervals, latency, prompt, completion, previews = [], [], [], [], [], []
    lazy, compaction, visible, total = [], [], [], []
    for path in sorted((base / "dispatch").glob("*-messages.json")):
        prefix = path.name.split("-")[0]
        number = int(prefix)
        messages = load(path)
        intent = load(base / "dispatch" / f"{prefix}-intent.json")
        receipt = load(base / "dispatch" / f"{prefix}-receipt.json")
        interval = load(base / "dispatch" / f"{prefix}-interval.json")
        dispatch = load(base / "dispatch" / f"{prefix}-dispatch.json")
        checksum = digest(messages)
        assert checksum == intent["messages_sha256"] == intents[number]["messages_sha256"]
        assert receipt["total_tokens"] == receipt["prompt_tokens"] + receipt["completion_tokens"]
        assert receipt["total_tokens"] == intents[number]["total_tokens"]
        entry = telemetry[checksum]
        byte_count = sum(len(message["content"].encode("utf-8")) for message in messages)
        assert byte_count == entry["total_context_bytes"] <= 12000
        assert (entry["input_tokens"], entry["output_tokens"], entry["total_tokens"]) == (
            receipt["prompt_tokens"], receipt["completion_tokens"], receipt["total_tokens"])
        payload = json.loads(messages[1]["content"])
        view = payload.get("context")
        probe = exploratory_representation(view) if view else None
        wire = {"number": number, "run_id": dispatch["run_id"], "role": dispatch["role"],
                "case_id": dispatch.get("case_id"), "route": dispatch.get("route"),
                "wire_bytes": byte_count, "system_bytes": len(messages[0]["content"].encode("utf-8")),
                "known_prompt_tokens": receipt["prompt_tokens"], "known_completion_tokens": receipt["completion_tokens"],
                "accounted_tokens": receipt["total_tokens"], "dispatch_reservation": intent["reservation"],
                "model_transport_receipt_ms": receipt["latency_ms"],
                "dispatch_interval_ms": span_ms(interval["started_at"], interval["finished_at"]),
                "wire_sha256": checksum, "exploratory_residual_metadata": probe}
        wires.append(wire)
        intervals.append((datetime.fromisoformat(interval["started_at"]), datetime.fromisoformat(interval["finished_at"])))
        latency.append(receipt["latency_ms"])
        prompt.append(receipt["prompt_tokens"])
        completion.append(receipt["completion_tokens"])
        if probe:
            previews.append(probe)
            lazy.append(entry["lazy_disclosure_saved_bytes"])
            compaction.append(entry["context_saved_bytes"])
            visible.append(entry["visible_evidence_count"])
            total.append(entry["total_evidence_count"])
    assert sum(prompt) + sum(completion) == final_ledger["known_tokens"] == final_ledger["tokens_accounted"]
    assert sum(wire["dispatch_reservation"] for wire in wires) == final_ledger["cumulative_tokens_reserved"]
    assert final_ledger["unknown_usage_calls"] == 0
    # Merge simultaneous model intervals; a sum would double count parallel I/O.
    merged = []
    for start, finish in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(finish, merged[-1][1]))
        else:
            merged.append((start, finish))
    run_results = []
    for row in rows:
        report, run_summary = row["report"], row["summary"]
        dispatched = [wire for wire in wires if wire["run_id"] == report["run_id"] or
                      wire["run_id"] in {child["run_id"] for child in row["child_reports"]}]
        own_tools = tool_spans([report] + row["child_reports"])
        groups = [entry for entry in report["trace"] if entry["event"] == "parallel_telemetry"]
        run_results.append({"case_id": row["case_id"], "route": row["route"], "run_id": report["run_id"],
                            "status": report["status"], "functional_passed": (
                                run_summary["assessment"]["functional_passed"] if "assessment" in run_summary else run_summary["success"]),
                            "wall_ms": run_summary.get("wall_clock_ms", run_summary.get("wall_ms")),
                            "known_tokens": sum(wire["accounted_tokens"] for wire in dispatched),
                            "accounted_tokens": report["root_budget"]["tokens_accounted"],
                            "cumulative_dispatch_reserved_tokens": sum(wire["dispatch_reservation"] for wire in dispatched),
                            "cumulative_root_including_allocation_reserved_tokens": report["root_budget"]["tokens_reserved"],
                            "transport_receipt_ms_sum_nested": sum(wire["model_transport_receipt_ms"] for wire in dispatched),
                            "tool_spans": own_tools, "parallel_groups": groups,
                            "independent_authorization_read_validation_ms": None})
    spans = tool_spans(all_reports)
    tools_by_name = defaultdict(list)
    for item in spans:
        tools_by_name[item["tool"]].append(item["elapsed_ms"])
    return {"label": label, "runs": run_results, "paid_decisions": len(wires),
            "known_prompt_tokens": sum(prompt), "known_completion_tokens": sum(completion),
            "known_total_tokens": sum(prompt) + sum(completion), "accounted_tokens": final_ledger["tokens_accounted"],
            "cumulative_dispatch_reserved_tokens": final_ledger["cumulative_tokens_reserved"],
            "cumulative_root_including_allocations_reserved_tokens": sum(report["root_budget"]["tokens_reserved"] for report in reports),
            "unknown_usage_calls": 0, "wires": wires,
            "transport_receipt_ms": describe(latency),
            "dispatch_intervals_union_ms": round(sum((finish - start).total_seconds() * 1000 for start, finish in merged), 3),
            "tool_elapsed_ms_by_name_nested": {key: describe(values) for key, values in tools_by_name.items()},
            "tool_dedup_hit_count": sum(item["dedup"] is True for item in spans),
            "explicit_disclose_action_count": sum(event["event"] == "context_disclosed"
                                                for report in all_reports for event in report["trace"]),
            "provider_cache_hit_count": None,
            "source_read_count_not_instrumented": None,
            "lazy_disclosure_saved_bytes_existing_parent_views": describe(lazy),
            "existing_total_compaction_saved_bytes_parent_views": describe(compaction),
            "visible_evidence_count_parent_views": describe(visible),
            "total_evidence_count_parent_views": describe(total),
            "exploratory_residual_metadata_saved_bytes": describe([probe["saved_bytes"] for probe in previews]),
            "exploratory_baseline_parent_wire_bytes": sum(wire["wire_bytes"] for wire in wires if wire["exploratory_residual_metadata"]),
            "exploratory_system_interpretation_overhead_not_included": True,
            "provider_network_calls": 0}


def candidate_preflight(output):
    """Check the implemented codec on exact old paid wires without new I/O."""
    from stock_research.research.dynamic_context_metadata import encode_metadata_view, decode_metadata_view
    from stock_research.research.dynamic_protocol import SYSTEM_PARENT_PARALLEL_V2, SYSTEM_PARENT_PARALLEL_V3
    appendix = (' In context v2 metadata, int=symbols[int], {"l":i}=list_table[i]; '
                'decode recursively to exact literals.')
    before = frozen_hashes()
    packets, summaries = [], []
    for base in (ORIGINAL, REPAIR):
        subset = []
        for path in sorted((base / "dispatch").glob("*-messages.json")):
            messages = load(path)
            payload = json.loads(messages[1]["content"])
            if "context" not in payload:
                continue
            candidate = encode_metadata_view(payload["context"])
            assert decode_metadata_view(candidate) == payload["context"]
            expanded = expand_view(payload["context"])
            assert expand_view(candidate) == expanded
            assert candidate["catalog_ref"] == payload["context"]["catalog_ref"]
            assert candidate["binding_ref"] == payload["context"]["binding_ref"]
            assert [row[0] for row in candidate["facts"]] == [row[0] for row in payload["context"]["facts"]]
            assert [row[2] for row in candidate["facts"]] == [row[2] for row in payload["context"]["facts"]]
            assert [row[0] for row in candidate["evidence"]] == [row[0] for row in payload["context"]["evidence"]]
            assert [row[2] for row in candidate["evidence"]] == [row[2] for row in payload["context"]["evidence"]]
            changed = deepcopy(payload)
            changed["context"] = candidate
            # Existing original campaign modes are representation-only probes;
            # only repair v2 -> v3 is the authorized candidate protocol comparison.
            if payload["protocol_version"] == "dynamic-parent-parallel-v2":
                changed["protocol_version"] = "dynamic-parent-parallel-v3"
            reconstructed = deepcopy(changed)
            reconstructed["context"] = decode_metadata_view(candidate)
            reconstructed["protocol_version"] = payload["protocol_version"]
            assert reconstructed == payload
            old_bytes = sum(len(message["content"].encode("utf-8")) for message in messages)
            old_system = messages[0]["content"]
            new_system = old_system.replace(
                "Financial values and object IDs remain literal.",
                "Financial value cells and Fact/Evidence row IDs remain literal; metadata IDs decode exactly."
            ) + appendix
            if payload["protocol_version"] == "dynamic-parent-parallel-v2":
                assert old_system == SYSTEM_PARENT_PARALLEL_V2
                assert new_system == SYSTEM_PARENT_PARALLEL_V3
            new_bytes = len(new_system.encode("utf-8")) + size(changed)
            entry = {"campaign": str(base.relative_to(ROOT)).replace("\\", "/"),
                     "wire_file": path.name, "protocol_version": payload["protocol_version"],
                     "stage": expanded["stage"], "baseline_paid_wire_sha256": digest(messages),
                     "baseline_wire_bytes": old_bytes, "candidate_wire_bytes_counterfactual": new_bytes,
                     "baseline_view_bytes": size(payload["context"]), "candidate_view_bytes": size(candidate),
                     "net_saved_bytes": old_bytes - new_bytes,
                     "view_saved_bytes": size(payload["context"]) - size(candidate),
                     "system_interpretation_appendix_bytes": len(appendix.encode("utf-8")),
                     "system_metadata_sentence_delta_bytes": len(new_system.encode("utf-8")) - len(old_system.encode("utf-8")) - len(appendix.encode("utf-8")),
                     "exact_production_parallel_v3_system": payload["protocol_version"] == "dynamic-parent-parallel-v2",
                     "decode_equals_exact_v1_view": True, "expanded_facts_evidence_refs_all_equal": True,
                     "entire_other_payload_unchanged": True, "actual_candidate_model_tokens": None}
            packets.append(entry)
            subset.append(entry)
        summaries.append({"campaign": str(base.relative_to(ROOT)).replace("\\", "/"),
                          "parent_paid_wire_count": len(subset),
                          "baseline_wire_bytes_sum": sum(entry["baseline_wire_bytes"] for entry in subset),
                          "candidate_counterfactual_wire_bytes_sum": sum(entry["candidate_wire_bytes_counterfactual"] for entry in subset),
                          "net_saved_bytes": describe([entry["net_saved_bytes"] for entry in subset]),
                          "view_saved_bytes": describe([entry["view_saved_bytes"] for entry in subset])})
    after = frozen_hashes()
    assert before == after
    result = {"schema": "phase6-lossless-candidate-wire-preflight/v1", "status": "passed",
              "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0,
              "historical_files": len(before), "historical_sha_before_equals_after": True,
              "represented_parent_wires": len(packets), "historical_child_wires_unchanged": 28,
              "summaries": summaries, "wires": packets,
              "candidate_code_sha256": sha(ROOT / "src/stock_research/research/dynamic_context_metadata.py"),
              "production_v2_system_sha256": digest(SYSTEM_PARENT_PARALLEL_V2),
              "production_v3_system_sha256": digest(SYSTEM_PARENT_PARALLEL_V3),
              "counterfactual_model_tokens": None, "counterfactual_latency": None,
              "scope": "representation_only_probe_of_all_58_parent_wires; repair_5_v2_wires_can_compare_exact_v3_appendix",
              "freeze_before_real_validation_required": True}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "status": "passed", "summaries": summaries}, ensure_ascii=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-preflight", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output is None:
        args.output = ROOT / (".runtime/phase6-candidate-wire-preflight.json" if args.candidate_preflight
                              else ".runtime/phase6-diagnosis.json")
    if args.output.exists():
        raise SystemExit("diagnosis output already exists; choose a new path to preserve evidence")
    if args.candidate_preflight:
        candidate_preflight(args.output)
        return
    before = frozen_hashes()
    dataset = load(ORIGINAL / "trace-dataset.json")
    summary = load(ORIGINAL / "summary.json")
    assert sha(ORIGINAL / "trace-dataset.json") == summary["trace_dataset_sha256"]
    export_checks = check_exports(dataset, ORIGINAL)
    manifest = load(REPAIR / "trace-manifest.json")
    for relative, expected in manifest["files_before_manifest"].items():
        assert sha(REPAIR / relative) == expected
    sqlite_results, persisted = [], {}
    for root in (ORIGINAL, REPAIR):
        for path in sorted(root.rglob("checkpoints.sqlite3")):
            result, reports = check_sqlite(path)
            sqlite_results.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), **result})
            persisted.update(reports)
    rows = [row for row in dataset["rows"] if row["sample_kind"] == "new_validation"]
    repair_summary, repair_report = load(REPAIR / "summary.json"), load(REPAIR / "report.json")
    repair_row = {"case_id": "p5-688184", "route": "parallel-parent-v2-retest",
                  "report": repair_report, "child_reports": repair_summary["child_reports"],
                  "summary": {"assessment": repair_summary["assessment"], "wall_clock_ms": repair_summary["wall_clock_ms"]}}
    for row in rows + [repair_row]:
        assert persisted[row["report"]["run_id"]] == row["report"]
        for child in row["child_reports"]:
            assert persisted[child["run_id"]] == child
    original_diagnosis = campaign(ORIGINAL, "original_phase5_three_cases_nine_routes", rows)
    repair_diagnosis = campaign(REPAIR, "same_case_parent_v2_reacceptance_independent_new_tasks_zero", [repair_row])
    after = frozen_hashes()
    assert before == after
    result = {"schema": "phase6-readonly-bottleneck-diagnosis/v1", "status": "passed",
              "read_scope": "authorized_local_frozen_paid_wires_reports_telemetry_and_hashchain_statistics_only",
              "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0,
              "current_source_grant_replay": "separate_Runtime_replay_required_no_source_store_opened_here",
              "integrity": {"historical_files": len(before), "sha_before_equals_after": True,
                            "original_frozen_export_hash_checks": export_checks,
                            "repair_manifest_hash_checks": len(manifest["files_before_manifest"]),
                            "sqlite": sqlite_results, "exported_reports_equal_persisted_reports": True},
              "denominators": {"original_independent_nonblind_cases": 3, "original_route_runs": 9,
                               "original_passed_route_runs": 8, "parent_v2_same_case_retests": 1,
                               "parent_v2_passed_retests": 1, "retests_independent_new_tasks": 0,
                               "independent_blind_tasks": 0},
              "campaigns": [original_diagnosis, repair_diagnosis],
              "latency_semantics": {
                  "transport_receipt": "adapter elapsed including configured model endpoint I/O; does not isolate endpoint compute from network",
                  "dispatch_interval": "paid harness start-to-finish; includes receipt persistence wrapper overhead",
                  "tool_span": "Trace tool_started to tool_finished; contains authorization/source/verification and AgentTool child I/O; nested spans must not be added to model spans",
                  "queue": "only parallel branch queue_ms available; no provider/model queue measurement",
                  "read_authorization_validation": "no separate historical timing spans; unknown rather than zero",
                  "cache": "tool dedup field measured; provider completed-cache hits and authorization reread counts not instrumented",
                  "p95": "not estimated as improvement; n=3 nonblind paired cases insufficient for statistical superiority"},
              "recommendation": {
                  "one_bottleneck": "residual repeated exact metadata strings and list collections in v1 view",
                  "candidate": "explicit new Parent protocol and deterministic lossless metadata/list intern codec",
                  "why": "actual frozen Parent wires retain repeated binding snapshot refs, period strings, and derived Observation C/E ref collections beyond row-only interning",
                  "current_lazy_disclosure": "already saves disclosed Evidence bytes; no actual disclose action or evidence loss found",
                  "cache_optimization": "not selected: historical traces cannot isolate repeated authorization/read/validation cost; no evidence supporting safe measurable cache latency benefit",
                  "limits": "exploratory size probe excludes new system instruction overhead and does not predict real model tokens or latency; defaults and 12000 remain"},
              "frozen_input_hashes": before}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "historical_files_unchanged": len(before),
                      "paid_decisions_verified": 86,
                      "original": {key: original_diagnosis[key] for key in ("known_total_tokens", "accounted_tokens", "cumulative_dispatch_reserved_tokens", "exploratory_residual_metadata_saved_bytes")},
                      "repair": {key: repair_diagnosis[key] for key in ("known_total_tokens", "accounted_tokens", "cumulative_dispatch_reserved_tokens", "exploratory_residual_metadata_saved_bytes")}}, ensure_ascii=True))


if __name__ == "__main__":
    main()
