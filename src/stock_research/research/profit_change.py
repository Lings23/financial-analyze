"""Opt-in signed profit-amount test, separate from positive-base percentage YoY.

Only a new versioned study may request this extension. This module neither changes
the legacy catalogue nor performs any data reads. Its independent Fraction oracle
checks the extra Claim and hypothesis from the already authorized source rows.
"""
from datetime import datetime
from decimal import Decimal, localcontext
from fractions import Fraction

from ..errors import IntegrityError
from ..models import DataRecord, PITMode, aware, digest


PROFIT_HYPOTHESIS_ID = "absolute_profit_change"
PROFIT_CLAIM_NAME = "financial_income.absolute_profit_change"
PROFIT_FORMULA = ("current_same_period - prior_year_same_period; signed CNY amount; "
                  "no positive-base condition")
PROFIT_CATALOGUE = (
    "同报告期归母净利润金额增加",
    ["financial_income"],
    "本期累计合并归母净利润减上年同报告期金额大于零；允许非正基数；不是百分比同比或因果解释",
)


def _require(condition):
    if not condition:
        raise IntegrityError("profit amount extension verification failed")


def _requested(request):
    return PROFIT_HYPOTHESIS_ID in request.hypotheses


def _visible_income(datasets, request):
    """Validate the read boundary, without treating missing data as an amount."""
    result = datasets.get("financial_income")
    if result is None:
        return []
    binding = next((b for b in request.bindings if b.dataset == "financial_income"), None)
    _require(binding is not None and result["snapshot"] == binding.snapshot
             and result["provider"] == binding.provider)
    rows = []
    for row in result["records"]:
        record = DataRecord.from_dict(row)
        _require(record.dataset.value == "financial_income"
                 and record.provider == binding.provider
                 and record.security_id == request.data_request(binding).security.security_id
                 and binding.start <= record.period <= binding.end
                 and record.available_at <= request.as_of
                 and (request.mode != PITMode.SYSTEM or record.ingested_at <= request.as_of))
        rows.append(record)
    # The normal PIT selector must have selected one version per report period.
    _require(len({r.period for r in rows}) == len(rows))
    return sorted(rows, key=lambda r: r.period)


def _production_inputs(datasets, request):
    rows = _visible_income(datasets, request)
    if not rows:
        return None, "no_visible_financial_period"
    current = rows[-1]
    prior_period = str(current.period.year - 1) + current.period.isoformat()[4:]
    prior = next((r for r in rows if r.period.isoformat() == prior_period), None)
    if prior is None:
        return None, "prior_year_same_period_not_visible"
    cm = next(m for m in current.metrics if m.name == "net_income_parent")
    pm = next(m for m in prior.metrics if m.name == "net_income_parent")
    if cm.value is None or pm.value is None:
        return None, "net_income_parent_missing"
    if cm.unit != "CNY" or pm.unit != "CNY" or current.basis != prior.basis:
        return None, "financial_unit_or_basis_mismatch"
    return (prior, current, pm, cm), None


def add_profit_change_claim(computed, datasets, request):
    """Append the explicitly requested signed monetary difference to a new study."""
    if not _requested(request):
        return computed
    inputs, reason = _production_inputs(datasets, request)
    if inputs is None:
        computed["gaps"] = sorted(set(computed.get("gaps", [])) |
                                  {"financial_income:absolute_profit_change:" + reason})
        return computed
    prior, current, pm, cm = inputs
    ids = [digest({"record": r.record_id, "metric": "net_income_parent"})
           for r in (prior, current)]
    for key, record, metric in zip(ids, (prior, current), (pm, cm)):
        source = computed["evidence"].get(key, {})
        _require(source.get("id") == key and source.get("record_id") == record.record_id
                 and source.get("metric") == "net_income_parent"
                 and source.get("value") == str(metric.value) and source.get("unit") == "CNY"
                 and source.get("period") == record.period.isoformat()
                 and source.get("snapshot") == datasets["financial_income"]["snapshot"])
    _require(not any(f["name"] == PROFIT_CLAIM_NAME for f in computed["facts"]))
    # A monetary subtraction can be exact, even if its inputs exceed the legacy
    # ratio precision. No percentage or division by a loss/zero base is introduced.
    with localcontext() as ctx:
        ctx.prec = max(34, max(pm.value.adjusted(), cm.value.adjusted())
                       - min(pm.value.as_tuple().exponent, cm.value.as_tuple().exponent) + 2)
        value = cm.value - pm.value
    fact = {"name": PROFIT_CLAIM_NAME, "value": str(value), "unit": "CNY",
            "inputs": ids, "formula": PROFIT_FORMULA,
            "window": [prior.period.isoformat(), current.period.isoformat()],
            "available_at": max(prior.available_at, current.available_at).isoformat()}
    fact["id"] = digest(fact)
    computed["facts"].append(fact)
    return computed


