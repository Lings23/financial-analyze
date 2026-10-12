"""Pure, exact and bounded v6 context windows.

The caller authorizes every read before and after invoking these functions.  A
catalogue hash, a window or an issued cursor never grants source permission.
Objects remain in the existing immutable catalogue.  Object pages contain
complete JSON scalars and explicit container markers.  The exact Fact/Hypothesis
projection identifies external lists by their original paths, counts and hashes.
"""
from copy import deepcopy

from ..errors import IntegrityError, PermissionDenied, ValidationError
from ..models import canonical_json, digest
from .dynamic_context import (
    MAX_REFS, STAGES, _at, _checked_catalog, _hash, _verification_brief,
    build_verification_audit, validate_execution_revisions,
)
from .dynamic_context_metadata import encode_state_versions, decode_state_versions


WINDOW_SCHEMA = "dynamic-context-window/v1"
WINDOW_DESCRIPTOR_SCHEMA = "dynamic-context-window-descriptor/v1"
SELECTION_SCHEMA = "dynamic-context-page-selection/v1"
CURSOR_SCHEMA = "dynamic-context-cursor/v1"
WINDOW_POLICY = "bound_exact_pages/v1"
ATOM_COLUMNS = ["ref", "path", "kind", "value"]
KINDS = frozenset({"directory", "facts", "hypotheses", "periods", "objects"})
_SELECTION_KEYS = frozenset({"schema", "catalog_ref", "request_ref", "kind", "refs",
                           "collection_ref", "object_revision", "start", "end"})
_DESCRIPTOR_CORE_KEYS = frozenset({"schema", "policy_version", "scope_ref", "run_id",
    "request_ref", "catalog_ref", "stage", "execution_revisions", "verification_ready",
    "read_enabled", "counts", "pages", "allowed_refs", "view_ref", "dispatch_ref"})
_WINDOW_VIEW_KEYS = frozenset({"schema", "policy_version", "catalog_ref", "binding_ref", "range",
    "required_checks", "stage", "state_versions", "counts", "observations", "atom_columns",
    "collections", "coverage", "causal_claim", "pages", "window_ref"})


class ContextMinimumViewExceeded(ValidationError):
    """The actual control header or a required indivisible item exceeds the cap."""


def _require(condition, message="invalid exact context window"):
    if not condition:
        raise ValidationError(message)


def _call(check):
    if check is not None:
        _require(callable(check), "invalid window cancellation check")
        check()


def _atoms(ref, value, check=None, path=()):
    """Yield a canonical preorder; an individual scalar is never subdivided."""
    _call(check)
    if type(value) is dict:
        yield [ref, list(path), "d", len(value)]
        for key in sorted(value):
            yield from _atoms(ref, value[key], check, (*path, key))
    elif type(value) is list:
        yield [ref, list(path), "l", len(value)]
        for position, child in enumerate(value):
            yield from _atoms(ref, child, check, (*path, position))
    else:
        _require(value is None or type(value) in {str, int, bool}, "invalid page scalar")
        yield [ref, list(path), "v", deepcopy(value)]


def _prepared(catalog, scope, run_id, check=None):
    _call(check)
    request, payload = _checked_catalog(catalog, scope=scope, run_id=run_id)
    objects = {ref: _at(payload, item["path"]) for ref, item in catalog["index"].items()}
    counts = {name: sum(ref.startswith(prefix) for ref in objects)
              for name, prefix in (("claims", "C:"), ("evidence", "E:"),
                                   ("hypotheses", "H:"), ("observations", "O:"))}
    return request, payload, objects, counts


