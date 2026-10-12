"""Independent, bounded A/B/C acceptance for explicit domain analysis.

Only the two existing Phase 5 immutable cases are eligible.  This script never
collects financial data, changes default routes, retries unknown paid requests,
or treats synthetic transports as real model evidence.  The deadline starts at
plan freeze, and failures plus separately frozen repair runs remain inspectable.
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

import phase5_evaluate as original
import phase6_evaluate as infrastructure
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.model_adapters.chat import ChatModelAdapter, ChatResult, load_model_config
from stock_research.models import AccessContext, canonical_json, digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest
from stock_research.research.dynamic_protocol import observe_tool
from stock_research.research.report import markdown
from stock_research.research.runtime import validate_model_result
from stock_research.research.tools import read_domain

OLD = original.old
OUT = OLD.ROOT / ".artifacts/domain-analysis/bounded-core-v1-20261009"
CASE_IDS = ("p5-603207", "p5-688184")
MODES = ("direct", "tool", "child")
ORDER = ((CASE_IDS[0], "direct"), (CASE_IDS[0], "tool"), (CASE_IDS[0], "child"),
         (CASE_IDS[1], "tool"), (CASE_IDS[1], "child"), (CASE_IDS[1], "direct"))
LIMITS = {"max_decisions": 128, "max_tokens_accounted": 768000, "max_seconds": 2400}
PROFILE, EXECUTION = "core/v1", "parallel"
ROOT_LIMITS = {"decisions": 16, "tools": 18, "tokens": 96000}
ACCEPTANCE = {
    "quality": "every frozen required output, lawful gap/counterevidence and full canonical independent verifier; actual final verification Tool required",
    "primary_metric": "whole-task measured Parent plus all Child known total_tokens, summed across both frozen cases; failed/repair paid attempts remain in their mode total",
    "aggregation": "sum all paid attempts per mode, including failures and separately frozen same-case repairs; no best-of-run selection",
    "efficiency_candidate_threshold": "Child aggregate total_tokens <= 0.90 times effective deterministic domain Tool B AND <= 0.90 times stronger valid aggregate A/B",
    "threshold_percent": 10,
    "quality_gate": "all three modes must produce equal complete accepted canonical quality on every frozen case; unresolved unknown usage invalidates efficiency comparison",
    "repair_rule": "at most two new run identities; only a recorded failed initial slot with specific log diagnosis and source-bound local fix/regression evidence; original failures retained",
    "secondary_metrics": "whole Runtime wall, overall measured wall, paid model I/O, coordination, production computation and independent validation spans, never substitute for the primary metric",
    "autonomy": "fixed read/calculation/review/finish shows responsibility transfer only; meaningful task-bound choice/adjustment needs actual paid action plus Observation evidence",
    "parallel": "C requires actual authorized DAG/group plus overlapping Financial/Market paid model dispatch intervals; source/derived quality remains separately exact",
    "cost": "no frozen endpoint price/invoice; monetary cost unknown",
    "scope": "two nonblind known-source cases, explicit experimental profile only, no statistical/P95/global routing claim",
}
TIMING_DEFINITIONS = {**infrastructure.TIMING_DEFINITIONS,
    "production_tool_span_sum_ms": "sum Child calculation and deterministic domain_calculation spans; A Parent calculation includes inseparable composition; B/C composition separate; overlaps never added to wall",
    "local_review_tool_span_sum_ms": "domain rule testing plus independent local review spans; never added to total wall",
    "coordination_tool_span_sum_ms": "wrapper and compose spans may include child computation/model I/O; never added to whole wall"}


def spec_for(mode):
    from stock_research.research.domain_analysis_contracts import DomainAnalysisParentSpec
    if mode not in MODES:
        raise IntegrityError("Domain analysis comparison mode outside frozen A/B/C")
    return DomainAnalysisParentSpec(mode=mode, execution=EXECUTION, profile_id=PROFILE)


def child_specs():
    from stock_research.research.domain_analysis_contracts import FinancialAnalysisChildSpec, MarketAnalysisChildSpec
    return {"financial": FinancialAnalysisChildSpec(), "market": MarketAnalysisChildSpec()}


def runtime(service, checkpoints, mode, model=None, **kwargs):
    return DynamicRuntime(service, checkpoints, model, spec_for(mode), **kwargs)


def local_limits(spec):
    return {"decisions": spec.max_decisions, "tools": spec.max_tools,
        "tokens": spec.max_tokens, "seconds": spec.max_seconds,
        "output_tokens": spec.output_tokens, "context_bytes": spec.context_bytes,
        "no_progress_limit": spec.no_progress_limit}


def spec_document():
    return {mode: {"identity": spec_for(mode).identity, "version": spec_for(mode).version,
        "mode": mode, "execution": EXECUTION, "profile_id": PROFILE,
        "local_limits": local_limits(spec_for(mode)), "root_limits": ROOT_LIMITS,
        "allowed_tools": sorted(spec_for(mode).allowed_tools),
        "visible_tools": sorted(spec_for(mode).visible_tools)} for mode in MODES}


def code_files():
    return {path.relative_to(OLD.ROOT).as_posix(): OLD.sha(path)
        for directory in ("src", "scripts", "tests")
        for path in sorted((OLD.ROOT / directory).rglob("*.py"))}


def history_hashes():
    # The independent new campaign is excluded; all older successes/failures,
    # paid wires and checkpoints are included without opening secret files.
    directory = OLD.ROOT / ".artifacts"
    return {path.relative_to(directory).as_posix(): OLD.sha(path)
        for path in sorted(directory.rglob("*")) if path.is_file()
        and path.relative_to(directory).parts[0] != "domain-analysis"}


def evidence_ref(path):
    path = Path(path).resolve()
    try:
        relative = path.relative_to(OLD.ROOT.resolve()).as_posix()
    except ValueError:
        raise IntegrityError("Acceptance evidence must remain workspace-local") from None
    return {"path": relative, "sha256": OLD.sha(path)}


def original_guard():
    return infrastructure.original_guard()


def cases_from(prior):
    return [deepcopy(next(case for case in prior["cases"] if case["id"] == identity)) for identity in CASE_IDS]


def frozen_item(case, mode, sources, *, run_id=None):
    service, access = sources.context(case)
    # Business question, source bindings and root goal are identical across A/B/C.
    # Execution control belongs to the explicit versioned Spec, never the question.
    request = DynamicRequest.from_dict({**case["request"], "question": original.QUESTION})
    run = run_id or uuid.uuid4().hex
    runner = runtime(service, None, mode)
    oracle = original.parallel.catalog_oracle(service, access, request)
    envelope = OLD.authorized_envelope(service, access, request)
    return {"case_id": case["id"], "mode": mode, "run_id": run, "scope": access.scope,
        "request": request.to_dict(), "request_ref": digest(request.to_dict()),
        "spec_identity": spec_for(mode).identity, "parent_version": spec_for(mode).version,
        "input_ref": digest(sources.inputs(case)), "authorization_envelope": envelope,
        "authorization_ref": digest(envelope), "catalog_observations": oracle,
        "oracle_ref": digest(oracle), "expected_outcome": original.expected_outcome(oracle),
        "required_check_ids": runner._requirements(request),
        "messages": runner.preview(request, access, run_id=run),
        "profile_id": PROFILE, "execution": EXECUTION, "independent_new_task_count": 0}


def preflight():
    """Read-only real source qualification and every prior targeted replay."""
    before = history_hashes()
    prior, sources = original_guard()
    rows = []
    for case in cases_from(prior):
        service, access = sources.context(case)
        request = DynamicRequest.from_dict({**case["request"], "question": original.QUESTION})
        oracle = original.parallel.catalog_oracle(service, access, request)
        rows.append({"case_id": case["id"], "source_input_ref": digest(sources.inputs(case)),
            "request_ref": digest(request.to_dict()), "oracle_ref": digest(oracle),
            "expected_outcome": original.expected_outcome(oracle),
            "bound_datasets": sorted(binding.dataset for binding in request.bindings),
            "real_factor_adjusted_branch_verified": False,
            "real_calendar_branch_verified": False, "real_cashflow_branch_verified": False,
            "reason": "existing selected immutable snapshots bind only financial_income and market_daily; absent branches remain unverified"})
    import context_window_optimized_acceptance as latest
    historical = latest.historical_replay()
    optimized = latest.readonly_replay(OLD.sha(latest.OUT / "plan.json"))
    if (not optimized["replay_same"] or optimized["identical_reports"] != 4
            or any(optimized[key] != 0 for key in ("model_calls", "provider_calls", "checkpoint_appends"))
            or before != history_hashes()):
        raise IntegrityError("Domain analysis historical replay changed prior evidence")
    return {"schema": "domain-analysis-readonly-preflight/v1", "status": "passed",
        "code_files": code_files(), "history_hashes": before, "cases": rows,
        "previous_35_reports": historical, "previous_optimized_four_reports": optimized,
        "unique_historical_reports_replayed": 39, "historical_files_unchanged": True,
        "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0,
        "agent_incremental_value_unproven": True, "defaults_changed": False}


def validate_gate(offline_path, preflight_path, *, check_current=True):
    offline, probe = OLD.read(offline_path), OLD.read(preflight_path)
    if (offline.get("status") != "passed" or offline.get("command") != "python -m unittest discover -s tests -v"
            or offline.get("pythonpath") != "src" or offline.get("failures") != 0 or offline.get("errors") != 0
            or type(offline.get("tests_run")) is not int or offline["tests_run"] <= 0
            or offline.get("code_files") != probe.get("code_files")
            or check_current and offline.get("code_files") != code_files()):
        raise IntegrityError("Domain analysis freeze requires complete current-code offline regression evidence")
    if (probe.get("schema") != "domain-analysis-readonly-preflight/v1" or probe.get("status") != "passed"
            or probe.get("history_hashes") != history_hashes() or probe.get("historical_files_unchanged") is not True
            or probe.get("unique_historical_reports_replayed") != 39
            or any(probe.get(key) != 0 for key in ("model_calls", "provider_calls", "checkpoint_appends"))):
        raise IntegrityError("Domain analysis freeze requires source qualification and zero-append historical replay")
    return offline, probe


def prepare(offline_path, preflight_path):
    if OUT.exists():
        raise IntegrityError("Independent domain analysis campaign is immutable and already exists")
    validate_gate(offline_path, preflight_path)
    prior, sources = original_guard()
    cases = cases_from(prior)
    validation = original.validate_cases(cases, sources.context)
    if not validation["all_cases_contract_valid"]:
        raise IntegrityError("Existing immutable domain analysis source contracts invalid")
    by_case = {case["id"]: case for case in cases}
    items = [frozen_item(by_case[identity], mode, sources) for identity, mode in ORDER]
    config = load_model_config()
    if (config.model != prior["model"] or digest(config.endpoint) != prior["endpoint_sha256"]
            or any(spec_for(mode).model != config.model for mode in MODES)):
        raise IntegrityError("Only the previously configured endpoint/model is authorized")
    frozen_at = utcnow()
    plan = {"schema": "domain-analysis-frozen-plan/v1", "frozen_at": frozen_at.isoformat(),
        "deadline": (frozen_at + timedelta(seconds=LIMITS["max_seconds"])).isoformat(),
        "cases": cases, "items": items, "comparison_order": [list(pair) for pair in ORDER],
        "contract_validation": validation, "model": config.model, "endpoint_sha256": digest(config.endpoint),
        "code_files": code_files(), "history_hashes": history_hashes(), "specs": spec_document(),
        "child_specs": {domain: {"identity": spec.identity, "version": spec.version, "local_limits": local_limits(spec)}
            for domain, spec in child_specs().items()},
        "offline_gate": evidence_ref(offline_path), "readonly_preflight": evidence_ref(preflight_path),
        "campaign_limits": LIMITS, "maximum_existing_cases": 2, "scheduled_initial_run_count": 6,
        "reserved_repair_run_slots": 2, "maximum_campaign_runs": 8, "independent_new_task_count": 0,
        "context_limit_bytes": 12000, "profile_id": PROFILE, "execution": EXECUTION,
        "old_budget_reused": False, "provider_network_calls": 0, "defaults_changed": False,
        "unknown_paid_outcomes_stop_external_dispatch": True, "paid_retries": False,
        "historical_failures_and_denominators_preserved": True, "acceptance": ACCEPTANCE,
        "timing_definitions": TIMING_DEFINITIONS, "blind": False,
        "confounds": ["two known-source nonblind cases", "rotated fixed order and caches",
            "A/B Parent 8/12 versus C Parent 6/8 plus each Child 5/4; same root 16/18/96000",
            "endpoint service time uncontrolled; no price/invoice or statistical/P95 claim"]}
    OLD.write_new(OUT / "plan.json", plan)
    return {"prepared": True, "plan_sha256": OLD.sha(OUT / "plan.json"), "deadline": plan["deadline"],
        "scheduled_initial_run_count": 6, "reserved_repair_run_slots": 2, "model_calls": 0, "provider_calls": 0}


def checked(expected_sha, *, replay=False):
    if type(expected_sha) is not str or OLD.sha(OUT / "plan.json") != expected_sha:
        raise IntegrityError("Domain analysis frozen plan hash differs")
    plan = OLD.read(OUT / "plan.json")
    frozen, deadline = datetime.fromisoformat(plan["frozen_at"]), datetime.fromisoformat(plan["deadline"])
    if frozen.tzinfo is None or deadline.tzinfo is None or (deadline - frozen).total_seconds() != LIMITS["max_seconds"]:
        raise IntegrityError("Domain analysis campaign deadline must start at original freeze")
    expected = {"schema": "domain-analysis-frozen-plan/v1", "comparison_order": [list(pair) for pair in ORDER],
        "campaign_limits": LIMITS, "maximum_existing_cases": 2, "scheduled_initial_run_count": 6,
        "reserved_repair_run_slots": 2, "maximum_campaign_runs": 8, "independent_new_task_count": 0,
        "context_limit_bytes": 12000, "profile_id": PROFILE, "execution": EXECUTION,
        "old_budget_reused": False, "provider_network_calls": 0, "defaults_changed": False,
        "unknown_paid_outcomes_stop_external_dispatch": True, "paid_retries": False,
        "historical_failures_and_denominators_preserved": True, "acceptance": ACCEPTANCE,
        "timing_definitions": TIMING_DEFINITIONS, "blind": False,
        "history_hashes": history_hashes()}
    if any(plan.get(key) != value for key, value in expected.items()) or not replay and plan["code_files"] != code_files():
        raise IntegrityError("Domain analysis frozen budget/goals/history/code changed")
    for key in ("offline_gate", "readonly_preflight"):
        if evidence_ref(OLD.ROOT / plan[key]["path"]) != plan[key]:
            raise IntegrityError("Domain analysis gate evidence changed")
    validate_gate(OLD.ROOT / plan["offline_gate"]["path"], OLD.ROOT / plan["readonly_preflight"]["path"], check_current=not replay)
    prior, sources = original_guard()
    if plan["cases"] != cases_from(prior) or original.validate_cases(plan["cases"], sources.context) != plan["contract_validation"]:
        raise IntegrityError("Domain analysis legal cases or source contracts changed")
    if plan["specs"] != spec_document() or plan["child_specs"] != {domain: {
            "identity": spec.identity, "version": spec.version, "local_limits": local_limits(spec)}
            for domain, spec in child_specs().items()}:
        raise IntegrityError("Domain analysis explicit Spec/local envelopes changed")
    by_case = {case["id"]: case for case in plan["cases"]}
    old_ids = {item["run_id"] for item in prior["items"]}
    ids = [item["run_id"] for item in plan["items"]]
    if len(ids) != 6 or len(set(ids)) != 6 or old_ids.intersection(ids):
        raise IntegrityError("Domain analysis requires six fresh initial run identities")
    if [(item["case_id"], item["mode"]) for item in plan["items"]] != list(ORDER):
        raise IntegrityError("Domain analysis frozen A/B/C order changed")
    for item in plan["items"]:
        if frozen_item(by_case[item["case_id"]], item["mode"], sources, run_id=item["run_id"]) != item:
            raise IntegrityError("Domain analysis immutable source/request/grants/oracle/preview changed")
    return plan, sources


def readonly_states(directory, scope):
    path = Path(directory) / "checkpoints.sqlite3"
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
        rows = connection.execute("SELECT run,seq,previous,hash,payload FROM checkpoints WHERE scope=? ORDER BY run,seq", (scope,)).fetchall()
    chains, result = {}, []
    for run, seq, previous, checksum, payload in rows:
        state = json.loads(payload)
        index, prior = chains.get(run, (0, ""))
        if seq != index or previous != prior or digest({"previous": previous, "state": state}) != checksum:
            raise IntegrityError("Domain analysis checkpoint append chain changed")
        chains[run] = (index + 1, checksum)
        result.append(state)
    return result


def role_spec(item, role):
    parent = spec_for(item["mode"])
    if role == parent.version:
        return parent
    for spec in child_specs().values():
        if item["mode"] == "child" and spec.version == role:
            return spec
    raise IntegrityError("Domain analysis paid role exceeds frozen A/B/C route")


def request_for_state(state, spec):
    from stock_research.research.domain_analysis_contracts import FinancialAnalysisRequest, MarketAnalysisRequest
    if spec.version.startswith("financial-analysis-child-"):
        return FinancialAnalysisRequest.from_dict(state["request"])
    if spec.version.startswith("market-analysis-child-"):
        return MarketAnalysisRequest.from_dict(state["request"])
    return DynamicRequest.from_dict(state["request"])


def validate_outbound(messages, item, kwargs, checkpoints):
    from stock_research.research.domain_analysis_protocol import messages as domain_messages
    payload = json.loads(messages[1]["content"])
    role = payload["protocol_version"]
    spec = role_spec(item, role)
    matching = [state for state in readonly_states(checkpoints, item["scope"])
        if state.get("phase") == "model_pending" and state.get("decisions")
        and state["decisions"][-1].get("message_sha256") == digest(messages)
        and state.get("spec_version") == role]
    if not matching:
        raise IntegrityError("Domain analysis outbound lacks exact durable paid intent")
    state = matching[0]
    request = request_for_state(state, spec)
    parent = DynamicRequest.from_dict(item["request"])
    if role == item["parent_version"]:
        if state["run_id"] != item["run_id"] or request.to_dict() != item["request"]:
            raise IntegrityError("Domain analysis paid Parent goal/Spec changed")
    elif (request.parent_request_ref != item["request_ref"] or request.security != parent.security
            or request.as_of != parent.as_of or request.mode != parent.mode
            or any(binding not in parent.bindings for binding in request.bindings)
            or request.question != parent.question):
        raise IntegrityError("Domain analysis paid Child exceeded frozen root request")
    turn = state["decisions"][-1]["turn"]
    available = (json.loads(item["messages"][1]["content"])["available_tools"]
        if role == item["parent_version"] else sorted(["calculation", "domain_review",
            "financial" if role.startswith("financial-") else "market"]))
    if payload["available_tools"] != available:
        raise IntegrityError("Domain analysis outbound changed its frozen effective tool visibility")
    for observation in state.get("observations", {}).values():
        if observation.get("kind") == "source_read" and observation != item["authorization_envelope"]["source_observations"].get(observation["tool"]):
            raise IntegrityError("Domain analysis outbound source differs from the authorized immutable oracle")
    rebuilt = domain_messages(state, request, available, 12000, spec=spec, decision=turn)
    if isinstance(rebuilt, tuple):
        rebuilt = rebuilt[0]
    if (rebuilt != messages or kwargs.get("max_tokens") != spec.output_tokens
            or sum(len(message["content"].encode("utf-8")) for message in messages) > 12000):
        raise IntegrityError("Domain analysis paid wire differs from exact bounded state")
    return role, spec, turn


class RecordingModel:
    """Durable paid intents; known settlement only, terminal unknown stops dispatch."""
    def __init__(self, config, deadline, directory):
        self.config, self.adapter = config, ChatModelAdapter(config)
        self.deadline, self.directory = deadline, Path(directory)
        self.ledger = OLD.RootLedger(LIMITS["max_decisions"], LIMITS["max_tokens_accounted"])
        self.lock, self.role_calls, self.revision = Lock(), {}, 0
        self.item, self.checkpoints, self.terminal_unknown = None, None, False

    def snapshot(self, kind):
        self.revision += 1
        OLD.write_new(self.directory / f"ledger-{self.revision:03d}-{kind}.json", self.ledger.snapshot())

    def complete(self, messages, **kwargs):
        item = self.item
        role, spec, turn = validate_outbound(messages, item, kwargs, self.checkpoints)
        if OLD.contains_secret(messages, self.config.api_key):
            raise IntegrityError("Domain analysis outbound credential reflection rejected")
        with self.lock:
            key = (item["run_id"], role)
            count = self.role_calls.get(key, 0) + 1
            if self.terminal_unknown or count != turn or count > spec.max_decisions:
                raise IntegrityError("Domain analysis unknown/repeated/local decision stops new paid dispatch")
            if (self.deadline - utcnow()).total_seconds() <= 0:
                raise ValidationError("Frozen domain analysis campaign deadline exceeded")
            intent = self.ledger.reserve(item["run_id"] + "/" + role, messages, spec.output_tokens)
            self.role_calls[key] = count
            prefix, started = f"{intent['number']:03d}", utcnow().isoformat()
            try:
                OLD.write_new(self.directory / (prefix + "-messages.json"), messages)
                OLD.write_new(self.directory / (prefix + "-intent.json"), deepcopy(intent))
                OLD.write_new(self.directory / (prefix + "-dispatch.json"), {"run_id": item["run_id"],
                    "case_id": item["case_id"], "mode": item["mode"], "role": role, "started_at": started})
                self.snapshot("reserved")
            except Exception:
                self.terminal_unknown = True
                raise
        try:
            with self.lock:
                remaining = (self.deadline - utcnow()).total_seconds()
                if self.terminal_unknown or remaining <= 0:
                    raise ValidationError("Domain analysis unknown/deadline stops post-intent dispatch")
            response = self.adapter.complete(messages, **{**kwargs, "timeout": min(kwargs["timeout"], remaining)})
            receipt = asdict(response)
            if OLD.receipt_reflects_secret(receipt, self.config.api_key) or len(canonical_json(receipt).encode("utf-8")) > 65536:
                raise ValidationError("Domain analysis receipt reflects credential or exceeds bound")
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
            original_intent, accounted = deepcopy(intent), self.ledger.accounted
            try:
                OLD.write_new(self.directory / (prefix + "-receipt.json"), receipt)
                OLD.write_new(self.directory / (prefix + "-interval.json"), {"run_id": item["run_id"], "role": role,
                    "started_at": started, "finished_at": utcnow().isoformat(), "outcome": "known"})
                self.ledger.accounted += response.total_tokens - intent["reservation"]
                intent.update(usage_status="known", prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens, total_tokens=response.total_tokens)
                self.snapshot("settled")
            except Exception as exc:
                intent.clear()
                intent.update(original_intent)
                self.ledger.accounted, self.terminal_unknown = accounted, True
                OLD.write_new(self.directory / (prefix + "-settlement-incomplete.json"), {
                    "status": "unknown", "error_type": type(exc).__name__, "paid_retry": False,
                    "reservation_retained": intent["reservation"]})
                self.snapshot("terminal-unknown")
                raise
        return response


def token_usage(intents, parent_version):
    roles = {"parent": parent_version, **{domain + "_child": spec.version for domain, spec in child_specs().items()}}
    result = {}
    for label, role in roles.items():
        selected = [item for item in intents if item["task_id"].rsplit("/", 1)[-1] == role]
        known = [item for item in selected if item["usage_status"] == "known"]
        result[label] = {"model_decisions": len(selected), "known_calls": len(known), "unknown_calls": len(selected) - len(known),
            "input_tokens": sum(item["prompt_tokens"] for item in known),
            "output_tokens": sum(item["completion_tokens"] for item in known),
            "total_tokens": sum(item["total_tokens"] for item in known),
            "tokens_accounted": sum(item["total_tokens"] if item["usage_status"] == "known" else item["reservation"] for item in selected),
            "cumulative_dispatch_tokens_reserved": sum(item["reservation"] for item in selected)}
    result["whole_task"] = {key: sum(row[key] for row in result.values()) for key in next(iter(result.values()))}
    return result


def evaluate(rows):
    initial = [row for row in rows if not row.get("repair_of_run_id")]
    pairs, accepted = [], {}
    for identity in CASE_IDS:
        selected = {}
        for mode in MODES:
            original_row = next((row for row in initial if row["case_id"] == identity and row["mode"] == mode), None)
            candidates = [row for row in rows if row["case_id"] == identity and row["mode"] == mode]
            final = candidates[-1] if candidates else None
            accepted[(identity, mode)] = bool(final and final["assessment"]["functional_passed"])
            selected[mode] = {"initial_run_id": original_row["run_id"] if original_row else None,
                "final_run_id": final["run_id"] if final else None, "accepted": accepted[(identity, mode)],
                "initial_failed": bool(original_row and not original_row["assessment"]["functional_passed"])}
        pairs.append({"case_id": identity, "modes": selected, "equal_accepted_quality": all(accepted[(identity, mode)] for mode in MODES)})
    totals = {mode: sum(row["token_usage"]["whole_task"]["total_tokens"] for row in rows if row["mode"] == mode) for mode in MODES}
    accounted = {mode: sum(row["token_usage"]["whole_task"]["tokens_accounted"] for row in rows if row["mode"] == mode) for mode in MODES}
    known = all(row["token_usage"]["whole_task"]["unknown_calls"] == 0 for row in rows)
    quality = len(initial) == 6 and all(pair["equal_accepted_quality"] for pair in pairs)
    strong = min(totals["direct"], totals["tool"]) if quality and known else None
    efficient = bool(quality and known and strong and totals["child"] * 10 <= strong * 9
        and totals["child"] * 10 <= totals["tool"] * 9)
    choices = [decision for row in rows for decision in (row.get("paid_usage") or {}).get("autonomy_audit", [])
        if decision["partial_required_operator_selection"]]
    return {"pairs": pairs, "equal_complete_accepted_quality": quality, "all_usage_known": known,
        "whole_task_known_total_tokens_by_mode_including_failures_and_repairs": totals,
        "whole_task_accounted_tokens_by_mode_including_failures_and_repairs": accounted,
        "stronger_valid_A_B_total_tokens": strong, "child_vs_tool_total_tokens_delta": totals["child"] - totals["tool"],
        "child_reduction_vs_tool_percent": 100 * (totals["tool"] - totals["child"]) / totals["tool"] if quality and known and totals["tool"] else None,
        "efficiency_10_percent_candidate_passed": efficient,
        "initial_functional_results": {"passed": sum(row["assessment"]["functional_passed"] for row in initial), "total": 6},
        "repair_functional_results": {"passed": sum(row["assessment"]["functional_passed"] for row in rows if row.get("repair_of_run_id")),
            "total": len(rows) - len(initial)},
        "autonomous_legal_operator_path_choice_observed": bool(choices),
        "actual_operator_choice_evidence": choices,
        "agent_incremental_value_proven": False, "statistical_superiority": False, "defaults_changed": False,
        "practical_value_decision": "limited_profile_efficiency_candidate_passed" if efficient else "explicit_experiment_retained_no_practical_benefit_proven"}


def children(directory, item, report):
    store = CheckpointStore(Path(directory) / "runs")
    results = []
    for child in report.get("child_results", []):
        restored = store.read(item["scope"], child["child_run_id"])["report"]
        if restored["parent_run_id"] != item["run_id"] or restored["run_id"] != child["child_run_id"]:
            raise IntegrityError("Analysis Child report is not bound to the original root")
        results.append(deepcopy(restored))
    return results


def dispatch_overlap(directory, intents):
    intervals = []
    for intent in intents:
        if intent["usage_status"] != "known":
            continue
        prefix = f"{intent['number']:03d}"
        interval = OLD.read(Path(directory) / (prefix + "-interval.json"))
        run, role = intent["task_id"].rsplit("/", 1)
        start, end = (datetime.fromisoformat(interval[key]) for key in ("started_at", "finished_at"))
        if (interval["run_id"] != run or interval["role"] != role
                or start.tzinfo is None or end.tzinfo is None or end < start):
            raise IntegrityError("Domain analysis paid overlap interval differs from durable intent")
        intervals.append((run, role, start, end))
    roles = {domain: spec.version for domain, spec in child_specs().items()}
    return any(first[0] == second[0] and first[1] == roles["financial"] and second[1] == roles["market"]
        and max(first[2], second[2]) < min(first[3], second[3]) for first in intervals for second in intervals)


def assess(item, report, child_reports, sources, intents, dispatch_directory):
    """Full expected quality and actual execution, separately from efficiency."""
    request, expected = DynamicRequest.from_dict(item["request"]), item["expected_outcome"]
    checks = {
        "exact_source_bound_factual_view": observe_tool("hypotheses", report) == item["catalog_observations"]["O:hypotheses"],
        "expected_status": report["status"] == expected["status"],
        "required_checks_retained": [check["id"] for check in report["required_checks"]] == item["required_check_ids"],
        "required_checks_match_oracle": {check["id"]: check["status"] for check in report["required_checks"]} == expected["required_check_statuses"],
        "full_independent_verifier": report["verification"]["status"] == "verified",
        "actual_final_verification_tool": len([event for event in report["trace"]
            if event["event"] == "tool_finished" and event["tool"] == "verification"]) == 1,
        "provider_network_calls_zero": report["usage"]["financial_provider_network_calls"] == 0,
    }
    case = next(case for case in original.build_cases() if case["id"] == item["case_id"])
    service, access = sources.context(case)
    checks["immutable_source_oracle"] = (digest(sources.inputs(case)) == item["input_ref"]
        and original.parallel.catalog_oracle(service, access, request) == item["catalog_observations"]
        and OLD.authorized_envelope(service, access, request) == item["authorization_envelope"])
    denied = []
    for domain in ("financial", "market"):
        try:
            read_domain(service, request, AccessContext(access.scope, frozenset({"explicit-denied-provider"})), domain)
        except PermissionDenied:
            denied.append(domain)
    checks["actual_denied_source_reauthorization"] = denied == ["financial", "market"]
    root, spec = report["root_budget"], spec_for(item["mode"])
    known = sum(intent["total_tokens"] or 0 for intent in intents)
    accounted = sum(intent["total_tokens"] if intent["usage_status"] == "known" else intent["reservation"] for intent in intents)
    checks["root_usage_bound_to_paid_receipts"] = (root["model_attempts"] == len(intents)
        and root["total_tokens"] == known and root["tokens_accounted"] == accounted
        and root["unknown_usage_calls"] == sum(intent["usage_status"] == "unknown" for intent in intents))
    checks["root_budget_passed"] = (root["model_attempts"] <= 16 and root["tool_attempts"] <= 18
        and root["tokens_accounted"] <= 96000 and root["unknown_usage_calls"] == 0
        and root["unresolved_child_allocations"] == 0 and all(value >= 0 for value in root["remaining"].values()))
    checks["parent_local_budget_passed"] = (report["usage"]["model_attempts"] <= spec.max_decisions
        and report["usage"]["tool_calls"] <= spec.max_tools and report["usage"]["tokens_accounted"] <= spec.max_tokens)
    analysis = report.get("domain_analysis", {})
    checks["explicit_route_profile"] = analysis.get("mode") == item["mode"] and analysis.get("profile_id", analysis.get("profile")) == PROFILE
    if item["mode"] == "child":
        checks["two_actual_analysis_children"] = len(child_reports) == 2 and all(
            child["status"] in {"completed", "insufficient"} and child.get("schema") == "domain-analysis-result/v1"
            for child in child_reports)
        checks["actual_child_calculation_review"] = all(all(any(event["event"] == "tool_finished" and event["tool"] == tool
            for event in child["trace"]) for tool in ("calculation", "domain_review")) for child in child_reports)
        reviews = [event for child in child_reports for event in child["trace"] if event["event"] == "domain_review_executed"]
        checks["one_actual_fraction_local_review_per_child"] = len(reviews) == 2 and all(
            event.get("production_calculations") == 0 and event.get("fraction_verifications") == 1 for event in reviews)
        joins = [event for event in report["trace"] if event["event"] == "domain_join"]
        checks["join_zero_production_zero_fraction"] = len(joins) == 2 and all(
            event.get("production_calculations") == 0 and event.get("fraction_verifications") == 0
            and event.get("source_checks", 0) > 0 and event.get("execution_receipt_checks", 0) > 0 for event in joins)
        checks["no_parent_duplicate_domain_production"] = not any(event["event"] == "tool_finished" and event["tool"] == "domain_review"
            for event in report["trace"])
        composition = [event for event in report["trace"] if event["event"] == "parent_composition"]
        checks["composition_consumes_both_domains"] = len(composition) == 1 and composition[0]["delegated_domains"] == ["financial", "market"] and composition[0]["produced_domains"] == []
        checks["actual_parallel_group"] = len(report.get("parallel_groups", [])) == 1
        checks["actual_parallel_child_model_io_overlap"] = dispatch_overlap(dispatch_directory, intents)
    else:
        checks["no_child_model_loops"] = not child_reports and all(intent["task_id"].endswith("/" + item["parent_version"]) for intent in intents)
    return {"checks": checks, "functional_passed": all(checks.values()), "status": report["status"],
        "source_proven_insufficiency": expected["status"] == "insufficient" and all(checks.values()),
        "stop_reason": report.get("stop_reason")}


def paid_usage(item, report, child_reports, directory, intents):
    from stock_research.research.domain_analysis_protocol import decode_model_view
    reports = {item["parent_version"]: report}
    reports.update({child_specs()[child["domain"]].version: child for child in child_reports})
    bound, autonomy = set(), []
    for intent in intents:
        prefix = f"{intent['number']:03d}"
        messages = OLD.read(Path(directory) / (prefix + "-messages.json"))
        payload = json.loads(messages[1]["content"])
        role, turn = payload["protocol_version"], payload["control"]["decision"]
        record = reports[role]["context_telemetry"][turn - 1]
        actual = sum(len(message["content"].encode("utf-8")) for message in messages)
        if ((role, turn) in bound or record["message_sha256"] != digest(messages)
                or record["total_context_bytes"] != actual or actual > 12000 or not record["model_dispatched"]):
            raise IntegrityError("Domain analysis telemetry differs from exact actual paid input")
        receipt = OLD.read(Path(directory) / (prefix + "-receipt.json"))
        if intent["usage_status"] == "known" and any(record[field] != receipt[source] for field, source in (
                ("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens"), ("total_tokens", "total_tokens"))):
            raise IntegrityError("Domain analysis telemetry differs from paid receipt Token")
        if role != item["parent_version"] and intent["usage_status"] == "known":
            action = json.loads(receipt["content"])
            operators = [reference.removeprefix("operator:") for reference in action.get("refs", [])
                if reference.startswith("operator:")]
            context = decode_model_view(payload["analysis_context"])
            required = context["operators"]
            autonomy.append({"intent_number": intent["number"], "case_id": item["case_id"], "root_run_id": item["run_id"],
                "role": role, "turn": turn, "actual_action": action,
                "paid_message_sha256": digest(messages), "paid_receipt_sha256": digest(receipt),
                "observation_ref": digest(context["observations"]),
                "registered_legal_actions_ref": digest(payload["control"]["legal_next_actions"]),
                "selected_operators": operators, "required_operators": required,
                "partial_required_operator_selection": bool(action.get("tool") == "calculation"
                    and operators and len(operators) < len(required)),
                "actual_task_bound_feedback": payload["control"].get("previous_action_error"),
                "incremental_usefulness_proven": False,
                "scope": "real paid path selection/ordering evidence only; mandatory coverage and deterministic value ownership unchanged"})
        bound.add((role, turn))
    dispatched = {(role, index + 1) for role, value in reports.items()
        for index, record in enumerate(value.get("context_telemetry", [])) if record["model_dispatched"]}
    if dispatched != bound:
        raise IntegrityError("Domain analysis omitted actual Parent/Child paid calls")
    return {"bound_paid_turns": len(bound), "actual_input_cap": 12000, "all_parent_child_paid_calls_retained": True,
        "autonomy_audit": autonomy}


def latency(report, child_reports, directory, intents):
    value = infrastructure.latency(report, child_reports, directory, intents)
    spans = value["tool_spans"]
    mode = report.get("domain_analysis", {}).get("mode")
    value.update(production_tool_span_sum_ms=sum(span["span_ms"] for span in spans
            if span["tool"] == "domain_calculation" or span["tool"] == "calculation"
                and (span["run_id"] != report["run_id"] or mode == "direct")),
        local_review_tool_span_sum_ms=sum(span["span_ms"] for span in spans if span["tool"] == "domain_review"),
        coordination_tool_span_sum_ms=sum(span["span_ms"] for span in spans if span["tool"].endswith("_child")
            or span["tool"].endswith("_analysis_tool")),
        parent_composition_calculation_span_sum_ms=sum(span["span_ms"] for span in spans
            if span["run_id"] == report["run_id"] and span["tool"] == "calculation"),
        production_vs_independent_review_split_available=False,
        pure_coordination_overhead_ms=None,
        coordination_scope="wrapper spans include nested Child model/source/production work; validated Join stage elapsed is reported separately",
        direct_parent_production_vs_composition_split_available=False)
    return value


def stage_metrics(report, child_reports, runtime_metrics=None):
    """Use executed counters, preserving missing instrumentation as unavailable.

    Trace measurements are immutable workload evidence. In-memory verifier audit
    counters are captured once for the original run, then separately for replay.
    They never change a frozen report or get added to overlapping wall spans.
    """
    categories = {
        "domain_production": {"domain_production"},
        "child_local_review": {"domain_review_executed"},
        "domain_local_review": {"domain_review_executed"},
        "parent_join": {"domain_join"},
        "parent_composition": {"parent_composition"},
        "parent_remaining_checks": {"parent_remaining_checks"},
        "final_verification": {"root_full_verification", "final_verification", "full_verification_executed"},
    }
    reports = [report] + child_reports
    counters = ("production_calculations", "fraction_verifications", "full_fraction_verifications",
        "source_checks", "execution_receipt_checks")
    result = {}
    for label, event_names in categories.items():
        events = [{"run_id": current["run_id"], **deepcopy(event)} for current in reports
            for event in current.get("trace", []) if event["event"] in event_names
            and (label != "child_local_review" or current in child_reports)]
        result[label] = {"actual_stage_events": len(events), "events": events,
            "elapsed_ms": sum(event["elapsed_ms"] for event in events)
                if events and all(type(event.get("elapsed_ms")) is int for event in events) else None,
            **{counter: sum(event[counter] for event in events)
                if events and all(type(event.get(counter)) is int for event in events) else None
                for counter in counters}}
    # Some versions place final independent verification counts on the successful
    # tool receipt rather than a separate stage event. Both remain actual trace.
    if not result["final_verification"]["actual_stage_events"]:
        events = [deepcopy(event) for event in report.get("trace", []) if event["event"] == "tool_finished"
            and event["tool"] == "verification" and type(event.get("full_fraction_verifications")) is int]
        result["final_verification"].update(actual_stage_events=len(events), events=events,
            full_fraction_verifications=sum(event["full_fraction_verifications"] for event in events) if events else None)
    result["runtime_verifier_audit_metrics"] = deepcopy(runtime_metrics) if runtime_metrics is not None else None
    internal_events = [deepcopy(event) for event in report.get("trace", [])
        if event["event"] == "tool_finished" and event.get("tool") in {"domain_calculation", "domain_review"}
        and event.get("wrapper_call_id") is not None]
    result["deterministic_domain_internal_tools"] = {
        "calculation_calls": sum(event["tool"] == "domain_calculation" for event in internal_events),
        "review_calls": sum(event["tool"] == "domain_review" for event in internal_events),
        "elapsed_ms": sum(event["elapsed_ms"] for event in internal_events)
            if internal_events and all(type(event.get("elapsed_ms")) is int for event in internal_events) else None,
        "events": internal_events,
        "fraction_oracle_calls": sum(event["fraction_verifications"] for event in internal_events)
            if internal_events and all(type(event.get("fraction_verifications")) is int for event in internal_events) else None,
    }
    result["measurement_scope"] = "stage elapsed/counters plus separately captured integrity audits; nested spans are not summed as complete wall"
    return result


def validate_receipts(directory, ledger, items, live_directory):
    by_run = {item["run_id"]: item for item in items}
    known, accounted, reserved, unknown, counts = 0, 0, 0, 0, {}
    for number, intent in enumerate(ledger["intents"], 1):
        prefix = f"{number:03d}"
        messages, raw = (OLD.read(Path(directory) / (prefix + "-" + kind + ".json")) for kind in ("messages", "intent"))
        run, role = intent["task_id"].rsplit("/", 1)
        item, spec = by_run[run], role_spec(by_run[run], role)
        actual_role, _, turn = validate_outbound(messages, item, {"max_tokens": spec.output_tokens}, Path(live_directory) / run / "runs")
        counts[(run, role)] = counts.get((run, role), 0) + 1
        amount = sum(len(message["content"].encode("utf-8")) for message in messages) + 256 + spec.output_tokens
        if (number != intent["number"] or role != actual_role or turn != counts[(run, role)]
                or amount != raw["reservation"] or amount != intent["reservation"]
                or raw["messages_sha256"] != digest(messages) or intent["messages_sha256"] != digest(messages)
                or raw["task_id"] != intent["task_id"] or raw["usage_status"] != "unknown" or raw["total_tokens"] is not None):
            raise IntegrityError("Domain analysis actual receipt lacks original reservation/wire identity")
        reserved += amount
        receipt = OLD.read(Path(directory) / (prefix + "-receipt.json"))
        if intent["usage_status"] == "known":
            response = ChatResult(**receipt)
            validate_model_result(response, spec, amount)
            if any(intent[field] != receipt[field] for field in ("prompt_tokens", "completion_tokens", "total_tokens")):
                raise IntegrityError("Domain analysis ledger Token does not match validated receipt")
            known += response.total_tokens
            accounted += response.total_tokens
        elif receipt.get("status") == "unknown" or (Path(directory) / (prefix + "-settlement-incomplete.json")).exists():
            unknown += 1
            accounted += amount
        else:
            raise IntegrityError("Domain analysis unknown receipt reservation was released or fabricated")
    expected = {"known_tokens": known, "tokens_accounted": accounted, "cumulative_tokens_reserved": reserved,
        "unknown_usage_calls": unknown, "decisions": len(ledger["intents"]),
        "max_decisions": LIMITS["max_decisions"], "max_tokens_accounted": LIMITS["max_tokens_accounted"]}
    if any(ledger.get(key) != value for key, value in expected.items()) or accounted > LIMITS["max_tokens_accounted"] or len(ledger["intents"]) > LIMITS["max_decisions"]:
        raise IntegrityError("Domain analysis receipt accounting differs from frozen campaign")
    return expected


def _run_item(item, cases, sources, model, directory, plan_sha256, *, repair_of=None):
    run_dir = Path(directory) / item["run_id"]
    run_dir.mkdir(exist_ok=False)
    stopped = model.terminal_unknown or utcnow() >= model.deadline
    OLD.write_new(run_dir / "run-intent.json", {"run_id": item["run_id"], "case_id": item["case_id"], "mode": item["mode"],
        "plan_sha256": plan_sha256, "deadline": model.deadline.isoformat(), "repair_of_run_id": repair_of,
        "external_dispatch_allowed": not stopped, "paid_retry": False, "campaign_before": model.ledger.snapshot()})
    model.item, model.checkpoints = item, run_dir / "runs"
    started, report, child_reports, paid, timings = time.monotonic(), None, [], None, None
    runner = None
    runtime_started, runtime_finished = None, None
    try:
        if stopped:
            raise ValidationError("Campaign unknown paid outcome or original freeze deadline stops remaining slots")
        service, access = sources.context(cases[item["case_id"]])
        runner = runtime(service, CheckpointStore(model.checkpoints), item["mode"], model, inherited_deadline=model.deadline)
        runtime_started = time.monotonic()
        try:
            report = runner.run(DynamicRequest.from_dict(item["request"]), access, run_id=item["run_id"])
        finally:
            runtime_finished = time.monotonic()
        OLD.write_new(run_dir / "report.json", report)
        with (run_dir / "report.md").open("x", encoding="utf-8") as stream:
            stream.write(markdown(report))
        if report["root_budget"]["unknown_usage_calls"] or report["root_budget"]["unresolved_child_allocations"]:
            model.terminal_unknown = True
        intents = original.run_intents(model.ledger.snapshot(), item["run_id"])
        child_reports = children(run_dir, item, report)
        assessment = assess(item, report, child_reports, sources, intents, model.directory)
        paid = paid_usage(item, report, child_reports, model.directory, intents)
        timings = latency(report, child_reports, model.directory, intents)
        error_type = None
    except Exception as exc:
        error_type = type(exc).__name__
        OLD.write_new(run_dir / "failure.json", {"error_type": error_type, "paid_retry": False,
            "report_retained": report is not None, "run_started": not stopped, "ledger": model.ledger.snapshot()})
        assessment = {"functional_passed": False, "checks": {}, "status": report.get("status") if report else None}
    intents = original.run_intents(model.ledger.snapshot(), item["run_id"])
    finished = time.monotonic()
    row = {"case_id": item["case_id"], "run_id": item["run_id"], "mode": item["mode"], "parent_version": item["parent_version"],
        "report": report, "child_reports": child_reports, "assessment": assessment, "paid_usage": paid,
        "latency": timings, "intents": intents, "error_type": error_type, "run_started": not stopped,
        "repair_of_run_id": repair_of, "token_usage": token_usage(intents, item["parent_version"]),
        "stage_metrics": stage_metrics(report, child_reports, getattr(runner, "analysis_metrics", None)) if report else None,
        "overall_measured_wall_ms": round((finished - started) * 1000) if not stopped else None,
        "runtime_wall_ms": round((runtime_finished - runtime_started) * 1000) if runtime_finished is not None else None,
        "runtime_preparation_ms": round((runtime_started - started) * 1000) if runtime_started is not None else None,
        "harness_validation_ms": round((finished - runtime_finished) * 1000) if runtime_finished is not None else None,
        "paid_retry": False, "independent_new_task_count": 0}
    OLD.write_new(run_dir / "summary.json", row)
    row["run_file_hashes"] = original.file_hashes(run_dir)
    return row


def _save_summary(directory, plan_sha256, plan, model, rows, items, *, name="initial"):
    if history_hashes() != plan["history_hashes"]:
        raise IntegrityError("Domain analysis changed prior historical financial/model artifacts")
    ledger = model.ledger.snapshot()
    receipt_validation = validate_receipts(model.directory, ledger, items, directory)
    summary = {"schema": "domain-analysis-live-summary/v1", "plan_sha256": plan_sha256,
        "deadline": plan["deadline"], "ledger": ledger, "receipt_validation": receipt_validation,
        "rows": rows, "evaluation": evaluate(rows), "phase": name,
        "unknown_paid_outcome_stopped_dispatch": model.terminal_unknown,
        "remaining_repair_slots": 2 - sum(bool(row["repair_of_run_id"]) for row in rows),
        "model": plan["model"], "financial_provider_network_calls": 0,
        "defaults_changed": False, "next_stage_started": False}
    OLD.write_new(Path(directory) / (name + "-summary.json"), summary)
    return summary


def live(expected_sha):
    plan, sources = checked(expected_sha)
    config = load_model_config()
    if config.model != plan["model"] or digest(config.endpoint) != plan["endpoint_sha256"]:
        raise IntegrityError("Domain analysis configured endpoint/model changed after freeze")
    directory = OUT / "live"
    directory.mkdir(exist_ok=False)
    dispatch = directory / "dispatch"
    dispatch.mkdir()
    model = RecordingModel(config, datetime.fromisoformat(plan["deadline"]), dispatch)
    OLD.write_new(directory / "campaign-intent.json", {"plan_sha256": expected_sha,
        "frozen_at": plan["frozen_at"], "deadline": plan["deadline"], "limits": LIMITS,
        "initial_ledger": model.ledger.snapshot(), "old_budget_reused": False, "maximum_runs": 8, "paid_retry": False})
    cases = {case["id"]: case for case in plan["cases"]}
    rows = [_run_item(item, cases, sources, model, directory, expected_sha) for item in plan["items"]]
    summary = _save_summary(directory, expected_sha, plan, model, rows, plan["items"])
    OLD.write_new(directory / "initial-manifest.json", {"schema": "domain-analysis-immutable-stage/v1", "plan_sha256": expected_sha,
        "files": original.file_hashes(directory), "initial_denominator": 6})
    return summary


def restored_model(plan, directory, items):
    config = load_model_config()
    if config.model != plan["model"] or digest(config.endpoint) != plan["endpoint_sha256"]:
        raise IntegrityError("Domain analysis controlled configuration changed")
    model = RecordingModel(config, datetime.fromisoformat(plan["deadline"]), Path(directory) / "dispatch")
    revisions = sorted(model.directory.glob("ledger-*.json"))
    if revisions:
        ledger = OLD.read(revisions[-1])
        model.ledger.intents = deepcopy(ledger["intents"])
        model.ledger.accounted, model.ledger.cumulative_reserved = ledger["tokens_accounted"], ledger["cumulative_tokens_reserved"]
        model.revision = max(int(path.name.split("-")[1]) for path in revisions)
        model.terminal_unknown = bool(ledger["unknown_usage_calls"])
        for intent in model.ledger.intents:
            run, role = intent["task_id"].rsplit("/", 1)
            key = (run, role)
            model.role_calls[key] = model.role_calls.get(key, 0) + 1
        validate_receipts(model.directory, model.ledger.snapshot(), items, directory)
    return model


def _repair_plans():
    return [OLD.read(path) for path in sorted((OUT / "repairs").glob("*/plan.json"))]


def freeze_repair(expected_sha, failed_run_id, diagnosis_path):
    # Repairs have a new code freeze; source, task, oracle, local/root budgets and
    # original absolute campaign deadline stay pinned to the initial plan.
    plan, sources = checked(expected_sha, replay=True)
    repairs = _repair_plans()
    if len(repairs) >= 2:
        raise ValidationError("Domain analysis two repair slots exhausted")
    initial = OLD.read(OUT / "live/initial-summary.json")
    failed = next((row for row in initial["rows"] if row["run_id"] == failed_run_id), None)
    if failed is None or failed["assessment"]["functional_passed"] or not failed["run_started"]:
        raise IntegrityError("Repair must refer to one actual failed initial slot")
    if any(item["repair_of_run_id"] == failed_run_id for item in repairs):
        raise IntegrityError("A failed initial slot cannot consume multiple automatic repair attempts")
    if initial["ledger"]["unknown_usage_calls"] or initial["unknown_paid_outcome_stopped_dispatch"]:
        raise ValidationError("Unknown paid/Child result cannot be repaired by new paid run")
    if utcnow() >= datetime.fromisoformat(plan["deadline"]):
        raise ValidationError("Original freeze deadline stops new repair dispatch")
    diagnosis = OLD.read(diagnosis_path)
    failure_path = OUT / "live" / failed_run_id / "summary.json"
    if (diagnosis.get("schema") != "domain-analysis-repair-diagnosis/v1"
            or diagnosis.get("failed_run_id") != failed_run_id
            or diagnosis.get("failure_evidence") != evidence_ref(failure_path)
            or not diagnosis.get("root_cause") or not diagnosis.get("minimal_fix")
            or diagnosis.get("regression_status") != "passed" or diagnosis.get("code_files") != code_files()):
        raise IntegrityError("Repair requires concrete failed logs, minimal fix and current-code regression evidence")
    old_item = next(item for item in plan["items"] if item["run_id"] == failed_run_id)
    case = next(case for case in plan["cases"] if case["id"] == old_item["case_id"])
    item = frozen_item(case, old_item["mode"], sources)
    for key in ("request", "input_ref", "authorization_envelope", "catalog_observations", "expected_outcome", "required_check_ids"):
        if item[key] != old_item[key]:
            raise IntegrityError("Repair changed the original frozen financial task or expected quality")
    repair = {"schema": "domain-analysis-repair-frozen-plan/v1", "initial_plan_sha256": expected_sha,
        "slot": len(repairs) + 1, "item": item, "repair_of_run_id": failed_run_id,
        "deadline": plan["deadline"], "campaign_limits": LIMITS, "code_files": code_files(),
        "diagnosis_evidence": evidence_ref(diagnosis_path), "old_failure_retained": True,
        "new_independent_task_count": 0, "new_budget": False, "unknown_paid_retry": False}
    path = OUT / "repairs" / str(repair["slot"]) / "plan.json"
    OLD.write_new(path, repair)
    return {"prepared": True, "repair_sha256": OLD.sha(path), "slot": repair["slot"], "deadline": plan["deadline"]}


def repair_live(expected_sha, repair_sha256):
    plan, sources = checked(expected_sha, replay=True)
    repairs = _repair_plans()
    repair = next((item for item in repairs if OLD.sha(OUT / "repairs" / str(item["slot"]) / "plan.json") == repair_sha256), None)
    if (repair is None or repair["initial_plan_sha256"] != expected_sha or repair["deadline"] != plan["deadline"]
            or repair["campaign_limits"] != LIMITS or repair["code_files"] != code_files()
            or repair["diagnosis_evidence"] != evidence_ref(OLD.ROOT / repair["diagnosis_evidence"]["path"])):
        raise IntegrityError("Domain analysis repair freeze/code/evidence changed")
    directory = OUT / "live"
    initial = OLD.read(directory / "initial-summary.json")
    prior_rows = initial["rows"] + [OLD.read(directory / ("repair-" + str(item["slot"]) + "-row.json"))
        for item in repairs if item["slot"] < repair["slot"]]
    items = plan["items"] + [item["item"] for item in repairs if item["slot"] <= repair["slot"]]
    model = restored_model(plan, directory, items)
    if len(prior_rows) >= 8 or model.terminal_unknown or utcnow() >= model.deadline:
        raise ValidationError("Domain analysis original campaign bounds stop repair")
    cases = {case["id"]: case for case in plan["cases"]}
    row = _run_item(repair["item"], cases, sources, model, directory, expected_sha, repair_of=repair["repair_of_run_id"])
    OLD.write_new(directory / ("repair-" + str(repair["slot"]) + "-row.json"), row)
    return _save_summary(directory, expected_sha, plan, model, prior_rows + [row], items, name="repair-" + str(repair["slot"]))


def readonly_replay(expected_sha):
    plan, sources = checked(expected_sha, replay=True)
    directory = OUT / "live"
    before = original.file_hashes(directory)
    initial_manifest = OLD.read(directory / "initial-manifest.json")
    if initial_manifest.get("plan_sha256") != expected_sha or initial_manifest.get("initial_denominator") != 6:
        raise IntegrityError("Domain analysis initial failure denominator/manifest changed")
    if any(before.get(name) != checksum for name, checksum in initial_manifest["files"].items()):
        raise IntegrityError("Domain analysis replaced an original frozen initial artifact")
    repairs = _repair_plans()
    completed_repairs = [item for item in repairs if (directory / ("repair-" + str(item["slot"]) + "-row.json")).exists()]
    items = plan["items"] + [item["item"] for item in completed_repairs]
    stage = "repair-" + str(completed_repairs[-1]["slot"]) if completed_repairs else "initial"
    summary = OLD.read(directory / (stage + "-summary.json"))
    if summary["evaluation"] != evaluate(summary["rows"]) or summary["receipt_validation"] != validate_receipts(
            directory / "dispatch", summary["ledger"], items, directory):
        raise IntegrityError("Domain analysis frozen Token/evaluation/receipt evidence changed")
    cases, matched, failures, recovery_audits = {case["id"]: case for case in plan["cases"]}, [], [], []
    by_run = {item["run_id"]: item for item in items}
    with patch.object(CheckpointStore, "append", side_effect=AssertionError("read-only replay cannot append")), \
            patch.object(original.NoNetwork, "complete", side_effect=AssertionError("read-only replay cannot pay")):
        for row in summary["rows"]:
            item = by_run[row["run_id"]]
            run_dir = directory / row["run_id"]
            if original.file_hashes(run_dir) != row["run_file_hashes"]:
                raise IntegrityError("Domain analysis report/checkpoint/failure files changed")
            if row["report"] is None:
                failures.append({"run_id": row["run_id"], "error_type": row["error_type"]})
                continue
            service, access = sources.context(cases[row["case_id"]])
            audit_started = time.monotonic()
            replay_runner = runtime(service, CheckpointStore(run_dir / "runs"), row["mode"], original.NoNetwork(),
                inherited_deadline=datetime.fromisoformat(plan["deadline"]))
            restored = replay_runner.run(DynamicRequest.from_dict(item["request"]), access, resume=row["run_id"])
            recovery_audits.append({"run_id": row["run_id"], "elapsed_ms": round((time.monotonic() - audit_started) * 1000),
                "runtime_verifier_audit_metrics": deepcopy(getattr(replay_runner, "analysis_metrics", None)),
                "model_calls": 0, "provider_network_calls": 0, "checkpoint_appends": 0})
            if restored != row["report"] or restored != OLD.read(run_dir / "report.json"):
                raise IntegrityError("Domain analysis completed zero-network replay changed report")
            if row["token_usage"] != token_usage(row["intents"], item["parent_version"]):
                raise IntegrityError("Domain analysis full root Token accounting changed")
            if row["error_type"] is None and assess(item, restored, row["child_reports"], sources, row["intents"], directory / "dispatch") != row["assessment"]:
                raise IntegrityError("Domain analysis complete quality/source/permission replay changed")
            matched.append(row["run_id"])
            if not row["assessment"]["functional_passed"]:
                failures.append({"run_id": row["run_id"], "error_type": row["error_type"], "status": restored["status"]})
    if before != original.file_hashes(directory) or history_hashes() != plan["history_hashes"]:
        raise IntegrityError("Domain analysis read-only replay changed historical/run artifacts")
    return {"schema": "domain-analysis-readonly-replay/v1", "status": "passed", "plan_sha256": expected_sha,
        "identical_reports": len(matched), "retained_failures": failures, "replay_same": True,
        "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0,
        "live_files_unchanged": True, "evaluation": summary["evaluation"], "recovery_audits": recovery_audits,
        "defaults_changed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "freeze", "live", "replay", "repair-freeze", "repair-live"))
    parser.add_argument("--plan-sha256")
    parser.add_argument("--offline-evidence")
    parser.add_argument("--preflight-evidence")
    parser.add_argument("--failed-run-id")
    parser.add_argument("--diagnosis-evidence")
    parser.add_argument("--repair-sha256")
    parser.add_argument("--evidence-out", help="Save read-only preflight as a new workspace-local JSON artifact")
    args = parser.parse_args(argv)
    if args.action == "preflight":
        result = preflight()
        if args.evidence_out:
            path = Path(args.evidence_out).resolve()
            if not path.is_relative_to(OLD.ROOT.resolve()):
                raise IntegrityError("Preflight output must stay within the authorized workspace")
            OLD.write_new(path, result)
            result = {"status": result["status"], "evidence": evidence_ref(path),
                "unique_historical_reports_replayed": result["unique_historical_reports_replayed"],
                "model_calls": 0, "provider_calls": 0, "checkpoint_appends": 0}
    elif args.action == "freeze":
        result = prepare(args.offline_evidence, args.preflight_evidence)
    elif args.action == "live":
        result = live(args.plan_sha256)
    elif args.action == "replay":
        result = readonly_replay(args.plan_sha256)
    elif args.action == "repair-freeze":
        result = freeze_repair(args.plan_sha256, args.failed_run_id, args.diagnosis_evidence)
    else:
        result = repair_live(args.plan_sha256, args.repair_sha256)
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
