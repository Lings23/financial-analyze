"""Exact message-local metadata/column encoding for the explicit v6.1 wire.

The immutable v1 window, descriptor, selection and cursor identities do not
change.  Only profitable representations are emitted; otherwise the original
literal v1 view is returned.  Financial value cells remain literal.  Decoding
confers neither source permission nor research execution progress.
"""
from collections import Counter
from copy import deepcopy

from ..errors import IntegrityError, ValidationError
from ..models import canonical_json
from .context_window import WINDOW_SCHEMA, KINDS, expand_window_view
from .dynamic_context import MAX_REFS, _hash, encode_arena


WINDOW_METADATA_SCHEMA = "dynamic-context-window/v2"
WINDOW_METADATA_CONTRACT = "exact_window_metadata/v1"
_WRAPPER_KEYS = frozenset({"schema", "metadata_schema", "symbols", "list_table", "layouts", "view"})
# Each known record is restored to this exact field set and field values.  A
# column layout is used only when its repeated field-name savings pay for it.
_LAYOUTS = (
    ("schema", "catalog_ref", "request_ref", "kind", "refs", "collection_ref", "object_revision", "start", "end"),
    ("name", "value", "unit", "window", "formula", "available_at", "inputs_ref"),
    ("status", "reason", "conclusion_strength", "claim_ids_ref", "counterevidence_claim_ids_ref"),
    ("ref", "kind", "object_revision", "status", "datasets", "gaps_ref"),
    ("ref", "kind", "object_revision", "counts", "event_anchor_ref", "gaps_ref"),
    ("ref", "kind", "object_revision", "result"),
    ("ref", "object_revision"),
    ("object_ref", "path", "count", "content_hash"),
    ("object_ref", "path", "content_hash"),
    ("dataset", "status", "records", "source_result_ref", "periods_ref"),
    ("selection", "kind", "total", "start", "end", "has_more", "atoms", "content_hash"),
    ("selection", "kind", "total", "start", "end", "has_more", "atoms", "content_hash", "next_cursor"),
    ("count", "collection_ref"),
    ("count", "collection_ref", "cursor"),
    ("provider", "snapshot_ref"),
)
_LAYOUT_SET = frozenset(_LAYOUTS)
_LAYOUT_BY_KEYS = {frozenset(columns): columns for columns in _LAYOUTS}


def _require(condition, message="invalid exact window metadata encoding"):
    if not condition:
        raise ValidationError(message)


def _bytes(value):
    return len(canonical_json(value).encode("utf-8"))


def _reference(value, *, counted):
    keys = {"object_ref", "path", "content_hash"} | ({"count"} if counted else set())
    _require(type(value) is dict and set(value) == keys and type(value["object_ref"]) is str
             and type(value["path"]) is list and all(type(part) in {str, int} for part in value["path"])
             and _hash(value["content_hash"]), "invalid exact metadata object path reference")
    if counted:
        _require(type(value["count"]) is int and value["count"] >= 0, "invalid exact metadata reference count")


