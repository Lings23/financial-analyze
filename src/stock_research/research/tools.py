from dataclasses import dataclass
from types import MappingProxyType

from ..errors import IntegrityError, PermissionDenied, ValidationError
from ..models import AccessContext, QueryContext, digest
from .contracts import DOMAINS, TOOLS


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str = "1"
    read_only: bool = True
    input_contract: str = "ResearchRequest/v1; no model-supplied scope or arguments"


class ToolRegistry:
    def __init__(self):
        self.tools = MappingProxyType({name: ToolSpec(name) for name in TOOLS})

    def authorize(self, name, spec, granted):
        if name not in self.tools:
            raise ValidationError("unknown research tool")
        if name not in spec.visible_tools & spec.allowed_tools & granted:
            raise PermissionDenied("research tool is not authorized")
        return self.tools[name]


def read_domain(service, request, access, name):
    """One aggregated tool, explicit single source per dataset, no network refresh."""
    results = {}
    for binding in request.bindings:
        if DOMAINS[binding.dataset] != name:
            continue
        if binding.provider not in access.allowed_providers:
            raise PermissionDenied("research binding provider is not authorized")
        narrowed = AccessContext(access.scope, frozenset({binding.provider}))
        context = QueryContext(narrowed, binding.snapshot, request.as_of, request.mode)
        result = service.query(request.data_request(binding), context)
        if len(result.records) > 1000:
            raise ValidationError("research tool result exceeds row budget")
        rows = [r.to_dict() for r in result.records]
        # A series must never blend conflicting facts from multiple revisions or sources.
        if binding.dataset not in {"announcement", "news_recent"}:
            periods = [r["period"] for r in rows]
            if len(periods) != len(set(periods)):
                raise IntegrityError("research series contains duplicate periods")
        results[binding.dataset] = {"snapshot": binding.snapshot, "provider": binding.provider,
                                    "status": result.status, "warnings": list(result.warnings),
                                    "coverage": result.coverage, "records": rows,
                                    "start": binding.start.isoformat(), "end": binding.end.isoformat()}
    return results


class ToolExecutor:
    """Run-local same-wave memoization. Reauthorization/hash checks precede every reuse."""
    def __init__(self, service, registry, spec, granted, request, access):
        self.service, self.registry, self.spec = service, registry, spec
        self.granted, self.request, self.access = granted, request, access
        self._wave = {}

    def execute(self, name, wave="fixed-plan"):
        tool = self.registry.authorize(name, self.spec, self.granted)
        key = digest({"tool": name, "version": tool.version, "request": self.request.to_dict(),
                      "scope": self.access.scope, "providers": sorted(self.access.allowed_providers), "wave": wave})
        # The data layer is local and immutable. Re-read validates current authorization and bytes;
        # only the aggregation is reused. This is not a cross-process or provider-call cache.
        fresh = read_domain(self.service, self.request, self.access, name)
        reused = key in self._wave
        if reused and self._wave[key] != fresh:
            raise IntegrityError("immutable research result changed")
        self._wave[key] = fresh
        return fresh, reused