def _collection(catalog, prepared, kind, refs=(), check=None):
    _require(type(kind) is str and kind in KINDS, "unknown page collection")
    _require(type(refs) in {list, tuple} and all(type(ref) is str for ref in refs),
             "invalid page object references")
    refs = list(refs)
    if kind == "objects":
        _require(1 <= len(refs) <= MAX_REFS and refs == sorted(set(refs))
                 and all(ref in catalog["index"] for ref in refs),
                 "unknown, duplicate or excessive page object references")
        members = refs
    else:
        _require(not refs, "collection page cannot contain arbitrary object references")
        prefix = {"facts": "C:", "hypotheses": "H:", "periods": "O:"}.get(kind)
        members = [ref for ref in catalog["index"] if prefix is None or ref.startswith(prefix)]
        if kind == "periods":
            members = [ref for ref in members if prepared[2][ref]["kind"] == "source_read"]
    revision = digest([[ref, catalog["index"][ref]["sha256"]] for ref in members])
    atoms = []
    for ref in members:
        _call(check)
        value = prepared[2][ref]
        if kind == "directory":
            atoms.append(["D:catalog", [ref], "v", {"ref": ref,
                          "object_revision": catalog["index"][ref]["sha256"]}])
        elif kind == "facts":
            synopsis = {key: deepcopy(child) for key, child in value.items() if key != "evidence_ids"}
            synopsis["inputs_ref"] = {"object_ref": ref, "path": ["evidence_ids"],
                "count": len(value["evidence_ids"]), "content_hash": digest(value["evidence_ids"])}
            atoms.append([ref, [], "summary", synopsis])
        elif kind == "hypotheses":
            synopsis = {key: deepcopy(child) for key, child in value.items()
                        if key not in {"claim_ids", "counterevidence_claim_ids"}}
            for key in ("claim_ids", "counterevidence_claim_ids"):
                synopsis[key + "_ref"] = {"object_ref": ref, "path": [key],
                    "count": len(value[key]), "content_hash": digest(value[key])}
            atoms.append([ref, [], "summary", synopsis])
        elif kind == "periods":
            for dataset in sorted(value["datasets"]):
                periods = value["datasets"][dataset]["periods"]
                atoms.extend(_atoms(ref, periods, check, ("datasets", dataset, "periods")))
        else:
            atoms.extend(_atoms(ref, value, check))
    collection_ref = digest({"kind": kind, "refs": refs, "object_revision": revision,
                             "atoms": atoms})
    return {"kind": kind, "refs": refs, "object_revision": revision,
            "collection_ref": collection_ref, "atoms": atoms}


def _selection(catalog, collection, start=0, end=None):
    return {"schema": SELECTION_SCHEMA, "catalog_ref": catalog["catalog_ref"],
            "request_ref": catalog["request_ref"], "kind": collection["kind"],
            "refs": deepcopy(collection["refs"]), "collection_ref": collection["collection_ref"],
            "object_revision": collection["object_revision"], "start": start, "end": end}


def _checked_selection(catalog, selection, prepared, check=None, *, pending=False):
    _require(type(selection) is dict and set(selection) == _SELECTION_KEYS
             and selection["schema"] == SELECTION_SCHEMA, "invalid page selection schema")
    if selection["catalog_ref"] != catalog["catalog_ref"] or selection["request_ref"] != catalog["request_ref"]:
        raise PermissionDenied("page selection belongs to a different catalogue or request")
    collection = _collection(catalog, prepared, selection["kind"], selection["refs"], check)
    if (selection["collection_ref"] != collection["collection_ref"]
            or selection["object_revision"] != collection["object_revision"]):
        raise IntegrityError("page collection content revision changed")
    start, end, total = selection["start"], selection["end"], len(collection["atoms"])
    _require(type(start) is int and 0 <= start < total, "page start is outside its collection")
    _require((pending and end is None) or (type(end) is int and start < end <= total),
             "page end is outside its collection")
    return collection


def _page(selection, collection):
    start, end = selection["start"], selection["end"]
    atoms = deepcopy(collection["atoms"][start:end])
    return {"selection": deepcopy(selection), "kind": collection["kind"],
            "total": len(collection["atoms"]), "start": start, "end": end,
            "has_more": end < len(collection["atoms"]), "atoms": atoms,
            "content_hash": digest(atoms)}


def rebuild_selection(catalog, selection, *, scope, run_id):
    """Rebuild exactly the committed nonempty range, without authorizing it."""
    prepared = _prepared(catalog, scope, run_id)
    collection = _checked_selection(catalog, selection, prepared)
    return _page(selection, collection)


