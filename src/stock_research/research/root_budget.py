"""Serializable root reservations for bounded parent/child runs.

This is a ledger, not another Runtime. Functions return a new dictionary; callers
must place it in parent state and checkpoint it before dispatching paid work. The
existing Runtime owns authorization, deadlines, cancellation and receipt checks.
Parallel v3 reservations are one all-or-none ledger event. The Parent remains the
sole ledger writer under its existing per-run CheckpointStore process lock;
workers consume already allocated local budgets and never write this dictionary.
"""
from copy import deepcopy
import re

from ..errors import IntegrityError, ValidationError
from .runtime import BudgetExceeded


SCHEMA = "root-budget/v1"
SCHEMA_V2 = "root-budget/v2"
SCHEMA_V3 = "root-budget/v3"
_LIMIT_KEYS = frozenset({"decisions", "tools", "tokens"})
_CHILD_USAGE_KEYS = frozenset({"decisions", "tools", "tokens_accounted", "tokens_reserved",
                              "total_tokens", "unknown_usage_calls"})
_PARENT_USAGE_KEYS = frozenset({"prompt_tokens", "completion_tokens", "total_tokens"})


def _require(condition, error=IntegrityError):
    if not condition:
        raise error("root budget contract or accounting differs")


def _number(value, *, positive=False):
    return type(value) is int and value >= (1 if positive else 0)


def _limits(value, error=IntegrityError):
    _require(type(value) is dict and set(value) == _LIMIT_KEYS
             and all(_number(n, positive=True) for n in value.values()), error)
    return dict(value)


def _max_children(value, error=IntegrityError):
    _require(type(value) is int and 1 <= value <= 2, error)
    return value


def _run_id(value, error=IntegrityError):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{32}", value) is not None, error)


def _intent_id(value, error=IntegrityError):
    _require(type(value) is str and re.fullmatch(r"[A-Za-z0-9:_./-]{1,160}", value) is not None, error)


def _hash(value, error=IntegrityError):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None, error)


def _parent_usage(value, reservation, error=IntegrityError):
    _require(type(value) is dict and set(value) == _PARENT_USAGE_KEYS
             and all(_number(n) for n in value.values())
             and value["total_tokens"] == value["prompt_tokens"] + value["completion_tokens"]
             and value["total_tokens"] <= reservation, error)
    return dict(value)


def _child_usage(value, allocation, error=IntegrityError):
    _require(type(value) is dict and set(value) == _CHILD_USAGE_KEYS
             and all(_number(n) for n in value.values()), error)
    _require(value["decisions"] <= allocation["decisions"]
             and value["tools"] <= allocation["tools"]
             and value["unknown_usage_calls"] <= value["decisions"]
             and value["total_tokens"] <= value["tokens_accounted"] <= allocation["tokens"]
             and value["tokens_accounted"] <= value["tokens_reserved"]
             and value["tokens_reserved"] <= value["decisions"] * allocation["tokens"], error)
    if value["unknown_usage_calls"]:
        _require(value["tokens_accounted"] > value["total_tokens"], error)
    else:
        _require(value["tokens_accounted"] == value["total_tokens"], error)
    return dict(value)