def _raw_shape(view, *, header_mode=False):
    """Validate the literal v1 view before transforming or after restoring it."""
    _require(type(header_mode) is bool and type(view) is dict, "invalid window metadata header mode")
    header = "window_ref" not in view
    _require(not header or header_mode and view.get("pages") == [], "paid window is missing its identity")
    probe = {**deepcopy(view), **({"window_ref": "0" * 64} if header else {})}
    expand_window_view(probe)
    # The existing v1 decoder binds page hashes/intervals and revision table.
    # Additional nested shapes freeze the new metadata slots/column layouts.
    _require(type(view["range"]) is dict and set(view["range"]) == {
        "security", "cutoff", "pit_mode", "objective", "bound_windows", "bindings", "declared_hypotheses"},
        "invalid exact window metadata range")
    for key in ("security", "cutoff", "pit_mode", "objective"):
        _require(type(view["range"][key]) is str, "invalid exact window range literal")
    _require(type(view["range"]["bound_windows"]) is dict and type(view["range"]["bindings"]) is dict
             and set(view["range"]["bound_windows"]) == set(view["range"]["bindings"]), "invalid exact bound windows")
    for name, window in view["range"]["bound_windows"].items():
        _require(type(name) is str and type(window) is list and len(window) == 2
                 and all(type(value) is str for value in window), "invalid exact source window")
    for binding in view["range"]["bindings"].values():
        _require(type(binding) is dict and set(binding) == {"provider", "snapshot_ref"}
                 and all(type(value) is str for value in binding.values()), "invalid exact source binding")
    _require(type(view["range"]["declared_hypotheses"]) is list
             and all(type(value) is str for value in view["range"]["declared_hypotheses"]), "invalid exact hypotheses list")
    _require(type(view["required_checks"]) is list and all(type(value) is str for value in view["required_checks"])
             and len(view["required_checks"]) == len(set(view["required_checks"])), "invalid exact required checks")
    _require(type(view["counts"]) is dict and set(view["counts"]) == {
        "claims", "evidence", "hypotheses", "observations"}
        and all(type(value) is int and value >= 0 for value in view["counts"].values()), "invalid exact window counts")
    _require(type(view["observations"]) is list and len(view["observations"]) <= 12, "invalid exact Observation list")
    for observation in view["observations"]:
        _require(type(observation) is dict and type(observation.get("kind")) is str, "invalid exact Observation summary")
        kind = observation["kind"]
        keys = ({"ref", "kind", "object_revision", "status", "datasets", "gaps_ref"} if kind == "source_read" else
                {"ref", "kind", "object_revision", "counts", "event_anchor_ref", "gaps_ref"} if kind == "derived" else
                {"ref", "kind", "object_revision", "result"} if kind == "verification" else None)
        _require(keys is not None and set(observation) == keys and type(observation["ref"]) is str
                 and observation["ref"].startswith("O:") and _hash(observation["object_revision"]),
                 "invalid exact Observation summary fields")
        if "gaps_ref" in observation:
            _reference(observation["gaps_ref"], counted=True)
        if kind == "derived":
            _reference(observation["event_anchor_ref"], counted=False)
            _require(type(observation["counts"]) is dict and set(observation["counts"]) == {"facts", "evidence", "hypotheses"}
                     and all(type(value) is int and value >= 0 for value in observation["counts"].values()),
                     "invalid exact Observation member counts")
        if kind == "source_read":
            _require(type(observation["status"]) is str and type(observation["datasets"]) is list,
                     "invalid exact source summary")
            for source in observation["datasets"]:
                _require(type(source) is dict and set(source) == {"dataset", "status", "records", "source_result_ref", "periods_ref"}
                         and type(source["dataset"]) is str and type(source["status"]) is str
                         and type(source["records"]) is int and source["records"] >= 0
                         and _hash(source["source_result_ref"]), "invalid exact dataset summary")
                _reference(source["periods_ref"], counted=True)
        if kind == "verification":
            _require(type(observation["result"]) is dict and set(observation["result"]) == {
                "status", "numeric_claims", "evidence_checked", "hypotheses_checked", "event_anchor_checked", "method",
                "provider_accuracy_certified", "causality_established"}, "invalid exact verification result")
            result = observation["result"]
            _require(type(result["status"]) is str and type(result["method"]) is str
                     and all(type(result[key]) is int and result[key] >= 0
                             for key in ("numeric_claims", "evidence_checked", "hypotheses_checked"))
                     and all(type(result[key]) is bool for key in
                             ("event_anchor_checked", "provider_accuracy_certified", "causality_established")),
                     "invalid exact verification result values")
    _require(type(view["collections"]) is dict and set(view["collections"]) == KINDS - {"objects"},
             "invalid exact window collections")
    for collection in view["collections"].values():
        _require(type(collection) is dict and set(collection) in ({"count", "collection_ref"}, {"count", "collection_ref", "cursor"})
                 and type(collection["count"]) is int and collection["count"] >= 0 and _hash(collection["collection_ref"]),
                 "invalid exact window collection entry")
        if "cursor" in collection:
            _require(not header and collection["count"] > 0 and _hash(collection["cursor"]), "invalid exact collection cursor")
    for page in view["pages"]:
        selection = page["selection"]
        _require(type(selection["refs"]) is list and selection["refs"] == sorted(set(selection["refs"]))
                 and all(type(ref) is str for ref in selection["refs"])
                 and (1 <= len(selection["refs"]) <= MAX_REFS if selection["kind"] == "objects" else not selection["refs"])
                 and all(_hash(selection[key]) for key in ("catalog_ref", "request_ref", "collection_ref", "object_revision")),
                 "invalid exact page selection binding")
        for ref, path, kind, value in page["atoms"]:
            if kind in {"d", "l"}:
                _require(type(value) is int and value >= 0, "invalid exact container atom")
            elif kind == "v":
                if ref == "D:catalog":
                    _require(type(value) is dict and set(value) == {"ref", "object_revision"}
                             and type(value["ref"]) is str and _hash(value["object_revision"]), "invalid exact directory atom")
                else:
                    _require(value is None or type(value) in {str, int, bool}, "invalid exact scalar atom")
            else:
                keys = ({"name", "value", "unit", "window", "formula", "available_at", "inputs_ref"} if ref.startswith("C:") else
                        {"status", "reason", "conclusion_strength", "claim_ids_ref", "counterevidence_claim_ids_ref"}
                        if ref.startswith("H:") else None)
                _require(keys is not None and type(value) is dict and set(value) == keys, "invalid exact projection atom")
                if ref.startswith("C:"):
                    _require(all(type(value[key]) is str for key in ("name", "value", "unit", "formula", "available_at"))
                             and type(value["window"]) is list and len(value["window"]) == 2
                             and all(type(period) is str for period in value["window"]),
                             "financial projection must retain exact literal values")
                    _reference(value["inputs_ref"], counted=True)
                else:
                    _require(all(type(value[key]) is str for key in ("status", "reason", "conclusion_strength")),
                             "hypothesis projection must retain exact literal values")
                    for key in ("claim_ids_ref", "counterevidence_claim_ids_ref"):
                        _reference(value[key], counted=True)
    if "verification_brief" in view:
        brief = view["verification_brief"]
        _require(type(brief) is dict and set(brief) == {"computed_ref", "source_refs", "counts"}
                 and type(brief["computed_ref"]) is str and type(brief["source_refs"]) is list
                 and all(type(ref) is str for ref in brief["source_refs"])
                 and type(brief["counts"]) is dict and set(brief["counts"]) == {
                    "facts", "evidence", "hypotheses", "source_datasets", "source_records"}
                 and all(type(value) is int and value >= 0 for value in brief["counts"].values()),
                 "invalid exact window verification brief")
    encode_arena(view)  # Reject non-JSON/float/Unicode/cycles and original structural limits.


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


