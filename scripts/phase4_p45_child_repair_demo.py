"""One frozen same-case P4.5 Child-progress repair retest.

The original 600500 failure and its denominator stay immutable. This harness
uses the identical request, public source envelope, configured endpoint/model
and limits with explicit v2 Child specs and a new run/checkpoint directory.
Synthetic transports can validate this contract, never the live repair outcome.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
import json
from pathlib import Path
from threading import Lock
import time
import uuid

import phase4_p45_demo as original
from phase3_benchmark_v2 import CampaignSources
from phase3_benchmark_v2_contract import validate_cases
from stock_research.errors import IntegrityError, ValidationError
from stock_research.model_adapters.chat import ChatModelAdapter, ChatResult, load_model_config
from stock_research.models import canonical_json, digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import (DynamicRequest, FinancialRequest,
    FinancialChildSpec, MarketRequest, MarketChildSpec, ParallelParentSpec)
from stock_research.research.dynamic_protocol import dynamic_messages
from stock_research.research.report import markdown
from stock_research.research.runtime import validate_model_result


ORIGINAL = original.OUT
ORIGINAL_PLAN_SHA256 = "33e71c95464bd61723b1b95d78e07ca351858a3f46e0d77cc717d716a31a2c13"
OUT = original.old.ROOT / ".artifacts/phase4/p45-child-progress-20261005/attempt-1"
SPEC = ParallelParentSpec()
CHILD_SPECS = {"financial": FinancialChildSpec(version="financial-child-v2"),
               "market": MarketChildSpec(version="market-child-v2")}
ROLES = {SPEC.version: (DynamicRequest, SPEC),
    CHILD_SPECS["financial"].version: (FinancialRequest, CHILD_SPECS["financial"]),
    CHILD_SPECS["market"].version: (MarketRequest, CHILD_SPECS["market"])}
ROLE_DOMAINS = {spec.version: domain for domain, spec in CHILD_SPECS.items()}
LIMITS = original.LIMITS
CASE_ID = original.CASE_ID


def runtime(service, checkpoints, model=None, **kwargs):
    return DynamicRuntime(service, checkpoints, model, SPEC,
                          domain_child_specs=CHILD_SPECS, **kwargs)


def original_hashes():
    """Content preservation guard; never writes to or resumes the original run."""
    return {path.relative_to(ORIGINAL).as_posix(): original.old.sha(path)
            for path in sorted(ORIGINAL.rglob("*")) if path.is_file()}


def original_plan():
    if original.old.sha(ORIGINAL / "plan.json") != ORIGINAL_PLAN_SHA256:
        raise IntegrityError("original P4.5 frozen plan changed")
    plan = original.old.read(ORIGINAL / "plan.json")
    report = original.old.read(ORIGINAL / "live/report.json")
    summary = original.old.read(ORIGINAL / "live/summary.json")
    if (plan["case"]["id"] != CASE_ID or plan["item"]["request"]["question"] != original.QUESTION
            or report["status"] != "partial" or summary["assessment"]["functional_passed"] is not False
            or (plan["max_decisions"], plan["max_tokens_accounted"], plan["max_seconds"]) != LIMITS
            or plan["context_limit_bytes"] != 12000 or plan["parent_spec_identity"] != SPEC.identity):
        raise IntegrityError("original failure, task or unchanged limits differ")
    return plan


def code_files():
    return {**original.code_files(),
            "scripts/phase4_p45_child_repair_demo.py": original.old.sha(Path(__file__))}


def local_limits(spec):
    return {key: getattr(spec, key) for key in ("max_decisions", "max_tools", "max_tokens",
            "max_seconds", "output_tokens", "context_bytes", "no_progress_limit")}


def prepare():
    prior, sources = original_plan(), CampaignSources()
    case = deepcopy(prior["case"])
    service, access = sources.context(case)
    request = DynamicRequest.from_dict(prior["item"]["request"])
    validation = validate_cases([case], sources.context)
    envelope = original.old.authorized_envelope(service, access, request)
    oracle = original.catalog_oracle(service, access, request)
    if (validation != prior["contract_validation"] or not validation["all_cases_contract_valid"]
            or digest(sources.inputs(case)) != prior["item"]["input_ref"]
            or access.scope != prior["item"]["scope"]
            or envelope != prior["item"]["authorization_envelope"]
            or oracle != prior["item"]["catalog_observations"]):
        raise IntegrityError("repair retest must retain the original input and authority")
    config, run = load_model_config(), uuid.uuid4().hex
    if config.model != prior["model"] or digest(config.endpoint) != prior["endpoint_sha256"]:
        raise IntegrityError("repair retest configured endpoint or model differs from original")
    item = {"case_id": CASE_ID, "request": request.to_dict(), "scope": access.scope, "run_id": run,
        "spec_identity": SPEC.identity, "input_ref": prior["item"]["input_ref"],
        "messages": runtime(service, None).preview(request, access, run_id=run),
        "authorization_envelope": envelope, "catalog_observations": oracle}
    plan = {"schema": "phase4-p45-child-progress-demo/v1", "case": case, "item": item,
        "contract_validation": validation, "model": config.model, "endpoint_sha256": digest(config.endpoint),
        "code_files": code_files(), "parent_spec_identity": SPEC.identity,
        "child_spec_identities": {spec.version: spec.identity for spec in CHILD_SPECS.values()},
        "child_protocol_versions": {domain: spec.version for domain, spec in CHILD_SPECS.items()},
        "parent_local_limits": local_limits(SPEC),
        "child_local_limits": {domain: local_limits(spec) for domain, spec in CHILD_SPECS.items()},
        "root_limits": {"decisions": SPEC.root_max_decisions, "tools": SPEC.root_max_tools,
                        "tokens": SPEC.root_max_tokens},
        "max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "max_seconds": LIMITS[2],
        "deadline_policy": "original_absolute_deadline_inheritance_with_unchanged_local_limits",
        "context_limit_bytes": 12000, "expected_status": "completed", "expected_parallel_width": 2,
        "provider_network_calls": 0, "old_budget_reused": False, "blind": False,
        "same_case_repair_retest": True, "repair_retest_count": 1, "independent_new_task_count": 0,
        "original_task_id": CASE_ID, "original_plan_sha256": ORIGINAL_PLAN_SHA256,
        "original_functional_results": {"passed": 0, "total": 1},
        "original_report_sha256": original.old.sha(ORIGINAL / "live/report.json"),
        "original_artifact_hashes": original_hashes(), "no_performance_superiority_claim": True}
    original.old.write_new(OUT / "plan.json", plan)
    return {"prepared": True, "plan_sha256": original.old.sha(OUT / "plan.json"),
            "model_calls": 0, "financial_provider_network_calls": 0,
            "same_case_repair_retest": True, "independent_new_task_count": 0,
            "original_functional_results": {"passed": 0, "total": 1}}


def checked(expected_sha, *, replay=False):
    plan, prior = original.old.read(OUT / "plan.json"), original_plan()
    if (original.old.sha(OUT / "plan.json") != expected_sha
            or plan["schema"] != "phase4-p45-child-progress-demo/v1"
            or plan["case"] != prior["case"] or plan["item"]["request"] != prior["item"]["request"]
            or plan["item"]["scope"] != prior["item"]["scope"]
            or plan["parent_spec_identity"] != SPEC.identity
            or plan["child_spec_identities"] != {spec.version: spec.identity for spec in CHILD_SPECS.values()}
            or plan["child_protocol_versions"] != {domain: spec.version for domain, spec in CHILD_SPECS.items()}
            or plan["parent_local_limits"] != local_limits(SPEC)
            or plan["child_local_limits"] != {domain: local_limits(spec) for domain, spec in CHILD_SPECS.items()}
            or plan["root_limits"] != {"decisions": SPEC.root_max_decisions, "tools": SPEC.root_max_tools,
                                      "tokens": SPEC.root_max_tokens}
            or (plan["max_decisions"], plan["max_tokens_accounted"], plan["max_seconds"]) != LIMITS
            or plan["context_limit_bytes"] != 12000 or plan["independent_new_task_count"] != 0
            or plan["same_case_repair_retest"] is not True or plan["repair_retest_count"] != 1
            or plan["original_functional_results"] != {"passed": 0, "total": 1}
            or plan["original_plan_sha256"] != ORIGINAL_PLAN_SHA256
            or plan["original_report_sha256"] != original.old.sha(ORIGINAL / "live/report.json")
            or plan["original_artifact_hashes"] != original_hashes()
            or not replay and plan["code_files"] != code_files()):
        raise IntegrityError("frozen Child repair plan, original evidence, code or bounds changed")
    sources = CampaignSources()
    service, access = sources.context(plan["case"])
    request = DynamicRequest.from_dict(plan["item"]["request"])
    if (digest(sources.inputs(plan["case"])) != plan["item"]["input_ref"]
            or plan["item"]["input_ref"] != prior["item"]["input_ref"]
            or validate_cases([plan["case"]], sources.context) != plan["contract_validation"]
            or original.catalog_oracle(service, access, request) != plan["item"]["catalog_observations"]
            or plan["item"]["catalog_observations"] != prior["item"]["catalog_observations"]
            or original.old.authorized_envelope(service, access, request) != plan["item"]["authorization_envelope"]
            or plan["item"]["authorization_envelope"] != prior["item"]["authorization_envelope"]
            or runtime(service, None).preview(request, access, run_id=plan["item"]["run_id"]) != plan["item"]["messages"]):
        raise IntegrityError("Child repair frozen source, permission, context or preview changed")
    return plan, sources


class RecordingModel:
    """Durable campaign intent and full receipts; no retries or network lock."""
    def __init__(self, config, plan, deadline, directory):
        self.config, self.adapter, self.plan = config, ChatModelAdapter(config), plan
        self.deadline, self.directory = deadline, directory
        self.ledger, self.role_calls, self.lock = original.old.RootLedger(LIMITS[0], LIMITS[1]), {}, Lock()
        self.revision = 0

    def snapshot(self, kind):
        self.revision += 1
        original.old.write_new(self.directory / f"ledger-{self.revision:02d}-{kind}.json", self.ledger.snapshot())

    def complete(self, messages, **kwargs):
        item = self.plan["item"]
        payload, parent = json.loads(messages[1]["content"]), DynamicRequest.from_dict(item["request"])
        role = payload["protocol_version"]
        if role not in ROLES:
            raise IntegrityError("outbound Child repair role exceeds frozen specs")
        request_type, spec = ROLES[role]
        control, context_args = payload["control"], {}
        if role == SPEC.version:
            request, observations, refs, stage = original.compact._parent_observations(payload, item)
            tools = json.loads(item["messages"][1]["content"])["available_tools"]
            required = payload["context"]["required_checks"]
            context_args = {"context_scope": item["scope"], "context_run_id": item["run_id"],
                            "context_refs": refs, "context_stage": stage}
        else:
            domain = ROLE_DOMAINS[role]
            request, tools = request_type.from_parent(parent), [domain]
            observations, required = payload["observations"], payload["required_checks"]
            for observation in observations:
                if observation != item["authorization_envelope"]["source_observations"][domain]:
                    raise IntegrityError("Child repair outbound observation exceeds frozen source")
        rebuilt, _ = dynamic_messages(request, tools, observations, required, control["plan"], 12000,
            decision=control["decision"], protocol_error=control.get("previous_action_error"), version=role,
            finish_rejection=control.get("finish_rejection"), delegation_results=payload.get("delegation_results"),
            **context_args)
        if rebuilt != messages or payload["available_tools"] != tools or kwargs["max_tokens"] != spec.output_tokens:
            raise IntegrityError("outbound repair messages differ from exact frozen public-source view")
        if original.old.contains_secret(messages, self.config.api_key):
            raise IntegrityError("outbound credential reflection rejected")
        with self.lock:
            count = self.role_calls.get(role, 0) + 1
            if count != control["decision"] or count > spec.max_decisions:
                raise IntegrityError("outbound repair turn exceeds unchanged bounds")
            self.role_calls[role] = count
            intent = self.ledger.reserve(CASE_ID + "/" + role, messages, spec.output_tokens)
            prefix = f"{intent['number']:02d}"
            original.old.write_new(self.directory / (prefix + "-messages.json"), messages)
            original.old.write_new(self.directory / (prefix + "-intent.json"), deepcopy(intent))
            self.snapshot("reserved")
        remaining, dispatched_at = (self.deadline - utcnow()).total_seconds(), utcnow().isoformat()
        original.old.write_new(self.directory / (prefix + "-dispatch.json"), {"role": role, "started_at": dispatched_at})
        try:
            if remaining <= 0:
                raise ValidationError("repair campaign deadline exceeded")
            result = self.adapter.complete(messages, **{**kwargs, "timeout": min(kwargs["timeout"], remaining)})
            receipt = asdict(result)
            if original.old.receipt_reflects_secret(receipt, self.config.api_key) or len(canonical_json(receipt).encode("utf-8")) > 65536:
                raise ValidationError("receipt reflected credentials or exceeded size bound")
            validate_model_result(result, spec, intent["reservation"])
        except BaseException as exc:
            with self.lock:
                original.old.write_new(self.directory / (prefix + "-receipt.json"), {
                    "status": "unknown", "error_type": type(exc).__name__})
                self.snapshot("unknown")
            raise
        with self.lock:
            self.ledger.settle(intent, result)
            original.old.write_new(self.directory / (prefix + "-receipt.json"), receipt)
            original.old.write_new(self.directory / (prefix + "-interval.json"), {"role": role,
                "started_at": dispatched_at, "finished_at": utcnow().isoformat()})
            self.snapshot("settled")
        return result


def dispatch_overlap(directory, intents):
    intervals = []
    for intent in intents:
        prefix = f"{intent['number']:02d}"
        path = directory / (prefix + "-interval.json")
        if not path.exists():
            continue
        interval = original.old.read(path)
        dispatched = original.old.read(directory / (prefix + "-dispatch.json"))
        role = intent["task_id"].split("/")[-1]
        start, end = datetime.fromisoformat(interval["started_at"]), datetime.fromisoformat(interval["finished_at"])
        if (role not in ROLES or interval["role"] != role or dispatched["role"] != role
                or interval["started_at"] != dispatched["started_at"]
                or start.tzinfo is None or end.tzinfo is None or end < start):
            raise IntegrityError("repair dispatch interval differs from paid intent")
        intervals.append({"domain": ROLE_DOMAINS.get(role), "start": start, "end": end})
    return any(max(a["start"], b["start"]) < min(a["end"], b["end"])
        for a in intervals for b in intervals if a["domain"] == "financial" and b["domain"] == "market")


def assess(plan, report, directory, intents):
    result = original.assessment(plan["case"], report, plan["item"]["catalog_observations"])
    result["actual_child_model_dispatch_overlap"] = dispatch_overlap(directory, intents)
    result["functional_passed"] = result["functional_passed"] and result["actual_child_model_dispatch_overlap"]
    return result


def live(expected_sha):
    plan, sources = checked(expected_sha)
    config = load_model_config()
    if config.model != plan["model"] or digest(config.endpoint) != plan["endpoint_sha256"]:
        raise IntegrityError("frozen repair endpoint or model changed")
    directory = OUT / "live"
    directory.mkdir(exist_ok=False)
    deadline = utcnow() + timedelta(seconds=LIMITS[2])
    model = RecordingModel(config, plan, deadline, directory)
    original.old.write_new(directory / "campaign-intent.json", {"plan_sha256": expected_sha,
        "deadline": deadline.isoformat(), "limits": list(LIMITS), "run_id": plan["item"]["run_id"],
        "same_case_repair_retest": True, "independent_new_budget": True,
        "old_limits_increased": False, "original_failure_retained": True})
    service, access = sources.context(plan["case"])
    started = time.monotonic()
    try:
        report = runtime(service, CheckpointStore(directory / "runs"), model, inherited_deadline=deadline).run(
            DynamicRequest.from_dict(plan["item"]["request"]), access, run_id=plan["item"]["run_id"])
    except BaseException as exc:
        original.old.write_new(directory / "failure.json", {"error_type": type(exc).__name__,
            "ledger": model.ledger.snapshot(), "deadline": deadline.isoformat(), "paid_retry": False})
        raise
    elapsed, ledger = round((time.monotonic() - started) * 1000), model.ledger.snapshot()
    original.old.write_new(directory / "report.json", report)
    (directory / "report.md").write_text(markdown(report), encoding="utf-8")
    summary = {"plan_sha256": expected_sha, "assessment": assess(plan, report, directory, ledger["intents"]),
        "ledger": ledger, "wall_clock_ms": elapsed, "deadline": deadline.isoformat(),
        "financial_provider_network_calls": 0, "old_results_preserved": original_hashes() == plan["original_artifact_hashes"],
        "paid_retry": False, "real_model_retest_count": 1, "independent_new_task_count": 0,
        "same_case_repair_retest": True, "original_functional_results": {"passed": 0, "total": 1},
        "no_performance_superiority_claim": True}
    original.old.write_new(directory / "summary.json", summary)
    return summary


def replay(expected_sha):
    plan, sources = checked(expected_sha, replay=True)
    saved = original.old.read(OUT / "live/report.json")
    summary = original.old.read(OUT / "live/summary.json")
    for intent in summary["ledger"]["intents"]:
        prefix = f"{intent['number']:02d}"
        messages = original.old.read(OUT / "live" / (prefix + "-messages.json"))
        if digest(messages) != intent["messages_sha256"]:
            raise IntegrityError("repair paid messages hash changed")
        if intent["usage_status"] == "known":
            role = intent["task_id"].split("/")[-1]
            if role not in ROLES:
                raise IntegrityError("repair paid role differs from frozen spec")
            result = ChatResult(**original.old.read(OUT / "live" / (prefix + "-receipt.json")))
            validate_model_result(result, ROLES[role][1], intent["reservation"])
            if any(getattr(result, key) != intent[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
                raise IntegrityError("repair paid receipt differs from campaign ledger")
    class NoNetwork:
        class config:
            model = SPEC.model
        def complete(self, *args, **kwargs):
            raise AssertionError("completed repair replay must not pay for a model")
    service, access = sources.context(plan["case"])
    before = original.old.sha(OUT / "live/runs/checkpoints.sqlite3")
    restored = runtime(service, CheckpointStore(OUT / "live/runs"), NoNetwork()).run(
        DynamicRequest.from_dict(plan["item"]["request"]), access, resume=saved["run_id"])
    if (restored != saved or assess(plan, restored, OUT / "live", summary["ledger"]["intents"]) != summary["assessment"]
            or original.old.sha(OUT / "live/runs/checkpoints.sqlite3") != before):
        raise IntegrityError("repair replay changed canonical result or checkpoint")
    return {"replay_same": True, "model_calls": 0, "financial_provider_network_calls": 0,
        "checkpoint_appends": 0, "functional_passed": summary["assessment"]["functional_passed"],
        "same_case_repair_retest": True, "independent_new_task_count": 0,
        "original_functional_results": {"passed": 0, "total": 1}}


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--replay", action="store_true")
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    if not args.prepare and not args.plan_sha256:
        parser.error("live/replay requires frozen --plan-sha256")
    result = prepare() if args.prepare else live(args.plan_sha256) if args.live else replay(args.plan_sha256)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("prepared") or result.get("replay_same") or result.get("assessment", {}).get("functional_passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
