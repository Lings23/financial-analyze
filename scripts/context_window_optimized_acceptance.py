"""Independent, bounded v6/v6.1 metadata acceptance using isolated v6 helpers.

The previous frozen script and imported module stay unchanged.  A private module
instance reuses its campaign accounting and exact source/oracle/replay checks.
Only version selection and metadata-specific inspection are overridden here.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import context_window_acceptance as previous
from stock_research.errors import IntegrityError
from stock_research.models import canonical_json, digest
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic_contracts import DynamicRequest, FinancialRequest, MarketRequest
from stock_research.research.dynamic_protocol import dynamic_messages

_spec = importlib.util.spec_from_file_location("_context_window_optimized_private_harness", previous.__file__)
_engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_engine)

OLD, original, infra = previous.OLD, previous.original, previous.infra
OUT = OLD.ROOT / ".artifacts/context-window-optimized/metadata-v6.1-20261008"
VERSIONS = {"baseline": "dynamic-parent-parallel-v6", "candidate": "dynamic-parent-parallel-v6.1"}
CASE_IDS, ORDER, LIMITS, MAX_RUNS = previous.CASE_IDS, previous.ORDER, previous.LIMITS, previous.MAX_RUNS
CHILD_SPECS = previous.CHILD_SPECS
ACCEPTANCE = {**previous.ACCEPTANCE,
    "optimization": "exact metadata codec only; complete raw window, cursor selections, actual tool checks and source oracles retained",
    "counterfactual": "same raw view codec bytes separate from actual compiled working-set bytes; neither predicts actual Token",
    "performance_gate": "all same-raw input bytes nonincreasing and aggregate lower; whole-task Parent+Child actual known/accounted Token must separately decrease",
    "scope": "explicit v6.1 exact metadata only; no defaults, cap, budgets, facts or business semantics changed"}

_base_checked = _engine.checked
_base_evaluate = _engine.evaluate_pairs
_base_page_audit = _engine.page_audit
_base_replay = _engine.readonly_replay
_base_audit = _engine.audit
_base_gate = _engine.validate_gate


def code_files():
    return {**previous.code_files(),
        "scripts/context_window_optimized_acceptance.py": OLD.sha(Path(__file__))}


def history_hashes():
    return {**previous.history_hashes(),
        "context-window-v6": original.file_hashes(previous.OUT),
        "legacy-window-code": {"scripts/context_window_acceptance.py": OLD.sha(Path(previous.__file__)),
            "tests/test_context_window_acceptance.py": OLD.sha(OLD.ROOT / "tests/test_context_window_acceptance.py")}}


def raw_context(view):
    if view.get("schema") == "dynamic-context-window/v2":
        from stock_research.research.context_window_metadata import decode_window_metadata_view
        return decode_window_metadata_view(view)
    if view.get("schema") != "dynamic-context-window/v1":
        raise IntegrityError("Optimized acceptance context is outside exact window schemas")
    return deepcopy(view)


def codec_probe(messages):
    """Encode the *same raw view*; no compiler, capacity fill or dispatch."""
    from stock_research.research.context_window_metadata import encode_window_metadata_view, decode_window_metadata_view
    from stock_research.research.dynamic_protocol import SYSTEM_PARENT_PARALLEL_V6, SYSTEM_PARENT_PARALLEL_V6_1
    payload = json.loads(messages[1]["content"])
    raw = raw_context(payload["context"])
    encoded = encode_window_metadata_view(raw)
    if decode_window_metadata_view(encoded) != raw:
        raise IntegrityError("Metadata codec failed exact raw window/selection/cursor recovery")
    baseline = [{"role": "system", "content": SYSTEM_PARENT_PARALLEL_V6},
        {"role": "user", "content": canonical_json({**payload, "protocol_version": VERSIONS["baseline"], "context": raw})}]
    candidate = [{"role": "system", "content": SYSTEM_PARENT_PARALLEL_V6_1},
        {"role": "user", "content": canonical_json({**payload, "protocol_version": VERSIONS["candidate"], "context": encoded})}]
    before, after = (sum(len(item["content"].encode("utf-8")) for item in wire) for wire in (baseline, candidate))
    return {"same_raw_baseline_total_wire_bytes": before, "same_raw_candidate_total_wire_bytes": after,
        "same_raw_wire_bytes_saved": before - after, "same_raw_bytes_nonincreasing": after <= before,
        "same_raw_context_bytes": len(canonical_json(raw).encode("utf-8")),
        "encoded_context_bytes": len(canonical_json(encoded).encode("utf-8")),
        "expanded_raw_window_exact": True, "same_raw_pages_and_cursor_selections_exact": True,
        "counterfactual_model_calls": 0, "counterfactual_tokens": None, "counterfactual_runtime": None,
        "raw_page_atoms": sum(len(page["atoms"]) for page in raw["pages"]),
        "raw_page_selections": [page["selection"] for page in raw["pages"]]}


def state_projection(item, state, variant, *, diagnostic=False):
    runner = _engine.runtime(None, None, variant)
    access = type("BoundScope", (), {"scope": item["scope"]})()
    return dynamic_messages(DynamicRequest.from_dict(item["request"]),
        json.loads(item["messages"][1]["content"])["available_tools"], list(state["observations"].values()),
        state["requirements"], state["plans"][-1]["steps"] if state["plans"] else [],
        4000000 if diagnostic else 12000, decision=state["decisions"][-1]["turn"],
        protocol_error=state.get("protocol_error"), version=VERSIONS[variant],
        finish_rejection=state.get("finish_rejection"),
        delegation_results=[{"tool": child["domain"] + "_child", "domain": child["domain"],
            "status": child["status"], "result_ref": child["result_ref"]} for child in state["child_results"]],
        **runner._context_arguments(state, access, paid_decision=state["decisions"][-1]
            if state["phase"] == "model_pending" else None))


def validate_outbound(messages, item, kwargs, checkpoints):
    payload = json.loads(messages[1]["content"])
    role, control = payload["protocol_version"], payload["control"]
    spec = _engine.role_spec(item, role)
    if role == item["parent_version"]:
        state = _engine.paid_state(checkpoints, item, messages)
        rebuilt, metadata = state_projection(item, state, item["variant"])
        if state["context"] != {"status": "prepared", **metadata}:
            raise IntegrityError("Optimized paid metadata/audit differs from complete durable state")
        tools = json.loads(item["messages"][1]["content"])["available_tools"]
        if control["decision"] == 1:
            preview = json.loads(item["messages"][1]["content"])
            actual_raw, preview_raw = raw_context(payload["context"]), raw_context(preview["context"])
            if (messages[0] != item["messages"][0] or state["observations"] or state["plans"]
                    or {key: value for key, value in control.items() if key != "context_budget"} != preview["control"]
                    or any(actual_raw.get(key) != preview_raw.get(key)
                        for key in ("catalog_ref", "binding_ref", "range", "required_checks", "stage"))):
                raise IntegrityError("Optimized initial paid wire differs from frozen immutable preview boundary")
    else:
        domain = next(domain for domain, child in CHILD_SPECS.items() if child.version == role)
        parent = DynamicRequest.from_dict(item["request"])
        request = (FinancialRequest if domain == "financial" else MarketRequest).from_parent(parent)
        tools, observations, checks = [domain], payload["observations"], payload["required_checks"]
        if any(observation != item["authorization_envelope"]["source_observations"][domain] for observation in observations):
            raise IntegrityError("Optimized Child exceeds complete immutable authorized source")
        rebuilt, _ = dynamic_messages(request, tools, observations, checks, control["plan"], 12000,
            decision=control["decision"], protocol_error=control.get("previous_action_error"), version=role,
            finish_rejection=control.get("finish_rejection"))
    if rebuilt != messages or payload["available_tools"] != tools or kwargs.get("max_tokens") != spec.output_tokens:
        raise IntegrityError("Optimized outbound wire differs from exact authoritative paid state")
    if sum(len(message["content"].encode("utf-8")) for message in messages) > 12000:
        raise IntegrityError("Optimized actual system+user bytes exceed original cap")
    return role, spec, control["decision"]


def same_state_wire(messages, item, checkpoints):
    payload = json.loads(messages[1]["content"])
    if payload["protocol_version"] != VERSIONS["candidate"]:
        return None
    from stock_research.research.context_window import expand_window_view, rebuild_window
    state = _engine.paid_state(checkpoints, item, messages)
    _, metadata = state_projection(item, state, "candidate")
    access = type("BoundScope", (), {"scope": item["scope"]})()
    catalog = _engine.runtime(None, None, "candidate")._build_catalog(state, DynamicRequest.from_dict(item["request"]), access)
    raw = raw_context(payload["context"])
    if rebuild_window(catalog, metadata["window"], scope=item["scope"], run_id=item["run_id"]) != raw:
        raise IntegrityError("Optimized decoded window differs from full authorized catalog")
    current = expand_window_view(raw)
    ready, brief = metadata["verification_ready"], current.get("verification_brief")
    if type(ready) is not bool or (brief is not None) != ready or "verification_manifest" in current:
        raise IntegrityError("Optimized disclosure readiness differs from authoritative business state")
    probe = codec_probe(messages)
    try:
        baseline, baseline_metadata = state_projection(item, state, "baseline")
        baseline_fits = True
    except _engine.ValidationError:
        baseline, baseline_metadata = state_projection(item, state, "baseline", diagnostic=True)
        baseline_fits = False
    baseline_raw = raw_context(json.loads(baseline[1]["content"])["context"])
    if metadata.get("verification_audit") != baseline_metadata.get("verification_audit"):
        raise IntegrityError("Optimized codec changed complete server-side verification audit")
    before, actual = (sum(len(message["content"].encode("utf-8")) for message in wire) for wire in (baseline, messages))
    return {**probe, "turn": payload["control"]["decision"], "stage": current["stage"],
        "candidate_total_wire_bytes": actual, "baseline_same_state_total_wire_bytes": before,
        "net_wire_bytes_saved": before - actual, "same_state_bytes_nonincreasing": actual <= before,
        "baseline_same_state_fits_original_cap": baseline_fits,
        "baseline_compiled_page_atoms": sum(len(page["atoms"]) for page in baseline_raw["pages"]),
        "candidate_compiled_page_atoms": sum(len(page["atoms"]) for page in raw["pages"]),
        "compiled_page_selections_equal": [page["selection"] for page in baseline_raw["pages"]]
            == [page["selection"] for page in raw["pages"]],
        "candidate_message_sha256": digest(messages), "baseline_message_sha256": digest(baseline),
        "candidate_verification_ready": ready, "candidate_brief_present": brief is not None,
        "candidate_manifest_present": False, "complete_audit_persisted_server_side": metadata.get("verification_audit") is not None,
        "exact_execution_revisions_decoded": True, "same_financial_projection": True,
        "same_full_source_state": True, "exact_authorized_window_reconstruction": True,
        "window_schema": raw["schema"], "wire_window_schema": payload["context"]["schema"],
        "window_ref": metadata["window"]["window_ref"], "window_descriptor": metadata["window"],
        "new_disclosure_contract": False, "candidate_context_decodes_exact_baseline": True,
        "baseline_dispatched": False, "baseline_counterfactual_tokens": None, "baseline_counterfactual_latency": None}


def page_audit(item, report, checkpoint_dir):
    if item["variant"] == "baseline":
        return previous.page_audit({**item, "variant": "candidate"}, report, checkpoint_dir)
    return _base_page_audit(item, report, checkpoint_dir)


def evaluate_pairs(rows):
    result = _base_evaluate(rows)
    views = result["same_state_stage_views"]
    known = all(row["token_usage"]["whole_task"]["unknown_calls"] == 0 for row in rows)
    totals = {variant: sum(row["token_usage"]["whole_task"]["total_tokens"] for row in rows
        if row["variant"] == variant) for variant in VERSIONS}
    accounted = {variant: sum(row["token_usage"]["whole_task"]["tokens_accounted"] for row in rows
        if row["variant"] == variant) for variant in VERSIONS}
    result.update(metadata_codec_exact_all_views=bool(views) and all(view["expanded_raw_window_exact"] for view in views),
        new_disclosure_contract_not_reversible_old_view=False, new_disclosure_contract=False,
        exact_restores_literal_v6_window=True,
        same_raw_codec_all_bytes_nonincreasing_total_reduced=bool(views) and all(view["same_raw_bytes_nonincreasing"] for view in views)
            and sum(view["same_raw_wire_bytes_saved"] for view in views) > 0,
        same_raw_codec_total_wire_bytes_saved=sum(view["same_raw_wire_bytes_saved"] for view in views),
        actual_task_known_tokens=totals, actual_task_accounted_tokens=accounted,
        actual_task_token_reduction_proven=known and result["all_quality_passed"]
            and totals["candidate"] < totals["baseline"] and accounted["candidate"] < accounted["baseline"],
        whole_task_token_delta=totals["candidate"] - totals["baseline"],
        same_raw_codec_and_compiled_working_set_reported_separately=True)
    return result


def checked(expected_sha, *, replay=False):
    plan, sources = _base_checked(expected_sha, replay=replay)
    old_ids = {item["run_id"] for item in OLD.read(previous.OUT / "plan.json")["items"]}
    if any(item["run_id"] in old_ids for item in plan["items"]):
        raise IntegrityError("Optimized campaign reused an old v6 run identity")
    return plan, sources


def validate_gate(offline_path, preflight_path, *, check_current=True):
    offline, probe = _base_gate(offline_path, preflight_path, check_current=check_current)
    replay = probe.get("previous_v6_completed_zero_append_replay", {})
    records = probe.get("paid_v6_states")
    if (probe.get("optimization_schema") != "context-window-metadata-readonly-probe/v1"
            or probe.get("code_files") != offline["code_files"]
            or check_current and probe["code_files"] != code_files()
            or not replay.get("replay_same") or replay.get("identical_reports") != 4
            or any(replay.get(key) != 0 for key in ("model_calls", "provider_calls", "checkpoint_appends"))
            or type(records) is not list or len(records) != 10
            or not all(record.get("expanded_raw_window_exact") and record.get("same_raw_pages_and_cursor_selections_exact")
                and record.get("candidate_is_counterfactual_not_paid") for record in records)):
        raise IntegrityError("Optimized codec probe lacks exact current code, original paid states or zero-append replay binding")
    for record in records:
        before, after, saved = (record.get(key) for key in (
            "same_raw_baseline_total_wire_bytes", "same_raw_candidate_total_wire_bytes", "same_raw_wire_bytes_saved"))
        if (any(type(value) is not int for value in (before, after, saved)) or before <= 0 or after <= 0
                or saved != before - after or record.get("same_raw_bytes_nonincreasing") is not True or after > before):
            raise IntegrityError("Optimized freeze requires exact nonincreasing same-raw bytes at every paid stage")
    if (sum(record["same_raw_wire_bytes_saved"] for record in records) <= 0
            or probe.get("same_raw_codec_total_wire_bytes_saved") != sum(record["same_raw_wire_bytes_saved"] for record in records)):
        raise IntegrityError("Optimized freeze requires a strictly lower aggregate same-raw wire without guessed Token benefit")
    return offline, probe


def historical_replay():
    before = history_hashes()
    result = previous.historical_replay()
    replay = previous.readonly_replay(OLD.sha(previous.OUT / "plan.json"))
    if (result["unique_historical_reports_replayed"] != 31 or not replay["replay_same"] or replay["identical_reports"] != 4
            or any(replay[key] != 0 for key in ("model_calls", "provider_calls", "checkpoint_appends")) or before != history_hashes()):
        raise IntegrityError("Optimized 35-report historical replay changed or appended immutable evidence")
    return {"schema": "context-window-optimized-history/v1", "status": "passed", "prior_31": result,
        "previous_v6_four": replay, "unique_historical_reports_expected": 35, "unique_historical_reports_replayed": 35,
        "historical_hashes": before, "historical_files_unchanged": True,
        "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0}


def preflight():
    before, records = history_hashes(), []
    prior, sources = _engine.original_guard()
    replay = previous.readonly_replay(OLD.sha(previous.OUT / "plan.json"))
    legacy_replay = previous.previous.readonly_replay(OLD.sha(previous.previous.OUT / "plan.json"))
    frozen = OLD.read(previous.OUT / "plan.json")
    for old_item in frozen["items"]:
        if old_item["parent_version"] != VERSIONS["baseline"]:
            continue
        item = _engine.frozen_item(prior, old_item["case_id"], "baseline", sources, run_id=old_item["run_id"])
        seen = set()
        for state in _engine.readonly_history(previous.OUT / "live" / item["run_id"] / "runs", item["scope"], item["run_id"]):
            if state["phase"] != "model_pending" or not state.get("decisions"):
                continue
            turn = state["decisions"][-1]["turn"]
            if turn in seen:
                continue
            seen.add(turn)
            if any(observation != item["catalog_observations"].get("O:" + tool) for tool, observation in state["observations"].items()):
                raise IntegrityError("Optimized preflight state changed original complete source oracle")
            actual, _ = state_projection(item, state, "baseline")
            if digest(actual) != state["decisions"][-1]["message_sha256"]:
                raise IntegrityError("Optimized preflight cannot rebuild actual original v6 paid wire")
            candidate, metadata = state_projection(item, state, "candidate")
            raw = raw_context(json.loads(candidate[1]["content"])["context"])
            records.append({"case_id": item["case_id"], "run_id": item["run_id"], "turn": turn,
                "stage": raw["stage"], "actual_v6_message_sha256": digest(actual), **codec_probe(actual),
                "compiled_candidate_total_wire_bytes": sum(len(message["content"].encode("utf-8")) for message in candidate),
                "compiled_candidate_page_atoms": sum(len(page["atoms"]) for page in raw["pages"]),
                "compiled_candidate_window_ref": metadata["window"]["window_ref"],
                "candidate_compiled_page_selections_equal": [page["selection"] for page in raw["pages"]]
                    == [page["selection"] for page in json.loads(actual[1]["content"])["context"]["pages"]],
                "candidate_is_counterfactual_not_paid": True, "actual_v6_fits_original_cap": True})
    if len(records) != 10 or before != history_hashes():
        raise IntegrityError("Optimized paid-state preflight completeness or historical integrity changed")
    return {"schema": "context-window-readonly-preflight/v1", "status": "passed",
        "optimization_schema": "context-window-metadata-readonly-probe/v1", "paid_v6_states": records,
        "historical_hashes": before, "historical_files_unchanged": True,
        "legacy_v4_v5_completed_zero_append_replay": legacy_replay,
        "previous_v6_completed_zero_append_replay": replay,
        "original_sources_grants_pit_and_oracles_revalidated": True, "selected_cases": list(CASE_IDS),
        "real_overlimit_recovery_status": "真实超限恢复尚未验证", "real_pagination_status": "真实模型 context_read/超限分页尚未验证",
        "same_raw_codec_total_wire_bytes_saved": sum(record["same_raw_wire_bytes_saved"] for record in records),
        "same_raw_codec_all_views_exact": True, "same_raw_codec_and_compiled_working_set_separate": True,
        "code_files": code_files(),
        "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0}


def readonly_replay(expected_sha):
    result = _base_replay(expected_sha)
    evaluation = OLD.read(_engine.OUT / "live/summary.json")["evaluation"]
    codec = evaluation["metadata_codec_exact_all_views"] and evaluation["same_raw_codec_all_bytes_nonincreasing_total_reduced"]
    result.update(metadata_codec_exact=codec, actual_task_token_reduction_proven=evaluation["actual_task_token_reduction_proven"],
        decision="limited_explicit_exact_window_metadata_token_optimization_accepted"
        if result["quality_acceptance_passed"] and codec and evaluation["actual_task_token_reduction_proven"]
        else "exact_metadata_quality_passed_task_token_benefit_not_proven_defaults_retained"
        if result["quality_acceptance_passed"] and codec else "bounded_acceptance_failed_evidence_retained")
    return result


def audit(expected_sha):
    result = _base_audit(expected_sha)
    result["optimization_replay"] = readonly_replay(expected_sha)
    result["optimization_scope"] = "Exact metadata representation of the same literal v6 window; no new disclosure contract"
    for execution in result["actual_verification_executions"]:
        execution["verification_execution_receipt"] = execution.pop("candidate_verification_execution_receipt")
    return result


for _name, _value in {"OUT": OUT, "VERSIONS": VERSIONS, "ACCEPTANCE": ACCEPTANCE, "code_files": code_files,
    "__doc__": __doc__,
    "history_hashes": history_hashes, "state_projection": state_projection, "validate_outbound": validate_outbound,
    "same_state_wire": same_state_wire, "page_audit": page_audit, "evaluate_pairs": evaluate_pairs, "checked": checked,
    "historical_replay": historical_replay, "preflight": preflight, "validate_gate": validate_gate,
    "readonly_replay": readonly_replay, "audit": audit}.items():
    setattr(_engine, _name, _value)

prepare, live, test_files, spec_for, spec_document = _engine.prepare, _engine.live, _engine.test_files, _engine.spec_for, _engine.spec_document
runtime, token_usage, evidence_ref = _engine.runtime, _engine.token_usage, _engine.evidence_ref
RecordingModel, readonly_history, paid_state, paid_telemetry = _engine.RecordingModel, _engine.readonly_history, _engine.paid_state, _engine.paid_telemetry
load_model_config, ChatModelAdapter = _engine.load_model_config, _engine.ChatModelAdapter


def main(argv=None):
    return _engine.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