def _choose_layouts(view):
    found = {}
    _records(view, found)
    candidates = sorted((columns for columns, values in found.items() if len(values) >= 2), key=lambda c: canonical_json(list(c)))
    while True:
        selected = []
        for index, columns in enumerate(candidates):
            savings = sum(_bytes(value) - _bytes({"r": index, "v": [value[column] for column in columns]})
                          for value in found[columns])
            if savings > _bytes(list(columns)) + 1:
                selected.append(columns)
        if selected == candidates:
            return candidates
        candidates = selected


def _pack_rows(value, aliases):
    if type(value) is dict:
        columns = _LAYOUT_BY_KEYS.get(frozenset(value))
        if columns in aliases:
            return {"r": aliases[columns], "v": [deepcopy(value[column]) if column == "value"
                     else _pack_rows(value[column], aliases) for column in columns]}
        return {key: deepcopy(child) if key == "value" else _pack_rows(child, aliases)
                for key, child in value.items()}
    if type(value) is list:
        return [_pack_rows(child, aliases) for child in value]
    return deepcopy(value)


def _atom(value):
    return (type(value) is list and len(value) == 4 and type(value[0]) is str
            and value[0].startswith(("C:", "E:", "H:", "O:", "D:"))
            and type(value[1]) is list and type(value[2]) is str and value[2] in {"d", "l", "v", "summary"})