def profit_change_hypothesis(computed, datasets, request):
    """A positive signed amount supports improvement; zero/decrease are counterfacts."""
    if not _requested(request):
        return None
    fact = next((f for f in computed["facts"] if f["name"] == PROFIT_CLAIM_NAME), None)
    references, counter = [], []
    if fact is None:
        _, reason = _production_inputs(datasets, request)
        status = "insufficient"
        _require(reason is not None)
    else:
        amount = Decimal(fact["value"])
        references = [fact["id"]]
        if amount > 0:
            status, reason = "supported", "same_period_profit_amount_increased"
        else:
            status, reason = "unsupported", ("same_period_profit_amount_decreased" if amount < 0
                                               else "same_period_profit_amount_unchanged")
            counter = references[:]
    return {"id": PROFIT_HYPOTHESIS_ID, "title": PROFIT_CATALOGUE[0], "status": status,
            "reason": reason, "required_evidence": PROFIT_CATALOGUE[1][:],
            "test_rule": PROFIT_CATALOGUE[2], "claim_ids": references,
            "counterevidence_claim_ids": counter, "anchor_record_id": None,
            "conclusion_strength": "descriptive_test_only", "causal_claim": False,
            "coverage": "not_verified"}


def expected_profit_change_claims(datasets, request):
    """Independent exact oracle: select and subtract raw input strings as Fractions.

    This does not call the production input selector, Decimal subtraction, or
    production hypothesis evaluator. The shared boundary validator validates only
    authorization/PIT/schema and does not supply arithmetic or conclusions.
    """
    if not _requested(request):
        return {}, None
    _visible_income(datasets, request)
    rows = sorted(datasets.get("financial_income", {}).get("records", []),
                  key=lambda row: row["period"])
    if not rows:
        return {}, "no_visible_financial_period"
    current = rows[-1]
    prior = next((row for row in rows if row["period"] ==
                  str(int(current["period"][:4]) - 1) + current["period"][4:]), None)
    if prior is None:
        return {}, "prior_year_same_period_not_visible"
    fields = [next(m for m in row["metrics"] if m["name"] == "net_income_parent")
              for row in (prior, current)]
    if any(m["value"] is None for m in fields):
        return {}, "net_income_parent_missing"
    if any(m["unit"] != "CNY" for m in fields) or prior["basis"] != current["basis"]:
        return {}, "financial_unit_or_basis_mismatch"
    ids = [digest({"record": DataRecord.from_dict(row).record_id, "metric": "net_income_parent"})
           for row in (prior, current)]
    difference = Fraction(fields[1]["value"]) - Fraction(fields[0]["value"])
    return {PROFIT_CLAIM_NAME: (difference, "CNY", ids,
                              [prior["period"], current["period"]], PROFIT_FORMULA)}, None


