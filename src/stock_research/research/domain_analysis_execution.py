"""Domain analysis adapters on DynamicRuntime, Registry and the existing ledger.

No scheduler, model-generated values, new sources or mutable snapshot operations.
Execution receipts are rebuilt from real trace intents and completions on reuse.
"""
from copy import deepcopy
from datetime import datetime
import json
from types import MappingProxyType

from ..errors import IntegrityError, PermissionDenied, ValidationError
from ..models import AccessContext, DataRecord, canonical_json, digest
from .contracts import DOMAINS
from .dynamic_contracts import SOURCE_TOOLS, FINANCIAL_DATASETS, MARKET_DATASETS
from .domain_analysis_contracts import (
    ANALYSIS_TOOLS, DOMAIN_TOOLS, FinancialAnalysisRequest, MarketAnalysisRequest,
    domain_of, required_operators, required_checks, domain_task, ownership, task_refs,
)
from .dynamic_protocol import observe_tool
from .runtime import BudgetExceeded
from .tools import ToolExecutor, ToolRegistry, ToolSpec


def setup(runtime, request, access):
    child = runtime._analysis_child()
    if child:
        domain = domain_of(request)
        if runtime.spec.version != domain + "-analysis-child-v1" or not runtime.parent_run_id or runtime.inherited_deadline is None:
            raise ValidationError("analysis child requires its bound parent and deadline")
        available = {domain, "calculation", "domain_review"}
    else:
        if isinstance(request, (FinancialAnalysisRequest, MarketAnalysisRequest)):
            raise ValidationError("analysis Parent requires a root request")
        task_refs(request, profile_id=runtime.spec.profile_id)
        available = {DOMAINS[b.dataset] for b in request.bindings} | {"calculation", "hypotheses", "verification"}
        for domain in ("financial", "market"):
            if domain in available:
                if runtime.spec.mode == "tool":
                    available.discard(domain)
                    available.add(domain + "_analysis_tool")
                elif runtime.spec.mode == "child":
                    available.discard(domain)
                    available.add(domain + "_child")
    if runtime.authorize_parent is not None and not runtime.authorize_parent():
        raise PermissionDenied("analysis delegation was revoked")
    if runtime.model is not None and runtime.model.config.model != runtime.spec.model:
        raise ValidationError("analysis requires the configured model")
    if any(b.provider not in access.allowed_providers for b in request.bindings):
        raise PermissionDenied("analysis source authorization was revoked")
    registry = ToolRegistry()
    registry.tools = MappingProxyType({name: ToolSpec(name, version="domain-analysis/v1") for name in ANALYSIS_TOOLS})
    available &= runtime.spec.allowed_tools & runtime.spec.visible_tools & runtime.granted
    return ToolExecutor(runtime.service, registry, runtime.spec, runtime.granted, request, access), sorted(available)


def analysis_dag():
    nodes = {}
    for domain in ("financial", "market"):
        nodes[domain + ":source"] = []
        nodes[domain + ":calculation"] = [domain + ":source"]
        nodes[domain + ":review"] = [domain + ":calculation"]
        nodes[domain + ":validated_join"] = [domain + ":review"]
    nodes.update(composition=["financial:validated_join", "market:validated_join"],
                 hypotheses=["composition"], verification=["hypotheses"], finish=["verification"])
    return nodes


def initialize(runtime, state, request, access):
    if runtime._analysis_child():
        state["analysis_task"] = domain_task(request, root_run_id=runtime.parent_run_id,
            parent_run_id=runtime.parent_run_id, spec=runtime.spec,
            source_envelope={b.dataset: b.to_dict() for b in request.bindings},
            allocation_id=state["run_id"], deadline=datetime.fromisoformat(state["deadline"]),
            authorization_ref=digest({"scope": access.scope, "providers": sorted(access.allowed_providers),
                                      "tools": sorted(runtime.granted)}))
    else:
        state["analysis_ownership"] = ownership(request)
        state["analysis_task_refs"] = task_refs(request, profile_id=runtime.spec.profile_id)


