"""Independent rational arithmetic verifier, bound to authorized PIT source rows.

This verifies transformation and lineage, not provider accuracy or causal truth.
"""
from datetime import datetime
from decimal import Decimal
from fractions import Fraction

from ..errors import IntegrityError
from ..models import DataRecord, PITMode, aware, digest
from .hypotheses import event_anchor, event_prices, test_hypotheses
from .profit_change import expected_profit_change_claims, verify_profit_change


FORMULAS = {
    "observed_price_change": "last_close / first_close - 1; unadjusted",
    "observed_max_drawdown": "max(1 - close / running_max(close)); observed unadjusted closes",
    "factor_adjusted_price_change": "(last_close * last_factor) / (first_close * first_factor) - 1; not total return",
    "benchmark_price_change": "last_index_close / first_index_close - 1; price index",
    "price_change_difference": "stock_unadjusted_price_change - benchmark_price_change; not alpha",
    "event_observed_price_change": "last_post_anchor_close / last_pre_anchor_close - 1; unadjusted; not causal impact",
}
IDENTITY = "identity; latest visible report period; preserve source basis"
YOY = "current_same_period / prior_year_same_period - 1; positive base required"


def eid(row, name):
    return digest({"record": DataRecord.from_dict(row).record_id, "metric": name})


def expected_claims(datasets, request):
    """No production Decimal calculation calls; exact arithmetic from pinned rows."""
    expected = {}

    def rows(dataset):
        return sorted(datasets.get(dataset, {}).get("records", []), key=lambda r: r["period"])

    def value(row, name):
        item = next(m["value"] for m in row["metrics"] if m["name"] == name)
        return None if item is None else Fraction(Decimal(item))

    def add(name, v, unit, inputs, window, formula=None):
        expected[name] = (v, unit, list(dict.fromkeys(inputs)), window, formula or FORMULAS[name])

    def series(dataset):
        rr = rows(dataset)
        vv = [value(r, "close") for r in rr]
        return (rr, vv) if len(rr) >= 2 and all(v is not None and v > 0 for v in vv) else ([], [])

    prices, closes = series("market_daily")
    if prices:
        window = [prices[0]["period"], prices[-1]["period"]]
        price_inputs = [eid(prices[0], "close"), eid(prices[-1], "close")]
        change = closes[-1] / closes[0] - 1
        add("observed_price_change", change, "ratio", price_inputs, window)
        add("observed_max_drawdown", max(1-v/max(closes[:i+1]) for i, v in enumerate(closes)),
            "ratio", [eid(r, "close") for r in prices], window)
        factors = {r["period"]: r for r in rows("adjustment_factor")}
        if all(r["period"] in factors and value(factors[r["period"]], "factor") is not None
               and value(factors[r["period"]], "factor") > 0 for r in prices):
            a, b = (factors[r["period"]] for r in (prices[0], prices[-1]))
            add("factor_adjusted_price_change", closes[-1]*value(b, "factor")/(closes[0]*value(a, "factor"))-1,
                "ratio", [*price_inputs, eid(a, "factor"), eid(b, "factor")], window)
        index, index_values = series("index_daily")
        if index and [r["period"] for r in index] == [r["period"] for r in prices]:
            benchmark = index_values[-1] / index_values[0] - 1
            inputs = [eid(index[0], "close"), eid(index[-1], "close")]
            add("benchmark_price_change", benchmark, "ratio", inputs, window)
            add("price_change_difference", change-benchmark, "ratio", [*price_inputs, *inputs], window)
        pair = event_prices(datasets, event_anchor(datasets, request))
        if pair:
            a, b = pair
            add("event_observed_price_change", value(b, "close")/value(a, "close")-1,
                "ratio", [eid(a, "close"), eid(b, "close")], [a["period"], b["period"]])
    for dataset in ("financial_income", "financial_balance", "financial_cashflow"):
        records = rows(dataset)
        if not records:
            continue
        latest = records[-1]
        for metric in latest["metrics"]:
            v = value(latest, metric["name"])
            if v is not None:
                add(dataset+"."+metric["name"], v, metric["unit"], [eid(latest, metric["name"])],
                    [latest["period"], latest["period"]], IDENTITY)
        if dataset == "financial_income":
            prior = next((r for r in records if r["period"] ==
                          str(int(latest["period"][:4])-1)+latest["period"][4:]), None)
            if prior:
                for name in ("revenue", "net_income_parent"):
                    current, base = value(latest, name), value(prior, name)
                    if current is not None and base is not None and base > 0:
                        add(name+"_yoy", current/base-1, "ratio", [eid(prior, name), eid(latest, name)],
                            [prior["period"], latest["period"]], YOY)
    if "absolute_profit_change" in request.hypotheses:
        extension, _ = expected_profit_change_claims(datasets, request)
        expected.update(extension)
    return expected


