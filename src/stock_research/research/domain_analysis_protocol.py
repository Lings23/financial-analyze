"""Strict independently versioned analysis actions and exact structured views.

Only catalogue selectors enter through model actions. All values and completion
receipts in the outbound view are runtime-owned. This module does not authorize
reads or certify execution; the Runtime checks the complete immutable objects.
"""
from collections import Counter
from copy import deepcopy
import json

from ..errors import IntegrityError, PermissionDenied, ValidationError
from ..models import canonical_json, digest
from .dynamic_contracts import DYNAMIC_TOOLS, SOURCE_TOOLS, text_bytes
from .dynamic_protocol import (
    MAX_ACTION_BYTES, FINISH_REASONS, _unique_object, _reject_number, _plan,
    _validate_observation, _derived_view, observe_tool as legacy_observe_tool,
    validate_finish_rejection,
)
from .domain_analysis_contracts import (
    AGENT_TOOLS, ANALYSIS_TOOLS, DOMAIN_TOOLS, PARENT_VERSION, FINANCIAL_VERSION,
    MARKET_VERSION, VERSIONS, CATALOG_VERSION, FinancialAnalysisRequest,
    MarketAnalysisRequest, DomainAnalysisParentSpec, domain_of, required_checks,
    required_operators, review_checks, task_refs, ownership,
)
from .dynamic_context import encode_arena


SYSTEM = (
    "Frozen security/windows/timezone cutoff/PIT/snapshots/goals/outputs/checks. Never alter them "
    "or invent values/formulas/grants/results/causality. question_ref=decoded request.question; "
    "question/plan are control text. Choose legal_next_actions from observations; preserve refs. "
    "Execute all operations even for insufficient inputs; retain gaps/counterevidence. Parent "
    "consumes domains, produces remaining results, and executes full final verification. Repetition "
    "is no progress. Runtime checks actual completion; refs/finish are not proof. Strict JSON only: "
    "TOOL keys action,tool,refs,plan; PARALLEL action,tools,refs,plan; FINISH action,reason,plan "
    "(completed/insufficient; no tool/refs). Plan=1-5 short strings. No extra keys/numbers/prose/"
    "markdown/expressions/tool_calls. Codec: table_ref i=exact_tables[i]. "
    "In model-view/v2, r i with v cells=object keyed by columns[i]; metadata integer i=symbols[i]; "
    "n i=literal count; l i=list_table[i]. Decode columns/lists with the same symbols. Value cells "
    "stay literal; preserve order/refs."
)