def child_context(runtime, request, access, run, deadline, domain):
    from .dynamic import DynamicRuntime
    cls, datasets = ((FinancialAnalysisRequest, FINANCIAL_DATASETS) if domain == "financial"
                     else (MarketAnalysisRequest, MARKET_DATASETS))
    child_request = cls.from_parent(request, runtime.delegated_datasets & datasets)
    spec = runtime._role_spec(domain)
    parent_tools = runtime.granted & runtime.spec.allowed_tools & runtime.spec.visible_tools
    def authorized():
        current = runtime.granted & runtime.spec.allowed_tools & runtime.spec.visible_tools
        return ({domain, domain + "_child", "calculation", "domain_review"} <= current
                and domain in runtime.delegated_tools)
    if not authorized():
        raise PermissionDenied("analysis child delegation is not authorized")
    effective = ({domain, "calculation", "domain_review"} & parent_tools
                 & spec.allowed_tools & spec.visible_tools)
    child_access = AccessContext(access.scope, access.allowed_providers & frozenset(b.provider for b in child_request.bindings))
    child = DynamicRuntime(runtime.service, runtime.checkpoints, runtime.model, spec,
        granted_tools=effective, cancelled=runtime.cancelled, now=runtime.now, monotonic=runtime.monotonic,
        parent_run_id=run, inherited_deadline=datetime.fromisoformat(deadline), authorize_parent=authorized,
        on_unknown_outcome=runtime.on_unknown_outcome)
    return child, child_request, child_access


def _source_call(state, domain):
    calls = [e["tool_call_id"] for e in state["trace"] if e["event"] == "tool_finished" and e.get("tool") == domain]
    if not calls:
        raise IntegrityError("analysis result lacks an actual source read")
    return calls[-1]


def _attribute(computed, state, domain):
    call = _source_call(state, domain)
    for evidence in computed["evidence"].values():
        evidence["tool_call_id"] = call
    return computed


def _timed(runtime, event, check, kind, domain, callback, **fields):
    check()
    start = runtime.monotonic()
    result = callback()
    check()
    event(kind, domain=domain, elapsed_ms=max(0, round((runtime.monotonic() - start) * 1000)),
          output_ref=digest(result), **fields)
    return result


def calculate_result(runtime, state, request, action, event, check):
    from .domain_operators import calculate_domain, compose_domains, merge_domain_calculations
    if runtime._analysis_child():
        domain = domain_of(request)
        selected = [r.removeprefix("operator:") for r in action["refs"] if r.startswith("operator:")]
        if set(selected) & set(state["analysis_operations"]):
            raise ValidationError("operator repeated without progress")
        operations = sorted(set(state["analysis_operations"]) | set(selected))
        # The operators are pure and bounded. Only newly selected work is progress;
        # the canonical projection is reconstructed without publishing duplicates.
        output = _timed(runtime, event, check, "domain_production", domain,
            lambda: calculate_domain(runtime._datasets(state), request, domain, operators=selected),
            operators=selected, input_revision=runtime._current(state), mode="child",
            production_calculations=len(selected), fraction_verifications=0)
        output = _attribute(output, state, domain)
        if "calculated" in state:
            output = merge_domain_calculations(state["calculated"], output)
        state["analysis_operations"] = operations
        return output
    accepted = trusted_domains(runtime, state, request)
    return _timed(runtime, event, check, "parent_composition", "parent",
        lambda: compose_domains(runtime._datasets(state), request, trusted_domains=accepted),
        delegated_domains=sorted(accepted), produced_domains=sorted(
            {DOMAINS[b.dataset] for b in request.bindings} & {"financial", "market"} - set(accepted)))


def verify_child(runtime, state, request):
    # Arithmetic belongs to the selected domain_review action. Reuse and recovery
    # authenticate its immutable execution, never rerun its Fraction oracle.
    if state.get("hypotheses_revision") != state.get("calculated_revision"):
        return {"status": "not_completed", "numeric_claims": len(state["calculated"]["facts"])}
    validate_local_execution(state, request, runtime.spec, state["calculated"],
                             state["outputs"][domain_of(request)])
    return deepcopy(state["local_verification"])


def review_result(runtime, state, request, event, check):
    from .domain_operators import review_domain
    if state.get("calculated_revision") != runtime._current(state) or set(state["analysis_operations"]) != set(required_operators(request)):
        raise ValidationError("domain review requires the complete current canonical operators")
    output = _timed(runtime, event, check, "domain_review_executed", domain_of(request),
        lambda: review_domain(state["calculated"], runtime._datasets(state), request, domain_of(request)),
        input_revision=state["calculated_revision"], production_calculations=0, fraction_verifications=1)
    state["calculated"] = output
    state["hypotheses_revision"] = state["calculated_revision"]
    state["local_verification"] = output["local_verification"]
    return output


def observe_review(output):
    return {**observe_tool("hypotheses", output), "tool": "domain_review"}


def execution_receipts(state):
    result = []
    for end in state["trace"]:
        if end["event"] != "tool_finished":
            continue
        starts = [e for e in state["trace"] if e["event"] == "tool_started" and e.get("tool_call_id") == end["tool_call_id"]]
        if len(starts) != 1 or starts[0]["tool"] != end["tool"] or starts[0]["seq"] >= end["seq"]:
            raise IntegrityError("analysis execution lacks its exact preceding intent")
        start = starts[0]
        result.append({"tool": end["tool"], "call_id": end["tool_call_id"],
            "input_revision": start.get("analysis_input_revision", digest(state["request"])),
            "output_revision": end["result_hash"], "started_ref": digest(start), "finished_ref": digest(end)})
    return result