def _summary(parent_models, parent_tools, child):
    parents = list(parent_models.values())
    result = {
        "decisions_accounted": len(parents), "tools_accounted": len(parent_tools),
        "tokens_accounted": sum(p["usage"]["total_tokens"] if p["status"] == "known"
                                else p["token_reservation"] for p in parents),
        "model_attempts": len(parents), "tool_attempts": len(parent_tools),
        "tokens_reserved": sum(p["token_reservation"] for p in parents),
        "tokens_dispatched_reserved": sum(p["token_reservation"] for p in parents),
        "total_tokens": sum(p["usage"]["total_tokens"] for p in parents if p["status"] == "known"),
        "unknown_usage_calls": sum(p["status"] != "known" for p in parents),
        "unresolved_child_allocations": 0,
    }
    if child is not None:
        allocation = child["limits"]
        result["tokens_reserved"] += allocation["tokens"]
        if child["status"] == "known":
            usage = child["usage"]
            result["decisions_accounted"] += usage["decisions"]
            result["tools_accounted"] += usage["tools"]
            result["tokens_accounted"] += usage["tokens_accounted"]
            result["model_attempts"] += usage["decisions"]
            result["tool_attempts"] += usage["tools"]
            result["tokens_dispatched_reserved"] += usage["tokens_reserved"]
            result["total_tokens"] += usage["total_tokens"]
            result["unknown_usage_calls"] += usage["unknown_usage_calls"]
        else:
            result["decisions_accounted"] += allocation["decisions"]
            result["tools_accounted"] += allocation["tools"]
            result["tokens_accounted"] += allocation["tokens"]
            # Entire-child unknown results give no reliable attempt count. The
            # complete allocation remains occupied and explicitly unresolved.
            result["unresolved_child_allocations"] = 1
    return result


def _fold(root_run_id, limits, events, overflow=IntegrityError):
    _run_id(root_run_id)
    limits = _limits(limits)
    _require(type(events) is list)
    models, tools, child = {}, set(), None
    for seq, event in enumerate(events):
        _require(type(event) is dict and type(event.get("seq")) is int
                 and event["seq"] == seq and type(event.get("kind")) is str)
        kind = event["kind"]
        if kind == "parent_model_reserved":
            _require(set(event) == {"seq", "kind", "intent_id", "token_reservation", "message_sha256"})
            _intent_id(event["intent_id"])
            _hash(event["message_sha256"])
            _require(event["intent_id"] not in models and _number(event["token_reservation"], positive=True))
            _require(all(m["status"] != "pending" for m in models.values())
                     and (child is None or child["status"] != "pending"))
            models[event["intent_id"]] = {"status": "pending", "token_reservation": event["token_reservation"]}
        elif kind == "parent_model_settled":
            _require(set(event) == {"seq", "kind", "intent_id", "usage"})
            _intent_id(event["intent_id"])
            _require(event["intent_id"] in models and models[event["intent_id"]]["status"] == "pending")
            intent = models[event["intent_id"]]
            if event["usage"] is None:
                intent["status"] = "unknown"
            else:
                intent["usage"] = _parent_usage(event["usage"], intent["token_reservation"])
                intent["status"] = "known"
        elif kind == "parent_tool_consumed":
            _require(set(event) == {"seq", "kind", "tool_call_id"})
            _intent_id(event["tool_call_id"])
            _require(event["tool_call_id"] not in tools)
            _require(child is None or child["status"] != "pending")
            tools.add(event["tool_call_id"])
        elif kind == "child_reserved":
            _require(set(event) == {"seq", "kind", "child_run_id", "limits"})
            _run_id(event["child_run_id"])
            _require(child is None and event["child_run_id"] != root_run_id)
            _require(all(m["status"] != "pending" for m in models.values()))
            child = {"run_id": event["child_run_id"], "limits": _limits(event["limits"]), "status": "pending"}
        elif kind == "child_settled":
            _require(set(event) == {"seq", "kind", "child_run_id", "usage"})
            _run_id(event["child_run_id"])
            _require(child is not None and child["run_id"] == event["child_run_id"]
                     and child["status"] == "pending")
            if event["usage"] is None:
                child["status"] = "unknown"
            else:
                child["usage"] = _child_usage(event["usage"], child["limits"])
                child["status"] = "known"
        else:
            raise IntegrityError("unknown root budget event")
        current = _summary(models, tools, child)
        if any(current[key + "_accounted"] > limits[key] for key in ("decisions", "tools", "tokens")):
            raise overflow("root_budget_exceeded")
    return models, tools, child, _summary(models, tools, child)


def _summary_v2(parent_models, parent_tools, children):
    result = _summary(parent_models, parent_tools, None)
    for child in children.values():
        contribution = _summary({}, set(), child)
        for key in result:
            result[key] += contribution[key]
    return result