def verify_profit_change(computed, datasets, request):
    """Verify the entire extension; the caller separately verifies legacy Claims."""
    expected, missing_reason = expected_profit_change_claims(datasets, request)
    facts = [f for f in computed["facts"] if f["name"] == PROFIT_CLAIM_NAME]
    hypotheses = [h for h in computed["hypotheses"] if h["id"] == PROFIT_HYPOTHESIS_ID]
    _require(len(facts) == len(expected) and len(hypotheses) == int(_requested(request)))
    if not _requested(request):
        return {"numeric_claims": 0, "hypotheses_checked": 0,
                "method": "independent_fraction_profit_amount/v1"}
    references, counter = [], []
    if not expected:
        status, reason = "insufficient", missing_reason
    else:
        exact, unit, inputs, window, formula = expected[PROFIT_CLAIM_NAME]
        fact = facts[0]
        _require(set(fact) == {"name", "value", "unit", "inputs", "formula", "window", "available_at", "id"}
                 and fact["id"] == digest({k: v for k, v in fact.items() if k != "id"})
                 and fact["unit"] == unit and fact["inputs"] == inputs
                 and fact["window"] == window and fact["formula"] == formula)
        try:
            _require(Fraction(fact["value"]) == exact)
        except (ValueError, TypeError, ZeroDivisionError):
            raise IntegrityError("profit amount extension verification failed") from None
        # Extra Evidence must match its original normalized/raw values and lineage.
        records = {r.record_id: r for r in _visible_income(datasets, request)}
        for key in inputs:
            source = computed["evidence"].get(key, {})
            record = records.get(source.get("record_id"))
            _require(record is not None)
            metric = next(m for m in record.metrics if m.name == "net_income_parent")
            binding = next(b for b in request.bindings if b.dataset == "financial_income")
            exact_source = {"id": key, "kind": "source", "record_id": record.record_id,
                            "metric": "net_income_parent", "value": str(metric.value), "unit": metric.unit,
                            "raw_value": metric.raw_value, "raw_unit": metric.raw_unit,
                            "period": record.period.isoformat(), "basis": record.basis,
                            "provider": record.provider, "provider_version": record.provider_version,
                            "source_url": record.source_url, "revision_id": record.revision_id,
                            "artifact_ids": list(record.artifact_ids), "provider_call_id": record.provider_call_id,
                            "available_at": record.available_at.isoformat(),
                            "published_at": record.published_at.isoformat() if record.published_at else None,
                            "retrieved_at": record.retrieved_at.isoformat(),
                            "ingested_at": record.ingested_at.isoformat(),
                            "availability_basis": record.availability_basis, "snapshot": binding.snapshot}
            _require(all(source.get(k) == v for k, v in exact_source.items())
                     and not set(source) - set(exact_source) - {"tool_call_id"})
        available = max(aware(datetime.fromisoformat(computed["evidence"][key]["available_at"]))
                        for key in inputs)
        _require(aware(datetime.fromisoformat(fact["available_at"])) == available
                 and available <= request.as_of)
        references = [fact["id"]]
        if exact > 0:
            status, reason = "supported", "same_period_profit_amount_increased"
        elif exact < 0:
            status, reason, counter = "unsupported", "same_period_profit_amount_decreased", references[:]
        else:
            status, reason, counter = "unsupported", "same_period_profit_amount_unchanged", references[:]
    exact_hypothesis = {
        "id": PROFIT_HYPOTHESIS_ID, "title": PROFIT_CATALOGUE[0], "status": status, "reason": reason,
        "required_evidence": PROFIT_CATALOGUE[1][:], "test_rule": PROFIT_CATALOGUE[2],
        "claim_ids": references, "counterevidence_claim_ids": counter, "anchor_record_id": None,
        "conclusion_strength": "descriptive_test_only", "causal_claim": False, "coverage": "not_verified"}
    _require(hypotheses[0] == exact_hypothesis)
    return {"numeric_claims": len(expected), "hypotheses_checked": 1,
            "method": "independent_fraction_profit_amount/v1"}


def profit_change_diagnostics(computed, datasets, request):
    """Optional v5 annotation for this test; missing fields stay explicitly missing."""
    hypothesis = next((h for h in computed.get("hypotheses", [])
                       if h["id"] == PROFIT_HYPOTHESIS_ID), None)
    if hypothesis is None or hypothesis["status"] != "insufficient":
        return []
    data = "data_or_evidence_insufficiency"
    contract = "benchmark_or_request_contract_defect"
    code, category, detail = {
        "no_visible_financial_period": ("missing_dataset", data, "授权可见利润表为空，未将缺失当零。"),
        "prior_year_same_period_not_visible": ("missing_report_period", data, "缺少上年同报告期可见归母净利润，未将缺失当零。"),
        "net_income_parent_missing": ("missing_metric", data, "归母净利润字段显式缺失，未将缺失当零。"),
        "financial_unit_or_basis_mismatch": ("incompatible_financial_unit", contract, "本期与基期未同时具备同口径人民币金额。"),
    }[hypothesis["reason"]]
    rows = _visible_income(datasets, request)
    refs = sorted(r.record_id for r in rows)
    return [{"hypothesis_id": PROFIT_HYPOTHESIS_ID, "status": "insufficient", "insufficiency_reasons": [{
        "code": code, "failure_category": category, "datasets": ["financial_income"],
        "record_refs": refs,
        "evidence_refs": sorted(key for key, value in computed["evidence"].items()
                                if value.get("record_id") in refs
                                and value.get("metric") == "net_income_parent"),
        "metric": "net_income_parent", "detail": detail}]}]