def _list_eligible(value):
    """Only exact metadata scalar lists/paths, never record rows or atom bodies."""
    if type(value) is list:
        return all(_list_eligible(child) for child in value)
    if type(value) is dict:
        return set(value) == {"s"} and type(value["s"]) is int
    return value is None or type(value) in {str, int, bool}


def _walk(value, layouts, string=lambda value: value, sequence=lambda value: value):
    if type(value) is str:
        return string(value)
    if type(value) is dict:
        if set(value) == {"r", "v"}:
            columns = layouts[value["r"]]
            return {"r": value["r"], "v": [deepcopy(child) if column == "value"
                else _walk(child, layouts, string, sequence) for column, child in zip(columns, value["v"])]}
        return {key: deepcopy(child) if key == "value" else _walk(child, layouts, string, sequence)
                for key, child in value.items()}
    if type(value) is list:
        if _atom(value):
            # Scalars in complete O/C/E/H object pages stay literal, including
            # exact financial values; only their ref/path/type is metadata.
            return [_walk(value[0], layouts, string, sequence), _walk(value[1], layouts, string, sequence),
                _walk(value[2], layouts, string, sequence), deepcopy(value[3]) if value[2] == "v"
                and value[0] != "D:catalog" else _walk(value[3], layouts, string, sequence)]
        transformed = [_walk(child, layouts, string, sequence) for child in value]
        return sequence(transformed) if _list_eligible(transformed) else transformed
    return deepcopy(value)


def _encode(view, header_mode):
    _raw_shape(view, header_mode=header_mode)
    layouts = _choose_layouts(view)
    packed = _pack_rows(view, {columns: index for index, columns in enumerate(layouts)})
    counts = Counter()
    def count(value):
        counts[value] += 1
        return value
    _walk(packed, layouts, count)
    # Column names are metadata too.  Repeated ref/kind/count/hash columns across
    # layouts share the same current-message string table rather than creating
    # another literal repetition beside the record encoding.
    counts.update(column for columns in layouts for column in columns)
    symbols = sorted(value for value, count in counts.items() if count >= 2)
    while True:
        profitable = [value for index, value in enumerate(symbols)
            if counts[value] * _bytes(value) > counts[value] * _bytes({"s": index}) + _bytes(value) + 1]
        if profitable == symbols:
            break
        symbols = profitable
    aliases = {value: index for index, value in enumerate(symbols)}
    symbolic = _walk(packed, layouts, lambda value: {"s": aliases[value]} if value in aliases else value)
    lists, list_counts = {}, Counter()
    def count_list(value):
        key = canonical_json(value)
        lists[key] = value
        list_counts[key] += 1
        return value
    _walk(symbolic, layouts, sequence=count_list)
    selected = sorted(key for key, count in list_counts.items() if count >= 2)
    while True:
        profitable = [key for index, key in enumerate(selected)
            if list_counts[key] * _bytes(lists[key]) > list_counts[key] * _bytes({"l": index}) + _bytes(lists[key]) + 1]
        if profitable == selected:
            break
        selected = profitable
    list_aliases = {key: index for index, key in enumerate(selected)}
    coded = _walk(symbolic, layouts, sequence=lambda value: {"l": list_aliases[canonical_json(value)]}
                  if canonical_json(value) in list_aliases else value)
    wrapper = {"schema": WINDOW_METADATA_SCHEMA, "metadata_schema": WINDOW_METADATA_CONTRACT,
               "symbols": symbols, "list_table": [deepcopy(lists[key]) for key in selected],
               "layouts": [[{"s": aliases[column]} if column in aliases else column for column in columns]
                           for columns in layouts], "view": coded}
    # Header/empty windows may not pay for a wrapper.  Literal fallback is exact
    # and deterministic, and the explicit v6.1 protocol admits both wire shapes.
    return wrapper if _bytes(wrapper) < _bytes(view) else deepcopy(view)


