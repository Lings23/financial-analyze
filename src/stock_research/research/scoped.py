"""Read-only composition through explicit, revocable application source grants.

No copying between namespaces and no model-provided permissions. Every read,
including evidence and replay, resolves the current grants before touching data.
"""
from dataclasses import dataclass

from ..errors import PermissionDenied
from ..models import AccessContext, QueryContext


@dataclass(frozen=True)
class SourceGrant:
    service: object
    access: AccessContext
    snapshot: str
    request: object
    provider: str


class ScopedReadService:
    def __init__(self, recipient_scope, current_grants):
        # current_grants belongs to the trusted application, never a request/LLM.
        self.recipient_scope = recipient_scope
        self.current_grants = current_grants

    def _resolve(self, request, context):
        if context.access.scope != self.recipient_scope:
            raise PermissionDenied("composed reader recipient is not authorized")
        matches = [g for g in self.current_grants()
                   if g.snapshot == context.snapshot_id and g.request == request
                   and g.provider in context.access.allowed_providers
                   and g.provider in g.access.allowed_providers]
        if len(matches) != 1:
            raise PermissionDenied("explicit source grant is missing or ambiguous")
        grant = matches[0]
        narrowed = AccessContext(grant.access.scope, frozenset({grant.provider}))
        return grant.service, QueryContext(narrowed, grant.snapshot, context.as_of_date, context.mode)

    def query(self, request, context):
        service, source_context = self._resolve(request, context)
        return service.query(request, source_context)

    def evidence(self, request, context, record_id, artifact_id=None):
        service, source_context = self._resolve(request, context)
        return service.evidence(request, source_context, record_id, artifact_id)