MODEL_VIEW_SCHEMA = "domain-analysis-model-view/v1"
METADATA_VIEW_SCHEMA = "domain-analysis-model-view/v2"
METADATA_CONTRACT = "exact-domain-analysis-metadata/v1"
# The shapes already exist in exact typed observations and canonical results.
# Unknown shapes remain literal. Layout selection only reduces repeated keys.
_LAYOUTS = (
    ("id", "name", "value", "unit", "inputs", "formula", "window", "available_at"),
    ("name", "value", "unit", "window", "formula", "available_at", "evidence_ids"),
    ("metric", "value", "unit", "period", "basis", "available_at", "availability_basis", "source_version_ref"),
    ("status", "reason", "conclusion_strength", "claim_ids", "counterevidence_claim_ids"),
    ("id", "title", "status", "reason", "required_evidence", "test_rule", "claim_ids",
     "counterevidence_claim_ids", "anchor_record_id", "conclusion_strength", "causal_claim", "coverage"),
    ("tool", "kind", "status", "datasets", "gaps"),
    ("tool", "kind", "facts", "evidence", "hypotheses", "event_anchor", "gaps"),
    ("tool", "kind", "result"),
    ("status", "records", "window", "periods", "source_result_ref"),
    ("dataset", "snapshot", "provider", "start", "end"),
    ("id", "status"),
    ("status", "domain", "numeric_claims", "evidence_checked", "hypotheses_checked", "method",
     "provider_accuracy_certified", "causality_established"),
    ("status", "numeric_claims", "evidence_checked", "hypotheses_checked", "event_anchor_checked", "method",
     "provider_accuracy_certified", "causality_established"),
    ("domain", "task_ref", "profile_id", "status", "input_revision", "request_ref", "spec_ref",
     "source_result_ref", "source_tool_call_id", "result_ref", "facts", "hypotheses", "gaps", "evidence_refs",
     "counterevidence_claim_ids", "computed_ref", "receipts_ref", "local_verification", "local_attestation_ref",
     "check_ownership_ref", "executed_operators"),
    ("domain", "task_ref", "profile_id", "status", "input_revision", "request_ref", "spec_ref",
     "source_result_ref", "source_tool_call_id", "result_ref", "facts", "hypotheses", "gaps", "evidence_refs",
     "counterevidence_claim_ids", "computed_ref", "receipts_ref", "local_verification", "local_attestation_ref",
     "check_ownership_ref", "executed_operators", "required_checks"),
    ("domain", "profile_id", "status", "result_ref", "facts", "hypotheses", "gaps", "evidence_refs",
     "counterevidence_claim_ids", "local_verification", "local_attestation_ref", "check_ownership_ref", "executed_operators"),
    ("domain", "profile_id", "status", "result_ref", "facts", "hypotheses", "gaps", "evidence_refs",
     "counterevidence_claim_ids", "local_verification", "local_attestation_ref", "check_ownership_ref", "executed_operators", "required_checks"),
    ("domain", "profile_id", "status", "result_ref", "facts", "hypotheses", "gaps", "evidence_refs",
     "local_verification", "local_attestation_ref", "check_ownership_ref", "executed_operators"),
    ("domain", "profile_id", "status", "result_ref", "facts", "hypotheses", "gaps", "evidence_refs",
     "local_verification", "local_attestation_ref", "check_ownership_ref", "executed_operators", "required_checks"),
)
_LAYOUT_BY_KEYS = {frozenset(columns): columns for columns in _LAYOUTS}


def _require(condition, message="invalid exact domain analysis metadata"):
    if not condition:
        raise ValidationError(message)


def _bytes(value):
    return text_bytes(canonical_json(value))


def _raw_model_view(view):
    _require(type(view) is dict and view.get("schema") == MODEL_VIEW_SCHEMA)
    encode_arena(view)  # Reuse the exact JSON/Unicode/depth/node/cycle bounds.
    def validate(value):
        if type(value) is dict:
            _require(set(value) not in ({"s"}, {"n"}, {"l"}, {"r", "v"}), "literal view collides with metadata reference shapes")
            for child in value.values():
                validate(child)
        elif type(value) is list:
            for child in value:
                validate(child)
    validate(view)


def _records(value, found):
    if type(value) is dict:
        columns = _LAYOUT_BY_KEYS.get(frozenset(value))
        if columns is not None:
            found.setdefault(columns, []).append(value)
        for key, child in value.items():
            if key != "value":
                _records(child, found)
    elif type(value) is list:
        for child in value:
            _records(child, found)


def _choose_columns(view):
    found = {}
    _records(view, found)
    candidates = sorted((columns for columns, rows in found.items() if len(rows) >= 2),
                        key=lambda columns: canonical_json(list(columns)))
    while True:
        profitable = [columns for index, columns in enumerate(candidates)
            if sum(_bytes(row) - _bytes({"r": index, "v": [row[key] for key in columns]})
                   for row in found[columns]) > _bytes(list(columns)) + 1]
        if profitable == candidates:
            return candidates
        candidates = profitable


def _pack_rows(value, indexes):
    if type(value) is dict:
        columns = _LAYOUT_BY_KEYS.get(frozenset(value))
        if columns in indexes:
            return {"r": indexes[columns], "v": [deepcopy(value[key]) if key == "value"
                    else _pack_rows(value[key], indexes) for key in columns]}
        return {key: deepcopy(child) if key == "value" else _pack_rows(child, indexes)
                for key, child in value.items()}
    if type(value) is list:
        return [_pack_rows(child, indexes) for child in value]
    return deepcopy(value)


def _list_eligible(value):
    if type(value) is list:
        return all(_list_eligible(child) for child in value)
    if type(value) is dict:
        return set(value) == {"n"} and type(value["n"]) is int
    return value is None or type(value) in {str, int, bool}