def _base_view(catalog, prepared, *, scope, run_id, stage, revisions, verification_ready):
    request, payload, objects, counts = prepared
    _require(type(stage) is str and stage in STAGES, "invalid window stage")
    _require(type(verification_ready) is bool, "invalid window verification readiness")
    summaries = []
    for observation in payload["observations"]:
        ref = "O:" + observation["tool"]
        summary = {"ref": ref, "kind": observation["kind"],
                   "object_revision": catalog["index"][ref]["sha256"]}
        if "status" in observation:
            summary["status"] = observation["status"]
        if observation["kind"] == "derived":
            summary["counts"] = {key: len(observation[key]) for key in ("facts", "evidence", "hypotheses")}
            summary["event_anchor_ref"] = {"object_ref": ref, "path": ["event_anchor"],
                "content_hash": digest(observation["event_anchor"])}
        if "gaps" in observation:
            summary["gaps_ref"] = {"object_ref": ref, "path": ["gaps"],
                "count": len(observation["gaps"]), "content_hash": digest(observation["gaps"])}
        if observation["kind"] == "source_read":
            summary["datasets"] = [{"dataset": name, "status": item["status"],
                "records": item["records"], "source_result_ref": item["source_result_ref"],
                "periods_ref": {"object_ref": ref, "path": ["datasets", name, "periods"],
                                "count": len(item["periods"]), "content_hash": digest(item["periods"])}}
                for name, item in sorted(observation["datasets"].items())]
        elif observation["kind"] == "verification":
            # The fixed verification result contains actual execution feedback.
            summary["result"] = deepcopy(observation["result"])
        summaries.append(summary)
    collections = {kind: _collection(catalog, prepared, kind) for kind in KINDS - {"objects"}}
    base = {"schema": WINDOW_SCHEMA, "policy_version": WINDOW_POLICY,
        "catalog_ref": catalog["catalog_ref"],
        "binding_ref": digest({"scope": scope, "run_id": run_id, "request_ref": catalog["request_ref"]}),
        "range": {"security": request.security.canonical_symbol, "cutoff": request.as_of.isoformat(),
            "pit_mode": request.mode.value, "objective": request.objective,
            "bound_windows": {binding.dataset: [binding.start.isoformat(), binding.end.isoformat()]
                              for binding in request.bindings},
            "bindings": {binding.dataset: {"provider": binding.provider, "snapshot_ref": binding.snapshot}
                         for binding in request.bindings}, "declared_hypotheses": list(request.hypotheses)},
        "required_checks": deepcopy(payload["required_checks"]), "stage": stage,
        "state_versions": encode_state_versions(revisions), "counts": counts,
        "observations": summaries, "atom_columns": ATOM_COLUMNS,
        "collections": {kind: {"count": len(collection["atoms"]),
                               "collection_ref": collection["collection_ref"]}
                        for kind, collection in sorted(collections.items())},
        "coverage": "not_verified", "causal_claim": False}
    if verification_ready:
        _require(stage == "verification" and revisions["source"] is not None
                 and revisions["source"] == revisions["calculated"] == revisions["hypotheses"]
                 and revisions["verified"] != revisions["source"], "invalid window verification readiness")
        base["verification_brief"] = _verification_brief(catalog,
            build_verification_audit(catalog, scope=scope, run_id=run_id, execution_revisions=revisions))
    return base, collections


def _allowed_refs(base, pages):
    refs = {item["ref"] for item in base["observations"]}
    for page in pages:
        for ref, path, kind, value in page["atoms"]:
            if ref == "D:catalog":
                refs.add(value["ref"])
            else:
                refs.add(ref)
                # Exact disclosed IDs within a parent Observation are also known.
                if ref.startswith("O:") and len(path) >= 2 and path[0] in {"facts", "evidence", "hypotheses"}:
                    refs.add({"facts": "C:", "evidence": "E:", "hypotheses": "H:"}[path[0]] + path[1])
                if kind == "v" and type(value) is str:
                    if ((ref.startswith("C:") and len(path) == 2 and path[0] == "evidence_ids")
                            or (ref.startswith("O:") and len(path) == 4
                                and path[0] == "facts" and path[2] == "evidence_ids")):
                        refs.add("E:" + value)
                    if ((ref.startswith("H:") and len(path) == 2
                         and path[0] in {"claim_ids", "counterevidence_claim_ids"})
                            or (ref.startswith("O:") and len(path) == 4
                                and path[0] == "hypotheses"
                                and path[2] in {"claim_ids", "counterevidence_claim_ids"})):
                        refs.add("C:" + value)
    brief = base.get("verification_brief")
    if brief:
        refs.update([brief["computed_ref"], *brief["source_refs"]])
    return sorted(refs)