def verify(computed, datasets, request):
    """Reject fabricated, omitted, rounded beyond contract, misbound or future Claims."""
    def require(condition):
        if not condition:
            raise IntegrityError("study claim verification failed")

    bindings = {b.dataset: b for b in request.bindings}
    records = {}
    for dataset, result in datasets.items():
        require(dataset in bindings and result["snapshot"] == bindings[dataset].snapshot
                and result["provider"] == bindings[dataset].provider)
        for row in result["records"]:
            record = DataRecord.from_dict(row)
            require(record.provider == bindings[dataset].provider
                    and record.available_at <= request.as_of
                    and (request.mode != PITMode.SYSTEM or record.ingested_at <= request.as_of)
                    and record.dataset.value == dataset
                    and bindings[dataset].start <= record.period <= bindings[dataset].end
                    and record.security_id == request.data_request(bindings[dataset]).security.security_id)
            records[record.record_id] = (record, result["snapshot"])
    evidence = computed["evidence"]
    for key, source in evidence.items():
        require(source["record_id"] in records)
        record, snapshot = records[source["record_id"]]
        metric = next((m for m in record.metrics if m.name == source["metric"]), None)
        require(metric is not None)
        require(key == source["id"] == digest({"record": record.record_id, "metric": metric.name}))
        exact = {"kind": "source", "value": None if metric.value is None else str(metric.value),
                 "unit": metric.unit, "raw_value": metric.raw_value, "raw_unit": metric.raw_unit,
                 "period": record.period.isoformat(), "basis": record.basis, "provider": record.provider,
                 "provider_version": record.provider_version, "source_url": record.source_url,
                 "revision_id": record.revision_id, "artifact_ids": list(record.artifact_ids),
                 "provider_call_id": record.provider_call_id, "available_at": record.available_at.isoformat(),
                 "published_at": record.published_at.isoformat() if getattr(record, "published_at", None) else None,
                 "retrieved_at": record.retrieved_at.isoformat(), "ingested_at": record.ingested_at.isoformat(),
                 "availability_basis": record.availability_basis, "snapshot": snapshot}
        require(all(source.get(k) == v for k, v in exact.items()))
        require(not set(source)-set(exact)-{"id", "record_id", "metric", "tool_call_id"})
    facts = computed["facts"]
    expected = expected_claims(datasets, request)
    require(len(facts) == len(expected) and {f["name"] for f in facts} == set(expected))
    for fact in facts:
        v, unit, inputs, window, formula = expected[fact["name"]]
        require(set(fact) == {"name", "value", "unit", "inputs", "formula", "window", "available_at", "id"})
        require(fact["id"] == digest({k: val for k, val in fact.items() if k != "id"})
                and fact["unit"] == unit and fact["inputs"] == inputs and fact["window"] == window
                and fact["formula"] == formula and all(i in evidence and evidence[i]["value"] is not None for i in inputs))
        number = Decimal(fact["value"])
        require(number.is_finite())
        tolerance = Fraction(0) if formula == IDENTITY else max(Fraction(1, 10**32), abs(v)/10**32)
        require(abs(Fraction(number)-v) <= tolerance)
        latest = max(aware(datetime.fromisoformat(evidence[i]["available_at"])) for i in inputs)
        if fact["name"] == "event_observed_price_change":
            latest = max(latest, aware(datetime.fromisoformat(computed["event_anchor"]["available_at"])))
        require(aware(datetime.fromisoformat(fact["available_at"])) == latest and latest <= request.as_of)
    require(computed["event_anchor"] == event_anchor(datasets, request))
    require(computed["hypotheses"] == test_hypotheses(computed, datasets, request))
    if "absolute_profit_change" in request.hypotheses:
        verify_profit_change(computed, datasets, request)
    return {"status": "verified", "numeric_claims": len(facts), "evidence_checked": len(evidence),
            "hypotheses_checked": len(computed["hypotheses"]), "event_anchor_checked": bool(request.event_record_id),
            "method": "independent_fraction_arithmetic_and_pinned_source_binding",
            "provider_accuracy_certified": False, "causality_established": False}


DOMAIN_DATASETS = {
    "financial": frozenset({"financial_income", "financial_balance", "financial_cashflow"}),
    "market": frozenset({"market_daily", "trade_calendar", "adjustment_factor"}),
}
DOMAIN_HYPOTHESES = {
    "financial": frozenset({"financial_deterioration", "cashflow_divergence", "absolute_profit_change"}),
    "market": frozenset({"mechanical_adjustment"}),
}


def claim_domain(name):
    if name.startswith("financial_") or name in {"revenue_yoy", "net_income_parent_yoy"}:
        return "financial"
    if name in {"observed_price_change", "observed_max_drawdown", "factor_adjusted_price_change"}:
        return "market"
    return "parent"