def _coverage(computed):
    return {"fact_ids": [f["id"] for f in computed["facts"]],
            "evidence_ids": sorted(computed["evidence"]),
            "hypothesis_ids": [h["id"] for h in computed.get("hypotheses", [])],
            "gaps_ref": digest(computed["gaps"]),
            "counterevidence_ref": digest({h["id"]: h["counterevidence_claim_ids"] for h in computed.get("hypotheses", [])})}


def validate_local_execution(state, request, spec, computed, sources, *, composite=False):
    """Authenticate committed execution and complete manifests without arithmetic.

    The authoritative state is read through CheckpointStore's append-only hash
    chain. Caller-provided statuses and report hashes cannot mint this receipt.
    """
    domain = domain_of(request)
    review_name = "domain_review"
    calculation_name = "domain_calculation" if composite else "calculation"
    trace = state["trace"]
    ends = [e for e in trace if e["event"] == "tool_finished" and e.get("tool") == review_name]
    if composite:
        ends = [e for e in ends if e.get("wrapper_call_id") == state["wrapper_call_id"]]
    if not ends:
        raise IntegrityError("local verification has no successful actual review")
    review = ends[-1]
    starts = [e for e in trace if e["event"] == "tool_started" and e.get("tool_call_id") == review["tool_call_id"]]
    if (len(starts) != 1 or starts[0]["seq"] >= review["seq"] or review["result_hash"] != digest(computed)
            or state.get("calculated_revision") != digest({domain: sources})
            or state.get("hypotheses_revision") != state.get("calculated_revision")):
        raise IntegrityError("local verification input revision or output differs")
    before_review = [e for e in trace[:starts[0]["seq"]] if e["event"] == "tool_finished" and e.get("tool") == calculation_name]
    reads = [e for e in trace[:starts[0]["seq"]] if e["event"] == "tool_finished" and e.get("tool") == domain]
    if (not before_review or not reads or reads[-1]["result_hash"] != digest(sources)
            or starts[0].get("analysis_computed_ref") != before_review[-1]["result_hash"]):
        raise IntegrityError("local review lacks its exact calculation and read dependencies")
    local = computed.get("local_verification")
    if (type(local) is not dict or local != state.get("local_verification") or local.get("status") != "verified"
            or local.get("domain") != domain or local.get("method") != "independent_fraction_domain_projection/v1"
            or local.get("numeric_claims") != len(computed["facts"])
            or local.get("evidence_checked") != len(computed["evidence"])
            or local.get("hypotheses_checked") != len(request.hypotheses)
            or sorted(state.get("analysis_operations", [])) != sorted(required_operators(request))
            or [h["id"] for h in computed.get("hypotheses", [])] != list(request.hypotheses)):
        raise IntegrityError("local review is not a complete immutable verification")
    for fact in computed["facts"]:
        if (fact["id"] != digest({k: v for k, v in fact.items() if k != "id"})
                or not fact["inputs"] or not set(fact["inputs"]) <= set(computed["evidence"])):
            raise IntegrityError("local output manifest or evidence lineage differs")
    records = {DataRecord.from_dict(row).record_id: row for result in sources.values() for row in result["records"]}
    for key, evidence in computed["evidence"].items():
        row = records.get(evidence["record_id"])
        if row is None or evidence.get("tool_call_id") != reads[-1]["tool_call_id"]:
            raise IntegrityError("local source lineage is outside the actual read")
        record = DataRecord.from_dict(row)
        if (record.available_at > request.as_of or request.mode.value == "system" and record.ingested_at > request.as_of
                or key != digest({"record": record.record_id, "metric": evidence["metric"]})):
            raise IntegrityError("local source visibility or evidence identity differs")
    receipt = next((r for r in execution_receipts(state) if r["call_id"] == review["tool_call_id"]), None)
    if receipt is None:
        raise IntegrityError("local review receipt cannot be rebuilt")
    proof = {"schema": "domain-local-verification-execution/v1", "domain": domain,
        "domain_request_ref": digest(request.to_dict()), "root_request_ref": request.parent_request_ref,
        "task_ref": state["analysis_task"]["task_ref"], "spec_ref": spec.identity,
        "checkpoint_ref": digest({"run_id": state["run_id"], "binding": state["binding"]}),
        "review_receipt_ref": digest(receipt), "ownership_ref": digest({"domain": domain,
            "operators": required_operators(request), "checks": list(request.hypotheses)}),
        "required_operators": sorted(required_operators(request)), "check_ids": required_checks(request),
        "input_revision": state["calculated_revision"], "source_result_ref": digest(sources),
        "computed_ref": digest(computed), "local_verification_ref": digest(local),
        "result_ref": digest(computed), "coverage": _coverage(computed),
        "source_read_call_id": reads[-1]["tool_call_id"], "review_call_id": review["tool_call_id"]}
    return {**proof, "attestation_ref": digest(proof)}


