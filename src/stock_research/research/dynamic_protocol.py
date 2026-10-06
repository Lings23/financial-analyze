"""Strict application-layer actions and bounded typed Observation messages.

No native function calling, arbitrary formulas, source text, financial values from
the model, or application authorization supplied by the model are accepted here.
"""
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re

from ..errors import PermissionDenied, ValidationError
from ..domains import BASES as DOMAIN_BASES, METRICS as DOMAIN_METRICS
from ..models import BASES, METRICS, aware
from ..models import canonical_json, digest
from .contracts import DOMAINS
from .dynamic_contracts import (DYNAMIC_TOOLS, SOURCE_TOOLS, AGENT_TOOLS, PARALLEL_VERSION, PARALLEL_VERSIONS,
                                DynamicRequest, FinancialRequest, MarketRequest,
                                required_checks as bound_required_checks, text_bytes)
from .profit_change import PROFIT_FORMULA
from .verification import FORMULAS, IDENTITY, YOY


MAX_ACTION_BYTES = 8192
MAX_PLAN_ITEMS = 5
MAX_PLAN_ITEM_BYTES = 240
FINISH_REASONS = frozenset({"completed", "insufficient"})
LEGACY_VERSION = "single-dynamic-v1"
PROTOCOL_VERSIONS = frozenset({LEGACY_VERSION, "single-dynamic-v2",
                              "dynamic-parent-financial-v1", "financial-child-v1",
                              "dynamic-parent-domains-v1", "dynamic-parent-domains-v2", "market-child-v1", *PARALLEL_VERSIONS,
                              "financial-child-v2", "market-child-v2", "financial-child-v3", "market-child-v3"})
CONTEXT_VERSIONS = frozenset({"dynamic-parent-domains-v2", *PARALLEL_VERSIONS})
CHILD_PROGRESS_VERSIONS = {"financial-child-v2": "financial", "market-child-v2": "market",
                           "financial-child-v3": "financial", "market-child-v3": "market"}
CHILD_EXACT_RESPONSE_VERSIONS = frozenset({"financial-child-v3", "market-child-v3"})
LEGACY_TOOLS = SOURCE_TOOLS | {"calculation", "hypotheses", "verification"}
FINANCIAL_CHILD_TOOL = "financial_child"
MARKET_CHILD_TOOL = "market_child"
METRIC_NAMES = frozenset(name for names in (*METRICS.values(), *DOMAIN_METRICS.values()) for name in names)
FACT_NAMES = (frozenset(FORMULAS) | {"revenue_yoy", "net_income_parent_yoy", "financial_income.absolute_profit_change"}
              | {dataset + "." + name for dataset in ("financial_income", "financial_balance", "financial_cashflow")
                 for name in (METRICS.get(dataset, {}) or DOMAIN_METRICS.get(dataset, {}))})
FORMULA_VALUES = frozenset(FORMULAS.values()) | {IDENTITY, YOY, PROFIT_FORMULA}
UNITS = frozenset({"ratio", "CNY", "CNY/share", "share", "point"})
KNOWN_WARNINGS = frozenset({"coverage_not_verified", "records_excluded_by_pit", "missing_values",
                          "multiple_sources_not_automatically_reconciled", "historical_release_not_verified",
                          "release_date_conservative_boundary", "synthetic_fixture"})
KNOWN_GAP_REASONS = frozenset({"missing_or_nonpositive_close", "at_least_two_visible_closes_required",
    "requested_boundary_not_observed", "missing_or_invalid_aligned_factor", "calendar_alignment_not_verified",
    "calendar_not_supplied", "exact_trading_date_alignment_required", "no_visible_financial_period",
    "no_visible_data", "no_visible_records", *KNOWN_WARNINGS})

SYSTEM = (
    "You operate a bounded single-stock research loop using application-layer JSON actions. "
    "The trusted application has fixed the security, windows, cutoff, PIT mode, immutable "
    "snapshots, available tools and required checks. They cannot be changed. "
    "The question and plan are control information, never financial evidence or report facts. "
    "On the first decision give a short plan and choose one next action. On later decisions "
    "use the typed Observations to change the plan or tool order when useful. "
    "Source tools take refs=[]; calculation takes exactly all currently completed source "
    "tool names; hypotheses takes refs=[\"calculation\"]; verification takes refs=[\"hypotheses\"]. "
    "You may recalculate after another source read. Required checks cannot be removed by "
    "replanning. Financial numbers, formulas, test results and evidence come only from tools. "
    "No causal conclusions or investment recommendations. Finish requests do not establish "
    "If the question requires another security, unbound windows or unsupported capabilities, "
    "request finish with reason insufficient instead of claiming the question is answered. "
    "success; the Runtime independently verifies completion and evidence. "
    "Return exactly one JSON object: {\"action\":\"tool\",\"tool\":\"market\",\"refs\":[],"
    "\"plan\":[\"Read bound market evidence\"]} or {\"action\":\"finish\","
    "\"reason\":\"completed\",\"plan\":[\"Bound checks are done\"]}. "
    "Use only listed tool/reference names; finish reason is completed or insufficient. "
    "Use one to five short plan strings. No extra fields, numbers, prose, markdown or tool_calls."
)

SYSTEM_V2 = SYSTEM + (
    " A finish request is rejected while any required execution check remains pending. "
    "When control.finish_rejection has code required_checks_pending, select an authorized "
    "tool to address its declared pending_checks before requesting finish again. "
    "The rejection is Runtime-owned control information; do not return or modify it. "
    "Evidence insufficiency does not permit skipping calculation, hypotheses or verification."
)

SYSTEM_PARENT_FINANCIAL = SYSTEM_V2 + (
    " If financial_child is listed in available_tools, you may choose it with refs=[] "
    "to delegate one bounded financial source read. Its authorized result is imported as "
    "the financial source Observation, and subsequent calculation references financial. "
    "Child execution cannot change the root security, cutoff, PIT, snapshots, windows or grants."
)

