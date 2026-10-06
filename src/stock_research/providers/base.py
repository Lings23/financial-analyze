from dataclasses import dataclass
from typing import Protocol

from ..errors import PermissionDenied, ProviderSchemaError, ValidationError
from ..models import AccessContext, DataRecord, DataRequest, Dataset


@dataclass(frozen=True)
class ProviderCapability:
    name: str
    version: str
    datasets: frozenset[Dataset]
    bases: frozenset[str]
    historical_release_verified: bool = False


class Provider(Protocol):
    capability: ProviderCapability

    def fetch(self, request: DataRequest, scope: str, timeout: float) -> tuple[DataRecord, ...]: ...


def validate_records(provider, request, records):
    from ..domains import DomainRecord
    if not isinstance(records, tuple):
        raise ProviderSchemaError("provider must return an immutable record tuple")
    for record in records:
        if (not isinstance(record, (DataRecord, DomainRecord))
                or record.provider != provider.capability.name
                or record.provider_version != provider.capability.version
                or record.security_id != request.security.security_id
                or record.canonical_symbol != request.security.canonical_symbol
                or record.dataset != request.dataset or record.basis != request.basis
                or not request.start <= record.period <= request.end):
            raise ProviderSchemaError("normalized record violates provider contract")
        if hasattr(request, "matches") and not request.matches(record):
            raise ProviderSchemaError("normalized record violates domain selector")
        if record.availability_basis in {"verified_release", "verified_release_date"} and not provider.capability.historical_release_verified:
            raise ProviderSchemaError("provider has not qualified for historical release evidence")


class ProviderRegistry:
    def __init__(self):
        self._providers = {}

    def register(self, provider: Provider):
        name = provider.capability.name
        if name in self._providers:
            raise ValidationError("duplicate provider name")
        self._providers[name] = provider

    def resolve(self, name: str, request: DataRequest, access: AccessContext) -> Provider:
        if name not in access.allowed_providers:
            raise PermissionDenied("provider not authorized")
        if name not in self._providers:
            raise ValidationError("provider not registered")
        provider = self._providers[name]
        if (request.dataset not in provider.capability.datasets
                or request.basis not in provider.capability.bases):
            raise ValidationError("provider does not support requested dataset and basis")
        return provider