def _assemble(catalog, base, pages, collections, *, scope, run_id, revisions, verification_ready, read_enabled,
              dispatch_ref):
    clean_pages = [{key: deepcopy(value) for key, value in page.items() if key != "next_cursor"} for page in pages]
    clean_view = {**deepcopy(base), "pages": clean_pages}
    core = {"schema": WINDOW_DESCRIPTOR_SCHEMA, "policy_version": WINDOW_POLICY,
        "scope_ref": digest(scope), "run_id": run_id, "request_ref": catalog["request_ref"],
        "catalog_ref": catalog["catalog_ref"], "stage": base["stage"],
        "execution_revisions": deepcopy(revisions), "verification_ready": verification_ready,
        "read_enabled": read_enabled, "counts": deepcopy(base["counts"]),
        "pages": [{"selection": deepcopy(page["selection"]), "content_hash": page["content_hash"]}
                  for page in clean_pages], "allowed_refs": _allowed_refs(base, clean_pages) if read_enabled else [],
        "view_ref": digest(clean_view), "dispatch_ref": dispatch_ref}
    window_ref = digest(core)
    cursors = {}

    def issue(selection):
        token = digest({"schema": CURSOR_SCHEMA, "policy_version": WINDOW_POLICY,
            "scope_ref": digest(scope), "run_id": run_id, "request_ref": catalog["request_ref"],
            "catalog_ref": catalog["catalog_ref"], "window_ref": window_ref, "selection": selection})
        cursors[token] = deepcopy(selection)
        return token

    view = {**clean_view, "window_ref": window_ref}
    represented = set()
    for page in view["pages"]:
        represented.add(page["kind"])
        if read_enabled and page["has_more"]:
            selection = {**page["selection"], "start": page["end"], "end": None}
            page["next_cursor"] = issue(selection)
    if read_enabled:
        # Every omitted collection has a precise entry, including a directory
        # larger than the current model window. No full list of IDs is resident.
        for kind, collection in sorted(collections.items()):
            if kind not in represented and collection["atoms"]:
                view["collections"][kind]["cursor"] = issue(_selection(catalog, collection))
    descriptor = {**core, "window_ref": window_ref, "allowed_cursors": sorted(cursors), "cursors": cursors}
    return view, descriptor