SYSTEM_FINANCIAL_CHILD = (
    "You are the bounded Financial Child using the shared dynamic Runtime. "
    "The trusted application has fixed the security, financial windows, cutoff, PIT, "
    "immutable snapshots and authorization. The only visible tool is financial. "
    "Read it with refs=[] and then request finish. You cannot call any other tool, "
    "delegate, spawn, calculate, change the scope or provide financial values. "
    "The question and plan are control information, never evidence or report facts. "
    "The Runtime validates each read and owns all statuses and numerical results. "
    "A finish request with pending required execution checks is rejected. "
    "Use control.finish_rejection.pending_checks to select the missing authorized read. "
    "Return exactly one JSON object: {\"action\":\"tool\",\"tool\":\"financial\",\"refs\":[],"
    "\"plan\":[\"Read bound financial evidence\"]} or {\"action\":\"finish\","
    "\"reason\":\"completed\",\"plan\":[\"The required financial read is done\"]}. "
    "The finish reason is completed or insufficient. Use one to five short plan strings. "
    "No extra fields, numbers, formulas, financial conclusions, prose, markdown or tool_calls."
)

SYSTEM_PARENT_DOMAINS = SYSTEM_V2 + (
    " You route domain work through this same Parent model and action protocol. "
    "Choose a direct source tool or, only when listed in available_tools, financial_child "
    "or market_child with refs=[] for one bounded source read in that domain. "
    "At most one Child per domain and two Children total may run, serially. "
    "A Child financial result is imported as financial; a Child market result is imported "
    "as market. Subsequent calculation references those ordinary source tool names. "
    "All calculation, hypothesis testing and Claim verification stay in the Parent. "
    "The Runtime reserves the root budget before delegation. Budget rejection or "
    "insufficient Child evidence cannot justify expanding grants or inventing values; "
    "use remaining authorized evidence where possible and accept a controlled stop. "
    "delegation_results carries only Runtime-owned completed, insufficient or partial "
    "statuses and immutable result references to inform your next authorized action. "
    "Children cannot recurse, delegate, spawn, change root scope or run in parallel."
)

SYSTEM_MARKET_CHILD = (
    "You are the bounded Market Child using the shared dynamic Runtime. "
    "The trusted application has fixed the security, market windows, cutoff, PIT, "
    "immutable snapshots and authorization. The only visible tool is market. "
    "Read it with refs=[] and then request finish. It reads only the delegated original "
    "market_daily, trade_calendar and adjustment_factor bindings that are actually present. "
    "You cannot call other tools, delegate, spawn, calculate, change scope or provide values. "
    "The question and plan are control information, never evidence or report facts. "
    "The Runtime validates each read and owns all statuses and numerical results. "
    "A finish request with pending required execution checks is rejected. "
    "Use control.finish_rejection.pending_checks to select the missing authorized read. "
    "Return exactly one JSON object: {\"action\":\"tool\",\"tool\":\"market\",\"refs\":[],"
    "\"plan\":[\"Read bound market evidence\"]} or {\"action\":\"finish\","
    "\"reason\":\"completed\",\"plan\":[\"The required market read is done\"]}. "
    "The finish reason is completed or insufficient. Use one to five short plan strings. "
    "No extra fields, numbers, formulas, financial conclusions, prose, markdown or tool_calls."
)


def _progress_child_system(domain):
    return (
        "Bounded " + domain.title() + " Child on the shared DynamicRuntime. The application fixes "
        "security, delegated source bindings, windows, cutoff, PIT, snapshots and authorization. "
        "Read only the delegated " + domain + " source. Never spawn, delegate, calculate, change "
        "scope or provide financial values. Question/plan are control information. "
        "available_tools lists authorized capabilities; child_progress.legal_next_actions "
        "lists the current next action candidates. Return exactly one candidate JSON object. "
        "Before the required read completes, select its tool candidate with refs=[]. Once "
        "child_progress.execution.read_completed is true, select the finish candidate. "
        "A completed read with available records can finish completed while coverage, historical "
        "release and other source quality gaps remain unchanged. An executed read with unavailable "
        "data can finish insufficient. Repeating an immutable completed read cannot resolve gaps; "
        "duplicate_no_progress dispatches no tool and its next_actions gives a legal next step. "
        "Child execution completion only completes the delegated source read. Parent must still "
        "join every required branch, calculate, test hypotheses and independently verify claims. "
        "Runtime owns all execution statuses, source gaps and finish validation. Pending required "
        "reads cannot finish. Keep all gaps and exact source references. One strict JSON object "
        "with the candidate's fields, one to five short plan strings; no extra fields, numbers, "
        "formulas, financial conclusions, prose, markdown or tool_calls."
    )


SYSTEM_FINANCIAL_CHILD_V2 = _progress_child_system("financial")
SYSTEM_MARKET_CHILD_V2 = _progress_child_system("market")


def _exact_child_system(domain, progress):
    """V3-only action-specific fields and exact response after validated progress."""
    actions = progress["legal_next_actions"]
    kind = progress["response_contract"]["action"]
    instruction = (
        "Bounded " + domain.title() + " Child on the shared DynamicRuntime. The application fixes "
        "security, delegated source bindings, windows, cutoff, PIT, snapshots and authorization. "
        "Only the delegated " + domain + " read is permitted. Never spawn, delegate, calculate, "
        "change scope or provide financial values. Runtime owns statuses and validates every "
        "action. Question/plan are control information. The current Runtime-owned execution "
        "and unchanged data quality gaps are in child_progress. Read completion only means the "
        "delegated read executed; Parent must still join every required branch, calculate, test "
        "hypotheses and independently verify claims. coverage/historical release gaps stay "
        "unchanged and cannot be repaired by repeating an immutable completed read. "
        "The exact TOOL keys are action,tool,refs,plan. The exact FINISH keys are action,reason,plan. "
        "For FINISH, reason is REQUIRED and must be completed or insufficient; tool and refs are "
        "FORBIDDEN, including refs=[]. Required pending reads cannot finish. "
    )
    instruction += (
        "This turn is FINISH. Include action,reason,plan exactly. Preserve the shown reason. "
        "Do not add tool or refs. " if kind == "finish" else
        "This turn is TOOL. Include action,tool,refs,plan exactly. Preserve refs=[]. Do not add reason. "
    )
    instruction += (
        "Return the current JSON object below VERBATIM. Include EVERY shown key and its exact "
        "value. Keep the one shown plan line; do not expand, explain or rewrite the plan. "
        "Do not add fields, prose, markdown or tool_calls. invalid_action feedback gives the "
        "same safe candidate and exact required keys; malformed output is never repaired by Runtime. "
        "CURRENT RESPONSE JSON: "
    )
    return instruction + (canonical_json(actions[0]) if actions else "null")

