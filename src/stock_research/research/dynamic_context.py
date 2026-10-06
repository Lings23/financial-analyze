"""Deterministic, run-bound storage and lazy views of exact typed Observations.

The catalogue retains every original field; its model view is a column encoding,
not a summary or a financial fact producer. Callers must first authorize/revalidate
the reads and persist this catalogue in their versioned checkpoint. The pure
functions here do not authorize data reads or maintain a shared cache.
"""
from copy import deepcopy
from datetime import date, datetime
import re

from ..errors import IntegrityError, PermissionDenied, ValidationError
from ..models import PITMode, Security, canonical_json, digest
from .contracts import Binding
from .dynamic_contracts import (
    DynamicRequest, FinancialRequest, MarketRequest, required_checks as bound_checks,
)


CATALOG_SCHEMA = "dynamic-context-catalog/v1"
VIEW_SCHEMA = "dynamic-context-view/v1"
ARENA_SCHEMA = "dynamic-context-arena/v1"
MAX_REFS = 16
MAX_CATALOG_BYTES = 4_000_000
MAX_ARENA_NODES = 200_000
MAX_ARENA_DEPTH = 32
STAGES = frozenset({"before_sources", "calculation", "hypotheses", "verification", "finish"})

FACT_COLUMNS = ("ref", "name", "value", "unit", "window", "formula", "available_at", "evidence_ids")
EVIDENCE_COLUMNS = ("ref", "metric", "value", "unit", "period", "basis", "available_at",
                    "availability_basis", "source_version_ref")
HYPOTHESIS_COLUMNS = ("ref", "status", "reason", "conclusion_strength", "claim_ids",
                      "counterevidence_claim_ids")
SOURCE_COLUMNS = ("observation_ref", "dataset", "status", "records", "periods", "source_result_ref")
OBSERVATION_COLUMNS = ("ref", "kind", "sha256", "status", "claim_ids", "evidence_ids", "hypothesis_ids")
GAP_COLUMNS = ("observation_ref", "gap_indices")
_VIEW_KEYS = frozenset({"schema", "catalog_ref", "binding_ref", "range", "required_checks", "catalog_ids",
                       "columns", "facts", "hypotheses", "evidence", "observations", "source_datasets",
                       "gaps", "gap_table", "symbols", "stage", "requested_refs", "event_anchor",
                       "verification", "disclosed_refs", "coverage", "causal_claim"})

# Only determines which already-existing Claim inputs to disclose before the
# hypothesis tool runs. This neither computes tests nor changes their rules.
HYPOTHESIS_FACT_NAMES = {
    "mechanical_adjustment": frozenset({"observed_price_change", "factor_adjusted_price_change"}),
    "market_direction": frozenset({"observed_price_change", "benchmark_price_change"}),
    "financial_deterioration": frozenset({"revenue_yoy", "net_income_parent_yoy"}),
    "cashflow_divergence": frozenset({"financial_income.net_income_parent", "financial_cashflow.operating_cashflow"}),
    "event_chronology": frozenset({"event_observed_price_change"}),
    "absolute_profit_change": frozenset({"financial_income.absolute_profit_change"}),
}


def _require(condition, message="invalid deterministic context catalogue"):
    if not condition:
        raise ValidationError(message)