def _walk_metadata(value, columns, string=lambda value: value, sequence=lambda value: value,
                   integer=lambda value: value):
    if type(value) is str:
        return string(value)
    if type(value) is dict:
        if set(value) == {"r", "v"}:
            return {"r": value["r"], "v": [deepcopy(child) if key == "value"
                else _walk_metadata(child, columns, string, sequence, integer)
                for key, child in zip(columns[value["r"]], value["v"])]}
        return {key: deepcopy(child) if key == "value" else _walk_metadata(child, columns, string, sequence, integer)
                for key, child in value.items()}
    if type(value) is list:
        transformed = [_walk_metadata(child, columns, string, sequence, integer) for child in value]
        return sequence(transformed) if _list_eligible(transformed) else transformed
    if type(value) is int:
        return integer(value)
    return deepcopy(value)


def encode_model_view(view):
    """Losslessly compress the exact projection; original value cells stay literal."""
    _raw_model_view(view)
    columns = _choose_columns(view)
    packed = _pack_rows(view, {keys: index for index, keys in enumerate(columns)})
    counts = Counter()
    def count_string(value):
        counts[value] += 1
        return value
    _walk_metadata(packed, columns, count_string)
    counts.update(key for keys in columns for key in keys)
    symbols = sorted(value for value, count in counts.items() if count >= 2)
    while True:
        selected = [value for index, value in enumerate(symbols)
            if counts[value] * _bytes(value) > counts[value] * _bytes(index) + _bytes(value) + 1]
        if selected == symbols:
            break
        symbols = selected
    symbol_indexes = {value: index for index, value in enumerate(symbols)}
    symbolic = _walk_metadata(packed, columns,
        lambda value: symbol_indexes[value] if value in symbol_indexes else value,
        integer=lambda value: {"n": value})
    list_counts, lists = Counter(), {}
    def count_list(value):
        key = canonical_json(value)
        list_counts[key] += 1
        lists[key] = value
        return value
    _walk_metadata(symbolic, columns, sequence=count_list)
    list_keys = sorted(key for key, count in list_counts.items() if count >= 2)
    while True:
        selected = [key for index, key in enumerate(list_keys)
            if list_counts[key] * _bytes(lists[key]) > list_counts[key] * _bytes({"l": index}) + _bytes(lists[key]) + 1]
        if selected == list_keys:
            break
        list_keys = selected
    list_indexes = {key: index for index, key in enumerate(list_keys)}
    coded = _walk_metadata(symbolic, columns, sequence=lambda value:
        {"l": list_indexes[canonical_json(value)]} if canonical_json(value) in list_indexes else value)
    wrapper = {"schema": METADATA_VIEW_SCHEMA, "metadata_schema": METADATA_CONTRACT,
               "symbols": symbols, "list_table": [deepcopy(lists[key]) for key in list_keys],
               "columns": [[symbol_indexes[key] if key in symbol_indexes else key for key in keys]
                           for keys in columns], "view": coded, "view_ref": digest(view)}
    return wrapper if _bytes(wrapper) < _bytes(view) else deepcopy(view)