def compile_window(catalog, *, scope, run_id, stage=None, current_stage=None,
                   execution_revisions, verification_ready, render, selection=None,
                   max_bytes=12000, read_enabled=True, check=None, admission_render=None,
                   requested_capacity=None):
    """Compile deterministic pages against *actual* system and user messages.

    ``render(view)`` returns the final message list.  Committed selection ends are
    immutable: a later larger header fails instead of silently shortening a page.
    At most one exact requested slice, then current facts/hypotheses and a
    directory preview are loaded.  Each search is bounded by the catalogue size.
    Explicit ``requested_capacity="actual"`` admits the requested page against
    its encoded messages, while automatic previews retain the positive increase
    in the legacy envelope.  The default retains the original whole-envelope
    admission rule exactly.
    """
    _require(callable(render) and (admission_render is None or callable(admission_render))
             and type(max_bytes) is int and max_bytes > 0
             and type(read_enabled) is bool
             and (requested_capacity is None or type(requested_capacity) is str
                  and requested_capacity == "actual"), "invalid context window compilation options")
    if current_stage is not None:
        _require(stage is None or stage == current_stage, "conflicting window stage")
        stage = current_stage
    revisions = validate_execution_revisions(execution_revisions)
    prepared = _prepared(catalog, scope, run_id, check)
    base, collections = _base_view(catalog, prepared, scope=scope, run_id=run_id,
        stage=stage, revisions=revisions, verification_ready=verification_ready)
    # Bind the actual system/control/decision/plan/budget/error header.  This
    # deliberately excludes the self window hash, cursor tokens and wire hash.
    # Consequently a token from a previous paid turn cannot become current
    # merely because the catalogue and displayed page happen to be unchanged.
    dispatch_ref = digest(render({**deepcopy(base), "pages": []}))
    pages = []

    def build(candidate):
        _call(check)
        view, descriptor = _assemble(catalog, base, candidate, collections, scope=scope,
            run_id=run_id, revisions=revisions, verification_ready=verification_ready, read_enabled=read_enabled,
            dispatch_ref=dispatch_ref)
        messages = render(view)
        _require(type(messages) is list and all(type(item) is dict
                 and type(item.get("content")) is str for item in messages), "invalid rendered window messages")
        size = sum(len(item["content"].encode("utf-8")) for item in messages)
        actual_size = size
        if admission_render is not None:
            # New callers can retain the prior literal working-set envelope.
            # This layout probe is not a dispatch or a read. Cursor identity
            # continues to bind render(), the actual outgoing coded header.
            admitted = admission_render(view)
            _require(type(admitted) is list and all(type(item) is dict
                     and type(item.get("content")) is str for item in admitted),
                     "invalid window admission messages")
            admission_size = sum(len(item["content"].encode("utf-8")) for item in admitted)
            if requested_capacity == "actual" and selection is not None and len(candidate) <= 1:
                size = actual_size
            elif requested_capacity == "actual" and selection is not None:
                # Candidate zero is always the explicit request; subsequent
                # pages are automatic previews. Do not spend codec savings on
                # those previews or let their literal envelope shrink the
                # already fitted request. Assemble the selected-only frame so
                # cursor/collection overhead is measured in both representations.
                requested_view, _ = _assemble(catalog, base, candidate[:1], collections, scope=scope,
                    run_id=run_id, revisions=revisions, verification_ready=verification_ready,
                    read_enabled=read_enabled, dispatch_ref=dispatch_ref)
                requested_messages = render(requested_view)
                _require(type(requested_messages) is list and all(type(item) is dict
                         and type(item.get("content")) is str for item in requested_messages),
                         "invalid rendered requested window messages")
                requested_admission = admission_render(requested_view)
                _require(type(requested_admission) is list and all(type(item) is dict
                         and type(item.get("content")) is str for item in requested_admission),
                         "invalid requested window admission messages")
                requested_size = sum(len(item["content"].encode("utf-8")) for item in requested_messages)
                requested_admission_size = sum(len(item["content"].encode("utf-8"))
                                               for item in requested_admission)
                size = max(size, requested_size + max(0, admission_size - requested_admission_size))
            else:
                size = max(size, admission_size)
        return size, view, descriptor, actual_size

    if build([])[0] > max_bytes:
        raise ContextMinimumViewExceeded("context minimum control window exceeds byte budget")

    def add(selected, collection, mandatory):
        if selected["end"] is not None:
            page = _page(selected, collection)
            if build([*pages, page])[0] > max_bytes:
                raise ContextMinimumViewExceeded("committed context page exceeds actual next window budget")
            pages.append(page)
            return selected
        start, total = selected["start"], len(collection["atoms"])
        # Full completion has no continuation token and may be a little smaller
        # than its predecessor. Try it before the monotone partial-range search.
        full = {**selected, "end": total}
        if build([*pages, _page(full, collection)])[0] <= max_bytes:
            pages.append(_page(full, collection))
            return full
        first = {**selected, "end": start + 1}
        if build([*pages, _page(first, collection)])[0] > max_bytes:
            if mandatory:
                raise ContextMinimumViewExceeded("minimum indivisible context page item exceeds byte budget")
            return None
        low, high = start + 1, total - 1
        while low < high:
            _call(check)
            middle = (low + high + 1) // 2
            candidate = {**selected, "end": middle}
            if build([*pages, _page(candidate, collection)])[0] <= max_bytes:
                low = middle
            else:
                high = middle - 1
        selected = {**selected, "end": low}
        pages.append(_page(selected, collection))
        return selected

    selected = None
    if selection is not None:
        collection = _checked_selection(catalog, selection, prepared, check, pending=True)
        selected = add(deepcopy(selection), collection, True)
    for kind in ("facts", "hypotheses", "directory"):
        if collections[kind]["atoms"] and not any(page["kind"] == kind for page in pages):
            add(_selection(catalog, collections[kind]), collections[kind],
                mandatory=kind == "facts" and selection is None)
    size, view, descriptor, actual_size = build(pages)
    _require(size <= max_bytes, "compiled context window exceeds actual byte budget")
    visible = set()
    for page in pages:
        for ref, path, kind, value in page["atoms"]:
            if ref.startswith("O:") and len(path) >= 2 and path[0] in {"facts", "evidence", "hypotheses"}:
                ref = {"facts": "C:", "evidence": "E:", "hypotheses": "H:"}[path[0]] + path[1]
            visible.add(ref)
    return view, {"window": descriptor, "window_selection": selected, "bytes": actual_size,
        "visible_fact_count": sum(ref.startswith("C:") for ref in visible),
        "visible_evidence_count": sum(ref.startswith("E:") for ref in visible)}