def _fold_v2(root_run_id, limits, events, max_children, overflow=IntegrityError):
    """Independent v2 child allocation replay; the v1 fold remains unchanged."""
    _run_id(root_run_id)
    limits = _limits(limits)
    _max_children(max_children)
    _require(type(events) is list)
    models, tools, children = {}, set(), {}
    for seq, event in enumerate(events):
        _require(type(event) is dict and type(event.get("seq")) is int
                 and event["seq"] == seq and type(event.get("kind")) is str)
        kind = event["kind"]
        child_pending = any(child["status"] == "pending" for child in children.values())
        if kind == "parent_model_reserved":
            _require(set(event) == {"seq", "kind", "intent_id", "token_reservation", "message_sha256"})
            _intent_id(event["intent_id"])
            _hash(event["message_sha256"])
            _require(event["intent_id"] not in models and _number(event["token_reservation"], positive=True)
                     and not child_pending and all(model["status"] != "pending" for model in models.values()))
            models[event["intent_id"]] = {"status": "pending", "token_reservation": event["token_reservation"]}
        elif kind == "parent_model_settled":
            _require(set(event) == {"seq", "kind", "intent_id", "usage"})
            _intent_id(event["intent_id"])
            _require(event["intent_id"] in models and models[event["intent_id"]]["status"] == "pending")
            intent = models[event["intent_id"]]
            if event["usage"] is None:
                intent["status"] = "unknown"
            else:
                intent["usage"] = _parent_usage(event["usage"], intent["token_reservation"])
                intent["status"] = "known"
        elif kind == "parent_tool_consumed":
            _require(set(event) == {"seq", "kind", "tool_call_id"})
            _intent_id(event["tool_call_id"])
            _require(event["tool_call_id"] not in tools and not child_pending)
            tools.add(event["tool_call_id"])
        elif kind == "child_reserved":
            _require(set(event) == {"seq", "kind", "child_run_id", "limits"})
            _run_id(event["child_run_id"])
            _require(event["child_run_id"] != root_run_id and event["child_run_id"] not in children
                     and len(children) < max_children and not child_pending
                     and all(model["status"] != "pending" for model in models.values()))
            children[event["child_run_id"]] = {"run_id": event["child_run_id"],
                "limits": _limits(event["limits"]), "status": "pending"}
        elif kind == "child_settled":
            _require(set(event) == {"seq", "kind", "child_run_id", "usage"})
            _run_id(event["child_run_id"])
            _require(event["child_run_id"] in children)
            child = children[event["child_run_id"]]
            _require(child["status"] == "pending")
            if event["usage"] is None:
                child["status"] = "unknown"
            else:
                child["usage"] = _child_usage(event["usage"], child["limits"])
                child["status"] = "known"
        else:
            raise IntegrityError("unknown root budget event")
        current = _summary_v2(models, tools, children)
        if any(current[key + "_accounted"] > limits[key] for key in ("decisions", "tools", "tokens")):
            raise overflow("root_budget_exceeded")
    return models, tools, children, _summary_v2(models, tools, children)


def _headroom(value, error=IntegrityError):
    """Mandatory Parent work may need no more tools, but always needs a finish."""
    _require(type(value) is dict and set(value) == _LIMIT_KEYS
             and all(_number(n) for n in value.values())
             and value["decisions"] > 0 and value["tokens"] > 0, error)
    return dict(value)


def _allocations(value, max_children, root_run_id, error=IntegrityError):
    _require(type(value) is list and 1 <= len(value) <= max_children, error)
    checked, run_ids = [], set()
    for allocation in value:
        _require(type(allocation) is dict and set(allocation) == {"child_run_id", "limits"}, error)
        child_run_id = allocation["child_run_id"]
        _run_id(child_run_id, error)
        _require(child_run_id != root_run_id and child_run_id not in run_ids, error)
        run_ids.add(child_run_id)
        checked.append({"child_run_id": child_run_id, "limits": _limits(allocation["limits"], error)})
    return checked