def seal_local_execution(runtime, state, request):
    state["local_attestation"] = validate_local_execution(state, request, runtime.spec,
        state["calculated"], state["outputs"][domain_of(request)])


def child_checks(runtime, state, request):
    current = state.get("calculated_revision") == runtime._current(state)
    reviewed = (current and state.get("hypotheses_revision") == state.get("calculated_revision")
                and "domain_review" in state["observations"] and state.get("local_verification", {}).get("status") == "verified")
    hypotheses = {h["id"]: h["status"] for h in state.get("calculated", {}).get("hypotheses", [])}
    checks = []
    for name in state["requirements"]:
        done = (domain_of(request) in state["outputs"] if name.startswith("read:") else
                current if name == "calculation" else reviewed if name == "domain_review" else
                current and name[9:] in state["analysis_operations"] if name.startswith("operator:") else
                reviewed and name[11:] in hypotheses)
        status = "passed" if done else "not_completed"
        if done and name.startswith("hypothesis:") and hypotheses[name[11:]] == "insufficient":
            status = "insufficient"
        checks.append({"id": name, "status": status})
    return checks


def finish_child(runtime, state, request, reason):
    withheld = state.get("withheld")
    computed = {} if withheld else deepcopy(state.get("calculated", {}))
    sources = {} if withheld else deepcopy(state["outputs"].get(domain_of(request), {}))
    checks = child_checks(runtime, state, request)
    executed = bool(computed) and all(c["status"] != "not_completed" for c in checks)
    status = "partial" if state.get("stop_reason") or withheld or not executed else (
        "insufficient" if reason == "insufficient" or any(c["status"] == "insufficient" for c in checks) else "completed")
    calls = [e["tool_call_id"] for e in state["trace"] if e["event"] == "tool_finished" and e.get("tool") == domain_of(request)]
    read = calls[-1] if calls else None
    refs = [{"record_id": DataRecord.from_dict(row).record_id, "artifact_sha256": row["artifact_id"],
             "snapshot": result["snapshot"], "tool_call_id": read} for _, result in sorted(sources.items()) for row in result["records"]]
    state["report"] = {"schema": "domain-analysis-result/v1", "run_id": state["run_id"],
        "parent_run_id": runtime.parent_run_id, "domain": domain_of(request), "status": status,
        "stop_reason": state.get("stop_reason"), "request_ref": digest(request.to_dict()),
        "profile_id": request.profile_id, "spec_ref": runtime.spec.identity,
        "task": deepcopy(state["analysis_task"]), "task_ref": state["analysis_task"]["task_ref"],
        "input_revision": runtime._current(state), "source_result_ref": digest(sources), "source_results": sources,
        "source_tool_call_id": read, "evidence_refs": refs, "computed": computed,
        "executed_operators": deepcopy(state["analysis_operations"]), "required_checks": checks,
        "local_verification": deepcopy(state.get("local_verification")), "receipts": execution_receipts(state),
        "local_attestation": deepcopy(state.get("local_attestation")),
        "local_attestation_ref": state.get("local_attestation", {}).get("attestation_ref"),
        "coverage": _coverage(computed) if computed else {"fact_ids": [], "evidence_ids": [], "hypothesis_ids": []},
        "gaps": deepcopy(computed.get("gaps", [])),
        "counterevidence": {h["id"]: deepcopy(h.get("counterevidence_claim_ids", [])) for h in computed.get("hypotheses", [])},
        "deadline": state["deadline"], "trace": deepcopy(state["trace"]),
        "checkpoint_ref": {"run_id": state["run_id"], "binding": state["binding"]},
        "usage": {"model_attempts": state["model_attempts"], "tool_calls": state["tools_used"],
            "tokens_accounted": state["tokens_accounted"], "tokens_reserved": state["tokens_reserved"],
            "total_tokens": sum(d.get("total_tokens", 0) for d in state["decisions"]),
            "unknown_usage_calls": sum("total_tokens" not in d for d in state["decisions"])}}
    state["report"] = json.loads(canonical_json(state["report"]))
    if "context_telemetry" in state:
        state["report"]["context_telemetry"] = deepcopy(state["context_telemetry"])
        state["report"]["trace_stratum"] = domain_of(request) + "_analysis_child"
    state["report"]["result_digest"] = digest(state["report"])
    state["finish_reason"], state["phase"] = reason, "completed"