def decode_model_view(wire):
    """Recover exactly every original field and reject noncanonical or tampered refs."""
    if type(wire) is dict and wire.get("schema") == MODEL_VIEW_SCHEMA:
        _raw_model_view(wire)
        return deepcopy(wire)
    _require(type(wire) is dict and set(wire) == {"schema", "metadata_schema", "symbols", "list_table", "columns", "view", "view_ref"}
             and wire.get("schema") == METADATA_VIEW_SCHEMA and wire.get("metadata_schema") == METADATA_CONTRACT)
    encode_arena(wire)
    symbols, list_table = wire["symbols"], wire["list_table"]
    _require(type(symbols) is list and all(type(value) is str for value in symbols)
             and symbols == sorted(set(symbols)) and type(list_table) is list and type(wire["columns"]) is list)
    def symbol(value):
        if type(value) is int:
            _require(0 <= value < len(symbols), "dangling analysis metadata symbol")
            return symbols[value]
        _require(type(value) is str, "invalid exact analysis column")
        return value
    columns = []
    for row in wire["columns"]:
        _require(type(row) is list)
        keys = tuple(symbol(key) for key in row)
        _require(keys in _LAYOUTS and keys not in columns, "unknown or duplicate exact analysis column layout")
        columns.append(keys)
    def restore(value, depth=0, list_allowed=True):
        _require(depth <= 32, "analysis metadata exceeds structural depth")
        if type(value) is dict:
            if set(value) == {"n"}:
                _require(type(value["n"]) is int, "invalid literal analysis metadata count")
                return value["n"]
            if set(value) == {"l"}:
                index = value["l"]
                _require(list_allowed and type(index) is int and 0 <= index < len(list_table),
                         "dangling or recursive analysis metadata list")
                _require(type(list_table[index]) is list, "exact metadata list must remain a list")
                return restore(list_table[index], depth + 1, False)
            if set(value) == {"r", "v"}:
                index, cells = value["r"], value["v"]
                _require(type(index) is int and 0 <= index < len(columns) and type(cells) is list
                         and len(cells) == len(columns[index]), "invalid exact analysis row")
                return {key: deepcopy(child) if key == "value" else restore(child, depth + 1, list_allowed)
                        for key, child in zip(columns[index], cells)}
            return {key: deepcopy(child) if key == "value" else restore(child, depth + 1, list_allowed)
                    for key, child in value.items()}
        if type(value) is list:
            return [restore(child, depth + 1, list_allowed) for child in value]
        if type(value) is int:
            return symbol(value)
        return deepcopy(value)
    raw = restore(wire["view"])
    _raw_model_view(raw)
    if digest(raw) != wire["view_ref"]:
        raise IntegrityError("analysis metadata differs from its complete literal view")
    _require(encode_model_view(raw) == wire, "noncanonical exact analysis metadata")
    return raw


def _version(request, state, spec, version=None):
    chosen = version or (spec.version if spec is not None else state.get("spec_version"))
    if chosen is None:
        chosen = (FINANCIAL_VERSION if isinstance(request, FinancialAnalysisRequest) else
                  MARKET_VERSION if isinstance(request, MarketAnalysisRequest) else PARENT_VERSION)
    if chosen not in VERSIONS:
        raise ValidationError("unknown domain analysis protocol")
    expected = (FINANCIAL_VERSION if isinstance(request, FinancialAnalysisRequest) else
                MARKET_VERSION if isinstance(request, MarketAnalysisRequest) else PARENT_VERSION)
    if chosen != expected:
        raise ValidationError("analysis request and protocol do not agree")
    return chosen


def _tools(value):
    if not isinstance(value, (list, tuple, set, frozenset, dict)):
        raise ValidationError("invalid analysis tool catalogue")
    names = list(value)
    if any(type(name) is not str or name not in ANALYSIS_TOOLS for name in names) or len(names) != len(set(names)):
        raise ValidationError("unknown or duplicate analysis tool")
    return set(names)


def _refs(value):
    if (type(value) is not list or any(type(ref) is not str for ref in value)
            or len(value) != len(set(value)) or len(value) > 16):
        raise ValidationError("unknown or duplicate analysis input reference")
    return set(value)


def _completed_operations(state, request):
    values = state.get("analysis_operations", [])
    if (type(values) is not list or any(type(v) is not str for v in values)
            or len(values) != len(set(values)) or not set(values) <= set(required_operators(request))):
        raise ValidationError("analysis operation state differs from frozen catalogue")
    return set(values)


def _review_refs(state, request):
    revision = state.get("calculated_revision")
    if type(revision) is not str or len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
        raise ValidationError("domain review requires a current calculated revision")
    return {"revision:" + revision, *("check:" + check for check in review_checks(request))}


