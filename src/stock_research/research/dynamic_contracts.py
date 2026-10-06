"""Phase 4 bounded dynamic Single contracts, separate from legacy fixed specs."""
from dataclasses import dataclass
import re

from ..errors import ValidationError
from ..models import PITMode, aware
from .contracts import AgentSpec, DOMAINS
from .hypotheses import CATALOGUE
from .study_contracts import StudyRequest


SOURCE_TOOLS = frozenset(DOMAINS.values())
DYNAMIC_TOOLS = SOURCE_TOOLS | {"calculation", "hypotheses", "verification"}
DYNAMIC_VERSION = "single-dynamic-v1"
FINANCIAL_DATASETS = frozenset({"financial_income", "financial_balance", "financial_cashflow"})
MARKET_DATASETS = frozenset({"market_daily", "trade_calendar", "adjustment_factor"})
AGENT_TOOLS = frozenset({"financial_child", "market_child"})
PARALLEL_VERSION = "dynamic-parent-parallel-v1"
PARALLEL_VERSIONS = frozenset({PARALLEL_VERSION, "dynamic-parent-parallel-v2", "dynamic-parent-parallel-v3"})
MAX_QUESTION_BYTES = 2000


def required_checks(request):
    """Freeze scope-derived reads and catalogue checks before the first decision."""
    if not isinstance(request, DynamicRequest):
        raise ValidationError("dynamic requirements need a DynamicRequest")
    if isinstance(request, FinancialRequest):
        return ["read:financial"]
    if isinstance(request, MarketRequest):
        return ["read:market"]
    datasets = {binding.dataset for binding in request.bindings}
    needed = {"market_daily", "financial_income"}
    for hid in request.hypotheses:
        needed.update(dataset for dataset in CATALOGUE[hid][1] if dataset != "explicit_event_record")
    reads = {DOMAINS[dataset] for dataset in needed & datasets}
    if request.event_record_id:
        reads.update(DOMAINS[dataset] for dataset in datasets & {"financial_income", "announcement", "news_recent"})
    return (["read:" + name for name in sorted(reads)]
            + ["binding:" + dataset for dataset in sorted(needed - datasets)]
            + ["calculation", "hypotheses", "verification"]
            + ["hypothesis:" + hid for hid in request.hypotheses])


def text_bytes(value):
    """Reject non-text and invalid Unicode instead of changing an immutable input."""
    if type(value) is not str:
        raise ValidationError("dynamic control text must be a string")
    try:
        return len(value.encode("utf-8"))
    except UnicodeError:
        raise ValidationError("invalid Unicode in dynamic control text") from None


@dataclass(frozen=True)
class DynamicRequest(StudyRequest):
    # A trusted application binds all inherited scope fields and required hypotheses.
    # This question expresses a goal; it never supplies financial evidence or grants.
    question: str = ""

    def __post_init__(self):
        super().__post_init__()
        if not 1 <= text_bytes(self.question) <= MAX_QUESTION_BYTES or not self.question.strip():
            raise ValidationError("dynamic research requires a bounded nonempty question")

    def to_dict(self):
        return {**super().to_dict(), "question": self.question}

    @classmethod
    def from_dict(cls, value):
        try:
            if type(value) is not dict or "question" not in value:
                raise ValueError()
            base = StudyRequest.from_dict({k: v for k, v in value.items() if k != "question"})
            return cls(base.security, base.as_of, base.mode, base.bindings, base.benchmark,
                       base.objective, base.hypotheses, base.event_record_id,
                       base.hypothesis_version, value["question"])
        except (KeyError, TypeError, ValueError):
            raise ValidationError("invalid dynamic request schema") from None