def expected_domain_projection(datasets, request, domain, *, operators=None):
    """Independent Fraction oracle plus complete source and gap coverage.

    This does not invoke any production calculation or producer input selector.
    It retains missing-valued and non-Claim source Evidence used by the domain.
    """
    if domain not in DOMAIN_DATASETS:
        raise IntegrityError("unknown analysis domain")
    scoped = {k: v for k, v in datasets.items() if k in DOMAIN_DATASETS[domain]}
    expected = {k: v for k, v in expected_claims(scoped, request).items() if claim_domain(k) == domain}
    defaults = ({"financial_snapshot", "income_yoy"} | ({"profit_amount_change"} if
                "absolute_profit_change" in request.hypotheses else set()) if domain == "financial"
                else {"market_price_window", "factor_adjusted_window"})
    selected = defaults if operators is None else set(operators)
    if not selected or not selected <= defaults:
        raise IntegrityError("unknown domain projection operator")
    def included(name):
        if domain == "financial":
            return ("profit_amount_change" in selected if name == "financial_income.absolute_profit_change"
                    else "income_yoy" in selected if name in {"revenue_yoy", "net_income_parent_yoy"}
                    else "financial_snapshot" in selected)
        return ("factor_adjusted_window" in selected if name == "factor_adjusted_price_change"
                else "market_price_window" in selected)
    expected = {name: value for name, value in expected.items() if included(name)}
    sources, gaps = [], []

    def rows(dataset):
        return sorted(scoped.get(dataset, {}).get("records", []), key=lambda row: row["period"])

    def value(row, name):
        raw = next(metric["value"] for metric in row["metrics"] if metric["name"] == name)
        return None if raw is None else Fraction(raw)

    def source(row, name):
        sources.append(eid(row, name))
        return value(row, name)

    if domain == "financial":
        for dataset in (("financial_income", "financial_balance", "financial_cashflow")
                        if selected & {"financial_snapshot", "income_yoy"} else ()):
            if dataset not in scoped:
                continue
            rr = rows(dataset)
            if not rr:
                gaps.append(dataset + ":no_visible_financial_period")
                continue
            latest = rr[-1]
            if "financial_snapshot" in selected:
                for metric in latest["metrics"]:
                    if source(latest, metric["name"]) is None:
                        gaps.append(dataset + ":missing:" + metric["name"])
            if "income_yoy" in selected and dataset == "financial_income":
                prior = next((row for row in rr if row["period"] ==
                              str(int(latest["period"][:4]) - 1) + latest["period"][4:]), None)
                for name in ("revenue", "net_income_parent"):
                    current = source(latest, name)
                    if prior is None:
                        gaps.append(name + ":yoy_prior_year_period_not_visible")
                    else:
                        base = source(prior, name)
                        if current is None or base is None or base <= 0:
                            gaps.append(name + ":yoy_missing_or_nonpositive_base")
        if "profit_amount_change" in selected:
            extension, reason = expected_profit_change_claims(scoped, request)
            if reason is not None:
                gaps.append("financial_income:absolute_profit_change:" + reason)
            elif extension:
                sources.extend(extension["financial_income.absolute_profit_change"][2])
    else:
        prices, invalid = rows("market_daily"), False
        for row in prices:
            close = source(row, "close")
            if close is None or close <= 0:
                gaps.append("market_daily:missing_or_nonpositive_close")
                invalid = True
                break
        if not invalid and len(prices) < 2:
            gaps.append("market_daily:at_least_two_visible_closes_required")
        if not invalid and len(prices) >= 2:
            window = [prices[0]["period"], prices[-1]["period"]]
            if "market_price_window" in selected and window != [scoped["market_daily"]["start"], scoped["market_daily"]["end"]]:
                gaps.append("market_daily:requested_boundary_not_observed")
            if "factor_adjusted_window" in selected and "adjustment_factor" in scoped:
                factors = {row["period"]: source(row, "factor") for row in rows("adjustment_factor")}
                if not all(row["period"] in factors and factors[row["period"]] is not None
                           and factors[row["period"]] > 0 for row in prices):
                    gaps.append("adjustment_factor:missing_or_invalid_aligned_factor")
            if "market_price_window" in selected and "trade_calendar" in scoped:
                days = {row["period"] for row in rows("trade_calendar")
                        if dict(row["attributes"]).get("is_open") == "1"
                        and window[0] <= row["period"] <= window[1]}
                if not days or days != {row["period"] for row in prices}:
                    gaps.append("market_daily:calendar_alignment_not_verified")
            elif "market_price_window" in selected:
                gaps.append("market_daily:calendar_not_supplied")
    for dataset, result in scoped.items():
        if result["status"] != "available":
            gaps.append(dataset + ":no_visible_data")
        gaps.extend(dataset + ":" + warning for warning in result["warnings"])
    return expected, list(dict.fromkeys(sources)), sorted(set(gaps))