def parse_action(content, available_tools, completed_tools, *, state=None, request=None,
                 spec=None, version=None):
    """Parse exactly the current frozen refs, without repairing model output."""
    state = state or {}
    chosen = _version(request, state, spec, version)
    if not 1 <= text_bytes(content) <= MAX_ACTION_BYTES:
        raise ValidationError("analysis action exceeds byte budget")
    available, completed = _tools(available_tools), _tools(completed_tools)
    try:
        action = json.loads(content, object_pairs_hook=_unique_object,
                            parse_int=_reject_number, parse_float=_reject_number,
                            parse_constant=_reject_number)
    except (json.JSONDecodeError, RecursionError):
        raise ValidationError("analysis action must be strict JSON") from None
    if type(action) is not dict or type(action.get("action")) is not str:
        raise ValidationError("invalid analysis action object")
    kind = action["action"]
    if kind == "finish":
        if (set(action) != {"action", "reason", "plan"}
                or type(action["reason"]) is not str or action["reason"] not in FINISH_REASONS):
            raise ValidationError("invalid analysis finish action")
        return {"action": "finish", "reason": action["reason"], "plan": _plan(action["plan"])}
    child = chosen != PARENT_VERSION
    if kind == "parallel":
        if (child or spec is None or spec.mode != "child" or spec.execution != "parallel"
                or set(action) != {"action", "tools", "refs", "plan"}
                or type(action["tools"]) is not list or len(action["tools"]) != 2
                or any(type(t) is not str for t in action["tools"]) or set(action["tools"]) != AGENT_TOOLS):
            raise ValidationError("parallel analysis requires the two frozen domain tasks")
        if not AGENT_TOOLS <= available:
            raise PermissionDenied("parallel analysis tasks are not authorized")
        expected = set(task_refs(request, profile_id=spec.profile_id).values())
        if len(expected) != 2 or _refs(action["refs"]) != expected or completed & {"financial", "market", *AGENT_TOOLS}:
            raise ValidationError("parallel tasks differ from frozen or completed domain work")
        return {"action": kind, "tools": sorted(AGENT_TOOLS), "refs": sorted(expected), "plan": _plan(action["plan"])}
    if kind != "tool" or set(action) != {"action", "tool", "refs", "plan"}:
        raise ValidationError("invalid analysis tool action")
    name = action["tool"]
    if type(name) is not str or name not in ANALYSIS_TOOLS:
        raise ValidationError("unknown analysis tool")
    if name not in available:
        raise PermissionDenied("analysis tool is not authorized")
    refs = _refs(action["refs"])
    if child:
        domain = domain_of(request)
        if name not in {domain, "calculation", "domain_review"}:
            raise PermissionDenied("analysis child cannot cross domains or spawn")
        if name == domain:
            expected = set()
        elif name == "calculation":
            operators = {"operator:" + op for op in required_operators(request)}
            if domain not in completed or domain not in refs or not refs - {domain} or not refs - {domain} <= operators:
                raise ValidationError("calculation requires the actual domain source and frozen operators")
            expected = refs
        else:
            if "calculation" not in completed or _completed_operations(state, request) != set(required_operators(request)):
                raise ValidationError("domain review requires all frozen domain operations")
            expected = _review_refs(state, request)
    elif name in AGENT_TOOLS | DOMAIN_TOOLS:
        if spec is None or name in AGENT_TOOLS and spec.mode != "child" or name in DOMAIN_TOOLS and spec.mode != "tool":
            raise ValidationError("domain task route differs from the frozen mode")
        if name in AGENT_TOOLS and spec.execution == "parallel" and AGENT_TOOLS <= available:
            raise ValidationError("the frozen two-domain parallel profile requires its atomic group")
        domain = "financial" if name.startswith("financial_") else "market"
        if domain in completed:
            raise ValidationError("domain result cannot be delegated again")
        expected = {task_refs(request, profile_id=spec.profile_id).get(domain)}
    elif name in SOURCE_TOOLS:
        expected = set()
    elif name == "calculation":
        expected = completed & SOURCE_TOOLS
        if not expected:
            raise ValidationError("Parent composition requires actual completed source inputs")
    elif name == "hypotheses":
        expected = {"calculation"}
        if not expected <= completed:
            raise ValidationError("hypotheses requires actual Parent composition")
    elif name == "verification":
        expected = {"hypotheses"}
        if not expected <= completed:
            raise ValidationError("verification requires actual Parent hypothesis aggregation")
    else:
        raise ValidationError("Parent cannot invoke child-local domain review")
    if refs != expected:
        raise ValidationError("analysis input references differ from current frozen contract")
    return {"action": "tool", "tool": name, "refs": sorted(refs), "plan": _plan(action["plan"])}


