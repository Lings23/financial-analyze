"""One new frozen, bounded M3 validation task on existing public snapshots.

Thread-safe intent recording wraps the same configured adapter. No retries, new
Providers, synthetic answers, changed failure denominator, or threshold tuning.
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

import phase4_demo as old
import phase4_p44_context_demo as compact
from phase3_benchmark_v2 import CampaignSources, candidate
from phase3_benchmark_v2_contract import validate_cases
from stock_research.errors import IntegrityError, ValidationError
from stock_research.model_adapters.chat import ChatModelAdapter, load_model_config, ChatResult
from stock_research.models import canonical_json, digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import (DynamicRequest, ParallelParentSpec,
    FinancialRequest, FinancialChildSpec, MarketRequest, MarketChildSpec)
from stock_research.research.dynamic_protocol import dynamic_messages, observe_tool
from stock_research.research.report import markdown
from stock_research.research.runtime import validate_model_result
from stock_research.research.study import calculate_study_claims
from stock_research.research.hypotheses import test_hypotheses, diagnose_insufficiency
from stock_research.research.tools import read_domain
from stock_research.research.verification import verify


OUT = old.ROOT / ".artifacts/phase4/p45-20261005"
SPEC = ParallelParentSpec()
ROLES = {SPEC.version: (DynamicRequest, SPEC),
    "financial-child-v1": (FinancialRequest, FinancialChildSpec()),
    "market-child-v1": (MarketRequest, MarketChildSpec())}
LIMITS = (16, 96000, 480)
CASE_ID = "p45-600500-independent-required-domains"
QUESTION = (
    "核对已绑定的2025半年报与2024半年报营业收入、归母净利润同报告期同比，检验两者是否均下降；"
    "同时报告本次冻结行情的实际观察价格变化和最大回撤。财务与行情都是本题必要输入，两个源读取彼此独立。"
    "第一步同时委派 Financial Child 和 Market Child：返回严格JSON对象，action为parallel，"
    "tools为[financial_child,market_child]并提供plan，各字段字符串须带JSON双引号。"
    "两Child只读各自绑定来源，合并后父运行依次通过tool动作完成calculation、hypotheses、verification，再finish。"
    "calculation引用financial和market，hypotheses引用calculation，verification引用hypotheses；"
    "这三个名称是tool字段值，action均为tool。保留全部事实、反证、来源和PIT，不推断因果或补缺数。")


def code_files():
    return {**old.implementation_files(), "scripts/phase4_p45_demo.py": old.sha(Path(__file__)),
            "scripts/phase4_p44_context_demo.py": old.sha(Path(compact.__file__))}


def build_case():
    manifest = old.read(old.PARENT)
    original = next(c for c in manifest["cases"] if c["id"] == "b2-l3-roster-600500")
    request = deepcopy(original["request"])
    request["bindings"] = [b for b in request["bindings"] if b["dataset"] in {"financial_income", "market_daily"}]
    request.update(hypotheses=["financial_deterioration"], objective="single_stock_research", event_record_id=None, benchmark=None)
    request.pop("hypothesis_version", None)
    case = candidate(CASE_ID, "L3", QUESTION, request,
        {b["dataset"]: original["source_scopes"][b["dataset"]] for b in request["bindings"]},
        stratum="parallel_two_required_independent_domains",
        mandatory=["observed_price_change", "observed_max_drawdown", "revenue_yoy", "net_income_parent_yoy"])
    case["scope"] = "phase4-p45-20261005/" + CASE_ID
    case["parent_case_id"] = original["id"]
    case["source_hashes"] = deepcopy(original["source_hashes"])
    case["success_criteria"].extend(["Both actual Child execution intervals overlap.",
        "All required checks pass; complete evidence graph, bounded root and exact no-model replay."])
    return case


def catalog_oracle(service, access, request):
    outputs = {d: read_domain(service, request, access, d) for d in ("financial", "market")}
    datasets = {k: v for output in outputs.values() for k, v in output.items()}
    calculated = calculate_study_claims(datasets, request)
    calculated["hypotheses"] = test_hypotheses(calculated, datasets, request)
    calculated["insufficiency_diagnostics"] = diagnose_insufficiency(calculated, datasets, request)
    observations = {"O:" + d: observe_tool(d, output) for d, output in outputs.items()}
    observations["O:hypotheses"] = observe_tool("hypotheses", calculated)
    observations["O:calculation"] = observe_tool("calculation", {**calculated, "hypotheses": []})
    observations["O:verification"] = observe_tool("verification", verify(calculated, datasets, request))
    return observations


def prepare():
    case, sources = build_case(), CampaignSources()
    service, access = sources.context(case)
    request = DynamicRequest.from_dict({**case["request"], "question": QUESTION})
    validation = validate_cases([case], sources.context)
    if not validation["all_cases_contract_valid"]:
        raise IntegrityError("new parallel public task is not contract-valid")
    config, run = load_model_config(), uuid.uuid4().hex
    item = {"case_id": CASE_ID, "request": request.to_dict(), "scope": access.scope, "run_id": run,
        "spec_identity": SPEC.identity, "input_ref": digest(sources.inputs(case)),
        "messages": DynamicRuntime(service, None, None, SPEC).preview(request, access, run_id=run),
        "authorization_envelope": old.authorized_envelope(service, access, request),
        "catalog_observations": catalog_oracle(service, access, request)}
    plan = {"schema": "phase4-p45-demo/v1", "case": case, "item": item, "contract_validation": validation,
        "model": config.model, "endpoint_sha256": digest(config.endpoint), "code_files": code_files(),
        "parent_spec_identity": SPEC.identity, "child_spec_identities": {r: s.identity for r, (_, s) in ROLES.items() if r != SPEC.version},
        "max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "max_seconds": LIMITS[2],
        "context_limit_bytes": 12000, "expected_status": "completed", "expected_parallel_width": 2,
        "provider_network_calls": 0, "old_budget_reused": False, "blind": False,
        "independent_new_task_count": 1, "underlying_sources_known_validation": True,
        "no_performance_superiority_claim": True}
    old.write_new(OUT / "plan.json", plan)
    return {"prepared": True, "plan_sha256": old.sha(OUT / "plan.json"), "model_calls": 0,
            "financial_provider_network_calls": 0, "contract_valid": True}


def checked(expected_sha, *, replay=False):
    plan = old.read(OUT / "plan.json")
    if old.sha(OUT / "plan.json") != expected_sha:
        raise IntegrityError("frozen P4.5 plan hash changed")
    if (plan["case"] != build_case() or plan["parent_spec_identity"] != SPEC.identity or
            (plan["max_decisions"], plan["max_tokens_accounted"], plan["max_seconds"]) != LIMITS or
            plan["context_limit_bytes"] != 12000 or not replay and plan["code_files"] != code_files()):
        raise IntegrityError("P4.5 frozen task, code, spec or bounds changed")
    sources = CampaignSources()
    service, access = sources.context(plan["case"])
    request = DynamicRequest.from_dict(plan["item"]["request"])
    if (request.question != QUESTION or digest(sources.inputs(plan["case"])) != plan["item"]["input_ref"] or
            validate_cases([plan["case"]], sources.context) != plan["contract_validation"] or
            catalog_oracle(service, access, request) != plan["item"]["catalog_observations"] or
            old.authorized_envelope(service, access, request) != plan["item"]["authorization_envelope"] or
            DynamicRuntime(service, None, None, SPEC).preview(request, access, run_id=plan["item"]["run_id"]) != plan["item"]["messages"]):
        raise IntegrityError("frozen P4.5 sources, permissions, context or preview changed")
    return plan, sources


class RecordingModel:
    """Independent campaign accounting: short locks never serialize network calls."""
    def __init__(self, config, plan, deadline, directory):
        self.config, self.adapter, self.plan = config, ChatModelAdapter(config), plan
        self.deadline, self.directory = deadline, directory
        self.ledger, self.role_calls, self.lock = old.RootLedger(LIMITS[0], LIMITS[1]), {}, Lock()
        self.revision = 0

    def snapshot(self, kind):
        self.revision += 1
        old.write_new(self.directory / f"ledger-{self.revision:02d}-{kind}.json", self.ledger.snapshot())

    def complete(self, messages, **kwargs):
        item = self.plan["item"]
        payload, parent = json.loads(messages[1]["content"]), DynamicRequest.from_dict(item["request"])
        role = payload["protocol_version"]
        if role not in ROLES:
            raise IntegrityError("outbound role exceeds frozen P4.5 specs")
        request_type, spec = ROLES[role]
        control, context_args = payload["control"], {}
        if role == SPEC.version:
            request, observations, refs, stage = compact._parent_observations(payload, item)
            tools = json.loads(item["messages"][1]["content"])["available_tools"]
            required = payload["context"]["required_checks"]
            context_args = {"context_scope": item["scope"], "context_run_id": item["run_id"],
                            "context_refs": refs, "context_stage": stage}
        else:
            request = request_type.from_parent(parent)
            tools = ["financial"] if role == "financial-child-v1" else ["market"]
            observations = payload["observations"]
            required = payload["required_checks"]
            for observation in observations:
                domain = tools[0]
                if observation != item["authorization_envelope"]["source_observations"][domain]:
                    raise IntegrityError("Child outbound observation exceeds exact frozen source")
        rebuilt, _ = dynamic_messages(request, tools, observations, required, control["plan"], 12000,
            decision=control["decision"], protocol_error=control.get("previous_action_error"), version=role,
            finish_rejection=control.get("finish_rejection"), delegation_results=payload.get("delegation_results"), **context_args)
        if rebuilt != messages or payload["available_tools"] != tools or kwargs["max_tokens"] != spec.output_tokens:
            raise IntegrityError("outbound P4.5 messages exceed frozen exact public-source view")
        if old.contains_secret(messages, self.config.api_key):
            raise IntegrityError("outbound credential reflection rejected")
        with self.lock:
            count = self.role_calls.get(role, 0) + 1
            if count != control["decision"] or count > spec.max_decisions:
                raise IntegrityError("outbound role turn exceeds frozen bounds")
            self.role_calls[role] = count
            intent = self.ledger.reserve(CASE_ID + "/" + role, messages, spec.output_tokens)
            prefix = f"{intent['number']:02d}"
            old.write_new(self.directory / (prefix + "-messages.json"), messages)
            old.write_new(self.directory / (prefix + "-intent.json"), deepcopy(intent))
            self.snapshot("reserved")
        remaining = (self.deadline - utcnow()).total_seconds()
        dispatched_at = utcnow().isoformat()
        old.write_new(self.directory / (prefix + "-dispatch.json"), {"role": role, "started_at": dispatched_at})
        try:
            if remaining <= 0:
                raise ValidationError("campaign deadline exceeded")
            result = self.adapter.complete(messages, **{**kwargs, "timeout": min(kwargs["timeout"], remaining)})
            receipt = asdict(result)
            if old.receipt_reflects_secret(receipt, self.config.api_key) or len(canonical_json(receipt).encode("utf-8")) > 65536:
                raise ValidationError("receipt reflected credentials or exceeded size bound")
            validate_model_result(result, spec, intent["reservation"])
        except BaseException as exc:
            with self.lock:
                old.write_new(self.directory / (prefix + "-receipt.json"), {"status": "unknown", "error_type": type(exc).__name__})
                self.snapshot("unknown")
            raise
        with self.lock:
            self.ledger.settle(intent, result)
            old.write_new(self.directory / (prefix + "-receipt.json"), receipt)
            old.write_new(self.directory / (prefix + "-interval.json"), {"role": role,
                "started_at": dispatched_at, "finished_at": utcnow().isoformat()})
            self.snapshot("settled")
        return result


def assessment(case, report, oracle):
    facts = {fact["name"] for fact in report["facts"]}
    checks = {"completed": report["status"] == "completed",
        "required_checks_passed": all(c["status"] == "passed" for c in report["required_checks"]),
        "required_checks_retained": [c["id"] for c in report["required_checks"]] ==
            old.bound_required_checks(DynamicRequest.from_dict({**case["request"], "question": case["research_question"]})),
        "mandatory_facts_present": set(case["expected_behavior"]["mandatory_fact_names"]) <= facts,
        "independent_claim_verification": report["verification"]["status"] == "verified",
        "exact_source_bound_factual_view": observe_tool("hypotheses", report) == oracle["O:hypotheses"],
        "financial_provider_network_calls_zero": report["usage"]["financial_provider_network_calls"] == 0}
    result = {"task_id": case["id"], "status": report["status"], "stop_reason": report["stop_reason"],
              "checks": checks, "functional_passed": all(checks.values())}
    groups = report.get("parallel_groups", [])
    result["actual_parallel_overlap"] = False
    if len(groups) == 1 and groups[0]["telemetry"]:
        branches = groups[0]["telemetry"]["branches"]
        result["actual_parallel_overlap"] = max(b["branch_started_at"] for b in branches) < min(b["branch_finished_at"] for b in branches)
    result["root_budget_passed"] = (report["root_budget"]["unknown_usage_calls"] == 0 and
        report["root_budget"]["unresolved_child_allocations"] == 0 and all(n >= 0 for n in report["root_budget"]["remaining"].values()))
    result["both_children_completed"] = len(report["child_results"]) == 2 and all(c["status"] == "completed" for c in report["child_results"])
    result["functional_passed"] = all((result["functional_passed"], result["actual_parallel_overlap"],
                                       result["root_budget_passed"], result["both_children_completed"]))
    return result


def live(expected_sha):
    plan, sources = checked(expected_sha)
    config = load_model_config()
    if config.model != plan["model"] or digest(config.endpoint) != plan["endpoint_sha256"]:
        raise IntegrityError("frozen configured endpoint/model changed")
    directory = OUT / "live"
    directory.mkdir(exist_ok=False)
    deadline = utcnow() + timedelta(seconds=LIMITS[2])
    model = RecordingModel(config, plan, deadline, directory)
    old.write_new(directory / "campaign-intent.json", {"plan_sha256": expected_sha, "deadline": deadline.isoformat(),
        "limits": list(LIMITS), "run_id": plan["item"]["run_id"], "independent_new_budget": True})
    service, access = sources.context(plan["case"])
    started = time.monotonic()
    try:
        report = DynamicRuntime(service, CheckpointStore(directory / "runs"), model, SPEC, inherited_deadline=deadline).run(
            DynamicRequest.from_dict(plan["item"]["request"]), access, run_id=plan["item"]["run_id"])
    except BaseException as exc:
        old.write_new(directory / "failure.json", {"error_type": type(exc).__name__, "ledger": model.ledger.snapshot(),
            "deadline": deadline.isoformat(), "paid_retry": False})
        raise
    elapsed = round((time.monotonic() - started) * 1000)
    old.write_new(directory / "report.json", report)
    (directory / "report.md").write_text(markdown(report), encoding="utf-8")
    assessment_result = assessment(plan["case"], report, plan["item"]["catalog_observations"])
    actual_io_overlap = dispatch_overlap(directory, model.ledger.snapshot()["intents"])
    assessment_result["actual_child_model_dispatch_overlap"] = actual_io_overlap
    assessment_result["functional_passed"] = assessment_result["functional_passed"] and actual_io_overlap
    summary = {"plan_sha256": expected_sha, "assessment": assessment_result,
        "ledger": model.ledger.snapshot(), "wall_clock_ms": elapsed, "deadline": deadline.isoformat(),
        "financial_provider_network_calls": 0, "old_results_preserved": True, "paid_retry": False,
        "real_model_task_count": 1, "no_performance_superiority_claim": True}
    old.write_new(directory / "summary.json", summary)
    return summary


def dispatch_overlap(directory, intents):
    intervals = []
    for intent in intents:
        prefix = f"{intent['number']:02d}"
        interval_path = directory / (prefix + "-interval.json")
        if not interval_path.exists():
            continue
        interval = old.read(interval_path)
        dispatched = old.read(directory / (prefix + "-dispatch.json"))
        role = intent["task_id"].split("/")[-1]
        if (interval["role"] != role or dispatched["role"] != role or
                interval["started_at"] != dispatched["started_at"] or
                datetime.fromisoformat(interval["finished_at"]) < datetime.fromisoformat(interval["started_at"])):
            raise IntegrityError("P4.5 dispatch interval differs from its paid intent")
        intervals.append(interval)
    return any(max(a["started_at"], b["started_at"]) < min(a["finished_at"], b["finished_at"])
        for a in intervals for b in intervals if a["role"] == "financial-child-v1" and b["role"] == "market-child-v1")


def replay(expected_sha):
    plan, sources = checked(expected_sha, replay=True)
    saved, summary = old.read(OUT / "live/report.json"), old.read(OUT / "live/summary.json")
    for intent in summary["ledger"]["intents"]:
        prefix = f"{intent['number']:02d}"
        messages = old.read(OUT / "live" / (prefix + "-messages.json"))
        if digest(messages) != intent["messages_sha256"]:
            raise IntegrityError("P4.5 paid message hash changed")
        if intent["usage_status"] == "known":
            result = ChatResult(**old.read(OUT / "live" / (prefix + "-receipt.json")))
            role = intent["task_id"].split("/")[-1]
            validate_model_result(result, ROLES[role][1], intent["reservation"])
            if any(getattr(result, k) != intent[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
                raise IntegrityError("P4.5 paid receipt differs from ledger")
    class NoNetwork:
        class config:
            model = SPEC.model
        def complete(self, *args, **kwargs):
            raise AssertionError("completed replay must never pay for a model")
    service, access = sources.context(plan["case"])
    restored = DynamicRuntime(service, CheckpointStore(OUT / "live/runs"), NoNetwork(), SPEC).run(
        DynamicRequest.from_dict(plan["item"]["request"]), access, resume=saved["run_id"])
    replay_assessment = assessment(plan["case"], restored, plan["item"]["catalog_observations"])
    replay_assessment["actual_child_model_dispatch_overlap"] = dispatch_overlap(OUT / "live", summary["ledger"]["intents"])
    replay_assessment["functional_passed"] = replay_assessment["functional_passed"] and replay_assessment["actual_child_model_dispatch_overlap"]
    if saved != restored or replay_assessment != summary["assessment"]:
        raise IntegrityError("P4.5 replay changed canonical result")
    return {"replay_same": True, "model_calls": 0, "financial_provider_network_calls": 0,
            "functional_passed": summary["assessment"]["functional_passed"]}


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