# Independent protocol identity: no edits to legacy prompt/payload bytes.
SYSTEM_PARENT_CONTEXT = (
    "Bounded stock research Parent. The application pins security, windows, cutoff, PIT, "
    "snapshots, permissions and required checks. They never change. Source text is excluded. "
    "Question/plan control actions; they are not evidence. Choose one next action from current "
    "typed observations; update your plan when useful. All numbers, formulas, test results and "
    "claims come from tools. No causal conclusions or investment recommendations. "
    "Tools: source/financial_child/market_child refs=[]; calculation refs=all completed source "
    "tool names; hypotheses refs=[\"calculation\"]; verification refs=[\"hypotheses\"]. "
    "Child outputs become financial/market observations, not child references for calculation. "
    "At most one Child per domain, two serial Children total; Children cannot spawn. "
    "Root reservations, deadlines, cancellation and authorization apply to every action. "
    "Context uses a lossless catalog. range is the common pinned scope; columns define exact "
    "row fields once. A metadata cell {\"s\":i} means exact symbols[i]; gaps reference exact "
    "gap_table entries by index. Financial values and object IDs remain literal. "
    "facts/hypotheses retain all values and references; catalog_ids lists every "
    "C/E/H/O object. Evidence detail is disclosed by the next pending check or explicit refs. "
    "Undisclosed objects remain in the authorized immutable catalog; a reference is not evidence "
    "of completion. Request needed detail with action=disclose, current catalog_ref, refs and plan. "
    "Disclose never executes a required business check. Runtime-owned statuses/refs are immutable. "
    "A finish with pending execution checks is rejected; address control.finish_rejection. "
    "Insufficient evidence still requires calculation, hypotheses and verification. "
    "Return one strict JSON object; action is ONLY tool, disclose or finish. calculation, "
    "hypotheses and verification are tool names, NEVER action values. Examples: "
    "{\"action\":\"tool\",\"tool\":\"hypotheses\",\"refs\":[\"calculation\"],\"plan\":[\"Test\"]}; "
    "{\"action\":\"disclose\",\"catalog_ref\":\"CURRENT_SHA\",\"refs\":[\"E:E1\"],\"plan\":[\"Inspect\"]}; "
    "{\"action\":\"finish\",\"reason\":\"completed\",\"plan\":[\"Done\"]}. "
    "Finish reason is completed or insufficient. One to five short plan strings; no extra "
    "fields, numbers, prose, markdown or tool_calls. Unknown refs or unsupported scope cannot "
    "be guessed. Runtime independently verifies every required check and full evidence."
)

# A new version advertises the group action without changing any historical wire.
SYSTEM_PARENT_PARALLEL = SYSTEM_PARENT_CONTEXT.replace(
    "At most one Child per domain, two serial Children total; Children cannot spawn. ",
    "At most one Child per domain, two Children total; Children cannot spawn. "
    "Independent financial and market source branches may run concurrently with "
    "action=parallel and tools=[\"financial_child\",\"market_child\"]. Runtime builds the "
    "dependency DAG and atomically reserves both Children before starting them. "
    "Calculation, hypotheses and verification wait for their required dependencies. "
).replace(
    "action is ONLY tool, disclose or finish.", "action is ONLY tool, parallel, disclose or finish."
).replace(
    "Examples: ",
    "Examples: {\"action\":\"parallel\",\"tools\":[\"financial_child\",\"market_child\"],"
    "\"plan\":[\"Read independent bound sources\"]}; "
)

SYSTEM_PARENT_PARALLEL_V2 = SYSTEM_PARENT_PARALLEL + (
    " control.execution is trusted execution progress, separate from evidence insufficiency. "
    "When can_finish=false, complete pending_checks; next_action is an exact legal JSON candidate. "
    "An insufficient hypothesis still needs the verification tool before finish.")
SYSTEM_PARENT_PARALLEL_V3 = SYSTEM_PARENT_PARALLEL_V2.replace(
    "Financial values and object IDs remain literal.",
    "Financial value cells and Fact/Evidence row IDs remain literal; metadata IDs decode exactly."
) + " In context v2 metadata, int=symbols[int], {\"l\":i}=list_table[i]; decode recursively to exact literals."


def _protocol_tools(version):
    if type(version) is not str or version not in PROTOCOL_VERSIONS:
        raise ValidationError("unknown dynamic action protocol version")
    # New protocols recognize all registered dynamic names so a known but hidden
    # tool is an authorization violation, including attempted recursive delegation.
    if version == LEGACY_VERSION:
        return LEGACY_TOOLS
    if version in {"dynamic-parent-domains-v1", "dynamic-parent-domains-v2", "market-child-v1", *PARALLEL_VERSIONS,
                   *CHILD_PROGRESS_VERSIONS}:
        return LEGACY_TOOLS | {FINANCIAL_CHILD_TOOL, MARKET_CHILD_TOOL}
    return LEGACY_TOOLS | {FINANCIAL_CHILD_TOOL}


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValidationError("duplicate dynamic action key")
        value[key] = item
    return value


def _reject_number(_):
    raise ValidationError("dynamic actions cannot contain numeric values")


def _plan(value):
    if (type(value) is not list or not 1 <= len(value) <= MAX_PLAN_ITEMS
            or any(type(item) is not str or not item.strip()
                   or not 1 <= text_bytes(item) <= MAX_PLAN_ITEM_BYTES for item in value)):
        raise ValidationError("invalid bounded dynamic plan")
    return list(value)


def _tool_names(value, *, version=LEGACY_VERSION):
    known = _protocol_tools(version)
    try:
        items = frozenset(value)
    except TypeError:
        raise ValidationError("invalid dynamic tool references") from None
    if isinstance(value, str) or not items <= known:
        raise ValidationError("unknown dynamic tool reference")
    return items