def _fold_v3(root_run_id, limits, events, max_children, overflow=IntegrityError):
    """Replay explicit atomic groups without weakening either legacy serial fold."""
    _run_id(root_run_id)
    limits = _limits(limits)
    _max_children(max_children)
    _require(type(events) is list)
    models, tools, children, groups = {}, set(), {}, set()
    for seq, event in enumerate(events):
        _require(type(event) is dict and type(event.get("seq")) is int
                 and event["seq"] == seq and type(event.get("kind")) is str)
        kind = event["kind"]
        child_pending = any(child["status"] == "pending" for child in children.values())
        event_headroom = None
        if kind == "parent_model_reserved":
            _require(set(event) == {"seq", "kind", "intent_id", "token_reservation", "message_sha256"})
            _intent_id(event["intent_id"])
            _hash(event["message_sha256"])
            _require(event["intent_id"] not in models and _number(event["token_reservation"], positive=True)
                     and not child_pending and all(model["status"] != "pending" for model in models.values()))
            models[event["intent_id"]] = {"status": "pending", "token_reservation": event["token_reservation"]}
        elif kind == "parent_model_settled":
            _require(set(event) == {"seq", "kind", "intent_id", "usage"})
            _intent_id(event["intent_id"])
            _require(event["intent_id"] in models and models[event["intent_id"]]["status"] == "pending")
            intent = models[event["intent_id"]]
            if event["usage"] is None:
                intent["status"] = "unknown"
            else:
                intent["usage"] = _parent_usage(event["usage"], intent["token_reservation"])
                intent["status"] = "known"
        elif kind == "parent_tool_consumed":
            _require(set(event) == {"seq", "kind", "tool_call_id"})
            _intent_id(event["tool_call_id"])
            _require(event["tool_call_id"] not in tools and not child_pending)
            tools.add(event["tool_call_id"])
        elif kind in {"child_reserved", "children_reserved"}:
            _require(not child_pending and all(model["status"] != "pending" for model in models.values()))
            if kind == "child_reserved":
                fields = {"seq", "kind", "child_run_id", "limits"}
                _require(set(event) in (fields, fields | {"headroom"}))
                allocations = _allocations([{key: event[key] for key in ("child_run_id", "limits")}],
                                           max_children, root_run_id)
                if "headroom" in event:
                    event_headroom = _headroom(event["headroom"])
            else:
                _require(set(event) == {"seq", "kind", "group_id", "allocations", "headroom"})
                _intent_id(event["group_id"])
                _require(event["group_id"] not in groups)
                allocations = _allocations(event["allocations"], max_children, root_run_id)
                event_headroom = _headroom(event["headroom"])
                groups.add(event["group_id"])
            _require(len(children) + len(allocations) <= max_children
                     and all(item["child_run_id"] not in children for item in allocations))
            for item in allocations:
                children[item["child_run_id"]] = {"run_id": item["child_run_id"],
                    "limits": item["limits"], "status": "pending"}
        elif kind == "child_settled":
            _require(set(event) == {"seq", "kind", "child_run_id", "usage"})
            _run_id(event["child_run_id"])
            _require(event["child_run_id"] in children)
            child = children[event["child_run_id"]]
            _require(child["status"] == "pending")
            if event["usage"] is None:
                child["status"] = "unknown"
            else:
                child["usage"] = _child_usage(event["usage"], child["limits"])
                child["status"] = "known"
        else:
            raise IntegrityError("unknown root budget event")
        current = _summary_v2(models, tools, children)
        if any(current[key + "_accounted"] + (event_headroom[key] if event_headroom else 0) > limits[key]
               for key in _LIMIT_KEYS):
            raise overflow("root_budget_exceeded")
    return models, tools, children, _summary_v2(models, tools, children)