def child_summary(report, parent_run_id, tool_call_id, domain):
    if report.get("parent_run_id") != parent_run_id or report.get("domain") != domain:
        raise IntegrityError("analysis result is outside its parent domain")
    return {"schema": report["schema"], "child_run_id": report["run_id"], "parent_run_id": parent_run_id,
        "tool_call_id": tool_call_id, "domain": domain, "result_ref": digest(report),
        **{k: deepcopy(report[k]) for k in ("status", "stop_reason", "request_ref", "source_result_ref",
            "source_tool_call_id", "evidence_refs", "required_checks", "usage", "deadline")}}


def authenticate_result(runtime, state, request, report, domain, access):
    """Validated Join: actual persistent execution, hashes and lineage, no oracle."""
    cls = FinancialAnalysisRequest if domain == "financial" else MarketAnalysisRequest
    child_request = cls.from_parent(request)
    if (report.get("domain") != domain or report.get("request_ref") != digest(child_request.to_dict())
            or report.get("status") not in {"completed", "insufficient"} or report.get("stop_reason") is not None
            or report.get("profile_id") != child_request.profile_id
            or report.get("executed_operators") != sorted(required_operators(child_request))
            or any(c["status"] == "not_completed" for c in report["required_checks"])
            or report.get("result_digest") != digest({k: v for k, v in report.items() if k != "result_digest"})):
        raise IntegrityError("domain result coverage or identity differs")
    if report.get("spec_ref") != runtime._role_spec(domain).identity:
        raise IntegrityError("domain result Spec differs from the frozen allocation")
    executor, _ = setup(runtime, request, access)
    child, _, child_access = child_context(runtime, request, access, state["run_id"], state["deadline"], domain)
    fresh_sources, _ = executor.execute(domain, wave="validated-analysis-join")
    if digest(fresh_sources) != report["source_result_ref"]:
        raise IntegrityError("domain result source differs from current authorized binding")
    history = runtime.checkpoints.history(access.scope, report["run_id"])
    actual, original = history[-1], history[0]
    for saved in history:
        if any(saved.get(key) != original.get(key) for key in
               ("binding", "request", "spec_version", "deadline", "requirements", "run_id", "analysis_task")):
            raise IntegrityError("Child immutable execution bindings changed")
    for earlier, later in zip(history, history[1:]):
        if (later["trace"][:len(earlier["trace"])] != earlier["trace"]
                or any(later[key] < earlier[key] for key in ("tools_used", "model_attempts", "tokens_reserved"))):
            raise IntegrityError("Child committed execution history was rewritten")
    child._validate_ledger(actual, child_request)
    expected_usage = {"model_attempts": actual["model_attempts"], "tool_calls": actual["tools_used"],
        "tokens_accounted": actual["tokens_accounted"], "tokens_reserved": actual["tokens_reserved"],
        "total_tokens": sum(d.get("total_tokens", 0) for d in actual["decisions"]),
        "unknown_usage_calls": sum("total_tokens" not in d for d in actual["decisions"])}
    if (report["usage"] != expected_usage or expected_usage["unknown_usage_calls"]
            or actual.get("stop_reason") is not None or actual.get("finish_reason") not in {"completed", "insufficient"}
            or not actual["decisions"] or actual["decisions"][-1].get("action", {}).get("action") != "finish"
            or report["required_checks"] != child_checks(child, actual, child_request)):
        raise IntegrityError("Child result execution status, checks or actual usage differs")
    _, child_available = setup(child, child_request, child_access)
    validate_paid_history(child, history, actual, child_request, child_available)
    if (digest(actual.get("report")) != digest(report) or actual["request"] != child_request.to_dict()
            or actual["spec_version"] != runtime._role_spec(domain).version
            or report["parent_run_id"] != state["run_id"]
            or report["coverage"] != _coverage(report["computed"])
            or report["gaps"] != report["computed"]["gaps"]
            or report["counterevidence"] != {h["id"]: h["counterevidence_claim_ids"] for h in report["computed"]["hypotheses"]}
            or report["input_revision"] != digest({domain: report["source_results"]})):
        raise IntegrityError("domain result lacks its authoritative immutable checkpoint")
    rebuilt = validate_local_execution(actual, child_request, runtime._role_spec(domain),
                                       report["computed"], report["source_results"])
    if (rebuilt != report.get("local_attestation") or rebuilt != actual.get("local_attestation")
            or report.get("local_attestation_ref") != rebuilt["attestation_ref"]
            or report["task_ref"] != actual["analysis_task"]["task_ref"]
            or report["task"] != actual["analysis_task"]
            or report["receipts"] != execution_receipts(actual)):
        raise IntegrityError("domain result local execution attestation cannot be rebuilt")
    return rebuilt


