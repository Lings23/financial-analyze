"""Explicit experimental domain analysis identities; legacy contracts stay intact.

These objects freeze goals and execution references, never authorization. Every
source read, reuse, join and recovery still needs trusted runtime authorization.
"""
from dataclasses import dataclass
from datetime import date, datetime
import re

from ..errors import ValidationError
from ..models import PITMode, Security, aware, digest
from .contracts import Binding
from .dynamic_contracts import (
    AGENT_TOOLS, DYNAMIC_TOOLS, FINANCIAL_DATASETS, MARKET_DATASETS,
    DynamicRequest, FinancialRequest, MarketRequest, FinancialChildSpec,
    MarketChildSpec, ParallelParentSpec, MAX_QUESTION_BYTES, text_bytes,
    required_checks as legacy_required_checks,
)


TASK_VERSION = "domain-analysis-task/v1"
RESULT_VERSION = "domain-analysis-result/v1"
CATALOG_VERSION = "domain-analysis-catalog/v1"
PARENT_VERSION = "dynamic-parent-domain-analysis-v1"
FINANCIAL_VERSION = "financial-analysis-child-v1"
MARKET_VERSION = "market-analysis-child-v1"
VERSIONS = frozenset({PARENT_VERSION, FINANCIAL_VERSION, MARKET_VERSION})
DOMAIN_TOOLS = frozenset({"financial_analysis_tool", "market_analysis_tool"})
PARENT_TOOLS = DYNAMIC_TOOLS | AGENT_TOOLS | DOMAIN_TOOLS | {"domain_review"}
ANALYSIS_TOOLS = PARENT_TOOLS
FINANCIAL_HYPOTHESES = frozenset({"financial_deterioration", "cashflow_divergence", "absolute_profit_change"})
MARKET_HYPOTHESES = frozenset({"mechanical_adjustment"})
PROFILES = frozenset({"core/v1", "profit-amount/v1"})
OPERATORS = {
    "financial-core/v1": ("financial_snapshot", "income_yoy"),
    "financial-profit-amount/v1": ("financial_snapshot", "income_yoy", "profit_amount_change"),
    "market-core/v1": ("market_price_window", "factor_adjusted_window"),
}