def _fold_ledger(ledger, overflow=IntegrityError):
    if ledger["schema"] == SCHEMA_V3:
        return _fold_v3(ledger["root_run_id"], ledger["limits"], ledger["events"],
                        ledger["max_children"], overflow)
    if ledger["schema"] == SCHEMA_V2:
        return _fold_v2(ledger["root_run_id"], ledger["limits"], ledger["events"],
                        ledger["max_children"], overflow)
    models, tools, child, summary = _fold(ledger["root_run_id"], ledger["limits"], ledger["events"], overflow)
    return models, tools, {} if child is None else {child["run_id"]: child}, summary


def new_root_budget(limits, root_run_id, *, max_children=None, parallel=False):
    """Legacy defaults stay exact; explicit ``parallel=True`` opts into v3."""
    _run_id(root_run_id, ValidationError)
    checked = _limits(limits, ValidationError)
    _require(type(parallel) is bool, ValidationError)
    if parallel:
        count = _max_children(2 if max_children is None else max_children, ValidationError)
        return {"schema": SCHEMA_V3, "root_run_id": root_run_id, "limits": checked,
                "max_children": count, "events": [], "summary": _summary_v2({}, set(), {})}
    if max_children is not None:
        count = _max_children(max_children, ValidationError)
        return {"schema": SCHEMA_V2, "root_run_id": root_run_id, "limits": checked,
                "max_children": count, "events": [], "summary": _summary_v2({}, set(), {})}
    return {"schema": SCHEMA, "root_run_id": root_run_id, "limits": checked, "events": [],
            "summary": _summary({}, set(), None)}


def validate_root_budget(ledger, history=None):
    """Recompute events and validate immutable limits plus historical event prefixes.

    ``history`` is an optional list of root-budget dictionaries obtained from the
    verified parent CheckpointStore history, ending in the supplied current ledger.
    Local parent intents and the child checkpoint must additionally be reconciled
    by the Runtime, which owns those records.
    """
    _require(type(ledger) is dict and type(ledger.get("schema")) is str
             and ledger["schema"] in {SCHEMA, SCHEMA_V2, SCHEMA_V3})
    keys = {"schema", "root_run_id", "limits", "events", "summary"}
    if ledger["schema"] in {SCHEMA_V2, SCHEMA_V3}:
        keys.add("max_children")
        _max_children(ledger.get("max_children"))
    _require(set(ledger) == keys)
    _, _, _, expected = _fold_ledger(ledger)
    _require(type(ledger["summary"]) is dict and set(ledger["summary"]) == set(expected)
             and all(_number(value) for value in ledger["summary"].values())
             and ledger["summary"] == expected)
    if history is not None:
        _require(type(history) is list and bool(history) and history[-1] == ledger)
        original = history[0]
        previous = []
        for saved in history:
            validate_root_budget(saved)
            _require(all(saved.get(key) == original.get(key) for key in ("schema", "root_run_id", "limits", "max_children"))
                     and saved["events"][:len(previous)] == previous)
            previous = saved["events"]
    return deepcopy(expected)


def _append(ledger, kind, **fields):
    validate_root_budget(ledger)
    updated = deepcopy(ledger)
    updated["events"].append({"seq": len(updated["events"]), "kind": kind, **deepcopy(fields)})
    _, _, _, updated["summary"] = _fold_ledger(updated, overflow=BudgetExceeded)
    return updated


def reserve_parent_model(ledger, intent_id, token_reservation, message_sha256):
    """Occupy one root decision and its input/output Token reservation before dispatch."""
    validate_root_budget(ledger)
    _intent_id(intent_id, ValidationError)
    _hash(message_sha256, ValidationError)
    _require(_number(token_reservation, positive=True), ValidationError)
    models, _, children, _ = _fold_ledger(ledger)
    _require(intent_id not in models and all(m["status"] != "pending" for m in models.values())
             and all(child["status"] != "pending" for child in children.values()), ValidationError)
    return _append(ledger, "parent_model_reserved", intent_id=intent_id,
                   token_reservation=token_reservation, message_sha256=message_sha256)


