"""Versioned domain production, review and Parent consumption adapters.

No model, service reads, grants or Runtime are created here. Runtime authorizes
every input/reuse; these pure adapters verify pinned scope and canonical results.
"""
from copy import deepcopy
import hashlib
import hmac
import json
import re
import secrets

from ..errors import IntegrityError, ValidationError
from ..models import canonical_json, digest
from .calculation import calculate_cross_domain, calculate_financial, calculate_market, dataset_gaps
from .hypotheses import test_hypotheses
from .profit_change import calculate_profit_change
from .study import add_event_claims
from .verification import (DOMAIN_DATASETS, DOMAIN_HYPOTHESES, claim_domain, eid,
                           expected_claims, verify_domain)


DOMAIN_OPERATOR_IDS = {
    "financial": ("financial_snapshot", "income_yoy"),
    "market": ("market_price_window", "factor_adjusted_window"),
}
AMOUNT_OPERATOR = "profit_amount_change"
_ATTESTATION_KEY = secrets.token_bytes(32)
_ATTESTATION_ISSUER = object()


def _require(condition):
    if not condition:
        raise IntegrityError("domain composition identity or coverage conflict")


def _hash(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _coverage(computed):
    return {"fact_ids": [fact["id"] for fact in computed["facts"]],
            "evidence_ids": sorted(computed["evidence"]),
            "hypothesis_ids": [hypothesis["id"] for hypothesis in computed["hypotheses"]],
            "gaps_ref": digest(computed["gaps"]),
            "counterevidence_ref": digest({hypothesis["id"]: hypothesis["counterevidence_claim_ids"]
                                          for hypothesis in computed["hypotheses"]})}


def _check_structure(computed, request, domain):
    """Hash/ownership/coverage only: no expected arithmetic or source calculator."""
    _require(type(computed) is dict and type(computed.get("facts")) is list
             and type(computed.get("evidence")) is dict and type(computed.get("gaps")) is list
             and type(computed.get("hypotheses")) is list)
    names, ids = set(), set()
    for fact in computed["facts"]:
        _require(set(fact) == {"name", "value", "unit", "inputs", "formula", "window", "available_at", "id"}
                 and claim_domain(fact["name"]) == domain
                 and fact["name"] not in names and fact["id"] not in ids
                 and fact["id"] == digest({k: v for k, v in fact.items() if k != "id"})
                 and all(key in computed["evidence"] for key in fact["inputs"]))
        names.add(fact["name"])
        ids.add(fact["id"])
    for key, source in computed["evidence"].items():
        _require(key == source.get("id") == digest({"record": source.get("record_id"), "metric": source.get("metric")}))
    expected_checks = [hid for hid in request.hypotheses if hid in DOMAIN_HYPOTHESES[domain]]
    _require([hypothesis["id"] for hypothesis in computed["hypotheses"]] == expected_checks
             and computed["gaps"] == sorted(set(computed["gaps"])))
    for hypothesis in computed["hypotheses"]:
        _require(set(hypothesis["claim_ids"]) <= ids
                 and set(hypothesis["counterevidence_claim_ids"]) <= ids)
    local = computed.get("local_verification", {})
    _require(local.get("status") == "verified" and local.get("domain") == domain
             and local.get("method") == "independent_fraction_domain_projection/v1"
             and local.get("numeric_claims") == len(computed["facts"])
             and local.get("evidence_checked") == len(computed["evidence"])
             and local.get("hypotheses_checked") == len(computed["hypotheses"]))


class ValidatedDomainResult:
    """Process-local immutable capability issued after Runtime receipt validation.

    It is never serialized into a Checkpoint or emitted to the model. On resume
    Runtime rebuilds it only after validating the persisted real review receipt.
    Its private issuer and MAC prevent a plain dictionary or copied report from
    claiming this trusted path. Python application code is the trusted boundary.
    """
    __slots__ = ("_content", "_proof", "_mac")

    def __init__(self, content, proof, *, _issuer=None):
        if _issuer is not _ATTESTATION_ISSUER:
            raise IntegrityError("domain attestation requires the Runtime issuer")
        object.__setattr__(self, "_content", json.dumps(content, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
        object.__setattr__(self, "_proof", canonical_json(proof))
        object.__setattr__(self, "_mac", self._signature())

    def __setattr__(self, name, value):
        raise IntegrityError("validated domain result is immutable")

    def _signature(self):
        return hmac.new(_ATTESTATION_KEY, (self._content + "\n" + self._proof).encode("utf-8"), hashlib.sha256).digest()

    def consume(self, datasets, request, domain):
        _require(hmac.compare_digest(self._mac, self._signature()))
        content, proof = json.loads(self._content), json.loads(self._proof)
        scoped = {key: value for key, value in datasets.items() if key in DOMAIN_DATASETS[domain]}
        _require(proof["domain"] == domain and proof["root_request_ref"] == digest(request.to_dict())
                 and proof["source_result_ref"] == digest(scoped)
                 and proof["computed_ref"] == digest(content)
                 and proof["coverage"] == _coverage(content))
        _check_structure(content, request, domain)
        return content


def _attest_validated_domain(computed, datasets, request, domain, proof):
    """Internal factory; Runtime must first authenticate the persisted checkpoint.

    This factory binds the already executed local proof to sources, requests,
    receipts, task/Spec/operator/ownership and full coverage. It deliberately
    performs no local arithmetic verification: only domain_review may do that.
    """
    from .domain_analysis_contracts import ownership
    _require(domain in DOMAIN_DATASETS and type(proof) is dict)
    mandatory = {"root_request_ref", "domain_request_ref", "task_ref", "spec_ref", "checkpoint_ref",
                 "review_receipt_ref", "ownership_ref", "required_operators", "check_ids", "result_ref"}
    _require(mandatory <= set(proof))
    _check_structure(computed, request, domain)
    for key in ("root_request_ref", "domain_request_ref", "spec_ref", "review_receipt_ref", "ownership_ref", "result_ref"):
        _require(_hash(proof[key]))
    _require(type(proof["task_ref"]) is str and _hash(proof["task_ref"].removeprefix("task:"))
             and type(proof["checkpoint_ref"]) in {dict, str} and bool(proof["checkpoint_ref"]))
    operators = list(DOMAIN_OPERATOR_IDS[domain]) + ([AMOUNT_OPERATOR] if domain == "financial"
                  and "absolute_profit_change" in request.hypotheses else [])
    checks = {"read:" + domain, "calculation", "domain_review", *["operator:" + operator for operator in operators],
              *["hypothesis:" + hid for hid in request.hypotheses if hid in DOMAIN_HYPOTHESES[domain]]}
    _require(set(proof["required_operators"]) == set(operators)
             and set(proof["check_ids"]) == checks and len(proof["check_ids"]) == len(checks)
             and proof["ownership_ref"] == digest(ownership(request)))
    scoped = {key: value for key, value in datasets.items() if key in DOMAIN_DATASETS[domain]}
    bindings = {"schema": "domain-local-verification-attestation/v1", "domain": domain,
                "root_request_ref": digest(request.to_dict()), "computed_ref": digest(computed),
                "source_result_ref": digest(scoped), "local_verification_ref": digest(computed["local_verification"]),
                "coverage": _coverage(computed)}
    for key, value in bindings.items():
        _require(key not in proof or proof[key] == value)
    return ValidatedDomainResult(deepcopy(computed), {**deepcopy(proof), **bindings}, _issuer=_ATTESTATION_ISSUER)


def _consume_domains(datasets, request, domain_results, trusted_domains):
    supplied, trusted = domain_results or {}, trusted_domains or {}
    if type(supplied) is not dict or not set(supplied) <= set(DOMAIN_DATASETS):
        raise ValidationError("unknown supplied analysis domain")
    _require(type(trusted) is dict and not set(supplied) & set(trusted)
             and set(trusted) <= set(DOMAIN_DATASETS))
    results = {}
    for domain, computed in supplied.items():
        verify_domain(computed, datasets, request, domain)
        results[domain] = computed
    for domain, attestation in trusted.items():
        _require(type(attestation) is ValidatedDomainResult)
        results[domain] = attestation.consume(datasets, request, domain)
    return results


def _canonicalize_domain(result, datasets, domain):
    """Canonical legacy order using only source field order and existing IDs."""
    names, sources = [], []
    def rows(dataset):
        return sorted(datasets.get(dataset, {}).get("records", []), key=lambda row: row["period"])
    if domain == "market":
        names = ["observed_price_change", "observed_max_drawdown", "factor_adjusted_price_change"]
        for dataset, metric in (("market_daily", "close"), ("adjustment_factor", "factor")):
            sources.extend(eid(row, metric) for row in rows(dataset))
    else:
        for dataset in ("financial_income", "financial_balance", "financial_cashflow"):
            rr = rows(dataset)
            if not rr:
                continue
            latest = rr[-1]
            names.extend(dataset + "." + metric["name"] for metric in latest["metrics"])
            sources.extend(eid(latest, metric["name"]) for metric in latest["metrics"])
            if dataset == "financial_income":
                names.extend(["revenue_yoy", "net_income_parent_yoy"])
                prior = next((row for row in rr if row["period"] ==
                              str(int(latest["period"][:4]) - 1) + latest["period"][4:]), None)
                for name in ("revenue", "net_income_parent"):
                    sources.append(eid(latest, name))
                    if prior is not None:
                        sources.append(eid(prior, name))
        names.append("financial_income.absolute_profit_change")
    order = {name: index for index, name in enumerate(names)}
    result["facts"].sort(key=lambda fact: order.get(fact["name"], len(order)))
    source_order = list(dict.fromkeys(key for key in sources if key in result["evidence"]))
    source_order.extend(key for key in result["evidence"] if key not in source_order)
    result["evidence"] = {key: result["evidence"][key] for key in source_order}


def _merge(*parts):
    facts, evidence, gaps = {}, {}, []
    names = {}
    for part in parts:
        for fact in part["facts"]:
            key = fact["id"]
            _require(key not in facts or facts[key] == fact)
            _require(fact["name"] not in names or names[fact["name"]] == key)
            facts.setdefault(key, deepcopy(fact))
            names[fact["name"]] = key
        for key, source in part["evidence"].items():
            _require(key not in evidence or evidence[key] == source)
            evidence.setdefault(key, deepcopy(source))
        gaps.extend(part["gaps"])
    return {"facts": list(facts.values()), "evidence": evidence, "gaps": sorted(set(gaps))}


def calculate_domain(datasets, request, domain, operators=None):
    """Execute only the selected registered production operators in one domain.

    All operators are required before review. Selection may change order/packing
    of legal calls; it never changes the frozen full-domain output requirements.
    """
    if domain not in DOMAIN_OPERATOR_IDS:
        raise ValidationError("unknown analysis domain")
    amount = "absolute_profit_change" in request.hypotheses
    allowed = set(DOMAIN_OPERATOR_IDS[domain])
    if domain == "financial" and amount:
        if getattr(request, "hypothesis_version", None) != "profit-change/v1":
            raise ValidationError("amount operator requires explicit profit-change/v1 profile")
        allowed.add(AMOUNT_OPERATOR)
    selected = tuple(DOMAIN_OPERATOR_IDS[domain]) + ((AMOUNT_OPERATOR,) if domain == "financial" and amount else ()) if operators is None else tuple(operators)
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= allowed:
        raise ValidationError("unknown or unauthorized domain operator")
    scoped = {k: v for k, v in datasets.items() if k in DOMAIN_DATASETS[domain]}
    core = [operator for operator in selected if operator != AMOUNT_OPERATOR]
    parts = []
    if core:
        parts.append(calculate_financial(scoped, core) if domain == "financial" else calculate_market(scoped, core))
    if AMOUNT_OPERATOR in selected:
        parts.append(calculate_profit_change(scoped, request))
    result = _merge(*parts)
    # These placeholders cannot establish or suppress a root event conclusion.
    result["event_anchor"] = {"status": "insufficient", "reason": "event_anchor_not_requested"}
    return result


def merge_domain_calculations(*parts):
    """Losslessly accumulate distinct operator outputs, rejecting conflicts."""
    result = _merge(*parts)
    result["event_anchor"] = {"status": "insufficient", "reason": "event_anchor_not_requested"}
    return result


def review_domain(computed, datasets, request, domain):
    """Run all frozen local rules and independent complete-domain verification."""
    if domain not in DOMAIN_DATASETS:
        raise ValidationError("unknown analysis domain")
    result = deepcopy(computed)
    scoped = {k: v for k, v in datasets.items() if k in DOMAIN_DATASETS[domain]}
    _canonicalize_domain(result, scoped, domain)
    result["hypotheses"] = test_hypotheses(result, scoped, request,
                                         hypothesis_ids=DOMAIN_HYPOTHESES[domain])
    result["local_verification"] = verify_domain(result, scoped, request, domain)
    return result


def compose_domains(datasets, request, domain_results=None, *, trusted_domains=None):
    """Consume validated delegated objects; produce only missing/cross domains.

    Empty results are the strong direct producer. Supplied domains are checked by
    the independent oracle and their production operators are never called here.
    The caller must actually execute the original full root verification later.
    """
    supplied = _consume_domains(datasets, request, domain_results, trusted_domains)
    domains = {}
    for domain in ("market", "financial"):
        if domain in supplied:
            domains[domain] = supplied[domain]
        else:
            domains[domain] = calculate_domain(datasets, request, domain)
    cross = calculate_cross_domain(datasets, domains["market"])
    computed = _merge(domains["market"], cross, domains["financial"])
    computed["gaps"] = sorted(set(computed["gaps"]) | set(dataset_gaps(datasets)))
    # Legacy canonical order is market, benchmark, financial, event, amount.
    amount = [fact for fact in computed["facts"] if fact["name"] == "financial_income.absolute_profit_change"]
    computed["facts"] = [fact for fact in computed["facts"] if fact["name"] != "financial_income.absolute_profit_change"]
    add_event_claims(computed, datasets, request)
    computed["facts"].extend(amount)
    if trusted_domains is None:
        # Preserve the old public dictionary path's independently checked oracle.
        expected = expected_claims(datasets, request)
        _require(len(computed["facts"]) == len(expected)
                 and {fact["name"] for fact in computed["facts"]} == set(expected))
    return computed


def test_remaining_hypotheses(computed, datasets, request, domain_results=None, *, trusted_domains=None):
    """Consume delegated reviews, evaluating only Parent/undelegated rules."""
    supplied = _consume_domains(datasets, request, domain_results, trusted_domains)
    hypotheses = {}
    delegated = set()
    for domain, result in supplied.items():
        if domain not in DOMAIN_HYPOTHESES:
            raise ValidationError("unknown supplied review domain")
        delegated.update(DOMAIN_HYPOTHESES[domain])
        for hypothesis in result["hypotheses"]:
            _require(hypothesis["id"] not in hypotheses)
            hypotheses[hypothesis["id"]] = deepcopy(hypothesis)
    for hypothesis in test_hypotheses(computed, datasets, request,
                                      hypothesis_ids=set(request.hypotheses) - delegated):
        _require(hypothesis["id"] not in hypotheses)
        hypotheses[hypothesis["id"]] = hypothesis
    _require(set(hypotheses) == set(request.hypotheses))
    return [hypotheses[hid] for hid in request.hypotheses]
