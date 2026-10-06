"""Dependency-aware bounded scheduling inside DynamicRuntime, never a second Runtime.

Only the Parent coordinator mutates its state/root ledger under the existing run
lock. Workers receive independent DynamicRuntime instances and durable allocations.
No worker receives the mutable Parent state, messages, executor or root dictionary.
"""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from copy import deepcopy
from datetime import datetime, timedelta
import threading
import uuid

from ..errors import IntegrityError, PermissionDenied, ValidationError
from ..models import digest
from .dynamic_protocol import observe_tool
from .runtime import BudgetExceeded
from .root_budget import consume_parent_tool, reserve_children, settle_child, root_usage


DOMAINS = ("financial", "market")
TERMINAL = {"completed", "insufficient", "failed", "cancelled", "late_discarded"}
STATUSES = TERMINAL | {"pending", "reserved", "running"}


def _ms(start, end):
    return max(0, round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000))


def runnable(nodes, node_id):
    node = nodes[node_id]
    return node["status"] in {"pending", "reserved"} and all(
        nodes[dep]["status"] in {"completed", "insufficient"} for dep in node["dependencies"])


def validate_groups(state):
    """Reconcile state with durable reservation, start, receipt and import events."""
    seen = set()
    for group in state.get("parallel_groups", []):
        gid = group["parallel_group_id"]
        if gid in seen or group["schema"] != "parallel-group/v1":
            raise IntegrityError("parallel group identity differs")
        seen.add(gid)
        nodes = group["nodes"]
        expected = {"financial_branch": [], "market_branch": [],
                    "calculation": ["financial_branch", "market_branch"],
                    "hypotheses": ["calculation"], "verification": ["hypotheses"]}
        if set(nodes) != set(expected) or any(nodes[k]["dependencies"] != v or
                nodes[k]["status"] not in STATUSES for k, v in expected.items()):
            raise IntegrityError("parallel dependency graph changed")
        reserves = [e for e in state["trace"] if e["event"] == "parallel_group_reserved"
                    and e["parallel_group_id"] == gid]
        if len(reserves) != 1:
            raise IntegrityError("parallel group lacks one atomic reservation")
        allocations = [{"child_run_id": nodes[d + "_branch"]["child_run_id"],
                        "limits": nodes[d + "_branch"]["limits"]} for d in DOMAINS]
        if reserves[0]["allocations"] != allocations:
            raise IntegrityError("parallel branch allocation changed")
        for domain in DOMAINS:
            node = nodes[domain + "_branch"]
            if node["domain"] != domain or node["tool"] != domain + "_child":
                raise IntegrityError("parallel branch domain changed")
            starts = [e for e in state["trace"] if e["event"] == "parallel_branch_running"
                      and e["child_run_id"] == node["child_run_id"]]
            if (len(starts) > 1 or bool(starts) != (node["started_at"] is not None)
                    or not starts and node["status"] not in {"reserved", "cancelled", "failed"}):
                raise IntegrityError("parallel branch was started more than once")
            imports = [e for e in state["trace"] if e["event"] == "tool_finished"
                       and e.get("tool_call_id") == node["tool_call_id"]]
            if len(imports) != int(node["submitted"]):
                raise IntegrityError("parallel branch submission differs from its receipt")
            if node["submitted"] and node["status"] not in {"completed", "insufficient"}:
                raise IntegrityError("discarded branch entered Parent state")
            if datetime.fromisoformat(node["deadline"]) > datetime.fromisoformat(state["deadline"]):
                raise IntegrityError("parallel deadline exceeds Parent")
        telemetry = group.get("telemetry")
        if telemetry is not None:
            ends = [e for e in state["trace"] if e["event"] == "parallel_group_ready_to_join"
                    and e["parallel_group_id"] == gid]
            observations = [e for e in state["trace"] if e["event"] == "parallel_telemetry"
                            and e["parallel_group_id"] == gid]
            expected_telemetry = build_telemetry(group)
            if (not ends or any(e["root_usage_after"] != group["root_usage_after"] for e in ends)
                    or telemetry != expected_telemetry or len(observations) != 1
                    or any(observations[0].get(k) != v for k, v in expected_telemetry.items())):
                raise IntegrityError("parallel telemetry differs from its durable group")
        for name in ("calculation", "hypotheses", "verification"):
            if nodes[name]["status"] == "completed" and not all(
                    nodes[dep]["status"] in {"completed", "insufficient"} for dep in nodes[name]["dependencies"]):
                raise IntegrityError("dependent stage ran before prerequisites")