@dataclass(frozen=True)
class DynamicSpec(AgentSpec):
    version: str = DYNAMIC_VERSION
    allowed_tools: frozenset[str] = DYNAMIC_TOOLS
    visible_tools: frozenset[str] = DYNAMIC_TOOLS
    max_tools: int = 12
    max_tokens: int = 48000
    max_seconds: int = 240
    output_tokens: int = 1024
    max_decisions: int = 8
    context_bytes: int = 12000
    no_progress_limit: int = 2

    def __post_init__(self):
        # AgentSpec's legacy TOOLS bound deliberately remains unchanged. Dynamic uses
        # the same identity mechanism, with its own version and restricted tool set.
        tools = DYNAMIC_TOOLS | (AGENT_TOOLS if isinstance(self, DomainParentSpec) else
                                {"financial_child"} if isinstance(self, FinancialParentSpec) else set())
        versions = (PARALLEL_VERSIONS if isinstance(self, ParallelParentSpec) else
                    {"dynamic-parent-domains-v1", "dynamic-parent-domains-v2"} if isinstance(self, DomainParentSpec) else
                    {"dynamic-parent-financial-v1"} if isinstance(self, FinancialParentSpec) else
                    {"market-child-v1", "market-child-v2", "market-child-v3"} if isinstance(self, MarketChildSpec) else
                    {"financial-child-v1", "financial-child-v2", "financial-child-v3"} if isinstance(self, FinancialChildSpec) else
                    {DYNAMIC_VERSION, "single-dynamic-v2"})
        if (self.version not in versions
                or type(self.allowed_tools) is not frozenset
                or type(self.visible_tools) is not frozenset
                or not self.visible_tools <= self.allowed_tools <= tools
                or type(self.model) is not str
                or not re.fullmatch(r"[A-Za-z0-9_./:-]{1,128}", self.model)):
            raise ValidationError("invalid dynamic instruction version or permissions")
        limits = ((self.max_tools, 12), (self.max_tokens, 48000),
                  (self.max_seconds, 240), (self.output_tokens, 1024),
                  (self.max_decisions, 8), (self.context_bytes, 12000),
                  (self.no_progress_limit, 2))
        if any(type(value) is not int or not 1 <= value <= upper for value, upper in limits):
            raise ValidationError("invalid dynamic execution budget")


@dataclass(frozen=True)
class FinancialRequest(DynamicRequest):
    """Application-created strict subset of a parent's immutable source bindings."""
    objective: str = "financial_evidence"
    hypotheses: tuple[str, ...] = ()
    question: str = "读取已绑定财务证据，保留可见性及缺口。"

    def __post_init__(self):
        aware(self.as_of)
        names = [b.dataset for b in self.bindings]
        if (not isinstance(self.mode, PITMode) or not names or len(names) != len(set(names))
                or not set(names) <= FINANCIAL_DATASETS or self.benchmark is not None
                or self.objective != "financial_evidence" or self.hypotheses != ()
                or self.event_record_id is not None or self.hypothesis_version is not None
                or not 1 <= text_bytes(self.question) <= MAX_QUESTION_BYTES):
            raise ValidationError("invalid bounded financial child request")
        for binding in self.bindings:
            self.data_request(binding)

    @classmethod
    def from_parent(cls, parent, datasets=FINANCIAL_DATASETS):
        if not isinstance(parent, DynamicRequest) or isinstance(parent, FinancialRequest):
            raise ValidationError("financial child requires a dynamic parent")
        return cls(parent.security, parent.as_of, parent.mode,
                   tuple(b for b in parent.bindings if b.dataset in datasets), None,
                   "financial_evidence", (), None, None,
                   "读取已绑定财务证据，保留可见性及缺口。")


@dataclass(frozen=True)
class FinancialChildSpec(DynamicSpec):
    version: str = "financial-child-v1"
    allowed_tools: frozenset[str] = frozenset({"financial"})
    visible_tools: frozenset[str] = frozenset({"financial"})
    max_tools: int = 1
    max_tokens: int = 18000
    max_seconds: int = 120
    max_decisions: int = 3

    def __post_init__(self):
        super().__post_init__()
        if (self.version not in {"financial-child-v1", "financial-child-v2", "financial-child-v3"} or not self.allowed_tools <= {"financial"}
                or self.max_tools > 1 or self.max_tokens > 18000
                or self.max_seconds > 120 or self.max_decisions > 3):
            raise ValidationError("financial child cannot widen or spawn")