def rebuild_window(catalog, descriptor, *, scope, run_id, render=None):
    """Strictly rebuild a paid window from its bound descriptor and catalogue."""
    _require(type(descriptor) is dict and set(descriptor) == _DESCRIPTOR_CORE_KEYS | {
        "window_ref", "allowed_cursors", "cursors"} and descriptor["schema"] == WINDOW_DESCRIPTOR_SCHEMA
        and descriptor["policy_version"] == WINDOW_POLICY, "invalid window descriptor schema")
    prepared = _prepared(catalog, scope, run_id)
    if (descriptor["scope_ref"] != digest(scope) or descriptor["run_id"] != run_id
            or descriptor["catalog_ref"] != catalog["catalog_ref"]
            or descriptor["request_ref"] != catalog["request_ref"]):
        raise PermissionDenied("context window belongs to a different scope, run, request or catalogue")
    revisions = validate_execution_revisions(descriptor["execution_revisions"])
    _require(type(descriptor["read_enabled"]) is bool, "invalid window reading policy")
    base, collections = _base_view(catalog, prepared, scope=scope, run_id=run_id,
        stage=descriptor["stage"], revisions=revisions, verification_ready=descriptor["verification_ready"])
    _require(_hash(descriptor["dispatch_ref"]), "invalid window dispatch header binding")
    if render is not None:
        _require(callable(render), "invalid window descriptor render callback")
        if digest(render({**deepcopy(base), "pages": []})) != descriptor["dispatch_ref"]:
            raise IntegrityError("context window dispatch header changed")
    _require(type(descriptor["pages"]) is list and len(descriptor["pages"]) <= 4,
             "invalid bounded window page list")
    pages = []
    for item in descriptor["pages"]:
        _require(type(item) is dict and set(item) == {"selection", "content_hash"}, "invalid window page descriptor")
        collection = _checked_selection(catalog, item["selection"], prepared)
        page = _page(item["selection"], collection)
        if item["content_hash"] != page["content_hash"]:
            raise IntegrityError("context window page content changed")
        pages.append(page)
    view, expected = _assemble(catalog, base, pages, collections, scope=scope, run_id=run_id,
        revisions=revisions, verification_ready=descriptor["verification_ready"], read_enabled=descriptor["read_enabled"],
        dispatch_ref=descriptor["dispatch_ref"])
    if expected != descriptor:
        raise IntegrityError("context window descriptor differs from its exact catalogue projection")
    return view


def validate_window_descriptor(catalog, descriptor, *, scope, run_id):
    rebuild_window(catalog, descriptor, scope=scope, run_id=run_id)
    return deepcopy(descriptor)


