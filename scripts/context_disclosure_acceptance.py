"""Independent bounded Parent v4/v5 phase-gated disclosure acceptance.

Reuse the existing DynamicRuntime, immutable original inputs/oracles and campaign
accounting conventions. No provider collection, model replacement or paid retry.
The candidate retains full audits server-side and discloses exact phase-gated briefs.
"""
import argparse
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from threading import Lock
import time
import uuid
from unittest.mock import patch

import phase6_evaluate as infra
import context_verification_acceptance as legacy
original, repair, OLD = infra.original, infra.repair, infra.OLD
from stock_research.errors import DataError, IntegrityError, ValidationError
from stock_research.model_adapters.chat import ChatModelAdapter, ChatResult, load_model_config
from stock_research.models import canonical_json, digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest, FinancialRequest, MarketRequest, ParallelParentSpec
from stock_research.research.dynamic_protocol import dynamic_messages
from stock_research.research.report import markdown
from stock_research.research.runtime import validate_model_result

OUT = OLD.ROOT / ".artifacts/context-disclosure/phase-gated-v5-20261007"
VERSIONS = {"baseline": "dynamic-parent-parallel-v4", "candidate": "dynamic-parent-parallel-v5"}
CASE_IDS = ("p5-603207", "p5-688184")
ORDER = ((CASE_IDS[0], "baseline"), (CASE_IDS[0], "candidate"),
         (CASE_IDS[1], "candidate"), (CASE_IDS[1], "baseline"))
LIMITS, MAX_RUNS = (64, 384000, 1800), 4
CHILD_SPECS, SAFETY = infra.CHILD_SPECS, infra.SAFETY
TIMING_DEFINITIONS = infra.TIMING_DEFINITIONS
ACCEPTANCE = {
    "quality": "complete original source oracle, lawful insufficiency, mandatory actual verification execution",
    "disclosure": "full audit server-side; brief iff authoritative verification ready; exact current-message revision codec",
    "counterfactual": "exact same durable full state rebuilt with v4 solely for system+user byte sizing",
    "replay": "zero model/provider/checkpoint appends; exact original report and paid-state reconstruction",
    "performance": "paired actual known/accounted Token and wall/model I/O; pricing unavailable means cost unknown",
    "performance_gate": "same-state system+user bytes never increase; aggregate bytes strictly decrease; real task Token independent",
    "scope": "phase-gated audit disclosure only; no generic pagination, unlimited continuation or parallel expansion"}


def spec_for(variant):
    if variant not in VERSIONS:
        raise IntegrityError("Phase-gated disclosure variant outside frozen comparison")
    return ParallelParentSpec(version=VERSIONS[variant])


def runtime(service, checkpoints, variant, model=None, **kwargs):
    return DynamicRuntime(service, checkpoints, model, spec_for(variant), domain_child_specs=CHILD_SPECS, **kwargs)


def code_files():
    result = {**infra.code_files(), "scripts/context_disclosure_acceptance.py": OLD.sha(Path(__file__)),
              "scripts/context_verification_acceptance.py": OLD.sha(Path(legacy.__file__))}
    result.update({p.relative_to(OLD.ROOT).as_posix(): OLD.sha(p)
        for p in sorted((OLD.ROOT / "src/stock_research/research").glob("*.py"))})
    return result


def test_files():
    return {path.relative_to(OLD.ROOT).as_posix(): OLD.sha(path)
        for path in sorted((OLD.ROOT / "tests").rglob("*.py"))}


def history_hashes():
    hashes = {"phase" + str(n): original.file_hashes(OLD.ROOT / ".artifacts" / ("phase" + str(n)))
        for n in range(2, 7)}
    hashes["context-verification"] = original.file_hashes(OLD.ROOT / ".artifacts/context-verification")
    hashes["legacy-acceptance-code"] = {
        "scripts/context_verification_acceptance.py": OLD.sha(Path(legacy.__file__)),
        "tests/test_context_verification_acceptance.py": OLD.sha(OLD.ROOT / "tests/test_context_verification_acceptance.py")}
    return hashes


original_guard = infra.original_guard


def readonly_history(directory, scope, run_id):
    """Read all append-chain rows with SQLite read-only mode; never creates a DB."""
    path = Path(directory) / "checkpoints.sqlite3"
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
        rows = connection.execute("SELECT seq,previous,hash,payload FROM checkpoints WHERE scope=? AND run=? ORDER BY seq",
            (scope, run_id)).fetchall()
    previous, result = "", []
    for expected, (seq, parent, checksum, payload) in enumerate(rows):
        state = json.loads(payload)
        if seq != expected or parent != previous or digest({"previous": parent, "state": state}) != checksum:
            raise IntegrityError("Phase-gated disclosure checkpoint chain changed")
        result.append(state)
        previous = checksum
    if not result:
        raise IntegrityError("Phase-gated disclosure paid state absent in bound scope/run")
    return result


def paid_state(directory, item, messages):
    payload = json.loads(messages[1]["content"])
    turn = payload["control"]["decision"]
    matches = [state for state in readonly_history(directory, item["scope"], item["run_id"])
        if state["phase"] == "model_pending" and state.get("decisions")
        and state["decisions"][-1]["turn"] == turn and state["decisions"][-1]["message_sha256"] == digest(messages)]
    if not matches:
        raise IntegrityError("Phase-gated disclosure wire has no exact durable pending paid state")
    state = matches[0]
    if state["request"] != item["request"] or state["run_id"] != item["run_id"] or state["spec_version"] != item["parent_version"]:
        raise IntegrityError("Phase-gated disclosure paid state request/run/Spec differs")
    if [check["id"] for check in runtime(None, None, item["variant"])._check_results(state, DynamicRequest.from_dict(item["request"]))] != item["required_check_ids"]:
        raise IntegrityError("Phase-gated disclosure required execution checks changed")
    for tool, observation in state["observations"].items():
        if observation != item["catalog_observations"].get("O:" + tool):
            raise IntegrityError("Phase-gated disclosure paid state exceeds complete original source oracle")
    return state


def state_projection(item, state, variant, *, diagnostic=False):
    """The full durable state is authority, never candidate model-view contents."""
    runner = runtime(None, None, variant)
    request = DynamicRequest.from_dict(item["request"])
    access = type("BoundScope", (), {"scope": item["scope"]})()
    tools = json.loads(item["messages"][1]["content"])["available_tools"]
    return dynamic_messages(request, tools, list(state["observations"].values()), state["requirements"],
        state["plans"][-1]["steps"] if state["plans"] else [], 4000000 if diagnostic else 12000,
        decision=state["decisions"][-1]["turn"], protocol_error=state.get("protocol_error"),
        version=VERSIONS[variant], finish_rejection=state.get("finish_rejection"),
        delegation_results=[{"tool": c["domain"] + "_child", "domain": c["domain"], "status": c["status"],
                            "result_ref": c["result_ref"]} for c in state["child_results"]],
        **runner._context_arguments(state, access))


def state_messages(item, state, variant, *, diagnostic=False):
    return state_projection(item, state, variant, diagnostic=diagnostic)[0]


def role_spec(item, role):
    if role == item["parent_version"]:
        return spec_for(item["variant"])
    for spec in CHILD_SPECS.values():
        if role == spec.version:
            return spec
    raise IntegrityError("Phase-gated disclosure outbound role differs from frozen Parent/Child versions")