def resume_known_child(runtime, state, request, access, executor, event, check):
    """Reconcile only a known immutable serial result; never dispatch a Child."""
    pending = state.get("pending_tool")
    if not pending or pending["tool"] not in {"financial_child", "market_child"}:
        return
    domain, call = pending["tool"].removesuffix("_child"), pending["tool_call_id"]
    summaries = [c for c in state["child_results"] if c["tool_call_id"] == call]
    reservation = state.get("pending_child")
    child_run = summaries[0]["child_run_id"] if summaries else reservation["run_id"] if reservation else None
    if child_run is None:
        return
    try:
        actual = runtime.checkpoints.read(access.scope, child_run)
    except PermissionDenied:
        return
    report = actual.get("report")
    if (not report or report["status"] not in {"completed", "insufficient"}
            or report["usage"]["unknown_usage_calls"]):
        return
    check()
    authenticate_result(runtime, state, request, report, domain, access)
    if not summaries:
        from .root_budget import settle_child
        usage = report["usage"]
        state["root_budget"] = settle_child(state["root_budget"], child_run,
            {"decisions": usage["model_attempts"], "tools": usage["tool_calls"],
             **{k: usage[k] for k in ("tokens_accounted", "tokens_reserved", "total_tokens", "unknown_usage_calls")}})
        summary = child_summary(report, state["run_id"], call, domain)
        state["child_results"].append(summary)
        state["pending_child"] = None
        event("child_finished", child_run_id=child_run, domain=domain, status=report["status"], result_ref=summary["result_ref"])
    import_result(runtime, state, request, report, domain, access)
    state["outputs"][domain] = deepcopy(report["source_results"])
    state["observations"][domain] = observe_tool(domain, report["source_results"])
    state["source_origins"][domain] = report["source_tool_call_id"]
    signature = digest({"tool": pending["tool"], "refs": sorted(state["pending_action"]["refs"]), "input": None})
    if signature not in state["completed_actions"]:
        state["completed_actions"].append(signature)
    state["pending_action"] = state["pending_tool"] = None
    state["no_progress"] = 0
    event("tool_finished", tool=domain + "_child", tool_call_id=call, dedup=True,
          result_hash=report["source_result_ref"], observation=state["observations"][domain])
    event("domain_join", **state.pop("pending_analysis_join"))


def import_result(runtime, state, request, report, domain, access, event=None):
    start = runtime.monotonic()
    authenticate_result(runtime, state, request, report, domain, access)
    if runtime.now() >= datetime.fromisoformat(report["deadline"]):
        raise BudgetExceeded("late_child_result")
    previous = state["domain_results"].get(domain)
    if previous is not None and digest(previous) != digest(report):
        raise IntegrityError("domain result ownership conflicts")
    state["domain_results"][domain] = deepcopy(report)
    state["pending_analysis_join"] = {"domain": domain, "result_ref": digest(report),
        "elapsed_ms": max(0, round((runtime.monotonic()-start)*1000)),
        "production_calculations": 0, "fraction_verifications": 0, "source_checks": 1, "execution_receipt_checks": 1}


def composite_tool(runtime, state, request, access, executor, event, check, domain, wrapper_call):
    from .domain_operators import calculate_domain, review_domain
    from .root_budget import consume_parent_tool
    cls = FinancialAnalysisRequest if domain == "financial" else MarketAnalysisRequest
    child_request = cls.from_parent(request)
    if domain in state["domain_results"] or domain in state["outputs"]:
        raise ValidationError("domain production already owned")
    def operation(name, callback, *, computed_ref=None):
        check()
        executor.registry.authorize(domain if name == domain else "calculation" if name == "domain_calculation" else "domain_review", runtime.spec, runtime.granted)
        if state["tools_used"] >= runtime.spec.max_tools:
            raise BudgetExceeded("tool_budget_exceeded")
        call = f"{state['run_id']}:{state['tools_used'] + 1}"
        state["root_budget"] = consume_parent_tool(state["root_budget"], call)
        state["tools_used"] += 1
        event("tool_started", tool=name, tool_call_id=call, turn=state["model_attempts"],
              wrapper_call_id=wrapper_call, analysis_input_revision=digest({domain: state["outputs"].get(domain)}),
              analysis_computed_ref=computed_ref)
        start = runtime.monotonic()
        output = callback()
        check()
        event("tool_finished", tool=name, tool_call_id=call, result_hash=digest(output),
              wrapper_call_id=wrapper_call, elapsed_ms=max(0, round((runtime.monotonic()-start)*1000)),
              production_calculations=len(required_operators(child_request)) if name == "domain_calculation" else 0,
              fraction_verifications=1 if name == "domain_review" else 0)
        return output
    sources = operation(domain, lambda: executor.execute(domain, wave="domain-composite")[0])
    state["outputs"][domain] = sources
    computed = operation("domain_calculation", lambda: _attribute(calculate_domain(sources, child_request, domain), state, domain))
    reviewed = operation("domain_review", lambda: review_domain(computed, sources, child_request, domain),
                         computed_ref=digest(computed))
    check()
    fresh, _ = executor.execute(domain, wave="domain-composite-reauthorize")
    if digest(fresh) != digest(sources):
        raise IntegrityError("composite immutable source changed")
    receipts = [r for r in execution_receipts(state) if r["call_id"] != wrapper_call][-3:]
    report = {"schema": "domain-analysis-tool-result/v1", "domain": domain, "status": "completed",
        "profile_id": child_request.profile_id, "request_ref": digest(child_request.to_dict()),
        "input_revision": digest(sources), "source_result_ref": digest(sources), "source_results": sources,
        "source_tool_call_id": _source_call(state, domain), "computed": reviewed,
        "executed_operators": sorted(required_operators(child_request)), "local_verification": reviewed["local_verification"],
        "receipts": receipts, "task_ref": state["analysis_task_refs"][domain], "wrapper_call_id": wrapper_call}
    proxy = {**state, "wrapper_call_id": wrapper_call, "analysis_task": {"task_ref": report["task_ref"]},
             "analysis_operations": sorted(required_operators(child_request)), "local_verification": reviewed["local_verification"],
             "calculated_revision": digest({domain: sources}), "hypotheses_revision": digest({domain: sources})}
    report["spec_ref"] = runtime.spec.identity
    report["local_attestation"] = validate_local_execution(proxy, child_request, runtime.spec, reviewed, sources, composite=True)
    report["local_attestation_ref"] = report["local_attestation"]["attestation_ref"]
    report["coverage"] = _coverage(reviewed)
    state["domain_results"][domain] = report
    event("domain_tool_committed", domain=domain, result_ref=digest(report), wrapper_call_id=wrapper_call)
    return report


