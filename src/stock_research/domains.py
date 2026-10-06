"""Typed P1.8 observations sharing the existing authorization/PIT/storage envelope."""
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

from .errors import ValidationError
from .models import Metric, aware, digest


class DomainDataset(str, Enum):
    CALENDAR = "trade_calendar"
    ADJUSTMENT = "adjustment_factor"
    INDEX_DAILY = "index_daily"
    INDEX_WEIGHT = "index_weight"
    BALANCE = "financial_balance"
    CASHFLOW = "financial_cashflow"
    ANNOUNCEMENT = "announcement"
    NEWS = "news_recent"


BASES = {
    DomainDataset.CALENDAR: "exchange_schedule",
    DomainDataset.ADJUSTMENT: "raw_adjustment_factor",
    DomainDataset.INDEX_DAILY: "price_index_daily",
    DomainDataset.INDEX_WEIGHT: "monthly_constituent_weight",
    DomainDataset.BALANCE: "consolidated_balance_cny",
    DomainDataset.CASHFLOW: "consolidated_cumulative_cashflow_cny",
    DomainDataset.ANNOUNCEMENT: "official_pdf_observed",
    DomainDataset.NEWS: "recent_news_observed",
}
METRICS = {
    DomainDataset.CALENDAR: {},
    DomainDataset.ADJUSTMENT: {"factor": "ratio"},
    DomainDataset.INDEX_DAILY: {"open": "point", "high": "point", "low": "point", "close": "point",
                              "volume": "share", "amount": "CNY"},
    DomainDataset.INDEX_WEIGHT: {"weight": "ratio"},
    DomainDataset.BALANCE: {"total_assets": "CNY", "total_liabilities": "CNY", "total_equity": "CNY",
                          "equity_parent": "CNY", "monetary_funds": "CNY"},
    DomainDataset.CASHFLOW: {"operating_cashflow": "CNY", "investing_cashflow": "CNY",
                           "financing_cashflow": "CNY", "cash_net_change": "CNY",
                           "cash_begin": "CNY", "cash_end": "CNY"},
    DomainDataset.ANNOUNCEMENT: {},
    DomainDataset.NEWS: {},
}
ATTRS = {
    DomainDataset.CALENDAR: {"is_open", "pretrade_date"},
    DomainDataset.ADJUSTMENT: set(),
    DomainDataset.INDEX_DAILY: set(),
    DomainDataset.INDEX_WEIGHT: {"constituent_code"},
    DomainDataset.BALANCE: {"ann_date", "f_ann_date", "report_type", "comp_type", "end_type", "update_flag"},
    DomainDataset.CASHFLOW: {"ann_date", "f_ann_date", "report_type", "comp_type", "end_type", "update_flag"},
    DomainDataset.ANNOUNCEMENT: {"announcement_id", "title", "source_date", "pdf_artifact_id", "document_sha256"},
    DomainDataset.NEWS: {"title", "snippet", "publisher", "source_time", "body_artifact_id", "body_kind"},
}
NEWS_ASSOCIATION = {"company_name", "association_basis"}


@dataclass(frozen=True)
class Subject:
    kind: str
    code: str
    exchange: str = ""

    def __post_init__(self):
        valid = ((self.kind == "exchange" and self.code in {"SSE", "SZSE"} and not self.exchange)
                 or (self.kind == "equity" and re.fullmatch(r"\d{6}", self.code)
                     and self.exchange in {"SSE", "SZSE", "BSE"})
                 or (self.kind == "index" and re.fullmatch(r"\d{6}\.(SH|SZ|CSI)", self.code)
                     and not self.exchange))
        if not valid:
            raise ValidationError("explicit supported exchange, equity or index subject required")

    @property
    def canonical_symbol(self):
        return f"{self.exchange}:{self.code}" if self.kind == "equity" else self.code

    @property
    def security_id(self):
        # Compatibility column name; calendar/index subjects never masquerade as equities.
        return f"CN:{self.kind}:{self.canonical_symbol}"

    @property
    def provider_symbol(self):
        if self.kind == "equity":
            return f"{self.code}." + {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}[self.exchange]
        return self.code


@dataclass(frozen=True)
class DomainRequest:
    subject: Subject
    dataset: DomainDataset
    start: date
    end: date
    selector: str = ""

    def __post_init__(self):
        if not isinstance(self.dataset, DomainDataset) or not isinstance(self.subject, Subject):
            raise ValidationError("typed domain and subject required")
        if type(self.start) is not date or type(self.end) is not date or self.start > self.end:
            raise ValidationError("valid inclusive date window required")
        if (self.end - self.start).days > (31 if self.dataset == DomainDataset.ANNOUNCEMENT else 366):
            raise ValidationError("domain window too large; split explicitly")
        kind = "exchange" if self.dataset == DomainDataset.CALENDAR else (
            "index" if self.dataset in {DomainDataset.INDEX_DAILY, DomainDataset.INDEX_WEIGHT} else "equity")
        if self.subject.kind != kind or len(self.selector) > 80 or "\x00" in self.selector:
            raise ValidationError("subject or selector does not match domain")
        if self.selector and self.dataset != DomainDataset.ANNOUNCEMENT:
            raise ValidationError("title selector is supported only for announcements")

    @property
    def security(self):
        return self.subject

    @property
    def basis(self):
        return BASES[self.dataset]

    def identity(self):
        return {"subject": asdict(self.subject), "dataset": self.dataset.value,
                "start": self.start.isoformat(), "end": self.end.isoformat(),
                "basis": self.basis, "selector": self.selector}

    def matches(self, record):
        if self.dataset == DomainDataset.NEWS:
            attrs = dict(record.attributes)
            if attrs.get("association_basis") != "current_company_name_or_qualified_code_in_article" or not attrs.get("company_name"):
                return False
        return not self.selector or self.selector in dict(record.attributes).get("title", "")


