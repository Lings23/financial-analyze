from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

from .errors import ValidationError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValidationError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class Dataset(str, Enum):
    MARKET_DAILY = "market_daily"
    FINANCIAL_INCOME = "financial_income"


class PITMode(str, Enum):
    PUBLIC = "public"
    SYSTEM = "system"


BASES = {
    Dataset.MARKET_DAILY: "unadjusted_daily",
    Dataset.FINANCIAL_INCOME: "consolidated_cumulative_cny",
}
METRICS = {
    Dataset.MARKET_DAILY: frozenset({"open", "high", "low", "close", "volume", "amount"}),
    Dataset.FINANCIAL_INCOME: frozenset({"revenue", "total_revenue", "net_income_parent"}),
}


@dataclass(frozen=True)
class Security:
    symbol: str
    exchange: str
    instrument_type: str = "equity"
    company_name: str | None = None

    def __post_init__(self):
        if not re.fullmatch(r"\d{6}", self.symbol) or self.exchange not in {"SSE", "SZSE", "BSE"}:
            raise ValidationError("explicit six-digit symbol and supported exchange required")
        if self.instrument_type != "equity":
            raise ValidationError("first adapter supports equities only")

    @property
    def canonical_symbol(self) -> str:
        return f"{self.exchange}:{self.symbol}"

    @property
    def security_id(self) -> str:
        return f"CN:{self.instrument_type}:{self.canonical_symbol}"

    @property
    def provider_symbol(self) -> str:
        return f"{self.symbol}.{ {'SSE': 'SH', 'SZSE': 'SZ', 'BSE': 'BJ'}[self.exchange]}"


@dataclass(frozen=True)
class DataRequest:
    security: Security
    dataset: Dataset
    start: date
    end: date

    def __post_init__(self):
        if not isinstance(self.dataset, Dataset):
            raise ValidationError("dataset must be a Dataset")
        if type(self.start) is not date or type(self.end) is not date or self.start > self.end:
            raise ValidationError("valid inclusive date window required")
        # Small bounded requests make row-limit truncation detectable and avoid unbounded fetching.
        if (self.end - self.start).days > 366:
            raise ValidationError("request window must not exceed 366 days; split explicitly")

    @property
    def basis(self) -> str:
        return BASES[self.dataset]

    def identity(self) -> dict:
        return {"security_id": self.security.security_id, "dataset": self.dataset.value,
                "start": self.start.isoformat(), "end": self.end.isoformat(), "basis": self.basis}


@dataclass(frozen=True)
class AccessContext:
    """Constructed by the trusted application, never accepted from model arguments."""
    scope: str
    allowed_providers: frozenset[str]

    def __post_init__(self):
        if not self.scope or not self.allowed_providers:
            raise ValidationError("scope and provider permissions required")
        object.__setattr__(self, "allowed_providers", frozenset(self.allowed_providers))


@dataclass(frozen=True)
class QueryContext:
    access: AccessContext
    snapshot_id: str
    as_of_date: datetime
    mode: PITMode = PITMode.PUBLIC

    def __post_init__(self):
        object.__setattr__(self, "as_of_date", aware(self.as_of_date))
        if not self.snapshot_id or not isinstance(self.mode, PITMode):
            raise ValidationError("snapshot and PIT mode required")


@dataclass(frozen=True)
class Metric:
    name: str
    value: Decimal | None
    unit: str
    raw_value: str | None
    raw_unit: str

    def __post_init__(self):
        if self.value is not None and (not isinstance(self.value, Decimal) or not self.value.is_finite()):
            raise ValidationError("finite Decimal or explicit missing value required")