def validate_outbound(messages, item, kwargs, checkpoints):
    payload = json.loads(messages[1]["content"])
    role, control = payload["protocol_version"], payload["control"]
    spec = role_spec(item, role)
    if role == item["parent_version"]:
        state = paid_state(checkpoints, item, messages)
        rebuilt, metadata = state_projection(item, state, item["variant"])
        if state["context"] != {"status": "prepared", **metadata}:
            raise IntegrityError("Phase-gated disclosure paid metadata/audit differs from complete durable state")
        tools = json.loads(item["messages"][1]["content"])["available_tools"]
        if control["decision"] == 1 and messages != item["messages"]:
            raise IntegrityError("Phase-gated disclosure first wire changed after freeze")
    else:
        domain = next(domain for domain, child in CHILD_SPECS.items() if child.version == role)
        parent = DynamicRequest.from_dict(item["request"])
        request = (FinancialRequest if domain == "financial" else MarketRequest).from_parent(parent)
        tools, observations, checks = [domain], payload["observations"], payload["required_checks"]
        if any(observation != item["authorization_envelope"]["source_observations"][domain] for observation in observations):
            raise IntegrityError("Phase-gated disclosure Child exceeds immutable authorized source")
        rebuilt, _ = dynamic_messages(request, tools, observations, checks, control["plan"], 12000,
            decision=control["decision"], protocol_error=control.get("previous_action_error"), version=role,
            finish_rejection=control.get("finish_rejection"))
    if rebuilt != messages or payload["available_tools"] != tools or kwargs.get("max_tokens") != spec.output_tokens:
        raise IntegrityError("Phase-gated disclosure outbound wire differs from exact authoritative state")
    if sum(len(message["content"].encode("utf-8")) for message in messages) > 12000:
        raise IntegrityError("Phase-gated disclosure actual system+user bytes exceed original cap")
    return role, spec, control["decision"]


def same_state_wire(messages, item, checkpoints):
    payload = json.loads(messages[1]["content"])
    if payload["protocol_version"] != VERSIONS["candidate"]:
        return None
    from stock_research.research.dynamic_context import expand_disclosure_view, expand_phase_gated_view
    state = paid_state(checkpoints, item, messages)
    baseline = state_messages(item, state, "baseline", diagnostic=True)
    full = expand_disclosure_view(json.loads(baseline[1]["content"])["context"])
    current = expand_phase_gated_view(payload["context"])
    _, metadata = state_projection(item, state, "candidate", diagnostic=True)
    audit = metadata.get("verification_audit")
    # Displayed financial content must remain exact. Only disclosure protocol,
    # revision representation and manifest/brief policy are intentionally different.
    ignored = {"schema", "disclosure_contract", "verification_manifest", "verification_brief", "state_versions"}
    if {k: v for k, v in full.items() if k not in ignored} != {k: v for k, v in current.items() if k not in ignored}:
        raise IntegrityError("Phase-gated disclosure changed same-state financial content or catalog")
    bound_arguments = runtime(None, None, "candidate")._context_arguments(
        state, type("BoundScope", (), {"scope": item["scope"]})())
    revisions = bound_arguments["parent_execution_revisions"]
    if current["state_versions"] != revisions:
        raise IntegrityError("Phase-gated disclosure codec differs from authoritative execution revisions")
    ready = metadata.get("verification_ready")
    brief = current.get("verification_brief")
    if type(ready) is not bool or (brief is not None) != ready or "verification_manifest" in payload["context"]:
        raise IntegrityError("Phase-gated disclosure brief/manifest violates authoritative readiness")
    if audit is not None:
        old_audit = full["verification_manifest"]
        audit_fields = {"schema", "input_refs", "manifest_ref"}
        if (audit.get("schema") != "dynamic-verification-audit/v1"
                or audit.get("input_refs") != bound_arguments["parent_verification_inputs"]
                or digest({key: value for key, value in audit.items() if key != "manifest_ref"}) != audit["manifest_ref"]
                or {key: value for key, value in audit.items() if key not in audit_fields}
                != {key: value for key, value in old_audit.items() if key not in audit_fields}):
            raise IntegrityError("Phase-gated server-side audit differs from original full v4 audit or raw inputs")
    if ready:
        expected_counts = {kind: value["count"] for kind, value in audit["collections"].items()}
        expected_counts["source_records"] = audit["source_records"]
        if brief["counts"] != expected_counts or brief["source_refs"] != sorted("O:" + source for source in state["computed_sources"]):
            raise IntegrityError("Phase-gated verification brief differs from full authoritative source collections")
    actual = sum(len(message["content"].encode("utf-8")) for message in messages)
    prior = sum(len(message["content"].encode("utf-8")) for message in baseline)
    return {"turn": payload["control"]["decision"], "stage": full["stage"],
        "candidate_message_sha256": digest(messages), "baseline_message_sha256": digest(baseline),
        "candidate_total_wire_bytes": actual, "baseline_same_state_total_wire_bytes": prior,
        "net_wire_bytes_saved": prior - actual, "system_bytes_candidate": len(messages[0]["content"].encode("utf-8")),
        "system_bytes_baseline": len(baseline[0]["content"].encode("utf-8")),
        "baseline_same_state_evidence_bodies": len(full["evidence"]),
        "candidate_disclosed_evidence_rows": len(payload["context"].get("evidence", [])),
        "same_state_bytes_nonincreasing": actual <= prior,
        "candidate_verification_ready": ready, "candidate_brief_present": brief is not None,
        "candidate_manifest_present": False, "complete_audit_persisted_server_side": audit is not None,
        "candidate_brief_counts": brief["counts"] if brief is not None else None,
        "exact_execution_revisions_decoded": True, "same_financial_projection": True,
        "candidate_state_versions_bytes": len(canonical_json(payload["context"]["state_versions"]).encode("utf-8")),
        "candidate_verification_brief_bytes": len(canonical_json(payload["context"]["verification_brief"]).encode("utf-8")) if brief is not None else 0,
        "baseline_full_manifest_bytes": len(canonical_json(full["verification_manifest"]).encode("utf-8")),
        "same_full_source_state": True, "new_disclosure_contract": True,
        "candidate_context_decodes_exact_baseline": False, "baseline_dispatched": False,
        "baseline_counterfactual_tokens": None, "baseline_counterfactual_latency": None}


def evidence_ref(path):
    path = Path(path).resolve()
    try:
        name = path.relative_to(OLD.ROOT.resolve()).as_posix()
    except ValueError:
        raise IntegrityError("Phase-gated disclosure gate evidence must be workspace-local") from None
    return {"path": name, "sha256": OLD.sha(path)}


def spec_document():
    return {variant: {"identity": spec_for(variant).identity, "version": version,
        "local_limits": original.local_limits(spec_for(variant)),
        "root_limits": {"decisions": 16, "tools": 18, "tokens": 96000}}
        for variant, version in VERSIONS.items()}


def frozen_item(prior, case_id, variant, sources, *, run_id=None):
    old_item = next(item for item in prior["items"] if item["case_id"] == case_id and item["route"] == "parallel")
    case = next(case for case in prior["cases"] if case["id"] == case_id)
    service, access = sources.context(case)
    request = DynamicRequest.from_dict(old_item["request"])
    item = deepcopy(old_item)
    item.update(run_id=run_id or uuid.uuid4().hex, variant=variant, spec_identity=spec_for(variant).identity,
        parent_version=VERSIONS[variant], original_run_id=old_item["run_id"], independent_new_task_count=0)
    item["messages"] = runtime(service, None, variant).preview(request, access, run_id=item["run_id"])
    if (item["catalog_observations"] != original.parallel.catalog_oracle(service, access, request)
            or item["authorization_envelope"] != OLD.authorized_envelope(service, access, request)
            or item["input_ref"] != digest(sources.inputs(case))):
        raise IntegrityError("Phase-gated disclosure immutable original request/source/oracle changed")
    return item