def parse_action(content, available_tools, completed_tools, *, version=LEGACY_VERSION,
                 context_catalog_ref=None, context_known_refs=()):
    """Validate one decision against effective grants and current typed references.

    Permission errors are distinct from correctable formatting/dependency errors,
    allowing the Runtime to stop immediately on an authorization violation.
    """
    if not 1 <= text_bytes(content) <= MAX_ACTION_BYTES:
        raise ValidationError("dynamic action exceeds byte budget")
    known = _protocol_tools(version)
    available, completed = (_tool_names(available_tools, version=version),
                            _tool_names(completed_tools, version=version))
    try:
        action = json.loads(content, object_pairs_hook=_unique_object,
                            parse_int=_reject_number, parse_float=_reject_number,
                            parse_constant=_reject_number)
    except (json.JSONDecodeError, RecursionError):
        raise ValidationError("dynamic action must be strict JSON") from None
    if type(action) is not dict or type(action.get("action")) is not str:
        raise ValidationError("invalid dynamic action object")
    kind = action["action"]
    if kind == "parallel":
        if (version not in PARALLEL_VERSIONS or set(action) != {"action", "tools", "plan"}
                or type(action["tools"]) is not list or len(action["tools"]) != 2
                or any(type(tool) is not str for tool in action["tools"])
                or set(action["tools"]) != AGENT_TOOLS):
            raise ValidationError("parallel action requires the two independent domain AgentTools")
        if not AGENT_TOOLS <= available:
            raise PermissionDenied("parallel domain delegation is not authorized")
        if completed & {"financial", "market", FINANCIAL_CHILD_TOOL, MARKET_CHILD_TOOL}:
            raise ValidationError("parallel branches cannot restart completed domain work")
        return {"action": kind, "tools": sorted(AGENT_TOOLS), "plan": _plan(action["plan"])}
    if kind == "disclose":
        if (version not in CONTEXT_VERSIONS or set(action) != {"action", "catalog_ref", "refs", "plan"}
                or not _hash(context_catalog_ref) or action["catalog_ref"] != context_catalog_ref
                or type(action["refs"]) is not list or not 1 <= len(action["refs"]) <= 16
                or any(type(ref) is not str for ref in action["refs"])
                or len(set(action["refs"])) != len(action["refs"])
                or not set(action["refs"]) <= set(context_known_refs)):
            raise ValidationError("disclosure must reference the current authorized context catalog")
        return {"action": kind, "catalog_ref": context_catalog_ref,
                "refs": sorted(action["refs"]), "plan": _plan(action["plan"])}
    if kind == "finish":
        if (set(action) != {"action", "reason", "plan"}
                or type(action["reason"]) is not str or action["reason"] not in FINISH_REASONS):
            raise ValidationError("invalid dynamic finish action")
        return {"action": kind, "reason": action["reason"], "plan": _plan(action["plan"])}
    if kind != "tool" or set(action) != {"action", "tool", "refs", "plan"}:
        raise ValidationError("invalid dynamic tool action")
    name, refs = action["tool"], action["refs"]
    if type(name) is not str or name not in known:
        raise ValidationError("unknown dynamic tool")
    if name not in available:
        raise PermissionDenied("dynamic tool is not authorized")
    if (type(refs) is not list or any(type(ref) is not str for ref in refs)
            or len(refs) != len(set(refs)) or not set(refs) <= completed):
        raise ValidationError("unknown or duplicate dynamic input reference")
    expected = (set() if name in SOURCE_TOOLS or name in {FINANCIAL_CHILD_TOOL, MARKET_CHILD_TOOL} else completed & SOURCE_TOOLS
                if name == "calculation" else {"calculation"} if name == "hypotheses"
                else {"hypotheses"})
    if set(refs) != expected or (name == "calculation" and not expected):
        raise ValidationError("dynamic input references differ from bound tool contract")
    return {"action": kind, "tool": name, "refs": sorted(refs), "plan": _plan(action["plan"])}


def validate_finish_rejection(rejection, declared_checks):
    """Validate trusted Runtime feedback, never accepted as a model action field."""
    if (type(rejection) is not dict or set(rejection) != {"code", "pending_checks"}
            or rejection["code"] != "required_checks_pending"
            or not isinstance(declared_checks, (list, tuple))
            or any(type(check) is not str for check in declared_checks)
            or len(declared_checks) != len(set(declared_checks))):
        raise ValidationError("invalid typed finish rejection")
    pending = rejection["pending_checks"]
    if (type(pending) is not list or not pending
            or any(type(check) is not str or check not in declared_checks for check in pending)
            or len(pending) != len(set(pending))):
        raise ValidationError("finish rejection contains undeclared or duplicate checks")
    return {"code": "required_checks_pending",
            "pending_checks": [check for check in declared_checks if check in pending]}


def validate_delegation_results(results):
    """Typed Runtime-owned routing feedback; source values stay in Observations."""
    if type(results) is not list or len(results) > 2:
        raise ValidationError("invalid bounded delegation results")
    domains = {FINANCIAL_CHILD_TOOL: "financial", MARKET_CHILD_TOOL: "market"}
    validated, seen = [], set()
    for result in results:
        if (type(result) is not dict or set(result) != {"tool", "domain", "status", "result_ref"}
                or type(result["tool"]) is not str or result["tool"] not in domains
                or result["tool"] in seen or result["domain"] != domains[result["tool"]]
                or type(result["status"]) is not str
                or result["status"] not in {"completed", "insufficient", "partial"}
                or not _hash(result["result_ref"])):
            raise ValidationError("invalid typed delegation result")
        seen.add(result["tool"])
        validated.append(dict(result))
    return validated


def _safe_gaps(gaps):
    # Source warnings can contain provider-controlled strings. Keep exact identity
    # locally and give the model a non-executable reference for unknown strings.
    result = []
    for item in gaps:
        if type(item) is not str:
            raise ValidationError("invalid typed Observation gap")
        parts = item.split(":")
        known = ((len(parts) == 2 and parts[0] == "source_gap_ref" and _hash(parts[1]))
                 or (len(parts) == 2 and parts[0] in DOMAINS and parts[1] in KNOWN_GAP_REASONS)
                 or (len(parts) == 3 and parts[0] in DOMAINS and parts[1] == "missing" and parts[2] in METRIC_NAMES)
                 or (len(parts) == 2 and parts[0] in {"revenue", "net_income_parent"}
                     and parts[1] in {"yoy_missing_or_nonpositive_base", "yoy_prior_year_period_not_visible"})
                 or (len(parts) == 3 and parts[:2] == ["financial_income", "absolute_profit_change"]
                     and parts[2] in {"no_visible_financial_period", "prior_year_same_period_not_visible",
                                      "net_income_parent_missing", "financial_unit_or_basis_mismatch"}))
        if known:
            result.append(item)
        else:
            result.append("source_gap_ref:" + digest(item))
    return sorted(set(result))