@dataclass(frozen=True)
class DomainRecord:
    subject: Subject
    dataset: DomainDataset
    period: date
    fact_id: str
    metrics: tuple[Metric, ...]
    attributes: tuple[tuple[str, str | None], ...]
    provider: str
    provider_version: str
    source_url: str
    source_key: str
    revision_id: str
    available_at: datetime
    retrieved_at: datetime
    ingested_at: datetime
    artifact_id: str
    provider_call_id: str
    revision_order: int = 0
    availability_basis: str = "observed_at"
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self):
        DomainRequest(self.subject, self.dataset, self.period, self.period)
        for key in ("available_at", "retrieved_at", "ingested_at"):
            object.__setattr__(self, key, aware(getattr(self, key)))
        if self.availability_basis != "observed_at" or self.available_at < self.retrieved_at:
            raise ValidationError("P1.8 observations must not claim historical release or backdate visibility")
        if self.ingested_at < self.retrieved_at:
            raise ValidationError("ingestion precedes capture")
        if self.dataset != DomainDataset.CALENDAR and self.period > self.retrieved_at.astimezone(
                timezone(timedelta(hours=8))).date():
            raise ValidationError("future non-schedule event")
        if not all((self.fact_id, self.provider, self.provider_version, self.source_url,
                    self.source_key, self.revision_id, self.provider_call_id)):
            raise ValidationError("domain lineage required")
        names = [m.name for m in self.metrics]
        if len(set(names)) != len(names) or set(names) != set(METRICS[self.dataset]):
            raise ValidationError("complete typed domain metric schema required")
        if any(m.unit != METRICS[self.dataset][m.name] for m in self.metrics):
            raise ValidationError("domain metric unit mismatch")
        attrs = dict(self.attributes)
        expected = ATTRS[self.dataset] | (NEWS_ASSOCIATION if self.dataset == DomainDataset.NEWS
                                          and self.provider_version != "p18-1" else set())
        if len(attrs) != len(self.attributes) or set(attrs) != expected:
            raise ValidationError("complete typed domain attributes required")
        if any(not isinstance(k, str) or (v is not None and not isinstance(v, str))
               for k, v in self.attributes):
            raise ValidationError("immutable scalar attributes required")
        if self.dataset == DomainDataset.CALENDAR and attrs["is_open"] not in {"0", "1"}:
            raise ValidationError("invalid calendar open flag")
        if self.dataset in {DomainDataset.ANNOUNCEMENT, DomainDataset.NEWS}:
            if not attrs["title"] or not attrs.get("pdf_artifact_id", attrs.get("body_artifact_id")):
                raise ValidationError("document title and original evidence required")
            if self.dataset == DomainDataset.ANNOUNCEMENT and attrs["document_sha256"] != attrs["pdf_artifact_id"]:
                raise ValidationError("document checksum differs from archived bytes ID")
        for value in self.artifact_ids:
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValidationError("content-addressed evidence required")
        object.__setattr__(self, "metrics", tuple(sorted(self.metrics, key=lambda m: m.name)))
        object.__setattr__(self, "attributes", tuple(sorted(self.attributes)))
        object.__setattr__(self, "quality_flags", tuple(sorted(set(self.quality_flags))))

    @property
    def basis(self):
        return BASES[self.dataset]

    @property
    def security_id(self):
        return self.subject.security_id

    @property
    def canonical_symbol(self):
        return self.subject.canonical_symbol

    @property
    def artifact_ids(self):
        attrs = dict(self.attributes)
        return (self.artifact_id,) + tuple(attrs[k] for k in ("pdf_artifact_id", "body_artifact_id")
                                           if k in attrs)

    @property
    def fact_key(self):
        return self.security_id, self.dataset, self.period, self.basis, self.provider, self.fact_id

    @property
    def value_signature(self):
        value = self.to_dict()
        attributes = dict(self.attributes)
        if self.dataset in {DomainDataset.BALANCE, DomainDataset.CASHFLOW}:
            # Administrative update flag is archived, but does not change an identical financial fact.
            attributes.pop("update_flag", None)
        return {"metrics": value["metrics"], "attributes": attributes}

    @property
    def record_id(self):
        return digest(self.identity_payload())

    def identity_payload(self):
        result = self.to_dict()
        result.pop("ingested_at")
        return result

    def to_dict(self):
        result = asdict(self)
        result["record_kind"] = "domain_v2"
        result["dataset"] = self.dataset.value
        for key in ("period", "available_at", "retrieved_at", "ingested_at"):
            result[key] = getattr(self, key).isoformat()
        result["metrics"] = [{**asdict(m), "value": str(m.value) if m.value is not None else None}
                             for m in self.metrics]
        return result

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        value.pop("record_kind")
        value["subject"] = Subject(**value["subject"])
        value["dataset"] = DomainDataset(value["dataset"])
        value["period"] = date.fromisoformat(value["period"])
        for key in ("available_at", "retrieved_at", "ingested_at"):
            value[key] = datetime.fromisoformat(value[key])
        value["metrics"] = tuple(Metric(**{**m, "value": Decimal(m["value"]) if m["value"] is not None else None})
                                 for m in value["metrics"])
        value["attributes"] = tuple(tuple(pair) for pair in value["attributes"])
        return cls(**value)