def preflight():
    """Only real existing materials; no extra facts, changed questions or models."""
    before = history_hashes()
    prior, sources = original_guard()
    records, overflows = [], []
    legacy_replay = legacy.readonly_replay(OLD.sha(legacy.OUT / "plan.json"))
    if (not legacy_replay["replay_same"] or legacy_replay["identical_reports"] != 4
            or any(legacy_replay[key] != 0 for key in ("model_calls", "provider_calls", "checkpoint_appends"))):
        raise IntegrityError("Phase-gated preflight cannot preserve four prior completed v3/v4 reports without appends")
    # Real v4 paid states exist in the completed W1a campaign. Reauthorize the
    # same original sources first and reconstruct with the full durable state.
    previous = OLD.read(legacy.OUT / "plan.json")
    for prior_item in previous["items"]:
        if prior_item["parent_version"] != VERSIONS["baseline"]:
            continue
        item = frozen_item(prior, prior_item["case_id"], "baseline", sources, run_id=prior_item["run_id"])
        checkpoint_dir = legacy.OUT / "live" / item["run_id"] / "runs"
        seen = set()
        for state in readonly_history(checkpoint_dir, item["scope"], item["run_id"]):
            if state["phase"] != "model_pending" or not state.get("decisions"):
                continue
            turn = state["decisions"][-1]["turn"]
            if turn in seen:
                continue
            seen.add(turn)
            for tool, observation in state["observations"].items():
                if observation != item["catalog_observations"].get("O:" + tool):
                    raise IntegrityError("Preflight paid state differs from reauthorized original oracle")
            messages = state_messages(item, state, "baseline", diagnostic=True)
            if digest(messages) != state["decisions"][-1]["message_sha256"]:
                raise IntegrityError("Preflight cannot reconstruct original v4 paid wire")
            from stock_research.research.dynamic_context import expand_disclosure_view
            view = expand_disclosure_view(json.loads(messages[1]["content"])["context"])
            amount = sum(len(message["content"].encode("utf-8")) for message in messages)
            candidate_messages = state_messages(item, state, "candidate", diagnostic=True)
            candidate_payload = json.loads(candidate_messages[1]["content"])
            candidate_amount = sum(len(message["content"].encode("utf-8")) for message in candidate_messages)
            records.append({"case_id": item["case_id"], "run_id": item["run_id"], "turn": turn,
                "stage": view["stage"], "actual_protocol_version": VERSIONS["baseline"],
                "system_user_bytes": amount, "evidence_bodies": len(view["evidence"]),
                "candidate_counterfactual_system_user_bytes": candidate_amount,
                "candidate_counterfactual_evidence_bodies": len(candidate_payload["context"].get("evidence", [])),
                "counterfactual_tokens": None, "candidate_fits_original_cap": candidate_amount <= 12000,
                "current_v4_over_limit": amount > 12000})
    # Record every historical reported overflow without relabeling a pre-v4
    # failure as a current-v4 bottleneck.
    for phase in (4, 5, 6):
        for path in sorted((OLD.ROOT / ".artifacts" / ("phase" + str(phase))).rglob("report.json")):
            report = OLD.read(path)
            if report.get("stop_reason") == "dynamic_context_budget_exceeded":
                overflows.append({"path": path.relative_to(OLD.ROOT).as_posix(), "sha256": OLD.sha(path),
                    "status": report.get("status"), "stop_reason": report["stop_reason"],
                    "current_v4_overlimit_proven": False,
                    "qualification": "historical pre-catalog-remediation failure; not current-v4 overflow"})
    if history_hashes() != before:
        raise IntegrityError("Read-only preflight changed historical immutable materials")
    suitable = any(record["current_v4_over_limit"] for record in records)
    return {"schema": "context-disclosure-readonly-preflight/v1", "status": "passed",
        "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0,
        "original_sources_grants_pit_and_oracles_revalidated": True,
        "historical_hashes": before, "historical_files_unchanged": True,
        "legacy_v3_v4_completed_zero_append_replay": legacy_replay,
        "paid_v4_states": records, "recorded_historical_overflows": overflows,
        "suitable_real_v4_overlimit_case_found": suitable,
        "real_overlimit_recovery_status": "eligible_existing_case_found" if suitable else "真实超限恢复尚未验证",
        "selected_cases": list(CASE_IDS), "scope": "existing real v4 paid states and all historical reported context stops",
        "remaining_boundary": "No generic pagination, validator batching or unlimited continuation"}


def validate_gate(offline_path, preflight_path, *, check_current=True):
    offline, probe = OLD.read(offline_path), OLD.read(preflight_path)
    if (offline.get("schema") != "context-disclosure-offline-gate/v1" or offline.get("status") != "passed"
            or offline.get("command") != "PYTHONPATH=src python -m unittest discover -s tests -v"
            or offline.get("failures") != 0 or offline.get("errors") != 0
            or type(offline.get("tests_run")) is not int or offline["tests_run"] <= 0
            or type(offline.get("skipped")) is not int or not 0 <= offline["skipped"] < offline["tests_run"]):
        raise IntegrityError("Independent current offline checks must pass before any live freeze")
    if (type(offline.get("code_files")) is not dict or type(offline.get("test_files")) is not dict
            or type(offline.get("log")) is not dict or set(offline["log"]) != {"path", "sha256"}
            or not offline["code_files"] or not offline["test_files"]
            or evidence_ref(OLD.ROOT / offline["log"]["path"]) != offline["log"]
            or check_current and (offline["code_files"] != code_files() or offline["test_files"] != test_files())):
        raise IntegrityError("Offline acceptance evidence lacks exact current implementation/tests/log binding")
    if (probe.get("schema") != "context-disclosure-readonly-preflight/v1" or probe.get("status") != "passed"
            or any(probe.get(key) != 0 for key in ("model_calls", "provider_calls", "checkpoint_appends"))
            or probe.get("historical_hashes") != history_hashes() or probe.get("selected_cases") != list(CASE_IDS)
            or not probe.get("original_sources_grants_pit_and_oracles_revalidated")
            or not probe.get("historical_files_unchanged")):
        raise IntegrityError("Frozen read-only real-case/source preflight changed or failed")
    prior_replay = probe.get("legacy_v3_v4_completed_zero_append_replay", {})
    if (not prior_replay.get("replay_same") or prior_replay.get("identical_reports") != 4
            or any(prior_replay.get(key) != 0 for key in ("model_calls", "provider_calls", "checkpoint_appends"))):
        raise IntegrityError("Frozen legacy completed report replay lacks exact zero append evidence")
    return offline, probe