def select_next(catalog, action, issued_window, *, scope, run_id):
    """Accept only members or tokens issued in the caller's current paid window."""
    validate_window_descriptor(catalog, issued_window, scope=scope, run_id=run_id)
    _require(type(action) is dict and action.get("action") == "context_read"
             and set(action) in ({"action", "catalog_ref", "cursor", "plan"},
                                 {"action", "catalog_ref", "refs", "plan"}), "invalid context page read action")
    if action["catalog_ref"] != catalog["catalog_ref"]:
        raise PermissionDenied("context page read uses a different catalogue")
    _require(issued_window["read_enabled"], "context page read has no required business headroom")
    if "cursor" in action:
        _require(_hash(action["cursor"]) and action["cursor"] in issued_window["allowed_cursors"],
                 "context cursor was not issued in the current paid window")
        return deepcopy(issued_window["cursors"][action["cursor"]])
    refs = action["refs"]
    _require(type(refs) is list and 1 <= len(refs) <= MAX_REFS and all(type(ref) is str for ref in refs)
             and len(refs) == len(set(refs)) and set(refs) <= set(issued_window["allowed_refs"]),
             "context references were not issued in the current paid window")
    prepared = _prepared(catalog, scope, run_id)
    return _selection(catalog, _collection(catalog, prepared, "objects", sorted(refs)))


def _coverage_members(catalog, page):
    members = {}
    for ref, path, kind, value in page["atoms"]:
        if ref == "D:catalog":
            ref, path, revision = "D:catalog", [value["ref"]], catalog["catalog_ref"]
        else:
            if ref.startswith("O:") and len(path) >= 2 and path[0] in {"facts", "evidence", "hypotheses"}:
                ref = {"facts": "C:", "evidence": "E:", "hypotheses": "H:"}[path[0]] + path[1]
                path = path[2:]
            revision = catalog["index"][ref]["sha256"]
        key = (ref, revision)
        members.setdefault(key, {})[canonical_json(path)] = deepcopy(path)
    return members


def _checked_coverage(coverage):
    _require(type(coverage) is list, "invalid context read coverage")
    result = {}
    for item in coverage:
        _require(type(item) is dict and set(item) == {"ref", "object_revision", "paths"}
                 and type(item["ref"]) is str and _hash(item["object_revision"])
                 and type(item["paths"]) is list and all(type(path) is list
                 and all(type(part) in {str, int} for part in path) for path in item["paths"]),
                 "invalid context read coverage member")
        key = (item["ref"], item["object_revision"])
        _require(key not in result, "duplicate context read coverage object")
        paths = {canonical_json(path): deepcopy(path) for path in item["paths"]}
        _require(len(paths) == len(item["paths"]) and item["paths"] == [paths[key] for key in sorted(paths)],
                 "noncanonical context read coverage paths")
        result[key] = paths
    _require(coverage == [{"ref": ref, "object_revision": revision,
        "paths": [result[(ref, revision)][key] for key in sorted(result[(ref, revision)])]}
        for ref, revision in sorted(result)], "noncanonical context read coverage objects")
    return result


def coverage_progress(catalog, selection, coverage, *, scope, run_id):
    """New object members, rather than different page hashes, establish progress."""
    old = _checked_coverage(coverage)
    members = _coverage_members(catalog, rebuild_selection(catalog, selection, scope=scope, run_id=run_id))
    return any(set(paths) - set(old.get(key, {})) for key, paths in members.items())


def merge_coverage(catalog, selection, coverage, *, scope, run_id):
    result = _checked_coverage(coverage)
    members = _coverage_members(catalog, rebuild_selection(catalog, selection, scope=scope, run_id=run_id))
    for key, paths in members.items():
        result.setdefault(key, {}).update(paths)
    return [{"ref": ref, "object_revision": revision,
             "paths": [result[(ref, revision)][key] for key in sorted(result[(ref, revision)])]}
            for ref, revision in sorted(result)]


