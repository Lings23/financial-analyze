"""Bounded Phase 3 requests. No executable plans or model-supplied permissions."""
from dataclasses import dataclass
import re

from ..errors import ValidationError
from .contracts import AgentSpec, ResearchRequest


HYPOTHESIS_IDS = (
    "mechanical_adjustment", "market_direction", "financial_deterioration",
    "cashflow_divergence", "event_chronology",
)
EXTENDED_HYPOTHESIS_IDS = HYPOTHESIS_IDS + ("absolute_profit_change",)


@dataclass(frozen=True)
class StudyRequest(ResearchRequest):
    objective: str = "single_stock_research"
    hypotheses: tuple[str, ...] = HYPOTHESIS_IDS
    event_record_id: str | None = None
    hypothesis_version: str | None = None

    def __post_init__(self):
        super().__post_init__()
        if (self.objective not in {"single_stock_research", "event_review"}
                or not isinstance(self.hypotheses, tuple) or not self.hypotheses
                or any(type(h) is not str or h not in EXTENDED_HYPOTHESIS_IDS for h in self.hypotheses)
                or len(set(self.hypotheses)) != len(self.hypotheses)):
            raise ValidationError("invalid bounded research objective or hypotheses")
        if (self.hypothesis_version not in {None, "profit-change/v1"}
                or ("absolute_profit_change" in self.hypotheses
                    and self.hypothesis_version != "profit-change/v1")):
            raise ValidationError("profit amount research requires an explicit new hypothesis version")
        if self.event_record_id is not None and (not isinstance(self.event_record_id, str)
                or not re.fullmatch(r"[0-9a-f]{64}", self.event_record_id)):
            raise ValidationError("event anchor requires a source record ID")
        if self.objective == "event_review" and (self.event_record_id is None
                or "event_chronology" not in self.hypotheses):
            raise ValidationError("event review requires an explicit anchor and chronology test")

    def to_dict(self):
        result = {**super().to_dict(), "objective": self.objective,
                  "hypotheses": list(self.hypotheses), "event_record_id": self.event_record_id}
        if self.hypothesis_version is not None:
            result["hypothesis_version"] = self.hypothesis_version
        return result

    @classmethod
    def from_dict(cls, value):
        try:
            extra = {"objective", "hypotheses", "event_record_id", "hypothesis_version"}
            if not isinstance(value, dict) or set(value) - extra - {
                    "symbol", "exchange", "as_of", "mode", "bindings", "benchmark"}:
                raise ValueError()
            base = ResearchRequest.from_dict({k: v for k, v in value.items() if k not in extra})
            hs = value.get("hypotheses", list(HYPOTHESIS_IDS))
            if not isinstance(hs, list):
                raise ValueError()
            return cls(base.security, base.as_of, base.mode, base.bindings, base.benchmark,
                       value.get("objective", "single_stock_research"), tuple(hs), value.get("event_record_id"),
                       value.get("hypothesis_version"))
        except (TypeError, ValueError):
            raise ValidationError("invalid study request schema") from None


@dataclass(frozen=True)
class StudySpec(AgentSpec):
    version: str = "single-research-v3"
    max_seconds: int = 120
    max_tokens: int = 16000
    output_tokens: int = 512
    context_bytes: int = 12000

    def __post_init__(self):
        super().__post_init__()
        if self.version not in {"single-research-v1", "single-research-v2", "single-research-v3", "single-research-v4", "single-research-v5"}:
            raise ValidationError("unknown study instruction version")
        if type(self.context_bytes) is not int or not 512 <= self.context_bytes <= 24000:
            raise ValidationError("invalid study context budget")
