"""One immutable same-case Phase 5 Parent progress v2 repair retest.

The original 8/9 campaign and its 688184 parallel failure remain intact.
Only the explicitly versioned Parent protocol and run ID change. No provider
collection, paid retry, independent new task, default change, or cap tuning.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import json
from pathlib import Path
import time
import uuid

import phase5_evaluate as original
from stock_research.errors import DataError, IntegrityError, ValidationError
from stock_research.model_adapters.chat import ChatModelAdapter, ChatResult, load_model_config
from stock_research.models import canonical_json, digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import (DynamicRequest, FinancialRequest,
    MarketRequest, ParallelParentSpec)
from stock_research.research.dynamic_protocol import dynamic_messages
from stock_research.research.report import markdown
from stock_research.research.runtime import validate_model_result


OLD = original.old
ORIGINAL = original.OUT
ORIGINAL_PLAN_SHA256 = "bae9f7aea9c4fb8764df60e4f4e106d21cc6ecd1da266ae0b418693828be5869"
FROZEN_ORIGINAL_SOURCE = OLD.ROOT / ".artifacts/phase5/parent-progress-original-source-20261006"
OUT = OLD.ROOT / ".artifacts/phase5/parent-progress-v2-20261006"
VERSION = "dynamic-parent-parallel-v2"
LIMITS = (16, 96000, 480)
CASE_ID = "p5-688184"
CHILD_SPECS = original.CHILD_SPECS
REPAIR_ACCEPTANCE_RULES = {
    "scope": "single_case_parent_v2_parallel_closed_loop_only",
    "execution_checks": {name: "passed" for name in
        ("read:financial", "read:market", "calculation", "hypotheses", "verification")},
    "hypothesis_check": {"id": "hypothesis:financial_deterioration", "status": "insufficient"},
    "expected_status": "insufficient", "facts": 6, "evidence": 12,
    "exact_original_source_oracle": True,
    "required_safety": ["point_in_time", "authorization", "immutable_snapshots", "lineage", "numeric_verification"],
    "unchanged_local_and_root_budgets": True, "exact_paid_wire_receipt_telemetry_usage": True,
    "unknown_paid_usage_calls": 0, "unresolved_child_allocations": 0,
    "actual_financial_market_child_model_io_overlap": True,
    "zero_model_provider_and_checkpoint_append_replay_identical": True,
    "original_campaign_results": {"passed": 8, "total": 9},
    "original_campaign_decision": "bounded_opt_in_not_supported",
    "independent_new_task_count": 0, "other_cases_parent_v2_validated": False,
}


def spec_for():
    return ParallelParentSpec(version=VERSION)


def runtime(service, checkpoints, model=None, **kwargs):
    return DynamicRuntime(service, checkpoints, model, spec_for(), domain_child_specs=CHILD_SPECS, **kwargs)


def code_files():
    return {**original.code_files(), "scripts/phase5_parent_repair.py": OLD.sha(Path(__file__))}


def original_guard():
    if OLD.sha(ORIGINAL / "plan.json") != ORIGINAL_PLAN_SHA256:
        raise IntegrityError("original Phase 5 plan changed")
    plan, sources = original.checked(ORIGINAL_PLAN_SHA256, replay=True)
    summary = OLD.read(ORIGINAL / "live/summary.json")
    item = next(i for i in plan["items"] if i["case_id"] == CASE_ID and i["route"] == "parallel")
    report = OLD.read(ORIGINAL / "live" / item["run_id"] / "report.json")
    checks = {c["id"]: c["status"] for c in report["required_checks"]}
    if (summary["passed_new_runs"] != 8 or summary["new_run_count"] != 9
            or report["status"] != "partial" or report["stop_reason"] != "no_progress"
            or checks["verification"] != "not_completed"
            or item["expected_outcome"]["status"] != "insufficient"
            or len(report["facts"]) != 6 or len(report["evidence"]) != 12):
        raise IntegrityError("original Phase 5 failure and denominator differ")
    for name, checksum in plan["code_files"].items():
        if OLD.sha(FROZEN_ORIGINAL_SOURCE / name) != checksum:
            raise IntegrityError("original frozen code source differs")
    return plan, item, report, sources


def prepare():
    if OUT.exists():
        raise IntegrityError("Parent repair output already exists; immutable retest cannot be replaced")
    prior, prior_item, prior_report, sources = original_guard()
    case = next(c for c in prior["cases"] if c["id"] == CASE_ID)
    service, access = sources.context(case)
    request = DynamicRequest.from_dict(prior_item["request"])
    item = deepcopy(prior_item)
    item.update(run_id=uuid.uuid4().hex, spec_identity=spec_for().identity)
    item["messages"] = runtime(service, None).preview(request, access, run_id=item["run_id"])
    config = load_model_config()
    if config.model != prior["model"] or digest(config.endpoint) != prior["endpoint_sha256"]:
        raise IntegrityError("repair endpoint/model differs from original campaign")
    plan = {"schema": "phase5-parent-progress-repair/v1", "case": deepcopy(case), "item": item,
        "model": config.model, "endpoint_sha256": prior["endpoint_sha256"], "code_files": code_files(),
        "parent_spec_identity": spec_for().identity, "parent_version": VERSION,
        "parent_local_limits": original.local_limits(spec_for()),
        "root_limits": {"decisions": spec_for().root_max_decisions, "tools": spec_for().root_max_tools,
                        "tokens": spec_for().root_max_tokens},
        "child_specs": {d: {"identity": s.identity, "version": s.version, "limits": original.local_limits(s)}
                        for d, s in CHILD_SPECS.items()},
        "campaign_limits": {"max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "max_seconds": LIMITS[2]},
        "original_plan_sha256": ORIGINAL_PLAN_SHA256,
        "original_report_sha256": OLD.sha(ORIGINAL / "live" / prior_item["run_id"] / "report.json"),
        "original_report_semantic_sha256": digest(prior_report),
        "original_campaign_file_hashes": original.file_hashes(ORIGINAL),
        "original_frozen_source_hashes": original.file_hashes(FROZEN_ORIGINAL_SOURCE),
        "original_functional_results": {"passed": 8, "total": 9},
        "original_failed_route_results": {"passed": 0, "total": 1},
        "original_campaign_decision": "bounded_opt_in_not_supported",
        "repair_scope": "single_case_parent_v2_parallel_closed_loop_only",
        "original_nine_run_gate_repaired": False, "other_cases_parent_v2_validated": False,
        "same_case_repair_retest": True, "independent_new_task_count": 0, "independent_test_task_count": 0,
        "repair_retest_count": 1, "context_limit_bytes": 12000, "old_budget_reused": False,
        "provider_network_calls": 0, "blind": False, "defaults_changed": False, "phase6_started": False,
        "repair_acceptance_rules": REPAIR_ACCEPTANCE_RULES,
        "question_source_oracle_and_limits_unchanged": True,
        "change_scope": "explicit Parent v2 trusted execution feedback only"}
    OLD.write_new(OUT / "plan.json", plan)
    return {"prepared": True, "plan_sha256": OLD.sha(OUT / "plan.json"), "same_case_repair_retest": True,
        "independent_new_task_count": 0, "original_functional_results": {"passed": 8, "total": 9},
        "model_calls": 0, "financial_provider_network_calls": 0}


def checked(expected_sha, *, replay=False):
    if not isinstance(expected_sha, str) or OLD.sha(OUT / "plan.json") != expected_sha:
        raise IntegrityError("Parent repair frozen plan hash differs")
    plan = OLD.read(OUT / "plan.json")
    prior, prior_item, prior_report, sources = original_guard()
    item = plan["item"]
    case = next(c for c in prior["cases"] if c["id"] == CASE_ID)
    service, access = sources.context(case)
    request = DynamicRequest.from_dict(prior_item["request"])
    expected = deepcopy(prior_item)
    expected.update(run_id=item["run_id"], spec_identity=spec_for().identity,
        messages=runtime(service, None).preview(request, access, run_id=item["run_id"]))
    if (plan["schema"] != "phase5-parent-progress-repair/v1" or item != expected or plan["case"] != case
            or item["run_id"] == prior_item["run_id"] or plan["parent_spec_identity"] != spec_for().identity
            or plan["parent_local_limits"] != original.local_limits(spec_for())
            or plan["root_limits"] != {"decisions": spec_for().root_max_decisions, "tools": spec_for().root_max_tools,
                                        "tokens": spec_for().root_max_tokens}
            or plan["child_specs"] != {d: {"identity": s.identity, "version": s.version, "limits": original.local_limits(s)}
                                      for d, s in CHILD_SPECS.items()}
            or plan["campaign_limits"] != {"max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "max_seconds": LIMITS[2]}
            or plan["original_campaign_file_hashes"] != original.file_hashes(ORIGINAL)
            or plan["original_frozen_source_hashes"] != original.file_hashes(FROZEN_ORIGINAL_SOURCE)
            or plan["original_report_sha256"] != OLD.sha(ORIGINAL / "live" / prior_item["run_id"] / "report.json")
            or plan["original_report_semantic_sha256"] != digest(prior_report)
            or plan["repair_acceptance_rules"] != REPAIR_ACCEPTANCE_RULES
            or plan["original_functional_results"] != {"passed": 8, "total": 9}
            or plan["original_campaign_decision"] != "bounded_opt_in_not_supported"
            or plan["original_nine_run_gate_repaired"] is not False or plan["other_cases_parent_v2_validated"] is not False
            or plan["independent_new_task_count"] != 0 or plan["context_limit_bytes"] != 12000
            or plan["same_case_repair_retest"] is not True or plan["old_budget_reused"] is not False
            or plan["defaults_changed"] is not False or plan["phase6_started"] is not False
            or not replay and plan["code_files"] != code_files()):
        raise IntegrityError("Parent repair original inputs, frozen code, bounds or identity differ")
    return plan, sources


def role_spec(role):
    if role == VERSION:
        return spec_for()
    for spec in CHILD_SPECS.values():
        if spec.version == role:
            return spec
    raise IntegrityError("repair outbound role exceeds frozen explicit v2/v3 specs")


def paid_parent_checks(checkpoint_directory, item, messages):
    """Recompute execution statuses from the exact durable pre-dispatch state."""
    payload = json.loads(messages[1]["content"])
    turn = payload["control"]["decision"]
    history = CheckpointStore(checkpoint_directory).history(item["scope"], item["run_id"])
    matches = [s for s in history if s["phase"] == "model_pending" and s.get("decisions")
        and s["decisions"][-1]["turn"] == turn and s["decisions"][-1]["message_sha256"] == digest(messages)]
    if not matches:
        raise IntegrityError("Parent repair wire has no matching durable paid state")
    request = DynamicRequest.from_dict(item["request"])
    state = matches[0]
    if state["request"] != item["request"] or state["run_id"] != item["run_id"]:
        raise IntegrityError("Parent repair execution state belongs to another request")
    # Pure existing Runtime check calculation; it does not execute tools or infer
    # financial facts from the outbound payload.
    checks = runtime(None, None)._check_results(state, request)
    if [c["id"] for c in checks] != item["required_check_ids"]:
        raise IntegrityError("Parent repair immutable execution requirements differ")
    return checks


def validate_outbound(messages, item, kwargs, checkpoint_directory):
    payload = json.loads(messages[1]["content"])
    role, control = payload["protocol_version"], payload["control"]
    spec, args = role_spec(role), {}
    if role == VERSION:
        request, observations, refs, stage = original.compact._parent_observations(payload, item)
        tools = json.loads(item["messages"][1]["content"])["available_tools"]
        checks = payload["context"]["required_checks"]
        args = {"context_scope": item["scope"], "context_run_id": item["run_id"],
            "context_refs": refs, "context_stage": stage,
            "parent_execution_checks": paid_parent_checks(checkpoint_directory, item, messages)}
    else:
        domain = next(d for d, s in CHILD_SPECS.items() if s.version == role)
        parent = DynamicRequest.from_dict(item["request"])
        request = (FinancialRequest if domain == "financial" else MarketRequest).from_parent(parent)
        tools, observations, checks = [domain], payload["observations"], payload["required_checks"]
        if any(o != item["authorization_envelope"]["source_observations"][domain] for o in observations):
            raise IntegrityError("repair Child observation exceeds frozen original source")
    rebuilt, _ = dynamic_messages(request, tools, observations, checks, control["plan"], 12000,
        decision=control["decision"], protocol_error=control.get("previous_action_error"), version=role,
        finish_rejection=control.get("finish_rejection"), delegation_results=payload.get("delegation_results"), **args)
    if rebuilt != messages or payload["available_tools"] != tools or kwargs.get("max_tokens") != spec.output_tokens:
        raise IntegrityError("repair outbound wire differs from durable exact source/execution view")
    return role, spec, control["decision"]


class RecordingModel(original.RecordingModel):
    def __init__(self, config, deadline, directory, item, checkpoints):
        super().__init__(config, deadline, directory, OLD.RootLedger(LIMITS[0], LIMITS[1]))
        self.adapter = ChatModelAdapter(config)
        self.item, self.checkpoints = item, checkpoints

    def complete(self, messages, **kwargs):
        role, spec, decision = validate_outbound(messages, self.item, kwargs, self.checkpoints)
        if OLD.contains_secret(messages, self.config.api_key):
            raise IntegrityError("repair outbound credential reflection rejected")
        with self.lock:
            count = self.role_calls.get(role, 0) + 1
            if count != decision or count > spec.max_decisions or (self.deadline - utcnow()).total_seconds() <= 0:
                raise ValidationError("repair local turn or campaign deadline exceeded")
            intent = self.ledger.reserve(self.item["run_id"] + "/" + role, messages, spec.output_tokens)
            self.role_calls[role] = count
            prefix = f"{intent['number']:03d}"
            OLD.write_new(self.directory / (prefix + "-messages.json"), messages)
            OLD.write_new(self.directory / (prefix + "-intent.json"), deepcopy(intent))
            self.snapshot("reserved")
        remaining, started = (self.deadline - utcnow()).total_seconds(), utcnow().isoformat()
        OLD.write_new(self.directory / (prefix + "-dispatch.json"), {"run_id": self.item["run_id"],
            "case_id": CASE_ID, "route": "parallel", "role": role, "started_at": started})
        try:
            if remaining <= 0:
                raise ValidationError("repair campaign deadline exceeded")
            response = self.adapter.complete(messages, **{**kwargs, "timeout": min(kwargs["timeout"], remaining)})
            receipt = asdict(response)
            if OLD.receipt_reflects_secret(receipt, self.config.api_key) or len(canonical_json(receipt).encode("utf-8")) > 65536:
                raise ValidationError("repair receipt reflected credentials or exceeded bound")
            validate_model_result(response, spec, intent["reservation"])
        except Exception as exc:
            with self.lock:
                OLD.write_new(self.directory / (prefix + "-receipt.json"), {"status": "unknown", "error_type": type(exc).__name__})
                OLD.write_new(self.directory / (prefix + "-interval.json"), {"run_id": self.item["run_id"],
                    "role": role, "started_at": started, "finished_at": utcnow().isoformat(), "outcome": "unknown"})
                self.snapshot("unknown")
            raise
        with self.lock:
            self.ledger.accounted += response.total_tokens - intent["reservation"]
            intent.update(usage_status="known", prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens, total_tokens=response.total_tokens)
            OLD.write_new(self.directory / (prefix + "-receipt.json"), receipt)
            OLD.write_new(self.directory / (prefix + "-interval.json"), {"run_id": self.item["run_id"],
                "role": role, "started_at": started, "finished_at": utcnow().isoformat(), "outcome": "known"})
            self.snapshot("settled")
        return response


def validate_receipts(directory, ledger, item, checkpoints):
    known, reserved, accounted, unknown, counts = 0, 0, 0, 0, {}
    for number, intent in enumerate(ledger["intents"], 1):
        prefix = f"{number:03d}"
        messages = OLD.read(Path(directory) / (prefix + "-messages.json"))
        raw = OLD.read(Path(directory) / (prefix + "-intent.json"))
        receipt = OLD.read(Path(directory) / (prefix + "-receipt.json"))
        run, role = intent["task_id"].split("/")
        spec = role_spec(role)
        actual_role, _, turn = validate_outbound(messages, item, {"max_tokens": spec.output_tokens}, checkpoints)
        counts[role] = counts.get(role, 0) + 1
        initial = {k: v for k, v in intent.items() if k not in {"prompt_tokens", "completion_tokens"}}
        initial.update(usage_status="unknown", total_tokens=None)
        amount = sum(len(m["content"].encode("utf-8")) for m in messages) + 256 + spec.output_tokens
        if (intent["number"] != number or run != item["run_id"] or raw != initial or actual_role != role
                or digest(messages) != intent["messages_sha256"] or amount != intent["reservation"]
                or turn != counts[role] or turn > spec.max_decisions):
            raise IntegrityError("repair paid intent/messages/local turn changed")
        reserved += amount
        if intent["usage_status"] == "known":
            result = ChatResult(**receipt)
            validate_model_result(result, spec, amount)
            if any(getattr(result, k) != intent[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
                raise IntegrityError("repair receipt differs from ledger")
            known += result.total_tokens
            accounted += result.total_tokens
        elif intent["usage_status"] == "unknown" and receipt.get("status") == "unknown":
            unknown += 1
            accounted += amount
        else:
            raise IntegrityError("repair unknown paid reservation was released or forged")
    if (known != ledger["known_tokens"] or accounted != ledger["tokens_accounted"]
            or reserved != ledger["cumulative_tokens_reserved"] or unknown != ledger["unknown_usage_calls"]
            or len(ledger["intents"]) != ledger["decisions"] or len(ledger["intents"]) > LIMITS[0] or accounted > LIMITS[1]):
        raise IntegrityError("repair campaign receipt accounting differs or exceeds frozen limits")
    return {"known_tokens": known, "tokens_accounted": accounted, "reserved": reserved,
            "unknown_usage_calls": unknown, "decisions": len(ledger["intents"])}


def validate_paid_telemetry(report, child_reports, directory, intents):
    reports = {VERSION: report}
    reports.update({CHILD_SPECS[c.get("domain", "financial")].version: c for c in child_reports})
    turns = set()
    for intent in intents:
        prefix = f"{intent['number']:03d}"
        messages = OLD.read(Path(directory) / (prefix + "-messages.json"))
        receipt = OLD.read(Path(directory) / (prefix + "-receipt.json"))
        payload = json.loads(messages[1]["content"])
        role, turn = payload["protocol_version"], payload["control"]["decision"]
        telemetry = reports[role]["context_telemetry"][turn - 1]
        actual = sum(len(m["content"].encode("utf-8")) for m in messages)
        if ((role, turn) in turns or telemetry["message_sha256"] != digest(messages)
                or telemetry["total_context_bytes"] != actual or telemetry["context_after_compaction_bytes"] != actual
                or actual > 12000 or telemetry["context_limit_bytes"] != 12000
                or not telemetry["model_dispatched"] or telemetry["context_budget_exceeded"]):
            raise IntegrityError("repair telemetry differs from exact bounded paid wire")
        turns.add((role, turn))
        if intent["usage_status"] == "known" and any(telemetry[a] != receipt[b] for a, b in
                (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens"), ("total_tokens", "total_tokens"))):
            raise IntegrityError("repair telemetry tokens differ from paid receipt")
    dispatched = {(role, index + 1) for role, report_value in reports.items()
        for index, t in enumerate(report_value.get("context_telemetry", [])) if t["model_dispatched"]}
    budget = report["root_budget"]
    known = sum(i["total_tokens"] or 0 for i in intents)
    accounted = known + sum(i["reservation"] for i in intents if i["usage_status"] == "unknown")
    if (dispatched != turns or budget["model_attempts"] != len(intents) or budget["total_tokens"] != known
            or budget["tokens_accounted"] != accounted
            or budget["tokens_dispatched_reserved"] != sum(i["reservation"] for i in intents)):
        raise IntegrityError("repair root paid usage differs from dispatched model turns")
    return {"bound_paid_turns": len(turns), "actual_wire_cap": 12000, "root_paid_usage_same": True}


def assess(item, report, directory, intents):
    # Original assessment checks bound outcomes/routes/budgets, not v1 identity.
    return original.assess(item, report, directory, intents)


def live(expected_sha):
    plan, sources = checked(expected_sha)
    config = load_model_config()
    if config.model != plan["model"] or digest(config.endpoint) != plan["endpoint_sha256"]:
        raise IntegrityError("repair frozen configured endpoint/model changed")
    directory, item = OUT / "live", plan["item"]
    directory.mkdir(exist_ok=False)
    dispatch = directory / "dispatch"
    dispatch.mkdir()
    deadline = utcnow() + timedelta(seconds=LIMITS[2])
    model = RecordingModel(config, deadline, dispatch, item, directory / "runs")
    OLD.write_new(directory / "campaign-intent.json", {"plan_sha256": expected_sha, "deadline": deadline.isoformat(),
        "limits": plan["campaign_limits"], "run_id": item["run_id"], "independent_new_budget": True,
        "same_case_repair_retest": True, "original_results": {"passed": 8, "total": 9}, "paid_retry": False})
    started, report, child_reports = time.monotonic(), None, []
    try:
        service, access = sources.context(plan["case"])
        report = runtime(service, CheckpointStore(directory / "runs"), model, inherited_deadline=deadline).run(
            DynamicRequest.from_dict(item["request"]), access, run_id=item["run_id"])
        OLD.write_new(directory / "report.json", report)
        with (directory / "report.md").open("x", encoding="utf-8") as stream:
            stream.write(markdown(report))
        child_reports = original.children_from_checkpoints(directory, item, report)
        assessment = assess(item, report, dispatch, model.ledger.snapshot()["intents"])
        safety = original.safety_checks(item, report, sources, assessment)
        telemetry = validate_paid_telemetry(report, child_reports, dispatch, model.ledger.snapshot()["intents"])
        assessment["checks"]["paid_telemetry_and_root_usage"] = True
        assessment["functional_passed"] = assessment["functional_passed"] and all(v == "passed" for v in safety.values())
        error_type = None
    except Exception as exc:
        error_type = type(exc).__name__
        OLD.write_new(directory / "failure.json", {"error_type": error_type, "paid_retry": False,
            "report_retained": report is not None, "ledger": model.ledger.snapshot()})
        assessment = {"functional_passed": False, "checks": {}, "status": report.get("status") if report else None}
        safety = {k: "unknown" for k in
                  ("point_in_time", "authorization", "immutable_snapshots", "lineage", "numeric_verification")}
        telemetry = None
    ledger = model.ledger.snapshot()
    receipt_validation = validate_receipts(dispatch, ledger, item, directory / "runs")
    summary = {"plan_sha256": expected_sha, "assessment": assessment, "safety_checks": safety,
        "paid_telemetry_validation": telemetry, "child_reports": child_reports,
        "ledger": ledger, "receipt_validation": receipt_validation,
        "wall_clock_ms": round((time.monotonic() - started) * 1000), "deadline": deadline.isoformat(), "error_type": error_type,
        "original_functional_results": {"passed": 8, "total": 9}, "repair_retest_count": 1,
        "original_campaign_decision": "bounded_opt_in_not_supported",
        "repair_scope": "single_case_parent_v2_parallel_closed_loop_only",
        "original_nine_run_gate_repaired": False, "other_cases_parent_v2_validated": False,
        "same_case_repair_retest": True, "independent_new_task_count": 0, "financial_provider_network_calls": 0,
        "paid_retry": False, "defaults_changed": False, "phase6_started": False}
    OLD.write_new(directory / "summary.json", summary)
    OLD.write_new(directory / "trace-dataset.json", {"schema": "phase5-parent-repair-trace/v1",
        "plan_sha256": expected_sha, "sample_kind": "retest", "case_id": CASE_ID, "route": "parallel",
        "run_id": item["run_id"], "report": report, "child_reports": child_reports, "summary": summary,
        "report_sha256": OLD.sha(directory / "report.json") if report is not None else None,
        "trace_sha256": digest(report["trace"]) if report is not None else None,
        "dispatch_receipt_hashes": original.file_hashes(dispatch), "independent_new_task_count": 0})
    OLD.write_new(directory / "trace-manifest.json", {"schema": "phase5-parent-repair-trace-manifest/v1",
        "plan_sha256": expected_sha, "trace_dataset_sha256": OLD.sha(directory / "trace-dataset.json"),
        "report_sha256": OLD.sha(directory / "report.json") if report is not None else None,
        "summary_sha256": OLD.sha(directory / "summary.json"),
        "files_before_manifest": original.file_hashes(directory)})
    if original.file_hashes(ORIGINAL) != plan["original_campaign_file_hashes"]:
        raise IntegrityError("repair changed original Phase 5 campaign")
    return summary


def replay(expected_sha):
    plan, sources = checked(expected_sha, replay=True)
    directory, item = OUT / "live", plan["item"]
    before = original.file_hashes(directory)
    summary, dataset = OLD.read(directory / "summary.json"), OLD.read(directory / "trace-dataset.json")
    manifest = OLD.read(directory / "trace-manifest.json")
    if (manifest["trace_dataset_sha256"] != OLD.sha(directory / "trace-dataset.json")
            or manifest["summary_sha256"] != OLD.sha(directory / "summary.json")
            or manifest["files_before_manifest"] != {k: v for k, v in before.items() if k != "trace-manifest.json"}):
        raise IntegrityError("repair immutable report/trace/receipt manifest differs")
    if validate_receipts(directory / "dispatch", summary["ledger"], item, directory / "runs") != summary["receipt_validation"]:
        raise IntegrityError("repair saved paid accounting changed")
    if original.file_hashes(directory / "dispatch") != dataset["dispatch_receipt_hashes"]:
        raise IntegrityError("repair retained paid receipts changed")
    if dataset["summary"] != summary:
        raise IntegrityError("repair trace summary differs from immutable report")
    exact = False
    if (directory / "report.json").exists():
        saved = OLD.read(directory / "report.json")
        service, access = sources.context(plan["case"])
        restored = runtime(service, CheckpointStore(directory / "runs"), original.NoNetwork()).run(
            DynamicRequest.from_dict(item["request"]), access, resume=item["run_id"])
        if (restored != saved or dataset["report"] != saved or digest(restored["trace"]) != dataset["trace_sha256"]
                or dataset["report_sha256"] != OLD.sha(directory / "report.json")
                or manifest["report_sha256"] != OLD.sha(directory / "report.json")):
            raise IntegrityError("repair canonical report or trace replay changed")
        exact = True
        if summary["error_type"] is None:
            children = original.children_from_checkpoints(directory, item, restored)
            assessment = assess(item, restored, directory / "dispatch", summary["ledger"]["intents"])
            safety = original.safety_checks(item, restored, sources, assessment)
            telemetry = validate_paid_telemetry(restored, children, directory / "dispatch", summary["ledger"]["intents"])
            assessment["checks"]["paid_telemetry_and_root_usage"] = True
            assessment["functional_passed"] = assessment["functional_passed"] and all(v == "passed" for v in safety.values())
            if (children != summary["child_reports"] or assessment != summary["assessment"]
                    or safety != summary["safety_checks"] or telemetry != summary["paid_telemetry_validation"]):
                raise IntegrityError("repair original assessment or safety replay changed")
    original_replay = original.replay(ORIGINAL_PLAN_SHA256)
    if original_replay["decision"] != "bounded_opt_in_not_supported":
        raise IntegrityError("repair altered original Phase 5 enablement decision")
    if before != original.file_hashes(directory) or original.file_hashes(ORIGINAL) != plan["original_campaign_file_hashes"]:
        raise IntegrityError("repair replay changed retained files or appended checkpoint")
    return {"replay_same": exact, "functional_passed": summary["assessment"]["functional_passed"],
        "original_campaign_replay": original_replay, "original_functional_results": {"passed": 8, "total": 9},
        "original_campaign_decision": "bounded_opt_in_not_supported",
        "repair_scope": "single_case_parent_v2_parallel_closed_loop_only",
        "original_nine_run_gate_repaired": False, "other_cases_parent_v2_validated": False,
        "repair_retest_count": 1, "independent_new_task_count": 0, "same_case_repair_retest": True,
        "model_calls": 0, "financial_provider_network_calls": 0, "checkpoint_appends": 0,
        "defaults_changed": False, "phase6_started": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--live", action="store_true")
    modes.add_argument("--replay", action="store_true")
    parser.add_argument("--plan-sha256")
    args = parser.parse_args(argv)
    if not args.prepare and not args.plan_sha256:
        parser.error("live/replay requires explicit frozen --plan-sha256")
    try:
        result = prepare() if args.prepare else live(args.plan_sha256) if args.live else replay(args.plan_sha256)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (DataError, OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"status": "failed", "error": "Parent repair frozen integrity or execution check failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