def encode_window_metadata_view(view, *, header_mode=False):
    """Encode without growing the literal view; header_mode is compiler-only."""
    try:
        return _encode(view, header_mode)
    except (KeyError, TypeError, IndexError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("invalid exact window metadata source structure") from None


def _decode(wire):
    _require(type(wire) is dict, "invalid exact window metadata wrapper")
    if wire.get("schema") == WINDOW_SCHEMA:
        _raw_shape(wire)
        return deepcopy(wire)
    _require(set(wire) == _WRAPPER_KEYS and wire.get("schema") == WINDOW_METADATA_SCHEMA
             and wire.get("metadata_schema") == WINDOW_METADATA_CONTRACT, "invalid exact window metadata wrapper fields")
    encode_arena(wire)
    symbols, lists, coded_layouts = wire["symbols"], wire["list_table"], wire["layouts"]
    _require(type(symbols) is list and all(type(value) is str for value in symbols)
             and symbols == sorted(set(symbols)), "invalid exact metadata symbol table")
    def column(value):
        if type(value) is str:
            return value
        _require(type(value) is dict and set(value) == {"s"} and type(value["s"]) is int
                 and 0 <= value["s"] < len(symbols), "dangling exact column symbol reference")
        return symbols[value["s"]]
    _require(type(coded_layouts) is list and all(type(columns) is list for columns in coded_layouts),
             "invalid exact metadata column table")
    layouts = [[column(value) for value in columns] for columns in coded_layouts]
    _require(all(tuple(columns) in _LAYOUT_SET for columns in layouts), "unknown exact metadata column layout")
    _require(layouts == [json_columns for _, json_columns in sorted(
        (canonical_json(columns), columns) for columns in layouts)]
        and len({tuple(columns) for columns in layouts}) == len(layouts), "noncanonical exact metadata layouts")
    _require(type(lists) is list and all(type(value) is list and _list_eligible(value) for value in lists),
             "invalid exact metadata list table")
    keys = [canonical_json(value) for value in lists]
    _require(keys == sorted(set(keys)), "noncanonical exact metadata list table")

    def index(value, table, message):
        _require(type(value) is int and 0 <= value < len(table), message)
        return table[value]

    def unpack(value, *, list_entry=False):
        if type(value) is dict:
            if set(value) == {"s"}:
                return index(value["s"], symbols, "dangling exact metadata symbol reference")
            if set(value) == {"l"}:
                _require(not list_entry, "nested exact metadata list reference")
                return unpack(index(value["l"], lists, "dangling exact metadata list reference"), list_entry=True)
            if set(value) == {"r", "v"}:
                _require(not list_entry and type(value["v"]) is list, "invalid exact metadata row")
                columns = index(value["r"], layouts, "dangling exact metadata row layout")
                _require(len(value["v"]) == len(columns), "exact metadata row width changed")
                return {column: unpack(child) for column, child in zip(columns, value["v"])}
            return {key: unpack(child, list_entry=list_entry) for key, child in value.items()}
        if type(value) is list:
            return [unpack(child, list_entry=list_entry) for child in value]
        return deepcopy(value)

    restored = unpack(wire["view"])
    _raw_shape(restored)
    if _encode(restored, False) != wire:
        raise IntegrityError("noncanonical exact window metadata encoding")
    return restored


def decode_window_metadata_view(wire):
    """Restore a strict final paid view; metadata indices are message-local only."""
    try:
        return _decode(wire)
    except (KeyError, TypeError, IndexError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("invalid exact window metadata structure") from None


encode_window_view = encode_window_metadata_view
decode_window_view = decode_window_metadata_view