def observe_tool(tool, output, *, request=None):
    """Reuse exact source and numeric projections with an independent tool identity."""
    if tool == "domain_review":
        observed = legacy_observe_tool("hypotheses", output, version="single-dynamic-v2")
        observed["tool"] = tool
        return observed
    return legacy_observe_tool(tool, output, version="single-dynamic-v2")


def _validate_observations(observations, request):
    if type(observations) is not list or len(observations) > 12:
        raise ValidationError("invalid bounded analysis observations")
    if len({item.get("tool") for item in observations if type(item) is dict}) != len(observations):
        raise ValidationError("analysis observations must be current and unique")
    child = isinstance(request, (FinancialAnalysisRequest, MarketAnalysisRequest))
    for observed in observations:
        if type(observed) is not dict:
            raise ValidationError("invalid typed analysis observation")
        if child and observed.get("tool") not in {domain_of(request), "calculation", "domain_review"}:
            raise PermissionDenied("analysis observation exceeds the delegated domain")
        copied = deepcopy(observed)
        if copied.get("tool") == "domain_review":
            copied["tool"] = "hypotheses"
        _validate_observation(copied, request, version="single-dynamic-v2")


def _result_view(result):
    """Exact registered field projection; no generated summary or fact selection."""
    if type(result) is not dict:
        raise ValidationError("invalid Parent domain result")
    computed = result.get("computed", result.get("analysis"))
    if type(computed) is not dict:
        raise ValidationError("Parent domain result has no complete computed object")
    # All canonical Fact fields, all hypothesis statuses/reasons/counterevidence,
    # and every gap survive this projection. Full source/Evidence audit stays local.
    facts = deepcopy(computed.get("facts", []))
    evidence = computed.get("evidence", {})
    attestation = result.get("local_attestation")
    attestation_fields = {}
    if attestation is not None:
        _require(type(attestation) is dict, "invalid immutable local analysis attestation")
        expected = digest({key: value for key, value in attestation.items() if key != "attestation_ref"})
        if attestation.get("attestation_ref", expected) != expected:
            raise IntegrityError("model view local attestation receipt digest differs")
        if result.get("local_attestation_ref", expected) != expected:
            raise IntegrityError("model view local attestation differs from its immutable receipt")
        attestation_fields["local_attestation_ref"] = expected
        if "ownership_ref" in attestation:
            attestation_fields["check_ownership_ref"] = attestation["ownership_ref"]
    # Scope/Spec/task/source/receipt details stay in the complete immutable result
    # addressed by result_ref and authenticated by the exact local attestation.
    # Root request bindings and ownership are shown once in this same model view.
    return {**{k: deepcopy(result[k]) for k in ("domain", "profile_id", "status") if k in result},
            "result_ref": digest(result),
            "facts": facts, "hypotheses": deepcopy(computed.get("hypotheses", [])),
            "gaps": deepcopy(computed.get("gaps", [])), "evidence_refs": sorted(evidence),
            # Counterevidence stays in each complete canonical hypothesis. A
            # second aggregate cannot add information and repeats its references.
            "local_verification": deepcopy(result.get("local_verification", computed.get("local_verification"))),
            **attestation_fields,
            **{key: deepcopy(result[key]) for key in ("operations", "operation_ids", "executed_operators") if key in result},
            **({"child_execution_checks_ref": digest(result["required_checks"])} if "required_checks" in result else {})}


def _exact_observation_tables(observations):
    """Intern only repeated identical fields; all financial cells stay literal."""
    counts, values = {}, {}
    for observed in observations:
        for field in ("facts", "evidence", "hypotheses", "event_anchor", "gaps"):
            if field in observed:
                value = observed[field]
                key = canonical_json(value)
                if text_bytes(key) > 200:
                    counts[key] = counts.get(key, 0) + 1
                    values[key] = value
    keys = sorted(key for key in counts if counts[key] > 1)
    indexes = {key: i for i, key in enumerate(keys)}
    compact = deepcopy(observations)
    for observed in compact:
        for field in ("facts", "evidence", "hypotheses", "event_anchor", "gaps"):
            if field in observed and canonical_json(observed[field]) in indexes:
                observed[field] = {"table_ref": indexes[canonical_json(observed[field])]}
    return compact, [deepcopy(values[key]) for key in keys]