def remaining_hypotheses(runtime, state, request, event, check):
    from .domain_operators import test_remaining_hypotheses
    return _timed(runtime, event, check, "parent_remaining_checks", "parent",
        lambda: test_remaining_hypotheses(state["calculated"], runtime._datasets(state), request,
                                          trusted_domains=trusted_domains(runtime, state, request)),
        consumed_domains=sorted(state["domain_results"]))


def trusted_domains(runtime, state, request):
    from .domain_operators import _attest_validated_domain
    result = {}
    for domain, report in state["domain_results"].items():
        proof = {k: deepcopy(v) for k, v in report["local_attestation"].items() if k != "schema"}
        proof["ownership_ref"] = digest(ownership(request))
        result[domain] = _attest_validated_domain(report["computed"], runtime._datasets(state), request, domain, proof)
    return result


def diagnostic_hypotheses(runtime, state, request, computed):
    from .domain_operators import test_remaining_hypotheses
    return test_remaining_hypotheses(computed, runtime._datasets(state), request,
                                     trusted_domains=trusted_domains(runtime, state, request))


def revalidate(runtime, state, request, access, executor, available, *, check, replay):
    runtime._validate_ledger(state, request)
    for domain, sources in state["outputs"].items():
        check()
        # Composite routes hide source tools from the model but grant them to the
        # bounded adapter. They remain authorized in the trusted Parent Spec.
        fresh, _ = executor.execute(domain, wave="analysis-revalidation")
        if digest(fresh) != digest(sources):
            raise IntegrityError("analysis pinned source changed")
        check()
    for summary in state.get("child_results", []):
        domain = summary["domain"]
        child, req, child_access = runtime._child_context(request, access, state["run_id"], state["deadline"], domain)
        for group in state.get("parallel_groups", []):
            node = group["nodes"][domain + "_branch"]
            if node["child_run_id"] == summary["child_run_id"]:
                child.inherited_deadline = datetime.fromisoformat(node["deadline"])
                child.telemetry_lineage = {"parallel_group_id": group["parallel_group_id"], "parallel_width": 2, "route_type": "parallel_child"}
        fresh = child.run(req, child_access, resume=summary["child_run_id"])
        if runtime._child_summary(fresh, state["run_id"], summary["tool_call_id"], domain=domain) != summary:
            raise IntegrityError("analysis child receipt changed")
        if domain in state["domain_results"] and digest(fresh) != digest(state["domain_results"][domain]):
            raise IntegrityError("Parent domain result differs from actual Child checkpoint")
        check()
    for domain, result in state["domain_results"].items():
        cls = FinancialAnalysisRequest if domain == "financial" else MarketAnalysisRequest
        req = cls.from_parent(request)
        if digest(result["source_results"]) != digest(state["outputs"].get(domain)):
            raise IntegrityError("Parent result source ownership changed")
        if result["schema"] == "domain-analysis-result/v1":
            authenticate_result(runtime, state, request, result, domain, access)
        if result["schema"] == "domain-analysis-tool-result/v1":
            current = execution_receipts(state)
            if any(receipt not in current for receipt in result["receipts"]):
                raise IntegrityError("composite result lacks real internal execution")
            required = {domain, "domain_calculation", "domain_review"}
            if {r["tool"] for r in result["receipts"]} != required:
                raise IntegrityError("composite result omits an internal execution")
            proxy = {**state, "wrapper_call_id": result["wrapper_call_id"],
                "analysis_task": {"task_ref": result["task_ref"]}, "analysis_operations": result["executed_operators"],
                "local_verification": result["local_verification"], "calculated_revision": digest({domain: result["source_results"]}),
                "hypotheses_revision": digest({domain: result["source_results"]})}
            proof = validate_local_execution(proxy, req, runtime.spec, result["computed"], result["source_results"], composite=True)
            if proof != result.get("local_attestation") or result["coverage"] != _coverage(result["computed"]):
                raise IntegrityError("composite local execution attestation differs")
    for name in state["observations"]:
        executor.registry.authorize(name, runtime.spec, runtime.granted)
    if "calculated" in state:
        runtime._verify_computed(state, request)
    for name, observation in state["observations"].items():
        if name in SOURCE_TOOLS:
            expected = observe_tool(name, state["outputs"][name])
        elif name == "verification":
            expected = observe_tool(name, runtime._verify_computed(state, request))
        elif name == "domain_review":
            expected = observe_review(state["calculated"])
        else:
            computed = deepcopy(state["calculated"])
            if name == "calculation":
                computed["hypotheses"] = []
            expected = observe_tool(name, computed)
        if observation != expected:
            raise IntegrityError("analysis cached Observation differs")
    if runtime._analysis_child():
        expected = deepcopy(state)
        initialize(runtime, expected, request, access)
        if expected["analysis_task"] != state["analysis_task"]:
            raise IntegrityError("analysis task changed on recovery")
        productions = [e for e in state["trace"] if e["event"] == "domain_production" and any(
            end["event"] == "tool_finished" and end.get("tool") == "calculation" and end["seq"] > e["seq"]
            and not any(start["event"] == "tool_started" and start["seq"] > e["seq"] and start["seq"] < end["seq"]
                        for start in state["trace"]) for end in state["trace"])]
        if sorted({op for e in productions for op in e["operators"]}) != state["analysis_operations"]:
            raise IntegrityError("analysis operator executions differ")
        for name in ("calculation", "domain_review"):
            if name in state["observations"]:
                ends = [e for e in state["trace"] if e["event"] == "tool_finished" and e["tool"] == name]
                if not ends or ends[-1].get("observation") != state["observations"][name]:
                    raise IntegrityError("analysis progress lacks actual tool execution")
        execution_receipts(state)
        if state.get("hypotheses_revision") == state.get("calculated_revision") and "calculated" in state:
            proof = validate_local_execution(state, request, runtime.spec, state["calculated"], state["outputs"][domain_of(request)])
            if state.get("local_attestation") is None and state.get("report") is None:
                # Crash after review completion but before sealing: the exact
                # persisted intent/result reconstruct the receipt without math.
                state["local_attestation"] = proof
            elif proof != state.get("local_attestation"):
                raise IntegrityError("analysis local attestation is missing or stale")
    else:
        if state["analysis_ownership"] != ownership(request) or state["analysis_task_refs"] != task_refs(request, profile_id=runtime.spec.profile_id):
            raise IntegrityError("analysis frozen ownership or task catalogue changed")
        runtime._validate_verification_execution(state)


def validate_paid_history(runtime, history, state, request, available):
    for saved in history:
        if not saved["trace"] or saved["trace"][-1]["event"] != "model_started":
            continue
        decision = saved["decisions"][-1]
        messages, metadata = runtime._messages(saved, request, available, decision=decision["turn"])
        if digest(messages) != decision["message_sha256"]:
            raise IntegrityError("analysis paid input differs on exact reconstruction")
        if metadata["bytes"] > 12000:
            raise IntegrityError("analysis paid input exceeds fixed byte cap")


def report_details(runtime, state, request):
    return {"schema": "domain-analysis-parent-report/v1", "mode": runtime.spec.mode,
        "execution": runtime.spec.execution, "profile_id": runtime.spec.profile_id,
        "ownership": deepcopy(state.get("analysis_ownership", ownership(request))),
        "results": deepcopy(state["domain_results"]), "task_refs": deepcopy(state["analysis_task_refs"]),
        "production_receipts": [deepcopy(e) for e in state["trace"] if e["event"] in {
            "parent_composition", "parent_remaining_checks", "domain_tool_committed"}],
        "execution_receipts": execution_receipts(state), "experimental": True}