def _hash(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _binding(scope, run_id):
    try:
        _require(type(scope) is str and bool(scope.strip()) and len(scope.encode("utf-8")) <= 512
                 and all(character.isprintable() for character in scope), "invalid catalogue scope")
    except UnicodeError:
        raise ValidationError("invalid Unicode in catalogue scope") from None
    _require(type(run_id) is str and re.fullmatch(r"[0-9a-f]{32}", run_id) is not None,
             "invalid catalogue run ID")


def encode_arena(value):
    """Encode JSON exactly using one deterministic string intern table.

    Strings, dictionaries and lists have distinct tags. None/bools/integers remain
    exact scalars; floats are rejected (financial decimal values must be strings).
    No dictionary key, list order, null or empty collection is discarded.
    """
    strings, count, active = set(), [0], set()

    def scan(item, depth):
        count[0] += 1
        _require(depth <= MAX_ARENA_DEPTH and count[0] <= MAX_ARENA_NODES,
                 "context arena exceeds structural budget")
        if item is None or type(item) in {bool, int}:
            return
        if type(item) is str:
            try:
                item.encode("utf-8")
            except UnicodeError:
                raise ValidationError("invalid Unicode in context arena") from None
            strings.add(item)
            return
        _require(type(item) in {dict, list}, "context arena requires exact JSON types")
        _require(id(item) not in active, "cyclic context arena")
        active.add(id(item))
        if type(item) is dict:
            _require(all(type(key) is str for key in item), "context object keys must be text")
            for key, child in item.items():
                scan(key, depth + 1)
                scan(child, depth + 1)
        else:
            for child in item:
                scan(child, depth + 1)
        active.remove(id(item))

    scan(value, 0)
    table = sorted(strings)
    aliases = {text: index for index, text in enumerate(table)}

    def pack(item):
        if type(item) is str:
            return ["s", aliases[item]]
        if type(item) is dict:
            return ["d", [[aliases[key], pack(item[key])] for key in sorted(item)]]
        if type(item) is list:
            return ["l", [pack(child) for child in item]]
        return item

    arena = {"schema": ARENA_SCHEMA, "strings": table, "value": pack(value)}
    try:
        _require(len(canonical_json(arena).encode("utf-8")) <= MAX_CATALOG_BYTES,
                 "context arena exceeds storage byte budget")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("invalid context arena serialization") from None
    return arena


def decode_arena(arena):
    """Decode a strict canonical arena; malformed/dangling aliases are rejected."""
    _require(type(arena) is dict and set(arena) == {"schema", "strings", "value"}
             and arena["schema"] == ARENA_SCHEMA)
    table = arena["strings"]
    _require(type(table) is list and all(type(text) is str for text in table))
    try:
        _require(table == sorted(set(table)))
        _require(len(canonical_json(arena).encode("utf-8")) <= MAX_CATALOG_BYTES,
                 "context arena exceeds storage byte budget")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("invalid context arena serialization") from None
    count = [0]

    def index(alias):
        _require(type(alias) is int and 0 <= alias < len(table), "dangling context string reference")
        return table[alias]

    def unpack(item, depth):
        count[0] += 1
        _require(depth <= MAX_ARENA_DEPTH and count[0] <= MAX_ARENA_NODES,
                 "context arena exceeds structural budget")
        if item is None or type(item) in {bool, int}:
            return item
        _require(type(item) is list and len(item) == 2 and type(item[0]) is str,
                 "invalid context arena node")
        tag, contents = item
        if tag == "s":
            return index(contents)
        _require(tag in {"l", "d"} and type(contents) is list, "invalid context arena node")
        if tag == "l":
            return [unpack(child, depth + 1) for child in contents]
        result = {}
        for pair in contents:
            _require(type(pair) is list and len(pair) == 2, "invalid context object pair")
            key = index(pair[0])
            _require(key not in result, "duplicate context object key")
            result[key] = unpack(pair[1], depth + 1)
        return result

    value = unpack(arena["value"], 0)
    _require(encode_arena(value) == arena, "noncanonical context arena")
    return value


def _restore_request(value):
    """Restore parent and application-created source Child requests exactly."""
    _require(type(value) is dict)
    try:
        objective = value["objective"]
        cls = (FinancialRequest if objective == "financial_evidence" else
               MarketRequest if objective == "market_evidence" else DynamicRequest)
        bindings = tuple(Binding(item["dataset"], item["snapshot"], item["provider"],
                                 date.fromisoformat(item["start"]), date.fromisoformat(item["end"]))
                         for item in value["bindings"])
        _require(all(set(item) == {"dataset", "snapshot", "provider", "start", "end"}
                     for item in value["bindings"]))
        request = cls(Security(value["symbol"], value["exchange"]), datetime.fromisoformat(value["as_of"]),
                      PITMode(value["mode"]), bindings, value.get("benchmark"), objective,
                      tuple(value["hypotheses"]), value.get("event_record_id"),
                      value.get("hypothesis_version"), value["question"])
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise ValidationError("invalid catalogue request") from None
    _require(request.to_dict() == value, "catalogue request lost or added fields")
    return request


def _validate_payload(payload):
    _require(type(payload) is dict and set(payload) == {"request", "observations", "required_checks"})
    request = _restore_request(payload["request"])
    observations = payload["observations"]
    _require(type(observations) is list and len(observations) <= 12)
    # A local import avoids an import cycle when the action protocol uses this codec.
    # The Runtime validates first too; the codec rechecks after restoring a catalogue.
    from .dynamic_protocol import _validate_observation
    version = ("financial-child-v1" if isinstance(request, FinancialRequest) else
               "market-child-v1" if isinstance(request, MarketRequest) else "dynamic-parent-domains-v1")
    try:
        for observation in observations:
            _validate_observation(observation, request, version=version)
        _require(len({item["tool"] for item in observations}) == len(observations))
    except (KeyError, TypeError, ValueError):
        raise ValidationError("invalid catalogue typed Observations") from None
    _require(type(payload["required_checks"]) is list and payload["required_checks"] == bound_checks(request),
             "catalogue immutable required checks differ")
    derived = [item for item in observations if item["kind"] == "derived"]
    if derived:
        latest = next((item for item in derived if item["tool"] == "hypotheses"), derived[0])
        _require(all(all(item[key] == latest[key] for key in ("facts", "evidence", "event_anchor"))
                     for item in derived), "catalogue derived source revisions differ")
        for item in derived:
            _require(all(hid in latest["hypotheses"] and value == latest["hypotheses"][hid]
                         for hid, value in item["hypotheses"].items()),
                     "catalogue hypothesis source revisions differ")
    return request


def _index(payload):
    result = {}
    for position, observation in enumerate(payload["observations"]):
        base = ["observations", position]
        result["O:" + observation["tool"]] = {"path": base, "sha256": digest(observation)}
        if observation["kind"] != "derived":
            continue
        for key, prefix in (("facts", "C:"), ("evidence", "E:"), ("hypotheses", "H:")):
            for alias, value in observation[key].items():
                ref = prefix + alias
                if ref in result:
                    _require(result[ref]["sha256"] == digest(value), "inconsistent catalogue reference value")
                else:
                    result[ref] = {"path": base + [key, alias], "sha256": digest(value)}
    return {key: result[key] for key in sorted(result)}


def build_catalog(request, observations, required_checks, *, scope, run_id):
    """Return a fresh complete catalogue bound to one trusted scope/run/request."""
    _binding(scope, run_id)
    _require(isinstance(request, DynamicRequest) and type(observations) in {list, tuple}
             and type(required_checks) in {list, tuple})
    payload = {"request": request.to_dict(), "observations": deepcopy(list(observations)),
               "required_checks": list(required_checks)}
    _validate_payload(payload)
    body = {"schema": CATALOG_SCHEMA, "scope": scope, "run_id": run_id,
            "request_ref": digest(payload["request"]), "arena": encode_arena(payload), "index": _index(payload)}
    _require(len(canonical_json(body).encode("utf-8")) <= MAX_CATALOG_BYTES,
             "context catalogue exceeds storage byte budget")
    return {**body, "catalog_ref": digest(body)}


def _checked_catalog(catalog, *, scope, run_id, catalog_ref=None):
    _binding(scope, run_id)
    _require(type(catalog) is dict and set(catalog) == {
        "schema", "scope", "run_id", "request_ref", "arena", "index", "catalog_ref"}
        and catalog["schema"] == CATALOG_SCHEMA)
    if catalog["scope"] != scope or catalog["run_id"] != run_id:
        raise PermissionDenied("context catalogue belongs to a different scope or run")
    if catalog_ref is not None:
        _require(_hash(catalog_ref), "invalid expected catalogue hash")
        if catalog_ref != catalog["catalog_ref"]:
            raise PermissionDenied("context reference belongs to a different catalogue")
    _require(_hash(catalog["catalog_ref"]) and _hash(catalog["request_ref"]))
    try:
        body = {key: value for key, value in catalog.items() if key != "catalog_ref"}
        _require(len(canonical_json(body).encode("utf-8")) <= MAX_CATALOG_BYTES,
                 "context catalogue exceeds storage byte budget")
        if digest(body) != catalog["catalog_ref"]:
            raise IntegrityError("context catalogue hash changed")
        payload = decode_arena(catalog["arena"])
        request = _validate_payload(payload)
        if digest(payload["request"]) != catalog["request_ref"] or _index(payload) != catalog["index"]:
            raise IntegrityError("context catalogue request or reference index changed")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("invalid context catalogue serialization") from None
    return request, payload


def validate_catalog(catalog, *, scope, run_id, catalog_ref=None):
    """Validate storage/hash/schema bindings, without asserting source authorization."""
    _, payload = _checked_catalog(catalog, scope=scope, run_id=run_id, catalog_ref=catalog_ref)
    return {"catalog_ref": catalog["catalog_ref"], "request_ref": catalog["request_ref"],
            "observations": len(payload["observations"]), "references": len(catalog["index"])}


def decode_catalog(catalog, *, scope, run_id, catalog_ref=None):
    """Return complete original request/checks/Observations, including local binding."""
    _, payload = _checked_catalog(catalog, scope=scope, run_id=run_id, catalog_ref=catalog_ref)
    return {"scope": scope, "run_id": run_id, **payload}


def _references(refs, index):
    _require(type(refs) in {list, tuple} and len(refs) <= MAX_REFS
             and all(type(ref) is str for ref in refs)
             and len(refs) == len(set(refs)) and all(ref in index for ref in refs),
             "unknown, duplicate or excessive catalogue reference")
    return list(refs)


def _at(payload, path):
    value = payload
    for part in path:
        value = value[part]
    return value


def resolve_catalog(catalog, refs, *, scope, run_id, catalog_ref):
    """Resolve exact objects only in the caller's current run-bound catalogue."""
    _, payload = _checked_catalog(catalog, scope=scope, run_id=run_id, catalog_ref=catalog_ref)
    selected = _references(refs, catalog["index"])
    return {ref: deepcopy(_at(payload, catalog["index"][ref]["path"])) for ref in selected}


def _reference(prefix, aliases):
    return [prefix + alias for alias in aliases]


def _view_shape(view, *, expanded=False):
    _require(type(view) is dict and set(view) == _VIEW_KEYS and view["schema"] == VIEW_SCHEMA,
             "invalid compact context view fields")
    _require(_hash(view["catalog_ref"]) and _hash(view["binding_ref"]))
    _require(type(view["stage"]) is str and view["stage"] in STAGES)
    _require(type(view["range"]) is dict and set(view["range"]) == {
        "security", "cutoff", "pit_mode", "objective", "bound_windows", "bindings", "declared_hypotheses"})
    expected_columns = {"facts": list(FACT_COLUMNS), "evidence": list(EVIDENCE_COLUMNS),
                        "hypotheses": list(HYPOTHESIS_COLUMNS), "source_datasets": list(SOURCE_COLUMNS),
                        "observations": list(OBSERVATION_COLUMNS),
                        "gaps": ["observation_ref", "gaps"] if expanded else list(GAP_COLUMNS)}
    _require(view["columns"] == expected_columns, "compact context field columns changed")
    for table, columns in expected_columns.items():
        _require(type(view[table]) is list and all(type(row) is list and len(row) == len(columns)
                  for row in view[table]), "compact context row width changed")
    _require(type(view["catalog_ids"]) is dict and set(view["catalog_ids"]) == {
        "claims", "evidence", "hypotheses", "observations"})
    for kind, prefix in (("claims", "C:"), ("evidence", "E:"), ("hypotheses", "H:"), ("observations", "O:")):
        ids = view["catalog_ids"][kind]
        _require(type(ids) is list and all(type(ref) is str and ref.startswith(prefix) for ref in ids)
                 and len(ids) == len(set(ids)), "compact context reference directory changed")
    _require(view["coverage"] == "not_verified" and view["causal_claim"] is False)
    _require(type(view["symbols"]) is list and type(view["gap_table"]) is list)
    # Reuse the exact JSON structural budget, including rejection of floats,
    # invalid Unicode and cyclic structures, before nested view decoding.
    encode_arena(view)


def encode_view(expanded):
    """Intern only repeated row metadata when its exact wire bytes decrease.

    Numeric decimal strings and C/E/H/O/F/E aliases are never interned. Dates,
    formula text, units and version hashes use {"s": index} cells, decoded by one
    symbols table. Equal gap text is also represented once, without losing order.
    """
    _view_shape(expanded, expanded=True)
    _require(expanded["symbols"] == [] and expanded["gap_table"] == [], "view is already compact")
    view = deepcopy(expanded)
    gaps = sorted({gap for _, values in view["gaps"] for gap in values})
    _require(all(type(gap) is str for gap in gaps), "invalid expanded context gap")
    gap_ids = {gap: index for index, gap in enumerate(gaps)}
    view["gap_table"] = gaps
    view["gaps"] = [[ref, [gap_ids[gap] for gap in values]] for ref, values in view["gaps"]]
    view["columns"]["gaps"] = list(GAP_COLUMNS)
    counts = {}

    def scan(item):
        if type(item) is str:
            # Leave aliases and every financial value directly readable.
            if len(item.encode("utf-8")) >= 10 and re.fullmatch(r"(?:[CEHO]:.*|[FE][1-9][0-9]*)", item) is None:
                counts[item] = counts.get(item, 0) + 1
        elif type(item) is list:
            for child in item:
                scan(child)

    for table in ("facts", "evidence"):
        for row in view[table]:
            for position, cell in enumerate(row):
                if position not in {0, 2}:  # ref and exact numeric value
                    scan(cell)
    candidates = sorted(text for text, count in counts.items() if count >= 2)
    # Index widths can change after removing unprofitable strings. Repeat until
    # every symbol itself saves bytes; fixed-point removal is deterministic.
    while True:
        selected = [text for index, text in enumerate(candidates)
                    if counts[text] * len(canonical_json(text).encode("utf-8"))
                    > counts[text] * len(canonical_json({"s": index}).encode("utf-8"))
                    + len(canonical_json(text).encode("utf-8")) + 1]
        if selected == candidates:
            break
        candidates = selected
    aliases = {text: index for index, text in enumerate(candidates)}

    def pack(item):
        if type(item) is str and item in aliases:
            return {"s": aliases[item]}
        if type(item) is list:
            return [pack(child) for child in item]
        return item

    original_tables = {table: deepcopy(view[table]) for table in ("facts", "evidence")}
    for table in ("facts", "evidence"):
        view[table] = [[cell if position in {0, 2} else pack(cell) for position, cell in enumerate(row)]
                       for row in view[table]]
    view["symbols"] = candidates
    original_size = len(canonical_json({"symbols": [], **original_tables}).encode("utf-8"))
    interned_size = len(canonical_json({key: view[key] for key in ("symbols", "facts", "evidence")}).encode("utf-8"))
    if interned_size >= original_size:
        # There is no lossy fallback: simply retain the exact original row cells.
        view.update(original_tables)
        view["symbols"] = []
    return view


def expand_view(view):
    """Expand a canonical wire view without consulting or fetching other data.

    This is decoding only, not source authorization. Use validate_view with the
    trusted current catalogue to verify the expanded values and their binding.
    """
    if type(view) is dict and view.get("schema") == "dynamic-context-view/v2":
        from .dynamic_context_metadata import decode_metadata_view
        return expand_view(decode_metadata_view(view))
    _view_shape(view)
    symbols, gap_table = view["symbols"], view["gap_table"]
    _require(all(type(text) is str for text in symbols) and symbols == sorted(set(symbols)),
             "invalid compact context symbols")
    _require(all(type(text) is str for text in gap_table) and gap_table == sorted(set(gap_table)),
             "invalid compact context gap table")

    def unpack(item):
        if type(item) is dict:
            _require(set(item) == {"s"} and type(item["s"]) is int and 0 <= item["s"] < len(symbols),
                     "dangling compact context symbol")
            return symbols[item["s"]]
        if type(item) is list:
            return [unpack(child) for child in item]
        _require(item is None or type(item) in {str, bool, int}, "invalid compact context cell")
        return item

    result = deepcopy(view)
    for table in ("facts", "evidence"):
        result[table] = []
        for row in view[table]:
            _require(type(row[0]) is str and (type(row[2]) is str or table == "evidence" and row[2] is None),
                     "refs and financial values must remain directly readable")
            result[table].append([unpack(cell) for cell in row])
    result["gaps"] = []
    for ref, aliases in view["gaps"]:
        _require(type(ref) is str and type(aliases) is list
                 and all(type(alias) is int and 0 <= alias < len(gap_table) for alias in aliases),
                 "dangling compact context gap")
        result["gaps"].append([ref, [gap_table[alias] for alias in aliases]])
    result["columns"]["gaps"] = ["observation_ref", "gaps"]
    result["symbols"], result["gap_table"] = [], []
    _require(encode_view(result) == view, "noncanonical compact context view")
    return result


def validate_view(view, catalog, *, scope, run_id):
    """Bind every wire value/ref/column to its exact authoritative current catalogue."""
    expanded = expand_view(view)
    wire = view
    if view["schema"] == "dynamic-context-view/v2":
        from .dynamic_context_metadata import decode_metadata_view
        wire = decode_metadata_view(view)
    _checked_catalog(catalog, scope=scope, run_id=run_id, catalog_ref=view["catalog_ref"])
    expected = view_catalog(catalog, scope=scope, run_id=run_id,
                            refs=wire["requested_refs"], current_stage=view["stage"],
                            catalog_ref=view["catalog_ref"])
    if expected != wire:
        raise IntegrityError("compact context view differs from its catalogue")
    return expanded


def view_catalog(catalog, *, scope, run_id, refs=(), current_stage="before_sources", catalog_ref=None):
    """Return compact exact facts/hypotheses and stage/reference-selected Evidence.

    Every C/E/H/O reference remains in the directory even when its object is not
    disclosed. O references retain hashes and exact original objects in storage.
    Referencing C/H discloses its input closure; O discloses that Observation's
    Evidence. The original question is kept in the catalogue and belongs once in
    the caller's control message, rather than being repeated in this data view.
    """
    request, payload = _checked_catalog(catalog, scope=scope, run_id=run_id, catalog_ref=catalog_ref)
    _require(type(current_stage) is str and current_stage in STAGES, "invalid context disclosure stage")
    selected = _references(refs, catalog["index"])
    observations = payload["observations"]
    derived = [item for item in observations if item["kind"] == "derived"]
    latest = next((item for item in derived if item["tool"] == "hypotheses"), derived[0] if derived else None)
    facts = latest["facts"] if latest else {}
    evidence = latest["evidence"] if latest else {}
    hypotheses = latest["hypotheses"] if latest else {}
    disclosed, claim_ids = set(), set()
    if current_stage == "verification":
        claim_ids.update(facts)
    elif current_stage in {"hypotheses", "finish"}:
        for hid in request.hypotheses:
            names = HYPOTHESIS_FACT_NAMES[hid]
            claim_ids.update(alias for alias, fact in facts.items() if fact["name"] in names)
            if hid in hypotheses:
                claim_ids.update(hypotheses[hid]["claim_ids"])
                claim_ids.update(hypotheses[hid]["counterevidence_claim_ids"])
    for ref in selected:
        value = _at(payload, catalog["index"][ref]["path"])
        if ref.startswith("E:"):
            disclosed.add(ref[2:])
        elif ref.startswith("C:"):
            claim_ids.add(ref[2:])
        elif ref.startswith("H:"):
            claim_ids.update(value["claim_ids"])
            claim_ids.update(value["counterevidence_claim_ids"])
        elif value["kind"] == "derived":
            disclosed.update(value["evidence"])
    for alias in claim_ids:
        disclosed.update(facts[alias]["evidence_ids"])
    _require(disclosed <= set(evidence), "disclosure points outside current Evidence")

    rows, source_rows, gaps, verification = [], [], [], []
    for observation in observations:
        ref = "O:" + observation["tool"]
        rows.append([ref, observation["kind"], catalog["index"][ref]["sha256"], observation.get("status"),
                     _reference("C:", observation.get("facts", {})),
                     _reference("E:", observation.get("evidence", {})),
                     _reference("H:", observation.get("hypotheses", {}))])
        if observation["kind"] == "source_read":
            for dataset, result in observation["datasets"].items():
                source_rows.append([ref, dataset, result["status"], result["records"],
                                    result["periods"], result["source_result_ref"]])
        if "gaps" in observation:
            gaps.append([ref, observation["gaps"]])
        if observation["kind"] == "verification":
            verification.append([ref, observation["result"]])

    # These fixed columns preserve exact decimals/nulls/time/units/formulas and IDs.
    # Only field names are shared; values are never rounded or abbreviated.
    expanded = {"schema": VIEW_SCHEMA, "catalog_ref": catalog["catalog_ref"],
            "binding_ref": digest({"scope": scope, "run_id": run_id, "request_ref": catalog["request_ref"]}),
            "range": {"security": request.security.canonical_symbol, "cutoff": request.as_of.isoformat(),
                      "pit_mode": request.mode.value, "objective": request.objective,
                      "bound_windows": {binding.dataset: [binding.start.isoformat(), binding.end.isoformat()]
                                        for binding in request.bindings},
                      "bindings": {binding.dataset: {"provider": binding.provider, "snapshot_ref": binding.snapshot}
                                   for binding in request.bindings},
                      "declared_hypotheses": list(request.hypotheses)},
            "required_checks": payload["required_checks"],
            "catalog_ids": {key: [ref for ref in catalog["index"] if ref.startswith(prefix)]
                            for key, prefix in (("claims", "C:"), ("evidence", "E:"),
                                                ("hypotheses", "H:"), ("observations", "O:"))},
            "columns": {"facts": list(FACT_COLUMNS), "evidence": list(EVIDENCE_COLUMNS),
                        "hypotheses": list(HYPOTHESIS_COLUMNS), "source_datasets": list(SOURCE_COLUMNS),
                        "observations": list(OBSERVATION_COLUMNS), "gaps": ["observation_ref", "gaps"]},
            "facts": [["C:" + alias, *[value[key] for key in FACT_COLUMNS[1:]]] for alias, value in facts.items()],
            "hypotheses": [["H:" + alias, *[value[key] for key in HYPOTHESIS_COLUMNS[1:]]]
                           for alias, value in hypotheses.items()],
            "evidence": [["E:" + alias, *[evidence[alias][key] for key in EVIDENCE_COLUMNS[1:]]]
                         for alias in sorted(disclosed)],
            "observations": rows, "source_datasets": source_rows, "gaps": gaps,
            "event_anchor": latest["event_anchor"] if latest else {}, "verification": verification,
            "disclosed_refs": sorted(set(selected) | {"E:" + alias for alias in disclosed}),
            "symbols": [], "gap_table": [], "stage": current_stage, "requested_refs": sorted(selected),
            "coverage": "not_verified", "causal_claim": False}
    return encode_view(expanded)