def prepare(offline_evidence, preflight_evidence):
    if OUT.exists():
        raise IntegrityError("Independent phase-gated disclosure campaign already exists")
    offline, probe = validate_gate(offline_evidence, preflight_evidence)
    prior, sources = original_guard()
    cases = [deepcopy(next(case for case in prior["cases"] if case["id"] == identity)) for identity in CASE_IDS]
    validation = original.validate_cases(cases, sources.context)
    if not validation["all_cases_contract_valid"]:
        raise IntegrityError("Independent phase-gated disclosure existing input contract invalid")
    items = [frozen_item(prior, case_id, variant, sources) for case_id, variant in ORDER]
    config = load_model_config()
    if config.model != prior["model"] or digest(config.endpoint) != prior["endpoint_sha256"]:
        raise IntegrityError("Independent phase-gated disclosure configured endpoint/model differs from original")
    plan = {"schema": "context-disclosure-frozen-plan/v1", "cases": cases, "items": items,
        "contract_validation": validation, "model": config.model, "endpoint_sha256": digest(config.endpoint),
        "offline_gate": evidence_ref(offline_evidence), "readonly_preflight": evidence_ref(preflight_evidence),
        "code_files": code_files(), "history_hashes": history_hashes(), "specs": spec_document(),
        "child_specs": {domain: {"identity": spec.identity, "version": spec.version, "limits": original.local_limits(spec)}
                        for domain, spec in CHILD_SPECS.items()},
        "campaign_limits": {"max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "max_seconds": LIMITS[2]},
        "maximum_existing_cases": 2, "maximum_campaign_runs": MAX_RUNS, "scheduled_run_count": len(items),
        "reserved_repair_run_slots": 0, "existing_case_count": len(cases), "independent_new_task_count": 0,
        "comparison_order": [list(pair) for pair in ORDER], "context_limit_bytes": 12000,
        "child_protocol_opt_in": "v3", "provider_network_calls": 0, "old_budget_reused": False,
        "original_functional_results": {"passed": 8, "total": 9}, "historical_failures_and_denominators_preserved": True,
        "unknown_paid_outcomes_stop_external_dispatch": True, "default_changed": False,
        "automatic_routing": False, "parallel_enablement_expanded": False, "threshold_tuning": False,
        "real_overlimit_recovery_status": probe["real_overlimit_recovery_status"],
        "confounds": ["two existing known-source nonblind cases", "rotated pair order without randomization/cache reset",
                      "endpoint service time uncontrolled; no statistical or P95 improvement claim"],
        "acceptance": ACCEPTANCE, "timing_definitions": TIMING_DEFINITIONS,
        "monetary_cost": {"known": False, "reason": "no frozen endpoint price or invoice supplied; actual Token disclosed"}}
    OLD.write_new(OUT / "plan.json", plan)
    return {"prepared": True, "plan_sha256": OLD.sha(OUT / "plan.json"), "scheduled_run_count": len(items),
        "independent_new_task_count": 0, "model_calls": 0, "provider_calls": 0}


def checked(expected_sha, *, replay=False):
    if not isinstance(expected_sha, str) or OLD.sha(OUT / "plan.json") != expected_sha:
        raise IntegrityError("Independent phase-gated disclosure explicit frozen plan hash differs")
    plan, (prior, sources) = OLD.read(OUT / "plan.json"), original_guard()
    expected = {
        "schema": "context-disclosure-frozen-plan/v1", "specs": spec_document(), "history_hashes": history_hashes(),
        "campaign_limits": {"max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "max_seconds": LIMITS[2]},
        "context_limit_bytes": 12000, "comparison_order": [list(pair) for pair in ORDER],
        "maximum_campaign_runs": 4, "maximum_existing_cases": 2, "reserved_repair_run_slots": 0,
        "scheduled_run_count": 4, "existing_case_count": 2, "independent_new_task_count": 0,
        "old_budget_reused": False, "default_changed": False, "automatic_routing": False,
        "parallel_enablement_expanded": False, "threshold_tuning": False,
        "child_protocol_opt_in": "v3", "provider_network_calls": 0,
        "original_functional_results": {"passed": 8, "total": 9}, "historical_failures_and_denominators_preserved": True,
        "unknown_paid_outcomes_stop_external_dispatch": True,
        "acceptance": ACCEPTANCE, "timing_definitions": TIMING_DEFINITIONS,
        "monetary_cost": {"known": False, "reason": "no frozen endpoint price or invoice supplied; actual Token disclosed"},
        "child_specs": {domain: {"identity": spec.identity, "version": spec.version, "limits": original.local_limits(spec)}
                        for domain, spec in CHILD_SPECS.items()}}
    if any(plan.get(key) != value for key, value in expected.items()) or not replay and plan["code_files"] != code_files():
        raise IntegrityError("Independent phase-gated disclosure frozen contract/code/limits changed")
    for key in ("offline_gate", "readonly_preflight"):
        if evidence_ref(OLD.ROOT / plan[key]["path"]) != plan[key]:
            raise IntegrityError("Independent phase-gated disclosure gate evidence changed")
    _, probe = validate_gate(OLD.ROOT / plan["offline_gate"]["path"], OLD.ROOT / plan["readonly_preflight"]["path"],
        check_current=not replay)
    if plan["real_overlimit_recovery_status"] != probe["real_overlimit_recovery_status"]:
        raise IntegrityError("Independent phase-gated disclosure real-overlimit qualification changed")
    expected_cases = [next(case for case in prior["cases"] if case["id"] == identity) for identity in CASE_IDS]
    if plan["cases"] != expected_cases or original.validate_cases(plan["cases"], sources.context) != plan["contract_validation"]:
        raise IntegrityError("Independent phase-gated disclosure existing case/source contract changed")
    if [(item["case_id"], item["variant"]) for item in plan["items"]] != list(ORDER):
        raise IntegrityError("Independent phase-gated disclosure frozen execution order changed")
    identities = [item["run_id"] for item in plan["items"]]
    old_identities = {item["run_id"] for item in prior["items"]}
    old_identities.update(item["run_id"] for item in OLD.read(infra.OUT / "plan.json")["items"])
    old_identities.update(item["run_id"] for item in OLD.read(legacy.OUT / "plan.json")["items"])
    if len(set(identities)) != 4 or set(identities) & old_identities:
        raise IntegrityError("Independent phase-gated disclosure must use four fresh run identities")
    for item in plan["items"]:
        if frozen_item(prior, item["case_id"], item["variant"], sources, run_id=item["run_id"]) != item:
            raise IntegrityError("Independent phase-gated disclosure original request/source/oracle/preview changed")
    return plan, sources


assess = infra.assess


def paid_telemetry(item, report, children, directory, intents):
    reports = {item["parent_version"]: report}
    reports.update({CHILD_SPECS[child.get("domain", "financial")].version: child for child in children})
    bound, comparisons = set(), []
    for intent in intents:
        prefix = f"{intent['number']:03d}"
        messages = OLD.read(Path(directory) / (prefix + "-messages.json"))
        receipt = OLD.read(Path(directory) / (prefix + "-receipt.json"))
        payload = json.loads(messages[1]["content"])
        role, turn = payload["protocol_version"], payload["control"]["decision"]
        telemetry = reports[role]["context_telemetry"][turn - 1]
        actual = sum(len(message["content"].encode("utf-8")) for message in messages)
        if ((role, turn) in bound or telemetry["message_sha256"] != digest(messages)
                or telemetry["total_context_bytes"] != actual or telemetry["context_after_compaction_bytes"] != actual
                or actual > 12000 or telemetry["context_limit_bytes"] != 12000
                or not telemetry["model_dispatched"] or telemetry["context_budget_exceeded"]):
            raise IntegrityError("Phase-gated disclosure telemetry differs from exact bounded system+user paid wire")
        bound.add((role, turn))
        if role == VERSIONS["candidate"]:
            checkpoint_dir = Path(directory).parent / item["run_id"] / "runs"
            comparisons.append(same_state_wire(messages, item, checkpoint_dir))
        if intent["usage_status"] == "known" and any(telemetry[a] != receipt[b] for a, b in
                (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens"), ("total_tokens", "total_tokens"))):
            raise IntegrityError("Phase-gated disclosure telemetry Token usage differs from durable receipt")
    dispatched = {(role, index + 1) for role, value in reports.items()
        for index, telemetry in enumerate(value.get("context_telemetry", [])) if telemetry["model_dispatched"]}
    root, known = report["root_budget"], sum(intent["total_tokens"] or 0 for intent in intents)
    unknown = sum(intent["usage_status"] == "unknown" for intent in intents)
    if (dispatched != bound or root["model_attempts"] != len(intents) or root["total_tokens"] != known
            or root["tokens_accounted"] != known + sum(intent["reservation"] for intent in intents if intent["usage_status"] == "unknown")
            or root["unknown_usage_calls"] != unknown or root["tokens_dispatched_reserved"] != sum(intent["reservation"] for intent in intents)):
        raise IntegrityError("Phase-gated disclosure root/paid telemetry accounting differs")
    return {"bound_paid_turns": len(bound), "actual_wire_cap": 12000, "root_paid_usage_same": True,
        "same_state_candidate_parent_views": comparisons,
        "net_same_state_wire_bytes_saved": sum(comparison["net_wire_bytes_saved"] for comparison in comparisons) if comparisons else None}


def token_usage(intents, parent_version):
    """Receipt-measured input/output/total remain separate from unknown reservations."""
    roles = {"parent": parent_version, **{domain + "_child": spec.version for domain, spec in CHILD_SPECS.items()}}
    result = {}
    for label, role in roles.items():
        selected = [item for item in intents if item["task_id"].rsplit("/", 1)[-1] == role]
        known = [item for item in selected if item["usage_status"] == "known"]
        result[label] = {"model_decisions": len(selected), "known_calls": len(known),
            "unknown_calls": len(selected) - len(known),
            "input_tokens": sum(item["prompt_tokens"] for item in known),
            "output_tokens": sum(item["completion_tokens"] for item in known),
            "total_tokens": sum(item["total_tokens"] for item in known),
            "tokens_accounted": sum(item["total_tokens"] if item["usage_status"] == "known" else item["reservation"] for item in selected),
            "cumulative_dispatch_tokens_reserved": sum(item["reservation"] for item in selected)}
    fields = next(iter(result.values())).keys()
    result["whole_task"] = {field: sum(value[field] for value in result.values()) for field in fields}
    return result


def evaluate_pairs(rows):
    pairs, stage_views = [], []
    for identity in CASE_IDS:
        pair = {row["variant"]: row for row in rows if row["case_id"] == identity}
        baseline, candidate = pair["baseline"], pair["candidate"]
        original_views = [original.observe_tool("hypotheses", row["report"]) if row.get("report") else None
                          for row in (baseline, candidate)]
        facts_equal = original_views[0] is not None and original_views[0] == original_views[1]
        quality = all(row["assessment"]["functional_passed"] for row in (baseline, candidate)) and facts_equal
        result = {"case_id": identity, "baseline_run_id": baseline["run_id"], "candidate_run_id": candidate["run_id"],
            "equal_accepted_quality": quality, "baseline_passed": baseline["assessment"]["functional_passed"],
            "candidate_passed": candidate["assessment"]["functional_passed"],
            "complete_fact_claim_evidence_hypothesis_gap_lineage_equal": facts_equal,
            "delta_semantics": "candidate_minus_baseline; descriptive only"}
        for key in ("known_tokens", "tokens_accounted", "cumulative_dispatch_tokens_reserved", "root_cumulative_tokens_reserved",
                "runtime_wall_ms", "runtime_preparation_ms", "harness_validation_ms", "overall_measured_wall_ms", "parent_wire_bytes"):
            a, b = baseline.get(key), candidate.get(key)
            result[key + "_delta"] = b - a if quality and a is not None and b is not None else None
        for key in ("model_dispatch_intervals_union_ms", "known_model_transport_sum_ms", "verification_tool_span_sum_ms"):
            a, b = (baseline.get("latency") or {}).get(key), (candidate.get("latency") or {}).get(key)
            result[key + "_delta"] = b - a if quality and a is not None and b is not None else None
        result["actual_token_usage"] = {variant: pair[variant]["token_usage"] for variant in ("baseline", "candidate")}
        result["actual_whole_task_token_delta"] = {field: candidate["token_usage"]["whole_task"][field] - baseline["token_usage"]["whole_task"][field]
            if quality else None for field in ("input_tokens", "output_tokens", "total_tokens", "tokens_accounted")}
        pairs.append(result)
        stage_views.extend((candidate.get("paid_telemetry_validation") or {}).get("same_state_candidate_parent_views", []))
    brief_views = [view for view in stage_views if view["candidate_verification_ready"]]
    phase_gated = (len(brief_views) >= len(CASE_IDS) and all(view["candidate_brief_present"] == view["candidate_verification_ready"]
        and not view["candidate_manifest_present"] and view["same_financial_projection"]
        and view["exact_execution_revisions_decoded"] for view in stage_views)
        and all(view["complete_audit_persisted_server_side"] and view["candidate_disclosed_evidence_rows"] == 0 for view in brief_views))
    byte_benefit = bool(stage_views) and all(view["same_state_bytes_nonincreasing"] for view in stage_views) and sum(
        view["net_wire_bytes_saved"] for view in stage_views) > 0
    return {"existing_case_count": 2, "scheduled_run_count": 4, "independent_new_task_count": 0,
        "pairs": pairs, "all_quality_passed": all(pair["equal_accepted_quality"] for pair in pairs),
        "phase_gated_audit_disclosure_observed": phase_gated,
        "same_state_all_stage_bytes_nonincreasing_and_total_reduced": byte_benefit,
        "same_state_stage_views": stage_views, "verification_ready_same_state_views": brief_views,
        "same_state_total_wire_bytes_saved": sum(view["net_wire_bytes_saved"] for view in stage_views),
        "new_disclosure_contract_not_reversible_old_view": True,
        "actual_additional_monetary_cost": None, "cost_limitation": "endpoint prices/invoice unavailable",
        "statistical_superiority": False, "p95_improvement_established": False, "defaults_changed": False}


class RecordingModel:
    """Durable campaign accounting and terminal-unknown stop, excluding I/O locks."""
    def __init__(self, config, deadline, directory):
        self.config, self.adapter = config, ChatModelAdapter(config)
        self.deadline, self.directory = deadline, Path(directory)
        self.ledger, self.lock = OLD.RootLedger(LIMITS[0], LIMITS[1]), Lock()
        self.item, self.checkpoints = None, None
        self.role_calls, self.revision, self.terminal_unknown = {}, 0, False

    def snapshot(self, kind):
        self.revision += 1
        OLD.write_new(self.directory / f"ledger-{self.revision:03d}-{kind}.json", self.ledger.snapshot())

    def complete(self, messages, **kwargs):
        item = self.item
        role, spec, decision = validate_outbound(messages, item, kwargs, self.checkpoints)
        if OLD.contains_secret(messages, self.config.api_key):
            raise IntegrityError("Phase-gated disclosure outbound credential reflection rejected")
        with self.lock:
            key = (item["run_id"], role)
            count = self.role_calls.get(key, 0) + 1
            if self.terminal_unknown or count != decision or count > spec.max_decisions:
                raise IntegrityError("Phase-gated disclosure unknown paid outcome or repeated/local bound blocks dispatch")
            if (self.deadline - utcnow()).total_seconds() <= 0:
                raise ValidationError("Phase-gated disclosure campaign deadline exceeded")
            intent = self.ledger.reserve(item["run_id"] + "/" + role, messages, spec.output_tokens)
            self.role_calls[key] = count
            prefix = f"{intent['number']:03d}"
            try:
                OLD.write_new(self.directory / (prefix + "-messages.json"), messages)
                OLD.write_new(self.directory / (prefix + "-intent.json"), deepcopy(intent))
                self.snapshot("reserved")
                started = utcnow().isoformat()
                OLD.write_new(self.directory / (prefix + "-dispatch.json"), {"run_id": item["run_id"],
                    "case_id": item["case_id"], "variant": item["variant"], "role": role, "started_at": started})
            except Exception:
                # An incomplete durable intent cannot be safely sent or retried.
                self.terminal_unknown = True
                raise
        try:
            # Linearize final transport permission after durable reservation. A
            # sibling may have reported unknown while this request was persisted.
            # Already permitted in-flight calls may finish; new permits stop.
            with self.lock:
                remaining = (self.deadline - utcnow()).total_seconds()
                if self.terminal_unknown or remaining <= 0:
                    raise ValidationError("Phase-gated disclosure unknown outcome or deadline blocks external dispatch after durable intent")
            response = self.adapter.complete(messages, **{**kwargs, "timeout": min(kwargs["timeout"], remaining)})
            receipt = asdict(response)
            if OLD.receipt_reflects_secret(receipt, self.config.api_key) or len(canonical_json(receipt).encode("utf-8")) > 65536:
                raise ValidationError("Phase-gated disclosure receipt reflected credentials or exceeded bound")
            validate_model_result(response, spec, intent["reservation"])
        except Exception as exc:
            with self.lock:
                self.terminal_unknown = True
                OLD.write_new(self.directory / (prefix + "-receipt.json"), {"status": "unknown", "error_type": type(exc).__name__})
                OLD.write_new(self.directory / (prefix + "-interval.json"), {"run_id": item["run_id"], "role": role,
                    "started_at": started, "finished_at": utcnow().isoformat(), "outcome": "unknown"})
                self.snapshot("terminal-unknown")
            raise
        with self.lock:
            original_intent, original_accounted = deepcopy(intent), self.ledger.accounted
            try:
                OLD.write_new(self.directory / (prefix + "-receipt.json"), receipt)
                OLD.write_new(self.directory / (prefix + "-interval.json"), {"run_id": item["run_id"], "role": role,
                    "started_at": started, "finished_at": utcnow().isoformat(), "outcome": "known"})
                self.ledger.accounted += response.total_tokens - intent["reservation"]
                intent.update(usage_status="known", prompt_tokens=response.prompt_tokens,
                              completion_tokens=response.completion_tokens, total_tokens=response.total_tokens)
                self.snapshot("settled")
            except Exception as exc:
                # A validated response is not a durable settlement until all
                # receipt/interval/ledger records are committed. Keep any saved
                # receipt unchanged; conservative accounting retains reservation.
                intent.clear()
                intent.update(original_intent)
                self.ledger.accounted = original_accounted
                self.terminal_unknown = True
                OLD.write_new(self.directory / (prefix + "-settlement-incomplete.json"), {
                    "status": "unknown", "error_type": type(exc).__name__, "paid_retry": False,
                    "reservation_retained": intent["reservation"], "receipt_preserved": (self.directory / (prefix + "-receipt.json")).exists()})
                self.snapshot("terminal-unknown")
                raise
        return response


def validate_receipts(directory, ledger, items, live_directory):
    by_run = {i["run_id"]: i for i in items}
    known, reserved, accounted, unknown, counts = 0, 0, 0, 0, {}
    for number, intent in enumerate(ledger["intents"], 1):
        prefix = f"{number:03d}"
        messages, raw = [OLD.read(Path(directory) / (prefix + "-" + kind + ".json")) for kind in ("messages", "intent")]
        incomplete_path = Path(directory) / (prefix + "-settlement-incomplete.json")
        incomplete = OLD.read(incomplete_path) if incomplete_path.exists() else None
        receipt_path = Path(directory) / (prefix + "-receipt.json")
        receipt = OLD.read(receipt_path) if receipt_path.exists() else {"status": "unknown"} if incomplete else None
        run, role = intent["task_id"].split("/")
        item, spec = by_run[run], role_spec(by_run[run], role)
        actual_role, _, turn = validate_outbound(messages, item, {"max_tokens": spec.output_tokens}, Path(live_directory) / run / "runs")
        counts[(run, role)] = counts.get((run, role), 0) + 1
        initial = {k: v for k, v in intent.items() if k not in {"prompt_tokens", "completion_tokens"}}
        initial.update(usage_status="unknown", total_tokens=None)
        amount = sum(len(m["content"].encode("utf-8")) for m in messages) + 256 + spec.output_tokens
        if (intent["number"] != number or raw != initial or actual_role != role
                or digest(messages) != intent["messages_sha256"] or amount != intent["reservation"]
                or turn != counts[(run, role)] or turn > spec.max_decisions):
            raise IntegrityError("Phase-gated disclosure paid intent/wire/local count changed")
        reserved += amount
        if intent["usage_status"] == "known":
            result = ChatResult(**receipt)
            validate_model_result(result, spec, amount)
            if any(getattr(result, k) != intent[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
                raise IntegrityError("Phase-gated disclosure paid receipt differs from durable ledger")
            known += result.total_tokens
            accounted += result.total_tokens
        elif intent["usage_status"] == "unknown" and (receipt.get("status") == "unknown" or incomplete):
            if incomplete and (incomplete.get("status") != "unknown" or incomplete.get("paid_retry") is not False
                               or incomplete.get("reservation_retained") != amount):
                raise IntegrityError("Phase-gated disclosure incomplete durable settlement does not retain original reservation")
            unknown += 1
            accounted += amount
        else:
            raise IntegrityError("Phase-gated disclosure unknown paid result released or forged")
    if (known != ledger["known_tokens"] or accounted != ledger["tokens_accounted"]
            or reserved != ledger["cumulative_tokens_reserved"] or unknown != ledger["unknown_usage_calls"]
            or len(ledger["intents"]) != ledger["decisions"] or len(ledger["intents"]) > LIMITS[0]
            or accounted > LIMITS[1] or ledger["max_decisions"] != LIMITS[0] or ledger["max_tokens_accounted"] != LIMITS[1]):
        raise IntegrityError("Phase-gated disclosure receipt accounting exceeds or differs from frozen campaign")
    return {"known_tokens": known, "tokens_accounted": accounted, "cumulative_dispatch_tokens_reserved": reserved,
            "unknown_usage_calls": unknown, "decisions": len(ledger["intents"])}


def latency(report, children, directory, intents):
    """Nested spans stay separate; missing read/authentication subcosts stay unknown."""
    models, adapter_ms, tools, intervals = [], 0, [], []
    for intent in intents:
        prefix = f"{intent['number']:03d}"
        interval = OLD.read(Path(directory) / (prefix + "-interval.json"))
        receipt = OLD.read(Path(directory) / (prefix + "-receipt.json"))
        start, end = (datetime.fromisoformat(interval[k]) for k in ("started_at", "finished_at"))
        if start.tzinfo is None or end.tzinfo is None or end < start:
            raise IntegrityError("Phase-gated disclosure timing is not bound to aware ordered paid intervals")
        models.append({"role": interval["role"], "io_interval_ms": round((end - start).total_seconds() * 1000),
                       "transport_ms": receipt.get("latency_ms"), "outcome": interval["outcome"]})
        intervals.append((start, end))
        adapter_ms += receipt.get("latency_ms") or 0
    for value in [report] + children:
        starts = {e["tool_call_id"]: e for e in value.get("trace", []) if e["event"] == "tool_started"}
        for event in value.get("trace", []):
            if event["event"] == "tool_finished" and event["tool_call_id"] in starts:
                first = starts[event["tool_call_id"]]
                ms = round((datetime.fromisoformat(event["time"]) - datetime.fromisoformat(first["time"])).total_seconds() * 1000)
                tools.append({"run_id": value["run_id"], "tool": event["tool"], "span_ms": ms,
                    "includes_child_model_io": event["tool"].endswith("_child")})
    branches = [b for g in report.get("parallel_groups", []) for b in (g.get("telemetry") or {}).get("branches", [])]
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return {"model_calls": models, "known_model_transport_sum_ms": adapter_ms, "tool_spans": tools,
        "model_dispatch_intervals_union_ms": round(sum((end - start).total_seconds() * 1000 for start, end in merged)),
        "verification_tool_span_sum_ms": sum(t["span_ms"] for t in tools if t["tool"] == "verification"),
        "parallel_queue_ms": {b["domain"]: b.get("queue_ms") for b in branches},
        "child_branch_spans": {b["domain"]: {key: b.get(key) for key in
            ("child_run_id", "branch_started_at", "branch_finished_at", "queue_ms", "execution_ms", "join_wait_ms")}
            for b in branches},
        "read_authorization_split_ms": None, "checkpoint_persistence_split_ms": None,
        "validation_inside_source_tool_split_ms": None,
        "measurement_scope": "Parent Runtime wall measured separately; Child branch spans include their Runtime, source validation and receipt return; model/tool/Child spans overlap and are never summed as whole-task wall time"}


def validate_timing(row):
    """Check frozen live boundaries without substituting replay elapsed times."""
    keys = ("runtime_wall_ms", "runtime_preparation_ms", "harness_validation_ms", "overall_measured_wall_ms", "wall_clock_ms")
    for key in keys:
        value = row.get(key)
        if value is not None and (type(value) is not int or value < 0):
            raise IntegrityError("Phase-gated disclosure recorded monotonic timing is not a nonnegative measurement")
    if row["wall_clock_ms"] != row["overall_measured_wall_ms"]:
        raise IntegrityError("Phase-gated disclosure overall wall alias differs from measured boundary")
    if not row["run_started"]:
        if any(row.get(key) is not None for key in keys):
            raise IntegrityError("Phase-gated disclosure nonstarted run cannot have execution timing")
    elif row["runtime_wall_ms"] is not None:
        if any(row.get(key) is None for key in keys):
            raise IntegrityError("Phase-gated disclosure Runtime timing lacks preparation/validation/overall boundaries")
        subtotal = sum(row[key] for key in ("runtime_wall_ms", "runtime_preparation_ms", "harness_validation_ms"))
        if abs(subtotal - row["overall_measured_wall_ms"]) > 2:
            raise IntegrityError("Phase-gated disclosure measured timing boundaries exceed overall elapsed time")


def live(expected_sha):
    plan, sources = checked(expected_sha)
    config = load_model_config()
    if config.model != plan["model"] or digest(config.endpoint) != plan["endpoint_sha256"]:
        raise IntegrityError("Phase-gated disclosure configured endpoint/model changed after freeze")
    directory = OUT / "live"
    directory.mkdir(exist_ok=False)
    dispatch = directory / "dispatch"
    dispatch.mkdir()
    deadline = utcnow() + timedelta(seconds=LIMITS[2])
    model = RecordingModel(config, deadline, dispatch)
    OLD.write_new(directory / "campaign-intent.json", {"plan_sha256": expected_sha, "deadline": deadline.isoformat(),
        "limits": plan["campaign_limits"], "run_ids": [i["run_id"] for i in plan["items"]], "initial_ledger": model.ledger.snapshot(),
        "independent_new_budget": True, "old_budget_reused": False, "paid_retry": False, "maximum_runs": MAX_RUNS})
    cases, rows = {c["id"]: c for c in plan["cases"]}, []
    for item in plan["items"]:
        run_dir = directory / item["run_id"]
        run_dir.mkdir()
        stopped = model.terminal_unknown or (deadline - utcnow()).total_seconds() <= 0
        OLD.write_new(run_dir / "run-intent.json", {"run_id": item["run_id"], "case_id": item["case_id"],
            "variant": item["variant"], "plan_sha256": expected_sha, "deadline": deadline.isoformat(),
            "paid_retry": False, "external_dispatch_allowed": not stopped, "campaign_decisions_before": model.ledger.snapshot()["decisions"]})
        model.item, model.checkpoints = item, run_dir / "runs"
        started, report, children, paid, timings = time.monotonic(), None, [], None, None
        runtime_started, runtime_finished = None, None
        try:
            if stopped:
                raise ValidationError("Phase-gated disclosure campaign unknown outcome or deadline stops remaining runs")
            service, access = sources.context(cases[item["case_id"]])
            runner = runtime(service, CheckpointStore(model.checkpoints), item["variant"], model, inherited_deadline=deadline)
            request = DynamicRequest.from_dict(item["request"])
            runtime_started = time.monotonic()
            try:
                report = runner.run(request, access, run_id=item["run_id"])
            finally:
                runtime_finished = time.monotonic()
            OLD.write_new(run_dir / "report.json", report)
            with (run_dir / "report.md").open("x", encoding="utf-8") as stream:
                stream.write(markdown(report))
            OLD.write_new(run_dir / "trace.json", {"trace": report["trace"], "context_telemetry": report.get("context_telemetry"),
                                                   "parallel_groups": report.get("parallel_groups", [])})
            intents = original.run_intents(model.ledger.snapshot(), item["run_id"])
            assessment = assess(item, report, dispatch, intents)
            safety = original.safety_checks(item, report, sources, assessment)
            children = original.children_from_checkpoints(run_dir, item, report)
            paid = paid_telemetry(item, report, children, dispatch, intents)
            timings = latency(report, children, dispatch, intents)
            assessment["checks"]["paid_telemetry_and_root_usage"] = True
            assessment["functional_passed"] = assessment["functional_passed"] and all(v == "passed" for v in safety.values())
            error_type = None
        except Exception as exc:
            error_type = type(exc).__name__
            OLD.write_new(run_dir / "failure.json", {"error_type": error_type, "paid_retry": False,
                "report_retained": report is not None, "started": not stopped, "ledger": model.ledger.snapshot()})
            assessment = {"functional_passed": False, "checks": {}, "status": report.get("status") if report else None}
            safety = {k: "unknown" for k in SAFETY}
        intents = original.run_intents(model.ledger.snapshot(), item["run_id"])
        root = report.get("root_budget", {}) if report else {}
        measured_finished = time.monotonic()
        overall_ms = round((measured_finished - started) * 1000) if not stopped else None
        row = {"case_id": item["case_id"], "run_id": item["run_id"], "variant": item["variant"], "parent_version": item["parent_version"],
            "report": report, "child_reports": children, "assessment": assessment, "safety_checks": safety,
            "paid_telemetry_validation": paid, "latency": timings, "intents": intents, "error_type": error_type,
            "run_started": not stopped, "wall_clock_ms": overall_ms, "overall_measured_wall_ms": overall_ms,
            "runtime_wall_ms": round((runtime_finished - runtime_started) * 1000) if runtime_finished is not None else None,
            "runtime_preparation_ms": round((runtime_started - started) * 1000) if runtime_started is not None else None,
            "harness_validation_ms": round((measured_finished - runtime_finished) * 1000) if runtime_finished is not None else None,
            "known_tokens": sum(i["total_tokens"] or 0 for i in intents),
            "tokens_accounted": sum(i["total_tokens"] if i["usage_status"] == "known" else i["reservation"] for i in intents),
            "token_usage": token_usage(intents, item["parent_version"]),
            "cumulative_dispatch_tokens_reserved": sum(i["reservation"] for i in intents),
            "root_cumulative_tokens_reserved": root.get("tokens_reserved"),
            "parent_wire_bytes": sum(t["total_context_bytes"] for t in report.get("context_telemetry", []) if t["model_dispatched"]) if report else None,
            "independent_new_task_count": 0, "paid_retry": False}
        validate_timing(row)
        OLD.write_new(run_dir / "summary.json", row)
        row["run_file_hashes"] = original.file_hashes(run_dir)
        rows.append(row)
    ledger = model.ledger.snapshot()
    receipt_validation = validate_receipts(dispatch, ledger, plan["items"], directory)
    if history_hashes() != plan["history_hashes"]:
        raise IntegrityError("Phase-gated disclosure modified historical frozen evidence")
    dataset = {"schema": "context-disclosure-real-paired-trace/v1", "plan_sha256": expected_sha, "rows": rows,
        "existing_case_count": len(CASE_IDS), "independent_new_task_count": 0, "scheduled_run_count": 4,
        "started_run_count": sum(r["run_started"] for r in rows), "maximum_runs": MAX_RUNS,
        "synthetic_rows": 0, "financial_provider_network_calls": 0, "model": config.model}
    OLD.write_new(directory / "trace-dataset.json", dataset)
    summary = {"schema": "context-disclosure-live-summary/v1", "plan_sha256": expected_sha, "ledger": ledger,
        "receipt_validation": receipt_validation, "evaluation": evaluate_pairs(rows),
        "trace_dataset_sha256": OLD.sha(directory / "trace-dataset.json"), "deadline": deadline.isoformat(),
        "remaining_run_slots": MAX_RUNS - sum(r["run_started"] for r in rows),
        "unknown_paid_outcome_stopped_dispatch": model.terminal_unknown,
        "decision": "pending_exact_read_only_replay", "defaults_changed": False, "next_phase_started": False}
    OLD.write_new(directory / "summary.json", summary)
    OLD.write_new(directory / "trace-manifest.json", {"schema": "context-disclosure-trace-manifest/v1", "plan_sha256": expected_sha,
        "trace_dataset_sha256": OLD.sha(directory / "trace-dataset.json"), "summary_sha256": OLD.sha(directory / "summary.json"),
        "files_before_manifest": original.file_hashes(directory)})
    return summary


def replay(expected_sha):
    plan, sources = checked(expected_sha, replay=True)
    directory = OUT / "live"
    before, manifest = original.file_hashes(directory), OLD.read(directory / "trace-manifest.json")
    dataset, summary = OLD.read(directory / "trace-dataset.json"), OLD.read(directory / "summary.json")
    if (manifest["trace_dataset_sha256"] != OLD.sha(directory / "trace-dataset.json")
            or manifest["summary_sha256"] != OLD.sha(directory / "summary.json")
            or manifest["files_before_manifest"] != {k: v for k, v in before.items() if k != "trace-manifest.json"}
            or summary["evaluation"] != evaluate_pairs(dataset["rows"])
            or validate_receipts(directory / "dispatch", summary["ledger"], plan["items"], directory) != summary["receipt_validation"]):
        raise IntegrityError("Phase-gated disclosure immutable manifest, paid ledger or evaluation changed")
    rows, identical, retained = {r["run_id"]: r for r in dataset["rows"]}, [], []
    cases = {c["id"]: c for c in plan["cases"]}
    for item in plan["items"]:
        run_dir, row = directory / item["run_id"], rows[item["run_id"]]
        validate_timing(row)
        if original.file_hashes(run_dir) != row["run_file_hashes"]:
            raise IntegrityError("Phase-gated disclosure frozen report, source validation or checkpoint changed")
        if row["report"] is None:
            retained.append({"run_id": item["run_id"], "run_started": row["run_started"], "validation_complete": False})
            continue
        if row["token_usage"] != token_usage(row["intents"], item["parent_version"]):
            raise IntegrityError("Phase-gated disclosure measured Parent/Child input/output/accounted tokens changed")
        service, access = sources.context(cases[item["case_id"]])
        restored = runtime(service, CheckpointStore(run_dir / "runs"), item["variant"], original.NoNetwork()).run(
            DynamicRequest.from_dict(item["request"]), access, resume=item["run_id"])
        if restored != row["report"] or restored != OLD.read(run_dir / "report.json"):
            raise IntegrityError("Phase-gated disclosure exact report replay changed")
        identical.append(item["run_id"])
        if row["error_type"] is None:
            assessed = assess(item, restored, directory / "dispatch", row["intents"])
            safety = original.safety_checks(item, restored, sources, assessed)
            children = original.children_from_checkpoints(run_dir, item, restored)
            paid = paid_telemetry(item, restored, children, directory / "dispatch", row["intents"])
            assessed["checks"]["paid_telemetry_and_root_usage"] = True
            assessed["functional_passed"] = assessed["functional_passed"] and all(v == "passed" for v in safety.values())
            if (assessed != row["assessment"] or safety != row["safety_checks"] or children != row["child_reports"]
                    or paid != row["paid_telemetry_validation"] or latency(restored, children, directory / "dispatch", row["intents"]) != row["latency"]):
                raise IntegrityError("Phase-gated disclosure oracle/safety/paid/timing replay changed")
        else:
            retained.append({"run_id": item["run_id"], "error_type": row["error_type"], "validation_complete": False})
    if before != original.file_hashes(directory) or history_hashes() != plan["history_hashes"]:
        raise IntegrityError("Phase-gated disclosure read-only replay appended checkpoint or changed historical files")
    quality = summary["evaluation"]["all_quality_passed"] and len(identical) == 4 and not retained and summary["ledger"]["unknown_usage_calls"] == 0
    benefit = (summary["evaluation"]["phase_gated_audit_disclosure_observed"]
               and summary["evaluation"]["same_state_all_stage_bytes_nonincreasing_and_total_reduced"])
    return {"schema": "context-disclosure-read-only-replay/v1", "plan_sha256": expected_sha,
        "replay_same": len(identical) == sum(r["report"] is not None for r in dataset["rows"]),
        "identical_reports": len(identical), "quality_acceptance_passed": quality, "retained_failures": retained,
        "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0,
        "phase_gated_audit_disclosure_observed": summary["evaluation"]["phase_gated_audit_disclosure_observed"],
        "same_state_all_stage_bytes_nonincreasing_and_total_reduced": summary["evaluation"]["same_state_all_stage_bytes_nonincreasing_and_total_reduced"],
        "decision": "limited_explicit_phase_gated_disclosure_accepted" if quality and benefit
                    else "phase_gated_byte_or_disclosure_gate_not_passed_defaults_retained" if quality else "bounded_acceptance_failed_evidence_retained",
        "independent_new_task_count": 0, "defaults_changed": False, "next_phase_started": False}


def readonly_replay(expected_sha):
    with patch.object(CheckpointStore, "append", side_effect=AssertionError("read-only acceptance cannot append")), \
            patch.object(original.NoNetwork, "complete", side_effect=AssertionError("read-only acceptance cannot dispatch model")):
        return replay(expected_sha)


def audit(expected_sha):
    """Bind every real paid receipt to its append-only state and actual tools."""
    result = readonly_replay(expected_sha)
    plan, _ = checked(expected_sha, replay=True)
    directory = OUT / "live"
    before = original.file_hashes(directory)
    dataset = OLD.read(directory / "trace-dataset.json")
    rows = {row["run_id"]: row for row in dataset["rows"]}
    matched, executions, chains = [], [], []
    for item in plan["items"]:
        row = rows[item["run_id"]]
        checkpoint_dir = directory / item["run_id"] / "runs"
        if row["report"] is None:
            continue
        histories = {item["parent_version"]: readonly_history(checkpoint_dir, item["scope"], item["run_id"])}
        for child in row["child_reports"]:
            role = CHILD_SPECS[child.get("domain", "financial")].version
            histories[role] = readonly_history(checkpoint_dir, item["scope"], child["run_id"])
            if histories[role][-1]["report"] != child:
                raise IntegrityError("Read-only audit Child report differs from persisted complete state")
        if histories[item["parent_version"]][-1]["report"] != row["report"]:
            raise IntegrityError("Read-only audit Parent report differs from persisted complete state")
        chains.append({"parent_run_id": item["run_id"], "run_count": len(histories),
            "checkpoint_rows": sum(len(history) for history in histories.values()), "hashchains_verified": True})
        for intent in row["intents"]:
            messages = OLD.read(directory / "dispatch" / f"{intent['number']:03d}-messages.json")
            payload = json.loads(messages[1]["content"])
            role, turn = payload["protocol_version"], payload["control"]["decision"]
            pending = [state for state in histories[role] if state["phase"] == "model_pending" and state.get("decisions")
                and state["decisions"][-1]["turn"] == turn and state["decisions"][-1]["message_sha256"] == digest(messages)]
            if not pending or pending[0]["decisions"][-1]["token_reservation"] != intent["reservation"]:
                raise IntegrityError("Read-only audit paid receipt has no exact durable reserved state")
            matched.append({"intent": intent["number"], "role": role, "turn": turn,
                "durable_predispatch_state_matched": True})
        verification = [event for event in row["report"]["trace"]
            if event["event"] == "tool_finished" and event["tool"] == "verification"]
        if row["assessment"]["functional_passed"] and len(verification) != 1:
            raise IntegrityError("Read-only audit verification was not actually executed exactly once")
        final = histories[item["parent_version"]][-1]
        receipt = final.get("verification_execution")
        if row["assessment"]["functional_passed"]:
            if receipt is None or not runtime(None, None, item["variant"])._verification_execution_matches(final):
                raise IntegrityError("Read-only audit v4/v5 lacks original validated actual verification execution")
        executions.append({"run_id": item["run_id"], "verification_tool_executions": len(verification),
            "required_execution_checks": row["report"]["required_checks"],
            "full_fact_count": len(row["report"].get("facts", [])),
            "full_evidence_count": len(row["report"].get("evidence", {})),
            "candidate_verification_execution_receipt": receipt})
    if original.file_hashes(directory) != before:
        raise IntegrityError("Read-only acceptance audit changed frozen live files")
    return {"schema": "context-disclosure-readonly-actual-audit/v1",
        "status": "passed" if result["quality_acceptance_passed"] else "failures_retained",
        "plan_sha256": expected_sha, "replay": result, "chains": chains, "matched_paid_states": matched,
        "actual_verification_executions": executions, "all_failures_retained": True,
        "original_sources_grants_pit_oracles_revalidated": True, "live_files_unchanged": True,
        "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0,
        "real_overlimit_recovery_status": plan["real_overlimit_recovery_status"],
        "remaining_boundary": "W1b phase-gated disclosure only; W2/general pagination and unlimited continuation unimplemented"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ("preflight", "prepare", "live", "replay", "audit"):
        mode.add_argument("--" + name, action="store_true")
    parser.add_argument("--plan-sha256")
    parser.add_argument("--offline-evidence", type=Path)
    parser.add_argument("--preflight-evidence", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.prepare and not (args.offline_evidence and args.preflight_evidence):
        parser.error("prepare requires completed new offline evidence and read-only real-source preflight")
    if (args.live or args.replay or args.audit) and not args.plan_sha256:
        parser.error("live/replay/audit requires explicit independently frozen --plan-sha256")
    if (args.preflight or args.replay or args.audit) and args.output is None:
        parser.error("read-only evidence requires a new --output path")
    try:
        if args.preflight:
            result = preflight()
        elif args.prepare:
            result = prepare(args.offline_evidence, args.preflight_evidence)
        elif args.live:
            result = live(args.plan_sha256)
        elif args.audit:
            result = audit(args.plan_sha256)
        else:
            result = readonly_replay(args.plan_sha256)
        if args.output is not None:
            OLD.write_new(args.output, result)
        printable = {key: value for key, value in result.items()
            if key not in {"historical_hashes", "paid_v4_states", "recorded_historical_overflows", "matched_paid_states"}}
        print(json.dumps(printable, ensure_ascii=True, indent=2))
        return 0
    except (DataError, OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"status": "failed", "error": "Independent frozen input or acceptance execution validation failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