def settle_parent_model(ledger, intent_id, usage):
    """A verified receipt replaces reservation; unknown outcome permanently retains it."""
    validate_root_budget(ledger)
    _intent_id(intent_id, ValidationError)
    models, _, _, _ = _fold_ledger(ledger)
    _require(intent_id in models and models[intent_id]["status"] == "pending", ValidationError)
    if usage is not None:
        _parent_usage(usage, models[intent_id]["token_reservation"], ValidationError)
    return _append(ledger, "parent_model_settled", intent_id=intent_id, usage=usage)


def consume_parent_tool(ledger, tool_call_id):
    """Consume an attempt before any tool dispatch, including failed attempts."""
    validate_root_budget(ledger)
    _intent_id(tool_call_id, ValidationError)
    _, tools, children, _ = _fold_ledger(ledger)
    _require(tool_call_id not in tools and all(child["status"] != "pending" for child in children.values()), ValidationError)
    return _append(ledger, "parent_tool_consumed", tool_call_id=tool_call_id)


def reserve_child(ledger, child_run_id, limits, *, headroom=None):
    """Atomically occupy one serial Child's entire local decision/tool/Token limits."""
    validate_root_budget(ledger)
    _run_id(child_run_id, ValidationError)
    checked = _limits(limits, ValidationError)
    models, _, children, _ = _fold_ledger(ledger)
    _require(child_run_id not in children and len(children) < ledger.get("max_children", 1)
             and child_run_id != ledger["root_run_id"]
             and all(child["status"] != "pending" for child in children.values())
             and all(m["status"] != "pending" for m in models.values()), ValidationError)
    fields = {}
    if headroom is not None:
        _require(ledger["schema"] == SCHEMA_V3, ValidationError)
        fields["headroom"] = _headroom(headroom, ValidationError)
    return _append(ledger, "child_reserved", child_run_id=child_run_id, limits=checked, **fields)


def reserve_children(ledger, group_id, allocations, headroom):
    """Reserve every runnable branch and retain Parent capacity in one event.

    The caller must persist this returned ledger and its group intent together
    before submitting any branch. It must hold the Parent's existing run lock;
    this immutable ledger does not provide a compare-and-swap for stale copies.
    No Child is started when any allocation or Parent headroom does not fit.
    """
    validate_root_budget(ledger)
    _require(ledger["schema"] == SCHEMA_V3, ValidationError)
    _intent_id(group_id, ValidationError)
    checked = _allocations(allocations, ledger["max_children"], ledger["root_run_id"], ValidationError)
    retained = _headroom(headroom, ValidationError)
    models, _, children, _ = _fold_ledger(ledger)
    _require(all(child["status"] != "pending" for child in children.values())
             and all(model["status"] != "pending" for model in models.values())
             and len(children) + len(checked) <= ledger["max_children"]
             and all(item["child_run_id"] not in children for item in checked)
             and not any(event["kind"] == "children_reserved" and event["group_id"] == group_id
                         for event in ledger["events"]), ValidationError)
    return _append(ledger, "children_reserved", group_id=group_id, allocations=checked, headroom=retained)


def settle_child(ledger, child_run_id, usage):
    """Release only verified unused capacity; a completely unknown result keeps all."""
    validate_root_budget(ledger)
    _run_id(child_run_id, ValidationError)
    _, _, children, _ = _fold_ledger(ledger)
    _require(child_run_id in children and children[child_run_id]["status"] == "pending", ValidationError)
    child = children[child_run_id]
    if usage is not None:
        _child_usage(usage, child["limits"], ValidationError)
    return _append(ledger, "child_settled", child_run_id=child_run_id, usage=usage)


def root_usage(ledger):
    """Return inspectable occupied capacity, reported usage and remaining root limits."""
    summary = validate_root_budget(ledger)
    return {**summary, "limits": deepcopy(ledger["limits"]),
            "remaining": {key: ledger["limits"][key] - summary[key + "_accounted"] for key in _LIMIT_KEYS}}