def _require(condition):
    if not condition:
        raise ValidationError("invalid typed Observation schema")


def _hash(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _number(value, *, nullable=False):
    if value is None:
        return nullable
    if type(value) is not str or not re.fullmatch(r"-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?", value):
        return False
    try:
        return Decimal(value).is_finite()
    except InvalidOperation:
        return False


def _date(value):
    if type(value) is not str:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _time(value, cutoff):
    if type(value) is not str:
        return False
    try:
        return aware(datetime.fromisoformat(value)) <= cutoff
    except (ValueError, ValidationError):
        return False


def _validate_observation(observation, request, *, version=LEGACY_VERSION):
    _protocol_tools(version)
    if (version in {"financial-child-v1", "financial-child-v2", "financial-child-v3"} and type(observation) is dict
            and observation.get("tool") in _protocol_tools(version)
            and observation.get("tool") != "financial"):
        raise PermissionDenied("Financial Child Observation exceeds delegated tools")
    if (version in {"market-child-v1", "market-child-v2", "market-child-v3"} and type(observation) is dict
            and observation.get("tool") in _protocol_tools(version)
            and observation.get("tool") != "market"):
        raise PermissionDenied("Market Child Observation exceeds delegated tools")
    allowed = {"source_read": {"tool", "kind", "status", "datasets", "gaps"},
               "derived": {"tool", "kind", "facts", "evidence", "hypotheses", "event_anchor", "gaps"},
               "verification": {"tool", "kind", "result"}}
    _require(type(observation) is dict and type(observation.get("kind")) is str
             and observation["kind"] in allowed and set(observation) == allowed[observation["kind"]]
             and type(observation.get("tool")) is str and observation["tool"] in DYNAMIC_TOOLS)
    tool, kind = observation["tool"], observation["kind"]
    if kind == "source_read":
        _require(tool in SOURCE_TOOLS and observation["status"] in {"available", "insufficient"}
                 and type(observation["datasets"]) is dict)
        bindings = {binding.dataset: binding for binding in request.bindings}
        for dataset, result in observation["datasets"].items():
            _require(type(result) is dict and DOMAINS.get(dataset) == tool and dataset in bindings
                     and set(result) == {"status", "records", "window", "periods", "source_result_ref"})
            binding = bindings[dataset]
            _require(result["status"] in {"available", "no_visible_data"}
                     and type(result["records"]) is int and 0 <= result["records"] <= 1000
                     and result["window"] == [binding.start.isoformat(), binding.end.isoformat()]
                     and type(result["periods"]) is list and len(result["periods"]) == result["records"]
                     and all(_date(period) and binding.start.isoformat() <= period <= binding.end.isoformat()
                             for period in result["periods"]) and _hash(result["source_result_ref"]))
    elif kind == "derived":
        _require(tool in {"calculation", "hypotheses"})
        facts, evidence, hypotheses = (observation[key] for key in ("facts", "evidence", "hypotheses"))
        _require(all(type(value) is dict for value in (facts, evidence, hypotheses)))
        for ref, value in facts.items():
            _require(type(ref) is str and re.fullmatch(r"F[1-9][0-9]*", ref) is not None
                     and type(value) is dict and set(value) == {"name", "value", "unit", "window", "formula", "available_at", "evidence_ids"})
            _require(value["name"] in FACT_NAMES and _number(value["value"]) and value["unit"] in UNITS
                     and type(value["window"]) is list and len(value["window"]) == 2
                     and all(_date(period) for period in value["window"])
                     and value["formula"] in FORMULA_VALUES and _time(value["available_at"], request.as_of)
                     and type(value["evidence_ids"]) is list and value["evidence_ids"]
                     and all(type(eid) is str and eid in evidence for eid in value["evidence_ids"]))
        for ref, value in evidence.items():
            _require(type(ref) is str and re.fullmatch(r"E[1-9][0-9]*", ref) is not None
                     and type(value) is dict and set(value) == {"metric", "value", "unit", "period", "basis", "available_at", "availability_basis", "source_version_ref"})
            _require(value["metric"] in METRIC_NAMES and _number(value["value"], nullable=True)
                     and value["unit"] in UNITS and _date(value["period"])
                     and value["basis"] in {*BASES.values(), *DOMAIN_BASES.values()}
                     and _time(value["available_at"], request.as_of)
                     and value["availability_basis"] in {"observed_at", "verified_release", "verified_release_date"}
                     and _hash(value["source_version_ref"]))
        for hid, value in hypotheses.items():
            _require(hid in request.hypotheses and type(value) is dict and set(value) == {
                "status", "reason", "conclusion_strength", "claim_ids", "counterevidence_claim_ids"})
            _require(value["status"] in {"supported", "unsupported", "conflicted", "insufficient"}
                     and type(value["reason"]) is str and re.fullmatch(r"[a-z_]{1,100}", value["reason"]) is not None
                     and value["conclusion_strength"] == "descriptive_test_only")
            for key in ("claim_ids", "counterevidence_claim_ids"):
                _require(type(value[key]) is list and all(type(cid) is str and cid in facts for cid in value[key]))
        anchor = observation["event_anchor"]
        _require(type(anchor) is dict and not set(anchor) - {"status", "reason", "precision", "boundary_date", "release_date", "disclosed_at", "available_at", "source_version_ref"})
        if anchor:
            _require(anchor.get("status") in {"verified", "insufficient"})
        for key, value in anchor.items():
            if key in {"boundary_date", "release_date"}:
                _require(_date(value))
            elif key in {"disclosed_at", "available_at"}:
                _require(_time(value, request.as_of))
            elif key == "source_version_ref":
                _require(_hash(value))
            elif key == "precision":
                _require(value in {"timestamp", "date_conservative_next_day"})
            elif key == "reason":
                _require(type(value) is str and re.fullmatch(r"[a-z_]{1,100}", value) is not None)
    else:
        result = observation["result"]
        _require(tool == "verification" and type(result) is dict and set(result) == {
            "status", "numeric_claims", "evidence_checked", "hypotheses_checked", "event_anchor_checked",
            "method", "provider_accuracy_certified", "causality_established"})
        _require(result["status"] == "verified"
                 and all(type(result[key]) is int and result[key] >= 0 for key in
                         ("numeric_claims", "evidence_checked", "hypotheses_checked"))
                 and type(result["event_anchor_checked"]) is bool
                 and result["method"] == "independent_fraction_arithmetic_and_pinned_source_binding"
                 and result["provider_accuracy_certified"] is False and result["causality_established"] is False)
    if "gaps" in observation:
        _require(type(observation["gaps"]) is list and _safe_gaps(observation["gaps"]) == observation["gaps"])


def _derived_view(output):
    facts, evidence = output.get("facts", []), output.get("evidence", {})
    aliases = {eid: f"E{i+1}" for i, eid in enumerate(sorted(evidence))}
    claim_aliases = {fact["id"]: f"F{i+1}" for i, fact in enumerate(facts)}
    view_facts = {
        claim_aliases[fact["id"]]: {
            **{key: fact[key] for key in ("name", "value", "unit", "window", "formula", "available_at")},
            "evidence_ids": [aliases[eid] for eid in fact["inputs"]]}
        for fact in facts}
    view_evidence = {
        aliases[eid]: {
            **{key: evidence[eid][key] for key in
               ("metric", "value", "unit", "period", "basis", "available_at", "availability_basis")},
            "source_version_ref": digest({key: evidence[eid][key] for key in
                ("provider", "provider_version", "revision_id", "snapshot", "record_id")})}
        for eid in sorted(evidence)}
    hypotheses = {
        hypothesis["id"]: {
            **{key: hypothesis[key] for key in ("status", "reason", "conclusion_strength")},
            "claim_ids": [claim_aliases[cid] for cid in hypothesis["claim_ids"]],
            "counterevidence_claim_ids": [claim_aliases[cid] for cid in hypothesis["counterevidence_claim_ids"]]}
        for hypothesis in output.get("hypotheses", [])}
    anchor = {key: output["event_anchor"][key] for key in
              ("status", "reason", "precision", "boundary_date", "release_date", "disclosed_at", "available_at")
              if key in output.get("event_anchor", {})}
    if "record_id" in output.get("event_anchor", {}):
        anchor["source_version_ref"] = digest({key: output["event_anchor"].get(key) for key in
                                              ("record_id", "snapshot", "revision_id", "provider")})
    return {"facts": view_facts, "evidence": view_evidence, "hypotheses": hypotheses,
            "event_anchor": anchor, "gaps": _safe_gaps(output.get("gaps", []))}


def observe_tool(tool, output, *, version=LEGACY_VERSION):
    """Build a source-text-free Observation from trusted local tool results.

    All rows/values and lineage remain in the local immutable result/Evidence store.
    Source reads expose completeness and exact periods. Derived reads expose every
    exact Claim/Evidence value without selecting highlights or trimming candidates.
    """
    _protocol_tools(version)
    if tool not in LEGACY_TOOLS or type(output) is not dict:
        raise ValidationError("invalid dynamic Observation tool or output")
    if tool in SOURCE_TOOLS:
        datasets, gaps = {}, []
        for dataset, result in sorted(output.items()):
            if DOMAINS.get(dataset) != tool:
                raise ValidationError("Observation dataset differs from bound source tool")
            rows = result["records"]
            datasets[dataset] = {"status": result["status"], "records": len(rows),
                                 "window": [result["start"], result["end"]],
                                 "periods": sorted(row["period"] for row in rows),
                                 "source_result_ref": digest(result)}
            if not rows:
                gaps.append(dataset + ":no_visible_records")
            gaps.extend(dataset + ":" + warning for warning in result.get("warnings", []))
        status = ("available" if datasets and all(d["status"] == "available" for d in datasets.values())
                  else "insufficient")
        return {"tool": tool, "kind": "source_read", "status": status,
                "datasets": datasets, "gaps": _safe_gaps(gaps)}
    if tool == "verification":
        keys = {"status", "numeric_claims", "evidence_checked", "hypotheses_checked",
                "event_anchor_checked", "method", "provider_accuracy_certified", "causality_established"}
        return {"tool": tool, "kind": "verification", "result": {key: output[key] for key in sorted(keys) if key in output}}
    try:
        return {"tool": tool, "kind": "derived", **_derived_view(output)}
    except (KeyError, TypeError, ValueError):
        raise ValidationError("invalid typed derived Observation") from None


def _child_progress(request, observations, declared_checks, tools, protocol_error, *, version):
    """Deterministic execution guidance; it neither executes nor certifies a read.

    Required read completion matches DynamicRuntime._check_results (a committed
    source output), while the finish candidate's reason matches _finish_child's
    separate nonempty/available source result criterion. Quality gaps stay exact.
    """
    domain = CHILD_PROGRESS_VERSIONS[version]
    read = next((observation for observation in observations if observation["tool"] == domain), None)
    completed = read is not None
    if completed and set(read["datasets"]) != {binding.dataset for binding in request.bindings}:
        raise ValidationError("child progress requires every delegated dataset result")
    available = completed and bool(read["datasets"]) and all(
        dataset["records"] > 0 and dataset["status"] == "available" for dataset in read["datasets"].values())
    pending = [] if completed else list(declared_checks)
    actions = ([{"action": "finish", "reason": "completed" if available else "insufficient",
                 "plan": ["The required " + domain + " read is done"]}] if completed else
               [{"action": "tool", "tool": domain, "refs": [],
                 "plan": ["Read bound " + domain + " evidence"]}] if domain in tools else [])
    gaps = list(read["gaps"]) if read else []
    progress = {
        "schema": "child-progress/v1", "domain": domain,
        "required_checks": [{"id": check, "status": "passed" if completed else "not_completed"}
                            for check in declared_checks],
        "execution": {"read_completed": completed, "pending_checks": pending, "can_finish": completed,
                      "completion_scope": "delegated_source_read"},
        "source_quality": {"coverage": "not_verified",
                           "historical_release": "not_verified" if any(
                               gap.endswith(":historical_release_not_verified") for gap in gaps) else "not_assessed",
                           "read_result_status": read["status"] if read else "not_read", "gaps": gaps},
        "legal_next_actions": actions,
    }
    if protocol_error == "duplicate_no_progress":
        progress["duplicate_feedback"] = {
            "code": "duplicate_no_progress", "tool": domain, "dispatched": False,
            "read_completed": completed, "next_actions": actions,
        }
    if version in CHILD_EXACT_RESPONSE_VERSIONS:
        contract = {"action": "finish" if completed else "tool",
                    "required_keys": ["action", "reason", "plan"] if completed else ["action", "tool", "refs", "plan"],
                    "forbidden_keys": ["tool", "refs"] if completed else ["reason"]}
        progress["response_contract"] = contract
        if protocol_error == "invalid_action":
            progress["invalid_action_feedback"] = {
                "code": "invalid_action", "response_contract": contract, "next_actions": actions,
            }
    return progress


def _parent_execution(observations, required_checks, tools, checks):
    """Small versioned feedback from Runtime revision checks, never a routing decision."""
    if checks is None:
        if observations:
            raise ValidationError("parent execution feedback requires authoritative revision checks")
        checks = [{"id": item, "status": "insufficient" if item.startswith("binding:") else "not_completed"}
                  for item in required_checks]
    if (type(checks) is not list or len(checks) != len(required_checks)
            or any(type(check) is not dict or set(check) != {"id", "status"}
                   or type(check["id"]) is not str or type(check["status"]) is not str
                   or check["id"] != item or check["status"] not in {"passed", "insufficient", "not_completed"}
                   for check, item in zip(checks, required_checks))):
        raise ValidationError("invalid authoritative parent execution checks")
    statuses = {check["id"]: check["status"] for check in checks}
    completed = {observation["tool"] for observation in observations}
    latest = next((o for o in observations if o["tool"] == "hypotheses"),
                  next((o for o in observations if o["tool"] == "calculation"), None))
    for item, status in statuses.items():
        if item.startswith("read:"):
            expected = "passed" if item[5:] in completed else "not_completed"
            if status != expected:
                raise ValidationError("parent read execution differs from current Observations")
        elif item.startswith("binding:"):
            if status != "insufficient":
                raise ValidationError("missing binding cannot become completed evidence")
        elif item in {"calculation", "hypotheses", "verification"}:
            if status == "insufficient" or status == "passed" and item not in completed:
                raise ValidationError("parent execution lacks its typed Observation")
            dependency = {"hypotheses": "calculation", "verification": "hypotheses"}.get(item)
            if status == "passed" and dependency and statuses[dependency] != "passed":
                raise ValidationError("parent execution has stale dependencies")
        else:
            result = latest["hypotheses"].get(item[11:]) if latest else None
            expected = ("not_completed" if result is None or statuses["calculation"] != "passed" else
                        "insufficient" if result["status"] == "insufficient" else "passed")
            if status != expected:
                raise ValidationError("hypothesis evidence status differs from current calculation")
    pending = [check["id"] for check in checks if check["status"] == "not_completed"]
    candidate = None
    if not any(item.startswith("read:") for item in pending):
        for stage in ("calculation", "hypotheses", "verification"):
            if stage not in pending:
                continue
            refs = (sorted(completed & SOURCE_TOOLS) if stage == "calculation" else
                    ["calculation"] if stage == "hypotheses" else ["hypotheses"])
            if stage in tools and refs and set(refs) <= completed:
                candidate = {"action": "tool", "tool": stage, "refs": refs, "plan": ["Complete required check"]}
            break
    return {"pending_checks": pending, "can_finish": not pending, "next_action": candidate}


def dynamic_messages(request, available_tools, observations, required_checks, plan,
                     max_bytes, *, decision=1, protocol_error=None,
                     version=LEGACY_VERSION, finish_rejection=None, delegation_results=None,
                     context_scope=None, context_run_id=None, context_refs=(), context_stage=None,
                     parent_execution_checks=None):
    """Return an exact outbound view; overflow never silently drops required facts.

    The Runtime supplies its current typed Observations, not unbounded chat history.
    Unknown Observation fields are rejected to prevent accidental source text or
    untrusted transport errors entering the model context.
    """
    if not isinstance(request, DynamicRequest) or type(max_bytes) is not int or max_bytes <= 0:
        raise ValidationError("invalid dynamic context request or budget")
    if version in CHILD_PROGRESS_VERSIONS:
        expected_request = FinancialRequest if CHILD_PROGRESS_VERSIONS[version] == "financial" else MarketRequest
        if not isinstance(request, expected_request):
            raise ValidationError("child progress protocol and delegated request must agree")
    tools = sorted(_tool_names(available_tools, version=version))
    if version in {"financial-child-v1", "financial-child-v2", "financial-child-v3"} and not set(tools) <= {"financial"}:
        raise PermissionDenied("Financial Child context contains undelegated tools")
    if version in {"market-child-v1", "market-child-v2", "market-child-v3"} and not set(tools) <= {"market"}:
        raise PermissionDenied("Market Child context contains undelegated tools")
    if type(decision) is not int or decision <= 0:
        raise ValidationError("invalid dynamic decision index")
    if not isinstance(observations, (list, tuple)) or len(observations) > 12:
        raise ValidationError("invalid bounded typed Observations")
    try:
        for observation in observations:
            _validate_observation(observation, request, version=version)
        if len({observation["tool"] for observation in observations}) != len(observations):
            raise ValidationError("dynamic context requires current unique tool Observations")
    except (KeyError, TypeError, ValueError):
        raise ValidationError("invalid typed Observation schema") from None
    if (not isinstance(required_checks, (list, tuple))
            or list(required_checks) != bound_required_checks(request)):
        raise ValidationError("invalid immutable dynamic required checks")
    control = {"question": request.question, "plan": _plan(plan) if plan else [], "decision": decision}
    if version in {"dynamic-parent-parallel-v2", "dynamic-parent-parallel-v3"}:
        control["execution"] = _parent_execution(observations, required_checks, tools, parent_execution_checks)
    elif parent_execution_checks is not None:
        raise ValidationError("legacy protocol has no parent execution feedback")
    if finish_rejection is not None:
        if version == LEGACY_VERSION:
            raise ValidationError("legacy dynamic protocol has no finish rejection feedback")
        control["finish_rejection"] = validate_finish_rejection(finish_rejection, required_checks)
    if protocol_error is not None:
        # Only Runtime-owned categories are accepted; never reflect response text.
        if protocol_error not in {"invalid_action", "duplicate_no_progress", "tool_failed", "dependency_not_ready"}:
            raise ValidationError("invalid dynamic protocol error category")
        control["previous_action_error"] = protocol_error
    # Calculation and hypothesis tools share the same current facts/Evidence. Send
    # those exact values once, with a view reference from both tool observations.
    # This is lossless state deduplication, not compression or candidate selection.
    derived = [observation for observation in observations if observation["kind"] == "derived"]
    latest = next((observation for observation in derived if observation["tool"] == "hypotheses"),
                  derived[0] if derived else None)
    derived_state = ({key: latest[key] for key in ("facts", "evidence", "hypotheses", "event_anchor")}
                     if latest else None)
    summaries = []
    for observation in observations:
        if observation["kind"] == "derived":
            if any(observation[key] != latest[key] for key in ("facts", "evidence", "event_anchor")):
                raise ValidationError("dynamic derived Observations have different source revisions")
            summaries.append({"tool": observation["tool"], "kind": "derived", "state_ref": "derived_state",
                              "result_ref": digest(observation), "gaps": observation["gaps"]})
        else:
            summaries.append(observation)
    payload = {"security": request.security.canonical_symbol, "cutoff": request.as_of.isoformat(),
               "pit_mode": request.mode.value, "objective": request.objective,
               "control": control, "required_checks": list(required_checks),
               "available_tools": tools, "completed_tools": sorted({o["tool"] for o in observations}),
               "bound_windows": {binding.dataset: [binding.start.isoformat(), binding.end.isoformat()]
                                 for binding in request.bindings},
               "observations": summaries, "derived_state": derived_state,
               "coverage": "not_verified", "causal_claim": False}
    if version != LEGACY_VERSION:
        payload["protocol_version"] = version
    if version in CHILD_PROGRESS_VERSIONS:
        payload["child_progress"] = _child_progress(request, observations, required_checks, tools,
                                                    protocol_error, version=version)
    if version in {"dynamic-parent-domains-v1", "dynamic-parent-domains-v2", *PARALLEL_VERSIONS}:
        payload["delegation_results"] = validate_delegation_results(
            [] if delegation_results is None else delegation_results)
    elif delegation_results is not None:
        raise ValidationError("dynamic protocol version has no delegation result feedback")
    if version in CONTEXT_VERSIONS:
        from .dynamic_context import build_catalog, view_catalog
        catalog = build_catalog(request, sorted(observations, key=lambda item: item["tool"]), list(required_checks),
                                scope=context_scope, run_id=context_run_id)
        stage = context_stage or context_next_stage(observations, required_checks)
        view = view_catalog(catalog, scope=context_scope, run_id=context_run_id,
                            refs=context_refs, current_stage=stage)
        if version == "dynamic-parent-parallel-v3":
            from .dynamic_context_metadata import encode_metadata_view
            view = encode_metadata_view(view)
        # Each control string is retained exactly once; compact JSON is reversible.
        payload = {"protocol_version": version, "control": control,
                   "available_tools": tools, "completed_tools": payload["completed_tools"],
                   "context": view, "delegation_results": payload["delegation_results"],
                   "coverage": "not_verified", "causal_claim": False}
    elif any(value is not None for value in (context_scope, context_run_id, context_stage)) or context_refs:
        raise ValidationError("legacy protocol has no lossless context catalog")
    system = {LEGACY_VERSION: SYSTEM, "single-dynamic-v2": SYSTEM_V2,
              "dynamic-parent-financial-v1": SYSTEM_PARENT_FINANCIAL,
              "financial-child-v1": SYSTEM_FINANCIAL_CHILD,
              "financial-child-v2": SYSTEM_FINANCIAL_CHILD_V2,
              "financial-child-v3": None,
              "dynamic-parent-domains-v1": SYSTEM_PARENT_DOMAINS,
              "dynamic-parent-domains-v2": SYSTEM_PARENT_CONTEXT,
              PARALLEL_VERSION: SYSTEM_PARENT_PARALLEL,
              "dynamic-parent-parallel-v2": SYSTEM_PARENT_PARALLEL_V2,
              "dynamic-parent-parallel-v3": SYSTEM_PARENT_PARALLEL_V3,
              "market-child-v1": SYSTEM_MARKET_CHILD,
              "market-child-v2": SYSTEM_MARKET_CHILD_V2,
              "market-child-v3": None}[version]
    if version in CHILD_EXACT_RESPONSE_VERSIONS:
        system = _exact_child_system(CHILD_PROGRESS_VERSIONS[version], payload["child_progress"])
    messages = [{"role": "system", "content": system}, {"role": "user", "content": canonical_json(payload)}]
    size = sum(text_bytes(message["content"]) for message in messages)
    if size > max_bytes:
        raise ValidationError("dynamic context exceeds lossless byte budget")
    facts = len(derived_state["facts"]) if derived_state else 0
    evidence = len(derived_state["evidence"]) if derived_state else 0
    metadata = {"strategy": "dynamic_typed_observation_view_no_source_text", "bytes": size,
                      "byte_budget": max_bytes, "message_sha256": digest(messages),
                      "facts_included": facts, "evidence_included": evidence,
                      "source_bodies_included": 0, "omitted_claims": 0}
    if version in CONTEXT_VERSIONS:
        from .dynamic_context import expand_view
        disclosed_refs = expand_view(view)["disclosed_refs"] if version == "dynamic-parent-parallel-v3" else view["disclosed_refs"]
        metadata.update(strategy="lossless_catalog_lazy_disclosure/v1", catalog_ref=catalog["catalog_ref"],
                        context_stage=stage, claims_preserved=facts, evidence_preserved=evidence,
                        evidence_included=len(view["evidence"]), evidence_details_disclosed=len(view["evidence"]),
                        observations_externalized=len(view["observations"]),
                        disclosed_refs=list(disclosed_refs))
        if version == "dynamic-parent-parallel-v3":
            metadata["strategy"] = "lossless_catalog_lazy_disclosure_metadata/v2"
    return messages, metadata


def context_next_stage(observations, required_checks):
    """Deterministic disclosure policy only; the model still chooses every action."""
    completed = {o["tool"] for o in observations}
    if any(check.startswith("read:") and check[5:] not in completed for check in required_checks):
        return "before_sources"
    for stage in ("calculation", "hypotheses", "verification"):
        if stage not in completed:
            return stage
    return "finish"