def start_group(runtime, state, request, access, executor, event):
    """Construct trusted independent source DAG and durably reserve before submit."""
    if state.get("parallel_groups") or any(e["event"] == "child_reserved" for e in state["trace"]):
        raise ValidationError("each domain permits only one Child")
    if any(d in state["outputs"] for d in DOMAINS):
        raise ValidationError("parallel source branches must both be unstarted")
    headroom = runtime._parent_headroom(state, additional_tools=2)
    run, gid = state["run_id"], uuid.uuid4().hex
    nodes, allocations, trace_items = {}, [], []
    now = runtime.now()
    for i, domain in enumerate(DOMAINS, start=1):
        executor.registry.authorize(domain + "_child", runtime.spec, runtime.granted)
        _, child_request, _ = runtime._child_context(request, access, run, state["deadline"], domain)
        spec = runtime._role_spec(domain)
        cid = uuid.uuid4().hex
        limits = {"decisions": spec.max_decisions, "tools": spec.max_tools, "tokens": spec.max_tokens}
        call = f"{run}:{state['tools_used'] + i}"
        nodes[domain + "_branch"] = {"domain": domain, "tool": domain + "_child", "dependencies": [],
            "status": "reserved", "child_run_id": cid, "tool_call_id": call, "limits": limits,
            "request_ref": digest(child_request.to_dict()), "deadline": min(
                datetime.fromisoformat(state["deadline"]), now + timedelta(seconds=spec.max_seconds)).isoformat(),
            "reserved_at": now.isoformat(), "started_at": None, "finished_at": None,
            "submitted": False, "result_ref": None, "unknown_usage": False, "stop_reason": None}
        allocations.append({"child_run_id": cid, "limits": limits})
        trace_items.append(("tool_started", {"tool": domain + "_child", "tool_call_id": call,
                            "turn": state["model_attempts"], "parallel_group_id": gid}))
    for name, deps in (("calculation", ["financial_branch", "market_branch"]),
                       ("hypotheses", ["calculation"]), ("verification", ["hypotheses"])):
        nodes[name] = {"dependencies": deps, "status": "pending"}
    ledger = state["root_budget"]
    for _, item in trace_items:
        ledger = consume_parent_tool(ledger, item["tool_call_id"])
    ledger = reserve_children(ledger, gid, allocations, headroom)
    group = {"schema": "parallel-group/v1", "parallel_group_id": gid, "nodes": nodes,
        "status": "reserved", "group_started_at": now.isoformat(), "group_finished_at": None,
        "result_order": [], "canonical_merge_order": list(DOMAINS), "reservation_headroom": headroom,
        "root_usage_before": root_usage(state["root_budget"]), "telemetry": None}
    state["root_budget"] = ledger
    state["tools_used"] += 2
    state["parallel_groups"].append(group)
    # One append carries the entire root transaction and both branch reservations.
    for kind, fields in trace_items:
        state["trace"].append({"seq": len(state["trace"]), "run_id": run,
            "time": now.isoformat(), "event": kind, **fields})
    for domain in DOMAINS:
        node = nodes[domain + "_branch"]
        state["trace"].append({"seq": len(state["trace"]), "run_id": run, "time": now.isoformat(),
            "event": "child_reserved", "domain": domain, "parallel_group_id": gid,
            "child_run_id": node["child_run_id"], "tool_call_id": node["tool_call_id"],
            "limits": node["limits"], "request_ref": node["request_ref"], "root_deadline": state["deadline"]})
    event("parallel_group_reserved", parallel_group_id=gid, allocations=allocations, headroom=headroom)
    return group


