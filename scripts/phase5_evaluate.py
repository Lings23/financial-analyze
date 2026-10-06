"""Frozen Phase 5 Dynamic route validation on existing immutable public sources.

Three known-source validation tasks, nine new runs, a separate bounded ledger,
and read-only legacy replay.  No provider collection, retries, default changes,
threshold tuning, statistical superiority claims, or synthetic financial truth.
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
import phase4_p45_demo as parallel
import phase4_p45_child_repair_demo as repair_v2
import phase4_p45_child_repair_v3_demo as repair_v3
from phase3_benchmark_v2 import CampaignSources, candidate
from phase3_benchmark_v2_contract import validate_cases
from stock_research.errors import DataError, IntegrityError, PermissionDenied, ValidationError
from stock_research.model_adapters.chat import ChatModelAdapter, ChatResult, load_model_config
from stock_research.models import AccessContext, canonical_json, digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import (DYNAMIC_TOOLS, DynamicRequest,
    DomainParentSpec, ParallelParentSpec, FinancialRequest, MarketRequest, required_checks)
from stock_research.research.dynamic_protocol import dynamic_messages, observe_tool
from stock_research.research.report import markdown
from stock_research.research.runtime import validate_model_result
from stock_research.research.tools import read_domain


OUT = old.ROOT / ".artifacts/phase5/targeted-20261006"
LIMITS = (120, 720000, 2400)
CASE_PARENTS = ("b2-l3-roster-603207", "b2-l3-roster-920110", "b2-l3-roster-688184")
ROUTES = ("direct", "serial", "parallel")
CHILD_SPECS = repair_v3.CHILD_SPECS
SPECS = {
    "direct": DomainParentSpec(version="dynamic-parent-domains-v2",
        allowed_tools=DYNAMIC_TOOLS, visible_tools=DYNAMIC_TOOLS,
        root_max_decisions=8, root_max_tools=12, root_max_tokens=48000),
    "serial": DomainParentSpec(version="dynamic-parent-domains-v2"),
    "parallel": ParallelParentSpec(),
}
QUESTION = ("核对已绑定的2025半年报与2024半年报营业收入、归母净利润同报告期同比，"
    "检验两者是否均下降；同时报告冻结行情的实际观察价格变化和最大回撤。"
    "财务与行情都是必要输入，两个来源的读取彼此独立。保留全部事实、反证、来源、PIT及缺口，"
    "不推断因果，不补缺数或对非正基数强算同比；完成全部必要执行检查，合法前提不足时明确报告不足。")
COMMON_DIRECTIVE = (" 路由控制（实验控制文本）：各轮仅返回严格JSON对象。"
    "calculation、hypotheses、verification均是tool字段值，action为tool；"
    "calculation的refs为[financial,market]，hypotheses的refs为[calculation]，"
    "verification的refs为[hypotheses]；依次执行，再finish。所有字符串和键使用JSON双引号，"
    "plan为1至5项的非空字符串数组，每项最多240 UTF-8字节。tool动作精确字段为action,tool,refs,plan；"
    "finish精确字段为action,reason,plan，reason只能completed或insufficient。")
DIRECTIVES = {
    "direct": "只通过普通financial和market工具分别读取两域，再执行父运行研究检查。",
    "serial": "首先通过financial_child和market_child工具依次委派两个Child，不使用普通financial/market直接读取。",
    "parallel": "第一步action为parallel、tools为[financial_child,market_child]同时委派两个Child，并提供plan。",
}
DECISION_RULE = {
    "scope": "explicit_v3_opt_in_for_existing_two_independent_bound_sources_only",
    "required": ["9/9 frozen expected outcomes and all required checks match source oracle",
        "all five execution checks passed, including exact source-bound numeric verification",
        "point_in_time, authorization, immutable snapshots, lineage and bounded budgets passed",
        "zero unknown paid usage and unresolved Child allocations",
        "9/9 exact zero-model/provider read-only replays",
        "3/3 parallel runs have actual Financial/Market paid model I/O overlap"],
    "default_changed": False, "automatic_routing": False, "phase6_started": False,
    "statistical_or_broad_performance_superiority": False,
    "independent_nonblind_validation_tasks": 3,
}


def local_limits(spec):
    return repair_v3.local_limits(spec)


def spec_document():
    return {route: {"identity": spec.identity, "version": spec.version,
        "allowed_tools": sorted(spec.allowed_tools), "visible_tools": sorted(spec.visible_tools),
        "local_limits": local_limits(spec), "root_limits": {"decisions": spec.root_max_decisions,
        "tools": spec.root_max_tools, "tokens": spec.root_max_tokens}}
        for route, spec in SPECS.items()}


def code_files():
    result = {**repair_v3.code_files(), "scripts/phase5_evaluate.py": old.sha(Path(__file__))}
    trace = old.ROOT / "src/stock_research/research/trace_evaluation.py"
    if trace.exists():
        result[trace.relative_to(old.ROOT).as_posix()] = old.sha(trace)
    return result


def file_hashes(directory):
    directory = Path(directory)
    return {p.relative_to(directory).as_posix(): old.sha(p)
            for p in sorted(directory.rglob("*")) if p.is_file()}


def history_hashes():
    return {"original_p45": file_hashes(parallel.OUT),
        "v2_same_case_retest": file_hashes(repair_v2.OUT),
        "v3_same_case_retest": file_hashes(repair_v3.OUT)}


def historical_index():
    path = old.ROOT / ".runtime/phase5-historical-audit.json"
    if not path.exists():
        raise IntegrityError("Phase 5 historical read-only audit is required before freezing")
    audit = old.read(path)
    if (audit.get("status") != "passed" or any(audit.get(k) != 0 for k in
            ("model_calls", "provider_calls", "checkpoint_appends"))
            or audit["file_sha256_before"] != audit["file_sha256_after"]):
        raise IntegrityError("historical audit lacks unchanged zero-network checkpoint proof")
    for name, checksum in audit["file_sha256_after"].items():
        if old.sha(old.ROOT / name) != checksum:
            raise IntegrityError("historical audited artifact changed")
    return {"path": path.relative_to(old.ROOT).as_posix(), "sha256": old.sha(path),
            "historical_trace_catalog": audit["historical_trace_catalog"]}


def build_cases():
    manifest = old.read(old.PARENT)
    originals = {c["id"]: c for c in manifest["cases"]}
    result = []
    for parent_id in CASE_PARENTS:
        original = originals[parent_id]
        request = deepcopy(original["request"])
        request["bindings"] = [b for b in request["bindings"]
                               if b["dataset"] in {"financial_income", "market_daily"}]
        request.update(hypotheses=["financial_deterioration"], objective="single_stock_research",
                       event_record_id=None, benchmark=None)
        request.pop("hypothesis_version", None)
        identity = "p5-" + parent_id.removeprefix("b2-l3-roster-")
        case = candidate(identity, "L3", QUESTION, request,
            {b["dataset"]: original["source_scopes"][b["dataset"]] for b in request["bindings"]},
            stratum={"603207": "ordinary_yoy", "920110": "bse", "688184": "nonpositive_base"}[request["symbol"]],
            mandatory=["financial_income.net_income_parent", "observed_price_change", "observed_max_drawdown"],
            allow_insufficient=request["symbol"] == "688184")
        case.update(scope="phase5-targeted-20261006/" + identity, parent_case_id=parent_id,
                    source_hashes=deepcopy(original["source_hashes"]), version="phase5-dynamic-validation/v1")
        case["novelty"].update(underlying_sources_known_validation=True, blind=False,
            independent_test_task_count=0, new_dynamic_validation_task=True)
        case["expected_behavior"]["model"] = "Actual bounded observation-driven JSON actions, explicit Child v3."
        case["success_criteria"] = ["All exact source-oracle facts, hypothesis states, references and gaps retained.",
            "All bound execution checks performed; only source-proven hypothesis insufficiency accepted.",
            "Preregistered route executed with original PIT, immutable sources, grants and budgets."]
        result.append(case)
    return result


def runtime(service, checkpoints, route, model=None, **kwargs):
    return DynamicRuntime(service, checkpoints, model, SPECS[route],
                          domain_child_specs=CHILD_SPECS, **kwargs)


def expected_outcome(oracle):
    derived = oracle["O:hypotheses"]
    hypothesis = derived["hypotheses"]["financial_deterioration"]
    status = "insufficient" if hypothesis["status"] == "insufficient" else "completed"
    return {"status": status, "hypothesis": deepcopy(hypothesis),
        "fact_count": len(derived["facts"]), "evidence_count": len(derived["evidence"]),
        "gaps": deepcopy(derived["gaps"]),
        "required_check_statuses": {"read:financial": "passed", "read:market": "passed",
            "calculation": "passed", "hypotheses": "passed", "verification": "passed",
            "hypothesis:financial_deterioration": "insufficient" if status == "insufficient" else "passed"}}


def frozen_item(case, route, sources, *, run_id=None):
    service, access = sources.context(case)
    question = QUESTION + COMMON_DIRECTIVE + DIRECTIVES[route]
    request = DynamicRequest.from_dict({**case["request"], "question": question})
    run = run_id or uuid.uuid4().hex
    oracle = parallel.catalog_oracle(service, access, request)
    return {"case_id": case["id"], "route": route, "run_id": run,
        "request": request.to_dict(), "scope": access.scope, "spec_identity": SPECS[route].identity,
        "input_ref": digest(sources.inputs(case)), "financial_question": QUESTION,
        "route_directive": COMMON_DIRECTIVE + DIRECTIVES[route],
        "messages": runtime(service, None, route).preview(request, access, run_id=run),
        "authorization_envelope": old.authorized_envelope(service, access, request),
        "catalog_observations": oracle, "expected_outcome": expected_outcome(oracle),
        "required_check_ids": required_checks(request),
        "dependency_dag": {"nodes": ["financial", "market", "calculation", "hypotheses", "verification"],
            "edges": [["financial", "calculation"], ["market", "calculation"],
                      ["calculation", "hypotheses"], ["hypotheses", "verification"]]}}


def prepare():
    if OUT.exists():
        raise IntegrityError("Phase 5 output already exists; immutable campaign cannot be replaced")
    sources, cases = CampaignSources(), build_cases()
    validation = validate_cases(cases, sources.context)
    if not validation["all_cases_contract_valid"]:
        raise IntegrityError("Phase 5 source contract invalid; tasks cannot be substituted")
    items = []
    for index, case in enumerate(cases):
        # Rotation records order/cache confounding without estimating its effect.
        for position, route in enumerate(ROUTES[index:] + ROUTES[:index]):
            item = frozen_item(case, route, sources)
            item["case_position"], item["route_position"] = index + 1, position + 1
            items.append(item)
    config = load_model_config()
    if any(s.model != config.model for s in SPECS.values()):
        raise IntegrityError("configured model differs from frozen Phase 5 specs")
    plan = {"schema": "phase5-targeted-validation-plan/v1", "cases": cases, "items": items,
        "contract_validation": validation, "model": config.model, "endpoint_sha256": digest(config.endpoint),
        "code_files": code_files(), "specs": spec_document(),
        "child_specs": {d: {"identity": s.identity, "version": s.version, "limits": local_limits(s)}
                        for d, s in CHILD_SPECS.items()},
        "campaign_limits": {"max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "max_seconds": LIMITS[2]},
        "history_hashes": history_hashes(), "historical_index": historical_index(), "context_limit_bytes": 12000,
        "provider_network_calls": 0, "old_budget_reused": False, "blind": False,
        "independent_new_validation_task_count": 3, "new_run_count": 9,
        "independent_test_task_count": 0, "underlying_sources_known_validation": True,
        "expected_statuses": {i["case_id"]: i["expected_outcome"]["status"] for i in items},
        "confounds": ["known Phase 3 underlying validation sources", "route directive is appended to question",
            "direct tools exclude AgentTool; serial/parallel specs expose both", "rotated route execution order and caches",
            "nonblind n=3; no independent statistical performance estimate"],
        "decision_rule": DECISION_RULE, "failed_or_missing_runs_retained_in_denominator": True,
        "unknown_paid_outcomes_never_resent": True, "child_protocol_opt_in": "v3"}
    old.write_new(OUT / "plan.json", plan)
    return {"prepared": True, "plan_sha256": old.sha(OUT / "plan.json"),
        "independent_new_validation_task_count": 3, "new_run_count": 9,
        "model_calls": 0, "financial_provider_network_calls": 0}


def checked(expected_sha, *, replay=False):
    if not isinstance(expected_sha, str) or old.sha(OUT / "plan.json") != expected_sha:
        raise IntegrityError("Phase 5 frozen plan hash differs")
    plan = old.read(OUT / "plan.json")
    if (plan["schema"] != "phase5-targeted-validation-plan/v1" or plan["cases"] != build_cases()
            or plan["specs"] != spec_document() or plan["decision_rule"] != DECISION_RULE
            or plan["campaign_limits"] != {"max_decisions": LIMITS[0], "max_tokens_accounted": LIMITS[1], "max_seconds": LIMITS[2]}
            or plan["history_hashes"] != history_hashes() or plan["historical_index"] != historical_index() or plan["context_limit_bytes"] != 12000
            or len(plan["items"]) != 9 or not replay and plan["code_files"] != code_files()):
        raise IntegrityError("Phase 5 frozen tasks, history, code or limits differ")
    sources = CampaignSources()
    if validate_cases(plan["cases"], sources.context) != plan["contract_validation"]:
        raise IntegrityError("Phase 5 contracts changed")
    cases = {c["id"]: c for c in plan["cases"]}
    expected_order = [(c["id"], r) for j, c in enumerate(plan["cases"]) for r in ROUTES[j:] + ROUTES[:j]]
    if [(i["case_id"], i["route"]) for i in plan["items"]] != expected_order:
        raise IntegrityError("Phase 5 frozen route order changed")
    for item in plan["items"]:
        rebuilt = frozen_item(cases[item["case_id"]], item["route"], sources, run_id=item["run_id"])
        if any(rebuilt[k] != item[k] for k in rebuilt):
            raise IntegrityError("Phase 5 frozen inputs, oracle, permissions or preview changed")
    return plan, sources


def role_spec(item, role):
    parent = SPECS[item["route"]]
    if role == parent.version:
        return parent
    if item["route"] != "direct":
        for spec in CHILD_SPECS.values():
            if role == spec.version:
                return spec
    raise IntegrityError("outbound role outside frozen route")


def validate_outbound(messages, item, kwargs):
    payload = json.loads(messages[1]["content"])
    role, control = payload["protocol_version"], payload["control"]
    spec = role_spec(item, role)
    context_args = {}
    if role == SPECS[item["route"]].version:
        request, observations, refs, stage = compact._parent_observations(payload, item)
        tools = json.loads(item["messages"][1]["content"])["available_tools"]
        checks = payload["context"]["required_checks"]
        context_args = {"context_scope": item["scope"], "context_run_id": item["run_id"],
                        "context_refs": refs, "context_stage": stage}
    else:
        domain = next(d for d, s in CHILD_SPECS.items() if s.version == role)
        parent = DynamicRequest.from_dict(item["request"])
        request = (FinancialRequest if domain == "financial" else MarketRequest).from_parent(parent)
        tools, observations, checks = [domain], payload["observations"], payload["required_checks"]
        if any(o != item["authorization_envelope"]["source_observations"][domain] for o in observations):
            raise IntegrityError("outbound Child observation exceeds exact frozen source")
    rebuilt, _ = dynamic_messages(request, tools, observations, checks, control["plan"], 12000,
        decision=control["decision"], protocol_error=control.get("previous_action_error"), version=role,
        finish_rejection=control.get("finish_rejection"), delegation_results=payload.get("delegation_results"), **context_args)
    if rebuilt != messages or payload["available_tools"] != tools or kwargs.get("max_tokens") != spec.output_tokens:
        raise IntegrityError("outbound messages differ from exact frozen view")
    return role, spec, control["decision"]


class RecordingModel:
    """Campaign-wide durable accounting; short locks exclude all network I/O."""
    def __init__(self, config, deadline, directory, ledger=None):
        self.config, self.adapter = config, ChatModelAdapter(config)
        self.deadline, self.directory = deadline, Path(directory)
        self.ledger = ledger or old.RootLedger(LIMITS[0], LIMITS[1])
        self.lock, self.role_calls, self.revision = Lock(), {}, 0
        self.item = None

    def snapshot(self, kind):
        self.revision += 1
        old.write_new(self.directory / f"ledger-{self.revision:03d}-{kind}.json", self.ledger.snapshot())

    def complete(self, messages, **kwargs):
        item = self.item
        role, spec, decision = validate_outbound(messages, item, kwargs)
        if old.contains_secret(messages, self.config.api_key):
            raise IntegrityError("outbound credential reflection rejected")
        key = (item["run_id"], role)
        with self.lock:
            count = self.role_calls.get(key, 0) + 1
            if count != decision or count > spec.max_decisions:
                raise IntegrityError("outbound local role turn exceeds frozen bound")
            if (self.deadline - utcnow()).total_seconds() <= 0:
                raise ValidationError("Phase 5 campaign deadline exceeded before reservation")
            intent = self.ledger.reserve(item["run_id"] + "/" + role, messages, spec.output_tokens)
            self.role_calls[key] = count
            prefix = f"{intent['number']:03d}"
            old.write_new(self.directory / (prefix + "-messages.json"), messages)
            old.write_new(self.directory / (prefix + "-intent.json"), deepcopy(intent))
            self.snapshot("reserved")
        remaining, started = (self.deadline - utcnow()).total_seconds(), utcnow().isoformat()
        old.write_new(self.directory / (prefix + "-dispatch.json"), {
            "run_id": item["run_id"], "case_id": item["case_id"], "route": item["route"],
            "role": role, "started_at": started})
        try:
            if remaining <= 0:
                raise ValidationError("Phase 5 campaign deadline exceeded")
            response = self.adapter.complete(messages, **{**kwargs, "timeout": min(kwargs["timeout"], remaining)})
            receipt = asdict(response)
            if old.receipt_reflects_secret(receipt, self.config.api_key) or len(canonical_json(receipt).encode("utf-8")) > 65536:
                raise ValidationError("receipt reflected credentials or exceeded bound")
            validate_model_result(response, spec, intent["reservation"])
        except Exception as exc:
            with self.lock:
                old.write_new(self.directory / (prefix + "-receipt.json"), {"status": "unknown", "error_type": type(exc).__name__})
                old.write_new(self.directory / (prefix + "-interval.json"), {"run_id": item["run_id"],
                    "role": role, "started_at": started, "finished_at": utcnow().isoformat(), "outcome": "unknown"})
                self.snapshot("unknown")
            raise
        with self.lock:
            self.ledger.accounted += response.total_tokens - intent["reservation"]
            intent.update(usage_status="known", prompt_tokens=response.prompt_tokens,
                          completion_tokens=response.completion_tokens, total_tokens=response.total_tokens)
            old.write_new(self.directory / (prefix + "-receipt.json"), receipt)
            old.write_new(self.directory / (prefix + "-interval.json"), {"run_id": item["run_id"],
                "role": role, "started_at": started, "finished_at": utcnow().isoformat(), "outcome": "known"})
            self.snapshot("settled")
        return response


def run_intents(ledger, run_id):
    return [i for i in ledger["intents"] if i["task_id"].split("/")[0] == run_id]


def dispatch_overlap(directory, intents):
    intervals = []
    for intent in intents:
        prefix = f"{intent['number']:03d}"
        interval = old.read(Path(directory) / (prefix + "-interval.json"))
        dispatch = old.read(Path(directory) / (prefix + "-dispatch.json"))
        run, role = intent["task_id"].split("/")
        start, end = (datetime.fromisoformat(interval[k]) for k in ("started_at", "finished_at"))
        if (interval["run_id"] != run or interval["role"] != role or dispatch["run_id"] != run
                or dispatch["role"] != role or dispatch["started_at"] != interval["started_at"]
                or start.tzinfo is None or end.tzinfo is None or end < start):
            raise IntegrityError("Phase 5 interval not bound to durable intent")
        if intent["usage_status"] == "known":
            intervals.append((run, role, start, end))
    return any(a[0] == b[0] and a[1] == "financial-child-v3" and b[1] == "market-child-v3"
        and max(a[2], b[2]) < min(a[3], b[3]) for a in intervals for b in intervals)


def validate_receipts(directory, ledger, items):
    by_run = {i["run_id"]: i for i in items}
    accounted, reserved, known, unknown, counts = 0, 0, 0, 0, {}
    for number, intent in enumerate(ledger["intents"], 1):
        if intent["number"] != number:
            raise IntegrityError("campaign intent numbering changed")
        prefix = f"{number:03d}"
        messages = old.read(Path(directory) / (prefix + "-messages.json"))
        raw = old.read(Path(directory) / (prefix + "-intent.json"))
        receipt = old.read(Path(directory) / (prefix + "-receipt.json"))
        initial = {k: v for k, v in intent.items() if k not in {"prompt_tokens", "completion_tokens"}}
        initial.update(usage_status="unknown", total_tokens=None)
        run, role = intent["task_id"].split("/")
        item = by_run[run]
        spec = role_spec(item, role)
        checked_role, _, decision = validate_outbound(messages, item, {"max_tokens": spec.output_tokens})
        counts[(run, role)] = counts.get((run, role), 0) + 1
        amount = sum(len(m["content"].encode("utf-8")) for m in messages) + 256 + spec.output_tokens
        if (raw != initial or digest(messages) != intent["messages_sha256"] or checked_role != role
                or amount != intent["reservation"] or decision != counts[(run, role)] or decision > spec.max_decisions):
            raise IntegrityError("campaign paid intent/messages/local turn changed")
        reserved += amount
        if intent["usage_status"] == "known":
            result = ChatResult(**receipt)
            validate_model_result(result, spec, amount)
            if any(getattr(result, k) != intent[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
                raise IntegrityError("campaign paid receipt differs from ledger")
            accounted += result.total_tokens
            known += result.total_tokens
        elif intent["usage_status"] == "unknown" and receipt.get("status") == "unknown":
            accounted += amount
            unknown += 1
        else:
            raise IntegrityError("unknown paid outcome was released or forged")
    if (accounted != ledger["tokens_accounted"] or reserved != ledger["cumulative_tokens_reserved"]
            or known != ledger["known_tokens"] or unknown != ledger["unknown_usage_calls"]
            or len(ledger["intents"]) != ledger["decisions"] or len(ledger["intents"]) > LIMITS[0]
            or accounted > LIMITS[1]):
        raise IntegrityError("campaign accounting exceeds or differs from receipts")
    return {"known_tokens": known, "tokens_accounted": accounted, "cumulative_tokens_reserved": reserved,
            "unknown_usage_calls": unknown, "decisions": len(ledger["intents"])}


def assess(item, report, directory, intents):
    expected, spec = item["expected_outcome"], SPECS[item["route"]]
    budget = report["root_budget"]
    source_routes = [(r["domain"], r["mode"]) for r in report["routes"] if r["domain"] in {"financial", "market"}]
    desired = [("financial", "direct"), ("market", "direct")] if item["route"] == "direct" else [
        ("financial", "delegated"), ("market", "delegated")]
    route_passed = sorted(source_routes) == sorted(desired)
    if item["route"] == "serial":
        route_passed = route_passed and not report.get("parallel_groups") and len(report["child_results"]) == 2
    elif item["route"] == "direct":
        route_passed = route_passed and not report["child_results"]
    else:
        route_passed = route_passed and len(report.get("parallel_groups", [])) == 1 and len(report["child_results"]) == 2
    checks = {
        "expected_status": report["status"] == expected["status"],
        "required_checks_retained": [c["id"] for c in report["required_checks"]] == item["required_check_ids"],
        "required_checks_match_oracle": {c["id"]: c["status"] for c in report["required_checks"]} == expected["required_check_statuses"],
        "exact_source_bound_factual_view": observe_tool("hypotheses", report) == item["catalog_observations"]["O:hypotheses"],
        "independent_claim_verification": report["verification"]["status"] == "verified",
        "provider_network_calls_zero": report["usage"]["financial_provider_network_calls"] == 0,
        "route_matches_preregistered_control": route_passed,
        "root_budget_passed": (budget["model_attempts"] <= spec.root_max_decisions
            and budget["tool_attempts"] <= spec.root_max_tools and budget["tokens_accounted"] <= spec.root_max_tokens
            and budget["unknown_usage_calls"] == 0 and budget["unresolved_child_allocations"] == 0
            and all(n >= 0 for n in budget["remaining"].values())),
        "parent_local_budget_passed": (report["usage"]["model_attempts"] <= spec.max_decisions
            and report["usage"]["tool_calls"] <= spec.max_tools and report["usage"]["tokens_accounted"] <= spec.max_tokens),
        "children_completed": all(c["status"] == "completed" for c in report["child_results"]),
    }
    overlap = dispatch_overlap(directory, intents)
    if item["route"] == "parallel":
        checks["actual_child_model_dispatch_overlap"] = overlap
    return {"checks": checks, "functional_passed": all(checks.values()), "status": report["status"],
        "stop_reason": report["stop_reason"], "actual_child_model_dispatch_overlap": overlap,
        "correct_source_proven_insufficiency": expected["status"] == "insufficient" and all(checks.values())}


def safety_checks(item, report, sources, assessment):
    """Executed source/permission checks, never inferred from completed status."""
    service, access = sources.context(next(c for c in build_cases() if c["id"] == item["case_id"]))
    request = DynamicRequest.from_dict(item["request"])
    exact = parallel.catalog_oracle(service, access, request) == item["catalog_observations"]
    envelope = old.authorized_envelope(service, access, request) == item["authorization_envelope"]
    denied = []
    for domain in ("financial", "market"):
        try:
            read_domain(service, request, AccessContext(access.scope, frozenset({"phase5-denied-provider"})), domain)
        except PermissionDenied:
            denied.append(domain)
    inputs = sources.inputs(next(c for c in build_cases() if c["id"] == item["case_id"]))
    frozen = digest(inputs) == item["input_ref"]
    actual = assessment["checks"]
    try:
        compact.report_semantics(report, compact.record_domains(inputs))
        lineage = True
    except (IntegrityError, ValidationError, KeyError, TypeError, ValueError):
        lineage = False
    return {"point_in_time": "passed" if exact and envelope else "failed",
        "authorization": "passed" if denied == ["financial", "market"] and envelope else "failed",
        "immutable_snapshots": "passed" if frozen else "failed",
        "lineage": "passed" if lineage and exact and actual["exact_source_bound_factual_view"] else "failed",
        "numeric_verification": "passed" if actual["independent_claim_verification"] and actual["exact_source_bound_factual_view"] else "failed"}


def children_from_checkpoints(directory, item, report):
    store = CheckpointStore(Path(directory) / "runs")
    results = []
    for child in report.get("child_results", []):
        state = store.read(item["scope"], child["child_run_id"])
        child_report = state["report"]
        if child_report["parent_run_id"] != item["run_id"] or child_report["run_id"] != child["child_run_id"]:
            raise IntegrityError("Child telemetry not bound to actual Parent")
        results.append(deepcopy(child_report))
    return results


def validate_paid_telemetry(item, report, child_reports, directory, intents):
    """Every observed model turn binds exact paid wire, receipt and root usage."""
    reports = {SPECS[item["route"]].version: report}
    for child in child_reports:
        domain = child.get("domain", "financial")
        reports[CHILD_SPECS[domain].version] = child
    bound_turns = set()
    for intent in intents:
        prefix = f"{intent['number']:03d}"
        messages = old.read(Path(directory) / (prefix + "-messages.json"))
        receipt = old.read(Path(directory) / (prefix + "-receipt.json"))
        payload = json.loads(messages[1]["content"])
        role, turn = payload["protocol_version"], payload["control"]["decision"]
        telemetry = reports[role]["context_telemetry"][turn - 1]
        actual = sum(len(m["content"].encode("utf-8")) for m in messages)
        if ((role, turn) in bound_turns or telemetry["message_sha256"] != digest(messages)
                or telemetry["total_context_bytes"] != actual or telemetry["context_after_compaction_bytes"] != actual
                or actual > 12000 or telemetry["context_limit_bytes"] != 12000
                or not telemetry["model_dispatched"] or telemetry["context_budget_exceeded"]):
            raise IntegrityError("context telemetry does not bind exact bounded paid wire")
        bound_turns.add((role, turn))
        if intent["usage_status"] == "known":
            if any(telemetry[a] != receipt[b] for a, b in
                   (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens"), ("total_tokens", "total_tokens"))):
                raise IntegrityError("telemetry Token usage differs from paid receipt")
    dispatched = {(role, index + 1) for role, value in reports.items()
        for index, t in enumerate(value.get("context_telemetry", [])) if t["model_dispatched"]}
    budget = report["root_budget"]
    known = sum(i["total_tokens"] or 0 for i in intents)
    unknown = sum(i["usage_status"] == "unknown" for i in intents)
    accounted = known + sum(i["reservation"] for i in intents if i["usage_status"] == "unknown")
    if (dispatched != bound_turns or budget["model_attempts"] != len(intents)
            or budget["total_tokens"] != known or budget["unknown_usage_calls"] != unknown
            or budget["tokens_accounted"] != accounted
            or budget["tokens_dispatched_reserved"] != sum(i["reservation"] for i in intents)):
        raise IntegrityError("root ledger, actual model turns and paid campaign usage differ")
    return {"bound_paid_turns": len(bound_turns), "actual_wire_cap": 12000, "root_paid_usage_same": True}


def row_for(item, report, summary, run_directory, dispatch_directory):
    files = file_hashes(run_directory)
    intents = summary["intents"]
    receipts = {}
    for intent in intents:
        prefix = f"{intent['number']:03d}"
        for kind in ("messages", "intent", "dispatch", "receipt", "interval"):
            path = Path(dispatch_directory) / (prefix + "-" + kind + ".json")
            if path.exists():
                receipts[path.name] = old.sha(path)
    return {"case_id": item["case_id"], "route": item["route"], "run_id": item["run_id"],
        "sample_kind": "new_validation", "report": report, "child_reports": summary.get("child_reports", []),
        "summary": {"success": summary["assessment"]["functional_passed"], "wall_ms": summary["wall_clock_ms"],
            "safety_checks": summary["safety_checks"], "root_tokens_reserved_dispatched": sum(i["reservation"] for i in intents),
            "expected_status": item["expected_outcome"]["status"],
            "expected_required_checks": [{"id": k, "status": item["expected_outcome"]["required_check_statuses"][k]}
                for k in item["required_check_ids"]]},
        "hashes": {"run_files": files, "dispatch_receipts": receipts},
        "expected_status": item["expected_outcome"]["status"], "oracle_assessment": summary["assessment"],
        "known_sources_nonblind": True, "route_position": item["route_position"], "case_position": item["case_position"]}


def historical_rows():
    rows = []
    for name, module, kind in (("original_p45", parallel, "historical"),
                              ("v2_same_case_retest", repair_v2, "retest"),
                              ("v3_same_case_retest", repair_v3, "retest")):
        report, summary = old.read(module.OUT / "live/report.json"), old.read(module.OUT / "live/summary.json")
        rows.append({"case_id": parallel.CASE_ID, "route": "parallel", "run_id": report["run_id"],
            "sample_kind": kind, "historical_identity": name, "report": report,
            "summary": {"success": summary["assessment"]["functional_passed"],
                "wall_ms": summary.get("wall_clock_ms"), "safety_checks": {k: "unknown" for k in
                ("point_in_time", "authorization", "immutable_snapshots", "lineage", "numeric_verification")},
                "root_tokens_reserved_dispatched": summary["ledger"]["cumulative_tokens_reserved"]},
            "hashes": {"report": old.sha(module.OUT / "live/report.json"), "trace": digest(report["trace"]),
                       "all_artifacts": file_hashes(module.OUT)}, "independent_new_validation_task_count": 0})
    return rows


def evaluate(rows):
    from stock_research.research.trace_evaluation import evaluate_traces
    return evaluate_traces(rows)


def live(expected_sha):
    plan, sources = checked(expected_sha)
    config = load_model_config()
    if config.model != plan["model"] or digest(config.endpoint) != plan["endpoint_sha256"]:
        raise IntegrityError("Phase 5 frozen configured endpoint/model changed")
    directory = OUT / "live"
    directory.mkdir(exist_ok=False)
    deadline = utcnow() + timedelta(seconds=LIMITS[2])
    dispatch_directory = directory / "dispatch"
    dispatch_directory.mkdir()
    model = RecordingModel(config, deadline, dispatch_directory)
    old.write_new(directory / "campaign-intent.json", {"plan_sha256": expected_sha, "deadline": deadline.isoformat(),
        "limits": plan["campaign_limits"], "run_ids": [i["run_id"] for i in plan["items"]],
        "independent_new_budget": True, "initial_ledger": model.ledger.snapshot(), "paid_retry": False})
    cases = {c["id"]: c for c in plan["cases"]}
    rows = []
    for item in plan["items"]:
        run_directory = directory / item["run_id"]
        run_directory.mkdir()
        old.write_new(run_directory / "run-intent.json", {"run_id": item["run_id"], "case_id": item["case_id"],
            "route": item["route"], "deadline": deadline.isoformat(), "plan_sha256": expected_sha,
            "retry": False, "campaign_decisions_before": model.ledger.snapshot()["decisions"]})
        model.item = item
        started, report = time.monotonic(), None
        try:
            # Reauthorize immutable sources for every new run.
            service, access = sources.context(cases[item["case_id"]])
            report = runtime(service, CheckpointStore(run_directory / "runs"), item["route"], model,
                inherited_deadline=deadline).run(DynamicRequest.from_dict(item["request"]), access, run_id=item["run_id"])
            old.write_new(run_directory / "report.json", report)
            with (run_directory / "report.md").open("x", encoding="utf-8") as stream:
                stream.write(markdown(report))
            old.write_new(run_directory / "trace.json", {"run_id": report["run_id"], "trace": report["trace"],
                "context_telemetry": report.get("context_telemetry"), "parallel_groups": report.get("parallel_groups", [])})
            intents = run_intents(model.ledger.snapshot(), item["run_id"])
            assessment = assess(item, report, dispatch_directory, intents)
            safety = safety_checks(item, report, sources, assessment)
            child_reports = children_from_checkpoints(run_directory, item, report)
            paid_telemetry = validate_paid_telemetry(item, report, child_reports, dispatch_directory, intents)
            assessment["checks"]["paid_telemetry_and_root_usage"] = True
            assessment["functional_passed"] = assessment["functional_passed"] and all(s == "passed" for s in safety.values())
            error_type = None
        except Exception as exc:
            error_type = type(exc).__name__
            old.write_new(run_directory / "failure.json", {"error_type": error_type, "paid_retry": False,
                "report_retained": report is not None, "deadline": deadline.isoformat(), "ledger": model.ledger.snapshot()})
            assessment = {"functional_passed": False, "checks": {}, "status": report.get("status") if report else None,
                          "actual_child_model_dispatch_overlap": False}
            safety = {k: "unknown" for k in ("point_in_time", "authorization", "immutable_snapshots", "lineage", "numeric_verification")}
            child_reports = []
            paid_telemetry = None
        summary = {"case_id": item["case_id"], "run_id": item["run_id"], "route": item["route"],
            "assessment": assessment, "safety_checks": safety, "wall_clock_ms": round((time.monotonic() - started) * 1000),
            "intents": run_intents(model.ledger.snapshot(), item["run_id"]), "child_reports": child_reports,
            "paid_telemetry_validation": paid_telemetry,
            "error_type": error_type, "paid_retry": False, "deadline": deadline.isoformat()}
        old.write_new(run_directory / "summary.json", summary)
        rows.append(row_for(item, report, summary, run_directory, dispatch_directory))
    if history_hashes() != plan["history_hashes"]:
        raise IntegrityError("Phase 5 live changed historical evidence")
    ledger = model.ledger.snapshot()
    receipt_validation = validate_receipts(dispatch_directory, ledger, plan["items"])
    rows.extend(historical_rows())
    dataset = {"schema": "phase5-real-trace-dataset/v1", "plan_sha256": expected_sha, "rows": rows,
        "independent_new_validation_task_count": 3, "new_run_count": 9, "historical_count": 1, "same_case_retest_count": 2,
        "synthetic_rows": 0, "confounds": plan["confounds"], "decision_rule": DECISION_RULE,
        "historical_index": plan["historical_index"], "independent_test_task_count": 0,
        "model": config.model, "financial_provider_network_calls": 0}
    old.write_new(directory / "trace-dataset.json", dataset)
    result = {"plan_sha256": expected_sha, "ledger": ledger, "receipt_validation": receipt_validation,
        "new_run_count": 9, "passed_new_runs": sum(r["summary"]["success"] for r in rows if r["sample_kind"] == "new_validation"),
        "deadline": deadline.isoformat(), "trace_dataset_sha256": old.sha(directory / "trace-dataset.json"),
        "evaluation": evaluate(rows), "old_results_preserved": True, "paid_retry": False,
        "decision": "pending_exact_read_only_replay", "phase6_started": False}
    old.write_new(directory / "summary.json", result)
    return result


class NoNetwork:
    class config:
        model = SPECS["parallel"].model
    def complete(self, *args, **kwargs):
        raise AssertionError("Phase 5 replay cannot dispatch a paid model")


def replay(expected_sha):
    plan, sources = checked(expected_sha, replay=True)
    directory = OUT / "live"
    before = file_hashes(directory)
    dataset, summary = old.read(directory / "trace-dataset.json"), old.read(directory / "summary.json")
    if old.sha(directory / "trace-dataset.json") != summary["trace_dataset_sha256"]:
        raise IntegrityError("Phase 5 trace dataset changed")
    receipt_validation = validate_receipts(directory / "dispatch", summary["ledger"], plan["items"])
    if receipt_validation != summary["receipt_validation"] or evaluate(dataset["rows"]) != summary["evaluation"]:
        raise IntegrityError("Phase 5 ledger or trace aggregation changed")
    cases, identical, failures = {c["id"]: c for c in plan["cases"]}, [], []
    for item in plan["items"]:
        run_directory = directory / item["run_id"]
        row = next(r for r in dataset["rows"] if r["run_id"] == item["run_id"])
        if file_hashes(run_directory) != row["hashes"]["run_files"]:
            raise IntegrityError("Phase 5 retained report/trace/checkpoint changed")
        for name, checksum in row["hashes"]["dispatch_receipts"].items():
            if old.sha(directory / "dispatch" / name) != checksum:
                raise IntegrityError("Phase 5 retained paid dispatch changed")
        path = run_directory / "report.json"
        if not path.exists():
            failures.append({"run_id": item["run_id"], "external_failure_retained": True, "exact_runtime_replay": False})
            continue
        saved = old.read(path)
        service, access = sources.context(cases[item["case_id"]])
        restored = runtime(service, CheckpointStore(run_directory / "runs"), item["route"], NoNetwork()).run(
            DynamicRequest.from_dict(item["request"]), access, resume=saved["run_id"])
        actual_summary = old.read(run_directory / "summary.json")
        if actual_summary["error_type"] is not None:
            # Preserve failed QA/unknown allocations. Exact recovery is useful
            # evidence, never a new success or another paid attempt.
            if restored != saved or row["report"] != saved or row["summary"]["success"] is not False:
                raise IntegrityError("retained validation failure or original report changed")
            identical.append(item["run_id"])
            failures.append({"run_id": item["run_id"], "external_failure_retained": True,
                "error_type": actual_summary["error_type"], "validation_incomplete": True, "exact_runtime_replay": True})
            continue
        assessed = assess(item, restored, directory / "dispatch", actual_summary["intents"])
        safety = safety_checks(item, restored, sources, assessed)
        paid_telemetry = validate_paid_telemetry(item, restored, row["child_reports"], directory / "dispatch", actual_summary["intents"])
        assessed["checks"]["paid_telemetry_and_root_usage"] = True
        assessed["functional_passed"] = assessed["functional_passed"] and all(s == "passed" for s in safety.values())
        if (restored != saved or row["report"] != saved or assessed != actual_summary["assessment"]
                or safety != actual_summary["safety_checks"] or paid_telemetry != actual_summary["paid_telemetry_validation"]
                or children_from_checkpoints(run_directory, item, restored) != row["child_reports"]):
            raise IntegrityError("Phase 5 exact report, safety or Child telemetry replay differs")
        identical.append(item["run_id"])
    historical = []
    for name, module in (("original_p45", parallel), ("v2_same_case_retest", repair_v2), ("v3_same_case_retest", repair_v3)):
        result = module.replay(old.sha(module.OUT / "plan.json"))
        historical.append({"identity": name, "result": result})
    if before != file_hashes(directory) or plan["history_hashes"] != history_hashes():
        raise IntegrityError("Phase 5 or historical replay appended/changed a checkpoint or artifact")
    new_rows = [r for r in dataset["rows"] if r["sample_kind"] == "new_validation"]
    allowed = (len(identical) == 9 and all(r["summary"]["success"] for r in new_rows)
        and receipt_validation["unknown_usage_calls"] == 0
        and all(r["oracle_assessment"]["actual_child_model_dispatch_overlap"] for r in new_rows if r["route"] == "parallel"))
    return {"schema": "phase5-read-only-replay/v1", "plan_sha256": expected_sha, "replay_same": len(identical) == 9,
        "identical_new_reports": len(identical), "retained_external_failures": failures, "historical_replays": historical,
        "model_calls": 0, "financial_provider_network_calls": 0, "checkpoint_appends": 0,
        "decision": "bounded_explicit_v3_opt_in_supported" if allowed else "bounded_opt_in_not_supported",
        "decision_rule": DECISION_RULE, "defaults_changed": False, "phase6_started": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--replay", action="store_true")
    parser.add_argument("--plan-sha256")
    args = parser.parse_args(argv)
    if not args.prepare and not args.plan_sha256:
        parser.error("live/replay requires explicit frozen --plan-sha256")
    try:
        result = prepare() if args.prepare else live(args.plan_sha256) if args.live else replay(args.plan_sha256)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (DataError, OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"status": "failed", "error": "Phase 5 input, frozen integrity or execution check failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