def expand_window_view(view):
    """Decode only message-local revisions; page contents stay literal and exact."""
    _require(type(view) is dict and view.get("schema") == WINDOW_SCHEMA
             and set(view) in (_WINDOW_VIEW_KEYS, _WINDOW_VIEW_KEYS | {"verification_brief"})
             and view.get("policy_version") == WINDOW_POLICY and _hash(view.get("window_ref"))
             and _hash(view.get("catalog_ref")) and _hash(view.get("binding_ref"))
             and type(view.get("stage")) is str and view["stage"] in STAGES
             and view.get("coverage") == "not_verified" and view.get("causal_claim") is False
             and view.get("atom_columns") == ATOM_COLUMNS
             and type(view.get("pages")) is list and len(view["pages"]) <= 4,
             "invalid exact window view schema")
    for page in view["pages"]:
        _require(type(page) is dict and set(page) in ({"selection", "kind", "total", "start", "end",
            "has_more", "atoms", "content_hash"}, {"selection", "kind", "total", "start", "end",
            "has_more", "atoms", "content_hash", "next_cursor"}), "invalid exact window page schema")
        _require(type(page["kind"]) is str and page["kind"] in KINDS
                 and type(page["selection"]) is dict and set(page["selection"]) == _SELECTION_KEYS
                 and page["selection"]["schema"] == SELECTION_SCHEMA
                 and page["selection"]["catalog_ref"] == view["catalog_ref"]
                 and page["selection"]["kind"] == page["kind"]
                 and type(page["start"]) is int and type(page["end"]) is int
                 and type(page["total"]) is int and 0 <= page["start"] < page["end"] <= page["total"]
                 and page["selection"]["start"] == page["start"] and page["selection"]["end"] == page["end"]
                 and type(page["has_more"]) is bool and page["has_more"] == (page["end"] < page["total"])
                 and type(page["atoms"]) is list and len(page["atoms"]) == page["end"] - page["start"],
                 "invalid exact window page interval")
        if "next_cursor" in page:
            _require(page["has_more"] and _hash(page["next_cursor"]), "invalid exact window page continuation")
        for atom in page["atoms"]:
            _require(type(atom) is list and len(atom) == 4 and type(atom[0]) is str
                     and type(atom[1]) is list and all(type(part) in {str, int} for part in atom[1])
                     and type(atom[2]) is str and atom[2] in {"d", "l", "v", "summary"},
                     "invalid exact window atom")
        if not _hash(page["content_hash"]) or digest(page["atoms"]) != page["content_hash"]:
            raise IntegrityError("exact window page content hash changed")
    result = deepcopy(view)
    result["state_versions"] = decode_state_versions(view["state_versions"])
    return result


def restore_object_atoms(atoms):
    """Decode complete canonical object pages and reject holes/reordering/duplicates."""
    _require(type(atoms) is list and atoms, "empty exact object atom stream")
    grouped = {}
    for atom in atoms:
        _require(type(atom) is list and len(atom) == 4 and type(atom[0]) is str
                 and type(atom[1]) is list and all(type(part) in {str, int} for part in atom[1])
                 and atom[2] in {"d", "l", "v"}, "invalid exact object atom")
        grouped.setdefault(atom[0], []).append(atom)
    result = {}
    for ref, values in grouped.items():
        entries = {}
        children_by_parent = {}
        for _, path, kind, value in values:
            key = canonical_json(path)
            _require(key not in entries, "duplicate exact object atom path")
            entries[key] = (path, kind, value)
            if path:
                children_by_parent.setdefault(canonical_json(path[:-1]), []).append(path[-1])

        def unpack(path):
            key = canonical_json(path)
            _require(key in entries, "incomplete exact object atom stream")
            _, kind, value = entries[key]
            if kind == "v":
                _require(value is None or type(value) in {str, int, bool}, "invalid exact scalar atom")
                return deepcopy(value)
            _require(type(value) is int and value >= 0, "invalid exact container atom size")
            children = children_by_parent.get(key, [])
            _require(len(children) == value, "exact object container member count differs")
            if kind == "l":
                _require(all(type(child) is int for child in children) and sorted(children) == list(range(value)),
                         "exact array atom indices are not complete")
                return [unpack([*path, position]) for position in range(value)]
            _require(all(type(child) is str for child in children), "exact object atom key is not text")
            return {child: unpack([*path, child]) for child in sorted(children)}

        result[ref] = unpack([])
        if list(_atoms(ref, result[ref])) != values:
            raise IntegrityError("exact object atom stream is noncanonical or has orphan members")
    return result