def execute_group(runtime, state, request, access, executor, event, check, group):
    """Run only runnable DAG source nodes, and import receipts in the coordinator."""
    stop = threading.Event()
    gid, nodes = group["parallel_group_id"], group["nodes"]
    futures = {}

    def child_for(node):
        child, req, child_access = runtime._child_context(request, access, state["run_id"],
                                                        state["deadline"], node["domain"])
        child.inherited_deadline = datetime.fromisoformat(node["deadline"])
        child.cancelled = lambda: stop.is_set() or runtime.cancelled()
        child.telemetry_lineage = {"parallel_group_id": gid, "parallel_width": 2,
                                  "route_type": "parallel_child"}
        return child, req, child_access

    def dispatch(node):
        child, req, child_access = child_for(node)
        if digest(req.to_dict()) != node["request_ref"]:
            raise IntegrityError("parallel request binding changed")
        try:
            runtime.checkpoints.read(access.scope, node["child_run_id"])
        except PermissionDenied:
            return child.run(req, child_access, run_id=node["child_run_id"])
        return child.run(req, child_access, resume=node["child_run_id"])

    def accept(node, report, *, known=False):
        child, req, child_access = child_for(node)
        # The actual Child checkpoint, not a caller-provided report, is authoritative.
        actual = runtime.checkpoints.read(access.scope, node["child_run_id"])
        if digest(actual["report"]) != digest(report):
            raise IntegrityError("parallel receipt differs from actual checkpoint")
        if report["run_id"] != node["child_run_id"] or report["request_ref"] != node["request_ref"]:
            raise IntegrityError("parallel receipt differs from reserved identity")
        if report["deadline"] != node["deadline"]:
            raise IntegrityError("parallel receipt differs from reserved deadline")
        summary = runtime._child_summary(report, state["run_id"], node["tool_call_id"], domain=node["domain"])
        usage = report["usage"]
        if known:
            if summary not in state["child_results"] or node["result_ref"] != summary["result_ref"]:
                raise IntegrityError("known parallel receipt changed during recovery")
        else:
            state["root_budget"] = settle_child(state["root_budget"], node["child_run_id"], {
                "decisions": usage["model_attempts"], "tools": usage["tool_calls"], **{k: usage[k] for k in
                ("tokens_accounted", "tokens_reserved", "total_tokens", "unknown_usage_calls")}})
            state["child_results"].append(summary)
            state["child_results"].sort(key=lambda c: c["domain"])
            node["result_ref"] = summary["result_ref"]
            node["unknown_usage"] = bool(usage["unknown_usage_calls"])
            node["stop_reason"] = report.get("stop_reason")
            node["finished_at"] = runtime.now().isoformat()
            group["result_order"].append(node["domain"])
            late = (runtime.cancelled() or runtime.now() >= datetime.fromisoformat(node["deadline"])
                    or report.get("stop_reason") in {"cancelled", "deadline_exceeded"})
            node["status"] = "late_discarded" if late else (report["status"] if report["status"] in {
                "completed", "insufficient"} else "failed")
            event("child_finished", child_run_id=node["child_run_id"], domain=node["domain"],
                  status=report["status"], result_ref=summary["result_ref"], parallel_group_id=gid)
            event("parallel_branch_finished", child_run_id=node["child_run_id"], domain=node["domain"],
                  status=node["status"], parallel_group_id=gid)
        if node["status"] not in {"completed", "insufficient"}:
            if late:
                event("late_result_discarded", child_run_id=node["child_run_id"], parallel_group_id=gid)
            return
        # Reauthorize even if a cache/dedup entry exists. Recheck after the read too.
        check()
        if not child.authorize_parent():
            raise PermissionDenied("parallel delegation was revoked")
        fresh, _ = executor.execute(node["domain"], wave="parallel-child-import")
        delegated = {key: value for key, value in fresh.items() if key in runtime.delegated_datasets}
        if digest(delegated) != digest(report["source_results"]) or digest(delegated) != report["source_result_ref"] or set(delegated) != set(fresh):
            raise IntegrityError("parallel source result exceeds its exact delegated binding")
        # Completed replay verifies all source grants, Evidence refs and trace usage.
        verified = child.run(req, child_access, resume=node["child_run_id"])
        if digest(verified) != digest(report):
            raise IntegrityError("parallel Child result changed during join")
        check()
        state["outputs"][node["domain"]] = deepcopy(delegated)
        state["observations"][node["domain"]] = observe_tool(node["domain"], delegated)
        state["source_origins"][node["domain"]] = report["source_tool_call_id"]
        node["submitted"] = True
        state["outputs"] = dict(sorted(state["outputs"].items()))
        state["observations"] = dict(sorted(state["observations"].items()))
        event("tool_finished", tool=node["tool"], tool_call_id=node["tool_call_id"], dedup=False,
              result_hash=digest(delegated), observation=state["observations"][node["domain"]], parallel_group_id=gid)

    try:
        pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="domain-child")
        try:
            for domain in DOMAINS:
                node = nodes[domain + "_branch"]
                if node["status"] in TERMINAL:
                    if node["status"] in {"completed", "insufficient"} and not node["submitted"]:
                        child, req, child_access = child_for(node)
                        accept(node, child.run(req, child_access, resume=node["child_run_id"]), known=True)
                    continue
                check()
                if node["status"] == "reserved":
                    if not runnable(nodes, domain + "_branch"):
                        continue
                    node["status"], node["started_at"] = "running", runtime.now().isoformat()
                    group["status"] = "running"
                    event("parallel_branch_running", child_run_id=node["child_run_id"], domain=domain, parallel_group_id=gid)
                # Recovery resumes the same run, never a new reservation or new Child.
                futures[pool.submit(dispatch, deepcopy(node))] = node
            while futures:
                if runtime.cancelled() or runtime.now() >= datetime.fromisoformat(state["deadline"]):
                    stop.set()
                done, _ = wait(futures, timeout=0.02, return_when=FIRST_COMPLETED)
                for future in sorted(done, key=lambda f: DOMAINS.index(futures[f]["domain"])):
                    node = futures.pop(future)
                    try:
                        report = future.result()
                    except (PermissionDenied, IntegrityError):
                        stop.set()
                        raise
                    except Exception as exc:
                        # Without an authoritative complete receipt keep the whole allocation.
                        node["status"] = "cancelled" if runtime.cancelled() else "failed"
                        node["stop_reason"] = "cancelled" if runtime.cancelled() else "unknown_child_result"
                        node["finished_at"], node["unknown_usage"] = runtime.now().isoformat(), True
                        group["result_order"].append(node["domain"])
                        event("parallel_branch_finished", child_run_id=node["child_run_id"], domain=node["domain"],
                              status=node["status"], error_type=type(exc).__name__, parallel_group_id=gid)
                        continue
                    accept(node, report)
        finally:
            # A synchronous bounded I/O call is cooperative; no new dispatch after stop.
            stop.set()
            pool.shutdown(wait=True, cancel_futures=True)
    except (PermissionDenied, IntegrityError, BudgetExceeded) as exc:
        reason = str(exc) if isinstance(exc, BudgetExceeded) else "security_violation"
        for domain in DOMAINS:
            node = nodes[domain + "_branch"]
            if node["status"] not in TERMINAL:
                node["status"] = "failed" if reason == "security_violation" else "cancelled"
                node["stop_reason"], node["finished_at"] = reason, runtime.now().isoformat()
                node["unknown_usage"] = node["started_at"] is not None
                group["result_order"].append(domain)
                event("parallel_branch_finished", child_run_id=node["child_run_id"], domain=domain,
                      status=node["status"], error_type=type(exc).__name__, parallel_group_id=gid)
        finalize_group(runtime, state, group, event)
        raise
    finalize_group(runtime, state, group, event)
    check()
    if group["status"] != "completed":
        raise BudgetExceeded("parallel_required_branch_incomplete")