@dataclass(frozen=True)
class FinancialParentSpec(DynamicSpec):
    version: str = "dynamic-parent-financial-v1"
    allowed_tools: frozenset[str] = DYNAMIC_TOOLS | {"financial_child"}
    visible_tools: frozenset[str] = DYNAMIC_TOOLS | {"financial_child"}
    root_max_decisions: int = 12
    root_max_tools: int = 16
    root_max_tokens: int = 72000

    def __post_init__(self):
        super().__post_init__()
        domain = isinstance(self, DomainParentSpec)
        limits = (16, 18, 96000) if domain else (12, 16, 72000)
        if (self.version not in (PARALLEL_VERSIONS if isinstance(self, ParallelParentSpec) else
                                {"dynamic-parent-domains-v1", "dynamic-parent-domains-v2"} if domain else
                                {"dynamic-parent-financial-v1"})
                or any(type(v) is not int or not 1 <= v <= upper for v, upper in zip(
                    (self.root_max_decisions, self.root_max_tools, self.root_max_tokens), limits))):
            raise ValidationError("invalid serial parent root budget")


@dataclass(frozen=True)
class MarketRequest(DynamicRequest):
    """Market-only application-bound subset, with no financial or event authority."""
    objective: str = "market_evidence"
    hypotheses: tuple[str, ...] = ()
    question: str = "读取已绑定行情证据，保留可见性及缺口。"

    def __post_init__(self):
        aware(self.as_of)
        names = [b.dataset for b in self.bindings]
        if (not isinstance(self.mode, PITMode) or not names or len(names) != len(set(names))
                or not set(names) <= MARKET_DATASETS or self.benchmark is not None
                or self.objective != "market_evidence" or self.hypotheses != ()
                or self.event_record_id is not None or self.hypothesis_version is not None
                or not 1 <= text_bytes(self.question) <= MAX_QUESTION_BYTES):
            raise ValidationError("invalid bounded market child request")
        for binding in self.bindings:
            self.data_request(binding)

    @classmethod
    def from_parent(cls, parent, datasets=MARKET_DATASETS):
        if not isinstance(parent, DynamicRequest) or isinstance(parent, (FinancialRequest, MarketRequest)):
            raise ValidationError("market child requires a dynamic parent")
        return cls(parent.security, parent.as_of, parent.mode,
                   tuple(b for b in parent.bindings if b.dataset in datasets), None,
                   "market_evidence", (), None, None,
                   "读取已绑定行情证据，保留可见性及缺口。")


@dataclass(frozen=True)
class MarketChildSpec(DynamicSpec):
    version: str = "market-child-v1"
    allowed_tools: frozenset[str] = frozenset({"market"})
    visible_tools: frozenset[str] = frozenset({"market"})
    max_tools: int = 1
    max_tokens: int = 18000
    max_seconds: int = 120
    max_decisions: int = 3

    def __post_init__(self):
        super().__post_init__()
        if (self.version not in {"market-child-v1", "market-child-v2", "market-child-v3"} or not self.allowed_tools <= {"market"}
                or self.max_tools > 1 or self.max_tokens > 18000
                or self.max_seconds > 120 or self.max_decisions > 3):
            raise ValidationError("market child cannot widen or spawn")


@dataclass(frozen=True)
class DomainParentSpec(FinancialParentSpec):
    version: str = "dynamic-parent-domains-v1"
    allowed_tools: frozenset[str] = DYNAMIC_TOOLS | AGENT_TOOLS
    visible_tools: frozenset[str] = DYNAMIC_TOOLS | AGENT_TOOLS
    root_max_decisions: int = 16
    root_max_tools: int = 18
    root_max_tokens: int = 96000
    max_children: int = 2

    def __post_init__(self):
        super().__post_init__()
        if type(self.max_children) is not int or not 1 <= self.max_children <= 2:
            raise ValidationError("domain parent permits at most two serial children")


@dataclass(frozen=True)
class ParallelParentSpec(DomainParentSpec):
    """Versioned M3 parent; domain children and all legacy identities stay intact."""
    version: str = PARALLEL_VERSION

    def __post_init__(self):
        super().__post_init__()
        if self.context_bytes != 12000:
            raise ValidationError("parallel context cap is frozen at 12000 UTF-8 bytes")