def expand_observation_tables(observations, exact_tables):
    """Restore the exact typed observations for wire and recovery verification."""
    if type(observations) is not list or type(exact_tables) is not list:
        raise ValidationError("invalid exact analysis observation tables")
    expanded = deepcopy(observations)
    for observed in expanded:
        if type(observed) is not dict:
            raise ValidationError("invalid exact analysis observation")
        for field in ("facts", "evidence", "hypotheses", "event_anchor", "gaps"):
            value = observed.get(field)
            if type(value) is dict and set(value) == {"table_ref"}:
                index = value["table_ref"]
                if type(index) is not int or not 0 <= index < len(exact_tables):
                    raise ValidationError("unknown exact analysis observation table reference")
                observed[field] = deepcopy(exact_tables[index])
    return expanded


def _legal_actions(state, request, available, spec):
    observations = state.get("observations", {})
    completed = set(observations)
    actions = []
    def add(name, refs, plan):
        if name in available:
            actions.append({"action": "tool", "tool": name, "refs": sorted(refs), "plan": [plan]})
    child = isinstance(request, (FinancialAnalysisRequest, MarketAnalysisRequest))
    if child:
        domain = domain_of(request)
        done = _completed_operations(state, request)
        needed = set(required_operators(request)) - done
        if domain not in completed:
            add(domain, [], "Read the authorized immutable domain source")
        elif needed:
            # Every required operation may be chosen individually or as one bounded
            # combination. Model selection changes ordering only, never the goal.
            add("calculation", {domain, *("operator:" + op for op in sorted(needed))}, "Compute every remaining required domain operator")
            if len(needed) > 1:
                for operator in required_operators(request):
                    if operator in needed:
                        add("calculation", [domain, "operator:" + operator], "Compute the selected required domain operator")
        elif "domain_review" not in completed or state.get("hypotheses_revision") != state.get("calculated_revision"):
            add("domain_review", _review_refs(state, request), "Run every domain check and independent local verification")
        else:
            actions.append({"action": "finish", "reason": "completed", "plan": ["Submit all locally verified domain results and retained gaps"]})
        return actions
    if spec is not None and spec.mode in {"tool", "child"}:
        task = task_refs(request, profile_id=spec.profile_id)
        names = AGENT_TOOLS if spec.mode == "child" else DOMAIN_TOOLS
        if (spec.mode == "child" and spec.execution == "parallel" and AGENT_TOOLS <= set(available)
                and not completed & {"financial", "market", *AGENT_TOOLS}):
            actions.append({"action": "parallel", "tools": sorted(AGENT_TOOLS), "refs": sorted(task.values()),
                            "plan": ["Analyze the two frozen independent domain tasks"]})
        serial_names = () if spec.mode == "child" and spec.execution == "parallel" and AGENT_TOOLS <= set(available) else sorted(names)
        for name in serial_names:
            domain = "financial" if name.startswith("financial_") else "market"
            if domain not in completed and domain in task:
                add(name, [task[domain]], "Execute the frozen " + domain + " analysis task")
    for name in sorted(set(available) & SOURCE_TOOLS):
        if name not in completed:
            add(name, [], "Read the authorized immutable source")
    source_revision = digest({"sources": state.get("outputs", {}), "domain_results": {
        domain: digest(result) for domain, result in sorted(state.get("domain_results", {}).items())}})
    calculated = ("calculation" in completed and state.get("calculated_revision") == source_revision)
    hypotheses = (calculated and "hypotheses" in completed
                  and state.get("hypotheses_revision") == state.get("calculated_revision"))
    verified = (hypotheses and "verification" in completed
                and state.get("verified_revision") == state.get("hypotheses_revision"))
    reads_ready = all(check[5:] in completed for check in required_checks(request) if check.startswith("read:"))
    if completed & SOURCE_TOOLS and reads_ready and not calculated:
        add("calculation", completed & SOURCE_TOOLS, "Consume accepted domain results and compose remaining canonical results")
    if calculated and not hypotheses:
        add("hypotheses", ["calculation"], "Consume domain checks and execute all remaining root checks")
    if hypotheses and not verified:
        add("verification", ["hypotheses"], "Execute the full independent root verification")
    if verified:
        actions.append({"action": "finish", "reason": "completed", "plan": ["Finish the fully verified frozen root task"]})
    return actions


