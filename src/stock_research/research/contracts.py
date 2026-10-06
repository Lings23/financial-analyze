from dataclasses import asdict, dataclass
from datetime import date, datetime

from ..domains import DomainDataset, DomainRequest, Subject
from ..errors import ValidationError
from ..models import DataRequest, Dataset, PITMode, Security, aware, digest


DOMAINS = {
    "market_daily": "market", "trade_calendar": "market", "adjustment_factor": "market",
    "financial_income": "financial", "financial_balance": "financial", "financial_cashflow": "financial",
    "index_daily": "benchmark", "announcement": "announcement", "news_recent": "news",
}
TOOLS = frozenset({*DOMAINS.values(), "calculation"})


@dataclass(frozen=True)
class Binding:
    dataset: str
    snapshot: str
    provider: str
    start: date
    end: date

    def __post_init__(self):
        if (self.dataset not in DOMAINS or not isinstance(self.snapshot, str)
                or len(self.snapshot) != 64 or any(c not in "0123456789abcdef" for c in self.snapshot)
                or not isinstance(self.provider, str) or not self.provider.strip()):
            raise ValidationError("invalid research dataset, snapshot or provider")

    def to_dict(self):
        return {**asdict(self), "start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True)
class ResearchRequest:
    security: Security
    as_of: datetime
    mode: PITMode
    bindings: tuple[Binding, ...]
    benchmark: str | None = None

    def __post_init__(self):
        aware(self.as_of)
        names = [b.dataset for b in self.bindings]
        if (not isinstance(self.mode, PITMode) or not 1 <= len(names) <= len(DOMAINS)
                or len(names) != len(set(names)) or "market_daily" not in names
                or "financial_income" not in names):
            raise ValidationError("overview requires unique market_daily and financial_income bindings")
        for binding in self.bindings:
            self.data_request(binding)  # Reuse bounded window and subject validation.

    def data_request(self, binding):
        if binding.dataset in {d.value for d in Dataset}:
            return DataRequest(self.security, Dataset(binding.dataset), binding.start, binding.end)
        dataset = DomainDataset(binding.dataset)
        if dataset == DomainDataset.CALENDAR:
            subject = Subject("exchange", self.security.exchange)
        elif dataset == DomainDataset.INDEX_DAILY:
            if not self.benchmark:
                raise ValidationError("index_daily requires an explicit benchmark code")
            subject = Subject("index", self.benchmark)
        else:
            subject = Subject("equity", self.security.symbol, self.security.exchange)
        return DomainRequest(subject, dataset, binding.start, binding.end)

    def to_dict(self):
        return {"symbol": self.security.symbol, "exchange": self.security.exchange,
                "as_of": self.as_of.isoformat(), "mode": self.mode.value,
                "bindings": [b.to_dict() for b in self.bindings], "benchmark": self.benchmark}

    @classmethod
    def from_dict(cls, value):
        try:
            if set(value) - {"symbol", "exchange", "as_of", "mode", "bindings", "benchmark"}:
                raise ValueError()
            bindings = tuple(Binding(b["dataset"], b["snapshot"], b["provider"],
                                     date.fromisoformat(b["start"]), date.fromisoformat(b["end"]))
                             for b in value["bindings"] if set(b) == {"dataset", "snapshot", "provider", "start", "end"})
            if len(bindings) != len(value["bindings"]):
                raise ValueError()
            return cls(Security(value["symbol"], value["exchange"]), datetime.fromisoformat(value["as_of"]),
                       PITMode(value["mode"]), bindings, value.get("benchmark"))
        except (KeyError, TypeError, ValueError):
            raise ValidationError("invalid research request schema") from None


@dataclass(frozen=True)
class AgentSpec:
    version: str = "single-overview-v1"
    model: str = "deepseek-v4-flash-0731"
    allowed_tools: frozenset[str] = TOOLS
    visible_tools: frozenset[str] = TOOLS
    max_tools: int = 8
    max_tokens: int = 8000
    max_seconds: int = 45
    output_tokens: int = 384

    def __post_init__(self):
        if (not self.visible_tools <= self.allowed_tools <= TOOLS
                or any(type(x) is not int or x <= 0 for x in
                       (self.max_tools, self.max_tokens, self.max_seconds, self.output_tokens))
                or self.max_tools > 20 or self.max_seconds > 240 or self.output_tokens > 4096):
            raise ValidationError("invalid agent permissions or budget")

    @property
    def identity(self):
        return digest({**asdict(self), "allowed_tools": sorted(self.allowed_tools),
                       "visible_tools": sorted(self.visible_tools)})