def _hash(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def domain_of(request):
    if isinstance(request, FinancialAnalysisRequest):
        return "financial"
    if isinstance(request, MarketAnalysisRequest):
        return "market"
    raise ValidationError("analysis domain requires an analysis child request")


def _request_validate(request, domain):
    aware(request.as_of)
    datasets = FINANCIAL_DATASETS if domain == "financial" else MARKET_DATASETS
    hypotheses = FINANCIAL_HYPOTHESES if domain == "financial" else MARKET_HYPOTHESES
    profiles = {"financial-core/v1", "financial-profit-amount/v1"} if domain == "financial" else {"market-core/v1"}
    names = [b.dataset for b in request.bindings]
    if (not isinstance(request.security, Security) or not isinstance(request.mode, PITMode)
            or type(request.bindings) is not tuple or not names or len(names) != len(set(names))
            or not set(names) <= datasets or request.benchmark is not None
            or request.objective != domain + "_analysis" or request.event_record_id is not None
            or type(request.hypotheses) is not tuple
            or any(type(h) is not str or h not in hypotheses for h in request.hypotheses)
            or len(request.hypotheses) != len(set(request.hypotheses))
            or type(request.profile_id) is not str or request.profile_id not in profiles or not _hash(request.parent_request_ref)
            or not 1 <= text_bytes(request.question) <= MAX_QUESTION_BYTES or not request.question.strip()):
        raise ValidationError("invalid bounded domain analysis request")
    amount = request.profile_id == "financial-profit-amount/v1"
    if (request.hypothesis_version is not None and type(request.hypothesis_version) is not str
            or request.hypothesis_version not in {None, "profit-change/v1"}
            or amount != ("absolute_profit_change" in request.hypotheses)
            or amount and request.hypothesis_version != "profit-change/v1"):
        raise ValidationError("profit amount profile must preserve the explicitly frozen root goal")
    for binding in request.bindings:
        request.data_request(binding)


def _request_from_dict(cls, value):
    fields = {"symbol", "exchange", "as_of", "mode", "bindings", "benchmark", "objective",
              "hypotheses", "event_record_id", "hypothesis_version", "question", "profile_id", "parent_request_ref"}
    try:
        if (type(value) is not dict or set(value) - fields
                or type(value["bindings"]) is not list or type(value["hypotheses"]) is not list):
            raise ValueError()
        bindings = tuple(Binding(b["dataset"], b["snapshot"], b["provider"],
                                 date.fromisoformat(b["start"]), date.fromisoformat(b["end"]))
                         for b in value["bindings"]
                         if type(b) is dict and set(b) == {"dataset", "snapshot", "provider", "start", "end"})
        if len(bindings) != len(value["bindings"]):
            raise ValueError()
        return cls(Security(value["symbol"], value["exchange"]), datetime.fromisoformat(value["as_of"]),
                   PITMode(value["mode"]), bindings, value.get("benchmark"), value["objective"],
                   tuple(value["hypotheses"]), value.get("event_record_id"), value.get("hypothesis_version"),
                   value["question"], value["profile_id"], value["parent_request_ref"])
    except (KeyError, TypeError, ValueError):
        raise ValidationError("invalid domain analysis request schema") from None


def _from_parent(cls, parent, datasets, domain, profile_id):
    if not isinstance(parent, DynamicRequest) or isinstance(parent, (FinancialRequest, MarketRequest)):
        raise ValidationError("analysis child requires a dynamic root request")
    permitted = FINANCIAL_DATASETS if domain == "financial" else MARKET_DATASETS
    if not isinstance(datasets, (set, frozenset)) or not datasets <= permitted:
        raise ValidationError("analysis child cannot widen the domain source subset")
    names = FINANCIAL_HYPOTHESES if domain == "financial" else MARKET_HYPOTHESES
    projected = tuple(h for h in parent.hypotheses if h in names)
    inferred = ("financial-profit-amount/v1" if "absolute_profit_change" in projected
                else domain + "-core/v1")
    if profile_id is not None and profile_id != inferred:
        raise ValidationError("analysis child profile differs from the frozen root goal")
    return cls(parent.security, parent.as_of, parent.mode,
               tuple(b for b in parent.bindings if b.dataset in datasets), None,
               domain + "_analysis", projected, None,
               parent.hypothesis_version if domain == "financial" else None,
               parent.question, inferred, digest(parent.to_dict()))


@dataclass(frozen=True)
class FinancialAnalysisRequest(FinancialRequest):
    objective: str = "financial_analysis"
    profile_id: str = "financial-core/v1"
    parent_request_ref: str = ""

    def __post_init__(self):
        _request_validate(self, "financial")

    def to_dict(self):
        return {**super().to_dict(), "profile_id": self.profile_id, "parent_request_ref": self.parent_request_ref}

    @classmethod
    def from_dict(cls, value):
        return _request_from_dict(cls, value)

    @classmethod
    def from_parent(cls, parent, datasets=FINANCIAL_DATASETS, *, profile_id=None):
        return _from_parent(cls, parent, datasets, "financial", profile_id)


@dataclass(frozen=True)
class MarketAnalysisRequest(MarketRequest):
    objective: str = "market_analysis"
    profile_id: str = "market-core/v1"
    parent_request_ref: str = ""

    def __post_init__(self):
        _request_validate(self, "market")

    def to_dict(self):
        return {**super().to_dict(), "profile_id": self.profile_id, "parent_request_ref": self.parent_request_ref}

    @classmethod
    def from_dict(cls, value):
        return _request_from_dict(cls, value)

    @classmethod
    def from_parent(cls, parent, datasets=MARKET_DATASETS, *, profile_id=None):
        return _from_parent(cls, parent, datasets, "market", profile_id)


def _spec_validate(spec, version, tools, decisions, calls, tokens, seconds):
    if (spec.version != version or type(spec.allowed_tools) is not frozenset
            or type(spec.visible_tools) is not frozenset
            or not spec.visible_tools <= spec.allowed_tools <= tools
            or type(spec.model) is not str or re.fullmatch(r"[A-Za-z0-9_./:-]{1,128}", spec.model) is None):
        raise ValidationError("invalid domain analysis instruction version or permissions")
    limits = ((spec.max_decisions, decisions), (spec.max_tools, calls), (spec.max_tokens, tokens),
              (spec.max_seconds, seconds), (spec.output_tokens, 1024))
    if (any(type(v) is not int or not 1 <= v <= upper for v, upper in limits)
            or type(spec.context_bytes) is not int or spec.context_bytes != 12000
            or type(spec.no_progress_limit) is not int or spec.no_progress_limit != 2):
        raise ValidationError("invalid domain analysis execution envelope")


@dataclass(frozen=True)
class FinancialAnalysisChildSpec(FinancialChildSpec):
    version: str = FINANCIAL_VERSION
    allowed_tools: frozenset[str] = frozenset({"financial", "calculation", "domain_review"})
    visible_tools: frozenset[str] = frozenset({"financial", "calculation", "domain_review"})
    max_tools: int = 4
    max_decisions: int = 5

    def __post_init__(self):
        _spec_validate(self, FINANCIAL_VERSION, {"financial", "calculation", "domain_review"}, 5, 4, 18000, 120)


@dataclass(frozen=True)
class MarketAnalysisChildSpec(MarketChildSpec):
    version: str = MARKET_VERSION
    allowed_tools: frozenset[str] = frozenset({"market", "calculation", "domain_review"})
    visible_tools: frozenset[str] = frozenset({"market", "calculation", "domain_review"})
    max_tools: int = 4
    max_decisions: int = 5

    def __post_init__(self):
        _spec_validate(self, MARKET_VERSION, {"market", "calculation", "domain_review"}, 5, 4, 18000, 120)


@dataclass(frozen=True)
class DomainAnalysisParentSpec(ParallelParentSpec):
    version: str = PARENT_VERSION
    allowed_tools: frozenset[str] = PARENT_TOOLS
    visible_tools: frozenset[str] = PARENT_TOOLS
    max_tools: int | None = None
    max_decisions: int | None = None
    mode: str = "child"
    execution: str = "parallel"
    profile_id: str = "core/v1"

    def __post_init__(self):
        if (type(self.mode) is not str or self.mode not in {"direct", "tool", "child"}
                or type(self.execution) is not str or self.execution not in {"serial", "parallel"}
                or type(self.profile_id) is not str or self.profile_id not in PROFILES):
            raise ValidationError("invalid frozen domain analysis route or profile")
        child = self.mode == "child"
        if self.max_decisions is None:
            object.__setattr__(self, "max_decisions", 6 if child else 8)
        if self.max_tools is None:
            object.__setattr__(self, "max_tools", 8 if child else 12)
        _spec_validate(self, PARENT_VERSION, PARENT_TOOLS, 6 if child else 8, 8 if child else 12, 48000, 240)
        limits = ((self.root_max_decisions, 16), (self.root_max_tools, 18), (self.root_max_tokens, 96000))
        if (any(type(v) is not int or not 1 <= v <= upper for v, upper in limits)
                or type(self.max_children) is not int or not 1 <= self.max_children <= 2):
            raise ValidationError("invalid domain analysis root envelope")


def required_operators(request):
    domain_of(request)
    return list(OPERATORS[request.profile_id])


def review_checks(request):
    domain_of(request)
    return ["local_verification", *request.hypotheses]


def required_checks(request):
    if isinstance(request, (FinancialAnalysisRequest, MarketAnalysisRequest)):
        return ["read:" + domain_of(request), "calculation", "domain_review"] + [
            "operator:" + operator for operator in required_operators(request)] + [
            "hypothesis:" + h for h in request.hypotheses]
    return legacy_required_checks(request)


def task_refs(parent, *, profile_id="core/v1"):
    """Task selector hashes freeze the original request and projected goal."""
    if profile_id not in PROFILES:
        raise ValidationError("unknown root domain analysis profile")
    amount = "absolute_profit_change" in parent.hypotheses
    if amount != (profile_id == "profit-amount/v1"):
        raise ValidationError("root profile differs from the explicit amount goal")
    refs = {}
    for domain, cls, datasets in (("financial", FinancialAnalysisRequest, FINANCIAL_DATASETS),
                                  ("market", MarketAnalysisRequest, MARKET_DATASETS)):
        if any(b.dataset in datasets for b in parent.bindings):
            request = cls.from_parent(parent)
            refs[domain] = "task:" + digest({"schema": TASK_VERSION, "catalog": CATALOG_VERSION,
                "root_request_ref": digest(parent.to_dict()), "request": request.to_dict(),
                "operators": required_operators(request), "checks": review_checks(request),
                "required_checks": required_checks(request)})
    return refs


def ownership(parent):
    """Rules for result/check ownership, independent of model choices or values."""
    checks = {h: ("financial" if h in FINANCIAL_HYPOTHESES else "market" if h in MARKET_HYPOTHESES else "parent")
              for h in parent.hypotheses}
    return {"schema": "domain-analysis-ownership/v1", "check_ownership": checks,
            "claim_ownership": {"financial_snapshot": "financial", "income_yoy": "financial",
                                "profit_amount_change": "financial", "market_price_window": "market",
                                "factor_adjusted_window": "market", "cross_domain": "parent"}}


def domain_task(request, *, root_run_id, parent_run_id, spec, source_envelope,
                allocation_id, deadline, authorization_ref):
    """Create the complete application-bound immutable task envelope."""
    domain = domain_of(request)
    aware(deadline)
    expected_spec = FinancialAnalysisChildSpec if domain == "financial" else MarketAnalysisChildSpec
    if (not isinstance(spec, expected_spec) or type(source_envelope) is not dict
            or not _hash(authorization_ref) or any(type(v) is not str or not v for v in
                (root_run_id, parent_run_id, allocation_id))):
        raise ValidationError("invalid domain analysis task bindings")
    task = {"schema": TASK_VERSION, "domain": domain, "root_run_id": root_run_id,
            "parent_run_id": parent_run_id, "request": request.to_dict(),
            "request_ref": digest(request.to_dict()), "parent_request_ref": request.parent_request_ref,
            "profile_id": request.profile_id, "spec_ref": spec.identity, "catalog_version": CATALOG_VERSION,
            "required_operators": required_operators(request), "allowed_operators": required_operators(request),
            "required_checks": required_checks(request), "review_checks": review_checks(request),
            "source_envelope": source_envelope, "source_envelope_ref": digest(source_envelope),
            "authorization_ref": authorization_ref, "allocation_id": allocation_id,
            "deadline": deadline.isoformat(), "context_bytes": 12000,
            "limits": {"decisions": spec.max_decisions, "tools": spec.max_tools, "tokens": spec.max_tokens,
                       "seconds": spec.max_seconds},
            "coverage_rules": {"canonical_domain_projection": domain, "retain_legal_insufficiency": True,
                               "independent_local_verification": True}}
    return {**task, "task_ref": digest(task)}


def validate_receipt(receipt, *, tool=None, input_revision=None, output_revision=None):
    """Validate explicit real execution linkage; a content digest alone is insufficient."""
    keys = {"tool", "call_id", "input_revision", "output_revision", "started_ref", "finished_ref"}
    if (type(receipt) is not dict or set(receipt) != keys
            or type(receipt["tool"]) is not str or type(receipt["call_id"]) is not str or not receipt["call_id"]
            or any(not _hash(receipt[k]) for k in ("input_revision", "output_revision", "started_ref", "finished_ref"))
            or tool is not None and receipt["tool"] != tool
            or input_revision is not None and receipt["input_revision"] != input_revision
            or output_revision is not None and receipt["output_revision"] != output_revision):
        raise ValidationError("domain analysis execution receipt differs from its bound operation")
    return dict(receipt)