def messages(state, request, available, max_bytes, *, spec=None, decision=None):
    """Prepare exact bounded model view; over-limit content is returned for typed stop.

    Runtime measures the metadata and stops before dispatch at >12000 bytes. No
    values, required checks or legal gaps are trimmed to make a view fit.
    """
    if type(state) is not dict or type(max_bytes) is not int or not 1 <= max_bytes <= 12000:
        raise ValidationError("invalid analysis context state or byte cap")
    version = _version(request, state, spec)
    tools = sorted(_tools(available))
    child = version != PARENT_VERSION
    if child and not set(tools) <= {domain_of(request), "calculation", "domain_review"}:
        raise PermissionDenied("analysis child context cannot widen delegated tools")
    observations = [value for _, value in sorted(state.get("observations", {}).items())]
    _validate_observations(observations, request)
    checks = required_checks(request)
    if "requirements" in state and state["requirements"] != checks:
        raise ValidationError("analysis context requirements differ from frozen goal")
    turn = decision if decision is not None else state.get("model_attempts", 0) + 1
    if type(turn) is not int or turn < 1:
        raise ValidationError("invalid analysis decision number")
    plans = state.get("plans", [])
    plan = plans[-1].get("steps", []) if plans else []
    control = {"question_ref": "analysis_context.request.question", "plan": _plan(plan) if plan else [], "decision": turn,
               "legal_next_actions": _legal_actions(state, request, tools, spec),
               "execution": {"calculated_revision": state.get("calculated_revision"),
                             "reviewed_revision": state.get("hypotheses_revision"),
                             "verified_revision": state.get("verified_revision")}}
    if spec is not None and not child:
        control["route"] = {"mode": spec.mode, "execution": spec.execution, "profile_id": spec.profile_id}
    if child:
        control["execution"]["completed_operators"] = sorted(_completed_operations(state, request))
    if state.get("finish_rejection") is not None:
        control["finish_rejection"] = validate_finish_rejection(state["finish_rejection"], checks)
    error = state.get("protocol_error")
    if error is not None:
        if error not in {"invalid_action", "duplicate_no_progress", "tool_failed", "dependency_not_ready"}:
            raise ValidationError("invalid analysis protocol error category")
        control["previous_action_error"] = error
    compact_observations, exact_tables = _exact_observation_tables(observations)
    context = {"schema": "domain-analysis-model-view/v1", "request": request.to_dict(),
               "required_checks": checks, "observations": compact_observations, "exact_tables": exact_tables,
               "catalog_version": CATALOG_VERSION}
    if child:
        context["operators"] = ["operator:" + op for op in required_operators(request)]
        context["review_checks"] = ["check:" + check for check in review_checks(request)]
    else:
        context["tasks"] = task_refs(request, profile_id=spec.profile_id if spec else "core/v1")
        context["accepted_domain_results"] = [_result_view(result) for _, result in sorted(state.get("domain_results", {}).items())]
        context["ownership"] = deepcopy(state.get("analysis_ownership", ownership(request)))
        context["ownership_ref"] = digest(context["ownership"])
    encoded_context = encode_model_view(context)
    literal_payload = {"protocol_version": version, "available_tools": tools,
                       "analysis_context": context, "control": control}
    wire = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": canonical_json({"protocol_version": version,
                 "available_tools": tools, "analysis_context": encoded_context, "control": control})}]
    metadata = {"bytes": sum(text_bytes(message["content"]) for message in wire),
                "message_sha256": digest(wire), "schema": encoded_context["schema"],
                "model_view_ref": digest(context), "literal_bytes": text_bytes(SYSTEM) + _bytes(literal_payload)}
    return wire, metadata


analysis_messages = messages