def finalize_group(runtime, state, group, event):
    """Close every orderly stop, without releasing unverified Child allocations."""
    gid, nodes = group["parallel_group_id"], group["nodes"]
    group["group_finished_at"] = group["group_finished_at"] or runtime.now().isoformat()
    group["status"] = "completed" if all(nodes[d + "_branch"]["submitted"] for d in DOMAINS) else "partial"
    group["root_usage_after"] = root_usage(state["root_budget"])
    event("parallel_group_ready_to_join", parallel_group_id=gid, status=group["status"],
          root_usage_after=deepcopy(group["root_usage_after"]))
    telemetry = build_telemetry(group)
    group["telemetry"] = telemetry
    state["pending_action"] = None
    state["context_store"]["requested_refs"] = []
    state["no_progress"] = 0
    event("parallel_telemetry", **telemetry)


def build_telemetry(group):
    """Reproducible observational measurement; never used to select routes."""
    gid, nodes = group["parallel_group_id"], group["nodes"]
    before, after = group["root_usage_before"], group["root_usage_after"]
    branches = [nodes[d + "_branch"] for d in DOMAINS]
    wall = _ms(group["group_started_at"], group["group_finished_at"])
    telemetry = {"schema": "parallel-telemetry/v1", "parallel_group_id": gid,
        "branch_count": 2, "branch_domains": list(DOMAINS), "branch_route_types": ["delegated", "delegated"],
        "group_started_at": group["group_started_at"], "group_finished_at": group["group_finished_at"],
        "branches": [{"domain": b["domain"], "child_run_id": b["child_run_id"], "status": b["status"], "stop_reason": b.get("stop_reason"),
            "branch_started_at": b["started_at"], "branch_finished_at": b["finished_at"],
            "queue_ms": _ms(b["reserved_at"], b["started_at"]) if b["started_at"] else None,
            "execution_ms": _ms(b["started_at"], b["finished_at"]) if b["started_at"] and b["finished_at"] else None,
            "join_wait_ms": _ms(b["finished_at"], group["group_finished_at"]) if b["finished_at"] else None} for b in branches],
        "wall_clock_ms": wall, "sum_branch_execution_ms": sum(_ms(b["started_at"], b["finished_at"])
             for b in branches if b["started_at"] and b["finished_at"]),
        **{"root_reserved_" + k: sum(b["limits"][k] for b in branches) + (2 if k == "tools" else 0)
           for k in ("decisions", "tools", "tokens")},
        "root_actual_decisions": after["model_attempts"] - before["model_attempts"],
        "root_actual_tools": after["tool_attempts"] - before["tool_attempts"],
        "root_actual_tokens": after["total_tokens"] - before["total_tokens"],
        "cancelled_branch_count": sum(b["status"] == "cancelled" or b.get("stop_reason") == "cancelled" for b in branches),
        "failed_branch_count": sum(b["status"] == "failed" for b in branches),
        "late_branch_count": sum(b["status"] == "late_discarded" for b in branches),
        "unknown_usage_count": sum(b["unknown_usage"] for b in branches),
        "result_order": list(group["result_order"]), "canonical_merge_order": list(DOMAINS)}
    return telemetry


def gate_stage(state, name):
    """Parent may execute a dependent stage only after accepted prerequisites."""
    for group in state.get("parallel_groups", []):
        node = group["nodes"].get(name)
        if node is not None and not all(group["nodes"][dep]["status"] in {"completed", "insufficient"}
                                        for dep in node["dependencies"]):
            raise ValidationError("parallel dependency is not ready")


def complete_stage(state, name):
    for group in state.get("parallel_groups", []):
        if name in {"calculation", "hypotheses", "verification"}:
            gate_stage(state, name)
            group["nodes"][name]["status"] = "completed"
