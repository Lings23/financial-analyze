from .errors import IntegrityError
from .models import DataRecord, DataRequest, PITMode, QueryContext, QueryResult, canonical_json


def select_records(records: tuple[DataRecord, ...], request: DataRequest,
                   context: QueryContext) -> QueryResult:
    """Filter BEFORE selecting latest revision; never filter a current-only view."""
    groups = {}
    warnings = {"coverage_not_verified"}
    blocked = 0
    for record in records:
        if (record.provider not in context.access.allowed_providers
                or record.security_id != request.security.security_id
                or record.dataset != request.dataset
                or record.basis != request.basis
                or not request.start <= record.period <= request.end):
            continue
        if hasattr(request, "matches") and not request.matches(record):
            continue
        if (record.available_at > context.as_of_date
                or (context.mode == PITMode.SYSTEM and record.ingested_at > context.as_of_date)):
            blocked += 1
            continue
        groups.setdefault(record.fact_key, []).append(record)
    chosen = []
    for versions in groups.values():
        best_rank = max((r.available_at, r.revision_order) for r in versions)
        best = [r for r in versions if (r.available_at, r.revision_order) == best_rank]
        signatures = {canonical_json(r.value_signature if hasattr(r, "value_signature") else
                                     {"metrics": r.to_dict()["metrics"]}) for r in best}
        if len(signatures) != 1:
            raise IntegrityError("ambiguous revisions at the same visibility time")
        chosen.append(min(best, key=lambda r: (r.ingested_at, r.record_id)))
    chosen.sort(key=lambda r: (r.period, r.provider, r.record_id))
    if blocked:
        warnings.add("records_excluded_by_pit")
    if len({r.provider for r in chosen}) > 1:
        warnings.add("multiple_sources_not_automatically_reconciled")
    for record in chosen:
        warnings.update(record.quality_flags)
        if record.availability_basis == "observed_at":
            warnings.add("historical_release_not_verified")
        elif record.availability_basis == "verified_release_date":
            warnings.add("release_date_conservative_boundary")
        if any(m.value is None for m in record.metrics):
            warnings.add("missing_values")
    status = "available" if chosen else "no_visible_data"
    return QueryResult(status, tuple(chosen), context.snapshot_id, context.as_of_date,
                       tuple(sorted(warnings)))