def verify_domain(computed, datasets, request, domain, *, operators=None, check_hypotheses=True):
    """Verify exact domain coverage against pinned rows and independent Fractions.

    Application authorization is rechecked by Runtime/Executor before this pure
    adapter. This proof is local; it never replaces the root's full verifier.
    """
    def require(condition):
        if not condition:
            raise IntegrityError("domain analysis verification failed")

    require(domain in DOMAIN_DATASETS)
    scoped = {k: v for k, v in datasets.items() if k in DOMAIN_DATASETS[domain]}
    bindings = {binding.dataset: binding for binding in request.bindings}
    records = {}
    for dataset, result in scoped.items():
        require(dataset in bindings and result["snapshot"] == bindings[dataset].snapshot
                and result["provider"] == bindings[dataset].provider)
        require(len({row["period"] for row in result["records"]}) == len(result["records"]))
        for row in result["records"]:
            record = DataRecord.from_dict(row)
            require(record.provider == bindings[dataset].provider
                    and record.dataset.value == dataset
                    and record.available_at <= request.as_of
                    and (request.mode != PITMode.SYSTEM or record.ingested_at <= request.as_of)
                    and bindings[dataset].start <= record.period <= bindings[dataset].end
                    and record.security_id == request.data_request(bindings[dataset]).security.security_id)
            require(record.record_id not in records)
            records[record.record_id] = (record, result["snapshot"])
    expected, expected_sources, expected_gaps = expected_domain_projection(scoped, request, domain, operators=operators)
    evidence, facts = computed["evidence"], computed["facts"]
    require(set(evidence) == set(expected_sources) and computed["gaps"] == expected_gaps)
    for key, source in evidence.items():
        require(source.get("record_id") in records)
        record, snapshot = records[source["record_id"]]
        metric = next((metric for metric in record.metrics if metric.name == source.get("metric")), None)
        require(metric is not None and key == source.get("id") == digest({"record": record.record_id, "metric": metric.name}))
        exact = {"kind": "source", "value": None if metric.value is None else str(metric.value),
                 "unit": metric.unit, "raw_value": metric.raw_value, "raw_unit": metric.raw_unit,
                 "period": record.period.isoformat(), "basis": record.basis, "provider": record.provider,
                 "provider_version": record.provider_version, "source_url": record.source_url,
                 "revision_id": record.revision_id, "artifact_ids": list(record.artifact_ids),
                 "provider_call_id": record.provider_call_id, "available_at": record.available_at.isoformat(),
                 "published_at": record.published_at.isoformat() if getattr(record, "published_at", None) else None,
                 "retrieved_at": record.retrieved_at.isoformat(), "ingested_at": record.ingested_at.isoformat(),
                 "availability_basis": record.availability_basis, "snapshot": snapshot}
        require(all(source.get(k) == v for k, v in exact.items()))
        require(not set(source) - set(exact) - {"id", "record_id", "metric", "tool_call_id"})
    require(len(facts) == len(expected) and {fact.get("name") for fact in facts} == set(expected))
    for fact in facts:
        exact, unit, inputs, window, formula = expected[fact["name"]]
        require(set(fact) == {"name", "value", "unit", "inputs", "formula", "window", "available_at", "id"})
        require(fact["id"] == digest({k: v for k, v in fact.items() if k != "id"})
                and fact["unit"] == unit and fact["inputs"] == inputs and fact["window"] == window
                and fact["formula"] == formula and all(key in evidence and evidence[key]["value"] is not None for key in inputs))
        number = Decimal(fact["value"])
        require(number.is_finite())
        tolerance = Fraction(0) if formula == IDENTITY else max(Fraction(1, 10**32), abs(exact) / 10**32)
        require(abs(Fraction(number) - exact) <= tolerance)
        latest = max(aware(datetime.fromisoformat(evidence[key]["available_at"])) for key in inputs)
        require(aware(datetime.fromisoformat(fact["available_at"])) == latest and latest <= request.as_of)
    hypotheses = computed.get("hypotheses", [])
    if check_hypotheses:
        require(hypotheses == test_hypotheses(computed, scoped, request, hypothesis_ids=DOMAIN_HYPOTHESES[domain]))
        if domain == "financial" and "absolute_profit_change" in request.hypotheses:
            verify_profit_change(computed, scoped, request)
    return {"status": "verified", "domain": domain, "numeric_claims": len(facts),
            "evidence_checked": len(evidence), "hypotheses_checked": len(hypotheses) if check_hypotheses else 0,
            "method": "independent_fraction_domain_projection/v1", "provider_accuracy_certified": False,
            "causality_established": False}