@dataclass(frozen=True)
class DataRecord:
    security_id: str
    canonical_symbol: str
    dataset: Dataset
    period: date
    basis: str
    metrics: tuple[Metric, ...]
    provider: str
    provider_version: str
    source_url: str
    source_key: str
    revision_id: str
    available_at: datetime
    retrieved_at: datetime
    ingested_at: datetime
    availability_basis: str
    artifact_id: str
    provider_call_id: str
    published_at: datetime | None = None
    announcement_date: date | None = None
    revision_order: int = 0
    quality_flags: tuple[str, ...] = ()
    release_date: date | None = None
    release_evidence_artifact_id: str | None = None
    supporting_artifact_ids: tuple[str, ...] = ()

    def __post_init__(self):
        for key in ("available_at", "retrieved_at", "ingested_at"):
            object.__setattr__(self, key, aware(getattr(self, key)))
        if self.published_at is not None:
            object.__setattr__(self, "published_at", aware(self.published_at))
        if self.basis != BASES[self.dataset] or type(self.period) is not date:
            raise ValidationError("invalid dataset basis or period")
        if self.ingested_at < self.retrieved_at:
            raise ValidationError("ingestion precedes retrieval")
        local_capture_date = self.retrieved_at.astimezone(timezone(timedelta(hours=8))).date()
        local_available_date = self.available_at.astimezone(timezone(timedelta(hours=8))).date()
        if self.period > local_capture_date:
            raise ValidationError("observed financial or market period is in the future")
        if self.period > local_available_date:
            raise ValidationError("observed period cannot precede its completion")
        if self.announcement_date is not None and self.announcement_date > local_capture_date:
            raise ValidationError("announcement date is later than captured content")
        if self.published_at is not None and self.published_at > self.retrieved_at:
            raise ValidationError("claimed publication is later than captured content")
        if self.availability_basis not in {"observed_at", "verified_release", "verified_release_date"}:
            raise ValidationError("unknown availability basis")
        if self.availability_basis == "observed_at" and self.available_at < self.retrieved_at:
            raise ValidationError("observed data cannot be backdated")
        if self.availability_basis == "verified_release":
            if self.published_at is None or self.available_at < self.published_at:
                raise ValidationError("verified release requires a valid publication timestamp")
        if self.availability_basis == "verified_release_date":
            if (type(self.release_date) is not date or self.published_at is not None
                    or self.release_date > local_capture_date
                    or not isinstance(self.release_evidence_artifact_id, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", self.release_evidence_artifact_id)):
                raise ValidationError("verified release date requires date-specific evidence and unknown intraday time")
            boundary = datetime.combine(self.release_date + timedelta(days=1), datetime.min.time(),
                                        timezone(timedelta(hours=8)))
            if self.available_at < boundary:
                raise ValidationError("date-only release cannot be visible before the conservative day boundary")
        elif self.release_date is not None or self.release_evidence_artifact_id is not None:
            raise ValidationError("release date evidence requires its explicit availability basis")
        if (not isinstance(self.supporting_artifact_ids, tuple) or len(self.supporting_artifact_ids) > 16
                or any(not isinstance(aid, str) or not re.fullmatch(r"[0-9a-f]{64}", aid)
                       for aid in self.supporting_artifact_ids)):
            raise ValidationError("immutable supporting artifact hashes required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.artifact_id):
            raise ValidationError("content-addressed artifact required")
        if not all((self.source_url, self.source_key, self.revision_id, self.provider_call_id, self.provider)):
            raise ValidationError("source lineage required")
        names = [m.name for m in self.metrics]
        if len(names) != len(set(names)) or set(names) != METRICS[self.dataset]:
            raise ValidationError("complete metric schema required; missing values must be explicit")
        object.__setattr__(self, "metrics", tuple(sorted(self.metrics, key=lambda m: m.name)))
        object.__setattr__(self, "quality_flags", tuple(sorted(set(self.quality_flags))))

    @property
    def record_id(self) -> str:
        return digest(self.identity_payload())

    def identity_payload(self) -> dict:
        # Recommitting a captured result must preserve its first ingestion timestamp.
        payload = self.to_dict()
        payload.pop("ingested_at")
        return payload

    @property
    def fact_key(self) -> tuple:
        return self.security_id, self.dataset, self.period, self.basis, self.provider

    @property
    def artifact_ids(self) -> tuple[str, ...]:
        return tuple(sorted({self.artifact_id, *self.supporting_artifact_ids,
                             *([self.release_evidence_artifact_id] if self.release_evidence_artifact_id else [])}))

    def to_dict(self) -> dict:
        result = asdict(self)
        result["dataset"] = self.dataset.value
        for key in ("period", "available_at", "retrieved_at", "ingested_at", "published_at", "announcement_date"):
            value = getattr(self, key)
            result[key] = value.isoformat() if value is not None else None
        result["metrics"] = [{**asdict(m), "value": str(m.value) if m.value is not None else None}
                             for m in self.metrics]
        # Preserve the byte-level identity of all legacy payloads/snapshots.
        for key in ("release_date", "release_evidence_artifact_id", "supporting_artifact_ids"):
            if not getattr(self, key):
                result.pop(key)
        if self.release_date is not None:
            result["release_date"] = self.release_date.isoformat()
        return result

    @classmethod
    def from_dict(cls, value: dict) -> DataRecord:
        if value.get("record_kind") == "domain_v2":
            from .domains import DomainRecord
            return DomainRecord.from_dict(value)
        value = dict(value)
        value["dataset"] = Dataset(value["dataset"])
        if value.get("release_date") is not None:
            value["release_date"] = date.fromisoformat(value["release_date"])
        if "supporting_artifact_ids" in value:
            value["supporting_artifact_ids"] = tuple(value["supporting_artifact_ids"])
        for key in ("period", "announcement_date"):
            value[key] = date.fromisoformat(value[key]) if value[key] else None
        for key in ("available_at", "retrieved_at", "ingested_at", "published_at"):
            value[key] = datetime.fromisoformat(value[key]) if value[key] else None
        value["metrics"] = tuple(Metric(**{**m, "value": Decimal(m["value"]) if m["value"] is not None else None})
                                 for m in value["metrics"])
        return cls(**value)


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    scope: str
    record_ids: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class QueryResult:
    status: str
    records: tuple[DataRecord, ...]
    snapshot_id: str
    as_of_date: datetime
    warnings: tuple[str, ...]
    coverage: str = "not_verified"


@dataclass(frozen=True)
class IngestionResult:
    snapshot: Snapshot
    provider: str
    record_count: int
    warnings: tuple[str, ...] = ()
