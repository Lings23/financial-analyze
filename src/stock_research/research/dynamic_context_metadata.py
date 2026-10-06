"""Explicit v2 lossless metadata representation of an existing v1 context view.

This pure codec neither reads sources nor authorizes anything. It only interns
exact strings and repeated lists in fixed metadata positions. Financial values,
the disclosure selection and every original object remain unchanged.
"""
from copy import deepcopy

from ..errors import ValidationError
from ..models import canonical_json
from .dynamic_context import (
    VIEW_SCHEMA, _VIEW_KEYS, encode_arena, encode_view, expand_view,
)


METADATA_VIEW_SCHEMA = "dynamic-context-view/v2"


def _require(condition, message="invalid metadata context view"):
    if not condition:
        raise ValidationError(message)


def _bytes(value):
    return len(canonical_json(value).encode("utf-8"))


def _slots(view):
    """Fixed scalar/list metadata positions; never the Fact/Evidence value cell."""
    scope = view["range"]
    for key in ("security", "cutoff", "pit_mode", "objective", "declared_hypotheses"):
        yield scope, key
    _require(type(scope["bound_windows"]) is dict and type(scope["bindings"]) is dict)
    for key in sorted(scope["bound_windows"]):
        yield scope["bound_windows"], key
    for key in sorted(scope["bindings"]):
        binding = scope["bindings"][key]
        _require(type(binding) is dict and set(binding) == {"provider", "snapshot_ref"})
        for field in ("provider", "snapshot_ref"):
            yield binding, field
    for table, positions in (("facts", (1, 3, 4, 5, 6, 7)),
                             ("evidence", (1, 3, 4, 5, 6, 7, 8)),
                             ("hypotheses", (1, 2, 3, 4, 5)),
                             ("observations", (0, 1, 2, 3, 4, 5, 6)),
                             ("source_datasets", (0, 1, 2, 4, 5))):
        _require(type(view[table]) is list)
        for row in view[table]:
            _require(type(row) is list and len(row) > max(positions))
            for position in positions:
                yield row, position
    for key in ("claims", "evidence", "hypotheses", "observations"):
        yield view["catalog_ids"], key
    for key in ("requested_refs", "disclosed_refs", "required_checks"):
        yield view, key


def _map(item, scalar):
    if item is None:
        return None
    if type(item) is list:
        return [_map(value, scalar) for value in item]
    return scalar(item)


def _literal(view):
    # v1 expansion checks the original canonical codec and structure first.
    expanded = expand_view(view)
    result = deepcopy(view)
    for table in ("facts", "evidence"):
        result[table] = expanded[table]
    result["symbols"] = []
    for parent, key in _slots(result):
        def checked(value):
            _require(type(value) is str, "metadata literals must be exact text")
            return value
        parent[key] = _map(parent[key], checked)
    return result


def encode_metadata_view(view):
    """Encode a canonical v1 wire view as exact, deterministic v2 metadata.

    Metadata integers refer to symbols; {"l": i} refers to list_table. Each list
    entry retains exact order and IDs. Only individually profitable entries are
    interned; unprofitable entries stay literal. No values are summarized.
    """
    _require(type(view) is dict and view.get("schema") == VIEW_SCHEMA)
    result = _literal(view)
    counts = {}
    for parent, key in _slots(result):
        def count(value):
            counts[value] = counts.get(value, 0) + 1
            return value
        _map(parent[key], count)
    candidates = sorted(text for text, count in counts.items() if count >= 2)
    while True:
        profitable = [text for index, text in enumerate(candidates)
                      if counts[text] * _bytes(text) > counts[text] * _bytes(index) + _bytes(text) + 1]
        if candidates == profitable:
            break
        candidates = profitable
    aliases = {value: index for index, value in enumerate(candidates)}
    for parent, key in _slots(result):
        parent[key] = _map(parent[key], lambda value: aliases.get(value, value))
    result["symbols"] = candidates
    lists, list_counts = {}, {}
    for parent, key in _slots(result):
        if type(parent[key]) is list:
            identity = canonical_json(parent[key])
            lists[identity] = parent[key]
            list_counts[identity] = list_counts.get(identity, 0) + 1
    selected = sorted(identity for identity, count in list_counts.items() if count >= 2)
    while True:
        profitable = [identity for index, identity in enumerate(selected)
                      if list_counts[identity] * _bytes(lists[identity])
                      > list_counts[identity] * _bytes({"l": index}) + _bytes(lists[identity]) + 1]
        if selected == profitable:
            break
        selected = profitable
    result["schema"] = METADATA_VIEW_SCHEMA
    result["list_table"] = []
    without_lists = deepcopy(result)
    list_aliases = {value: index for index, value in enumerate(selected)}
    for parent, key in _slots(result):
        if type(parent[key]) is list and canonical_json(parent[key]) in list_aliases:
            parent[key] = {"l": list_aliases[canonical_json(parent[key])]}
    result["list_table"] = [deepcopy(lists[identity]) for identity in selected]
    if _bytes(result) >= _bytes(without_lists):
        result = without_lists
    encode_arena(result)  # Exact JSON, depth/node/Unicode/storage budgets.
    return result


def _decode_metadata_view(view):
    """Recover the complete original canonical v1 wire; reject tampered codecs."""
    _require(type(view) is dict and set(view) == _VIEW_KEYS | {"list_table"}
             and view.get("schema") == METADATA_VIEW_SCHEMA)
    encode_arena(view)
    symbols, lists = view.get("symbols"), view["list_table"]
    _require(type(symbols) is list and all(type(value) is str for value in symbols)
             and symbols == sorted(set(symbols)), "invalid metadata symbol table")
    _require(type(lists) is list and all(type(value) is list for value in lists),
             "invalid metadata list table")

    def unpack_scalar(value):
        if type(value) is int:
            _require(0 <= value < len(symbols), "dangling metadata symbol index")
            return symbols[value]
        _require(type(value) is str, "invalid metadata scalar or boolean index")
        return value

    def unpack(value):
        if type(value) is dict:
            _require(set(value) == {"l"} and type(value["l"]) is int
                     and 0 <= value["l"] < len(lists), "dangling metadata list index")
            value = lists[value["l"]]
        return _map(value, unpack_scalar)

    result = deepcopy(view)
    result.pop("list_table")
    result["schema"] = VIEW_SCHEMA
    # The ordinary v1 schema validates every untouched field after decoding.
    for parent, key in _slots(result):
        parent[key] = unpack(parent[key])
    gaps = result["gap_table"]
    _require(type(gaps) is list and all(type(value) is str for value in gaps)
             and gaps == sorted(set(gaps)), "invalid metadata gap table")
    expanded_gaps = []
    for row in result["gaps"]:
        _require(type(row) is list and len(row) == 2 and type(row[0]) is str
                 and type(row[1]) is list, "invalid metadata gaps")
        _require(all(type(index) is int and 0 <= index < len(gaps) for index in row[1]),
                 "dangling metadata gap index")
        expanded_gaps.append([row[0], [gaps[index] for index in row[1]]])
    result["gaps"] = expanded_gaps
    result["columns"]["gaps"] = ["observation_ref", "gaps"]
    result["symbols"], result["gap_table"] = [], []
    restored = encode_view(result)
    expand_view(restored)
    _require(encode_metadata_view(restored) == view, "noncanonical metadata context view")
    return restored


def decode_metadata_view(view):
    """Strict codec boundary; malformed shape always raises typed validation."""
    try:
        return _decode_metadata_view(view)
    except (KeyError, TypeError, IndexError, ValueError, RecursionError):
        raise ValidationError("invalid metadata context view structure") from None
