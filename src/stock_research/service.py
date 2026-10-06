import time
from dataclasses import replace

from .errors import IntegrityError, PermissionDenied, ProviderSchemaError, ProviderUnavailable, TransientProviderError, ValidationError
from .models import IngestionResult, utcnow
from .providers.base import validate_records
from .temporal import select_records


class DataService:
    """Separate current ingestion from cutoff-constrained snapshot queries.

    Business tools will depend on this layer, not on provider implementation classes.
    """

    def __init__(self, registry, executor, repository, artifacts):
        self.registry = registry
        self.executor = executor
        self.repository = repository
        self.artifacts = artifacts

    def refresh(self, request, access, provider_order=("tushare",), parent_snapshot_id=None, use_cache=True):
        if not provider_order or len(set(provider_order)) != len(provider_order):
            raise ValidationError("explicit unique provider priority list required")
        # Validate the entire configured chain before doing network work.
        providers = [self.registry.resolve(name, request, access) for name in provider_order]
        if parent_snapshot_id:
            self.repository.snapshot(access.scope, parent_snapshot_id)
        failures = []
        deadline = time.monotonic() + self.executor.policy.total_timeout
        for provider in providers:
            try:
                records = self.executor.fetch(provider, request, access, use_cache,
                                              timeout=deadline - time.monotonic())
                validate_records(provider, request, records)
                for record in records:
                    for aid in getattr(record, "artifact_ids", (record.artifact_id,)):
                        self.artifacts.get(access.scope, aid)
            except (TransientProviderError, ProviderSchemaError) as exc:
                failures.append(f"{provider.capability.name}:{type(exc).__name__}")
                continue
            # Capture time is not system ingestion time. Cached observations retain the
            # first ingestion stored by the repository under their stable content ID.
            ingested_at = utcnow()
            records = tuple(replace(record, ingested_at=ingested_at) for record in records)
            snapshot = self.repository.commit(access.scope, records, parent_snapshot_id)
            warnings = tuple(failures) + (("empty_response_coverage_unknown",) if not records else ())
            return IngestionResult(snapshot, provider.capability.name, len(records), warnings)
        raise ProviderUnavailable("configured compatible providers failed: " + ", ".join(failures))

    def query(self, request, context):
        records = self.repository.read(context.access.scope, context.snapshot_id)
        result = select_records(records, request, context)
        # Missing/corrupt evidence is fatal, not a warning on an apparently verified result.
        for record in result.records:
            try:
                for aid in getattr(record, "artifact_ids", (record.artifact_id,)):
                    self.artifacts.get(context.access.scope, aid)
            except FileNotFoundError:
                raise IntegrityError("visible record has no archived source") from None
        return result

    def evidence(self, request, context, record_id, artifact_id=None):
        """Resolve bytes only through a visible authorized snapshot record."""
        result = self.query(request, context)
        record = next((r for r in result.records if r.record_id == record_id), None)
        if record is None:
            raise PermissionDenied("evidence record is not visible in this query")
        permitted = getattr(record, "artifact_ids", (record.artifact_id,))
        aid = artifact_id or record.artifact_id
        if aid not in permitted:
            raise PermissionDenied("evidence is not linked to the visible record")
        return self.artifacts.get(context.access.scope, aid)
