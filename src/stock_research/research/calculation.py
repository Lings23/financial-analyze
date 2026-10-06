"""Fixed Decimal formulas and full input lineage; never accepts executable expressions."""
from decimal import Decimal, localcontext

from ..models import DataRecord, digest


def calculate(datasets):
    evidence, facts, gaps = {}, [], []

    def source(row, metric):
        record = DataRecord.from_dict(row)
        m = next(m for m in record.metrics if m.name == metric)
        eid = digest({"record": record.record_id, "metric": metric})
        evidence[eid] = {"id": eid, "kind": "source", "record_id": record.record_id,
                         "metric": metric, "value": None if m.value is None else str(m.value),
                         "unit": m.unit, "raw_value": m.raw_value, "raw_unit": m.raw_unit,
                         "period": record.period.isoformat(), "basis": record.basis,
                         "provider": record.provider, "provider_version": record.provider_version,
                         "source_url": record.source_url, "revision_id": record.revision_id,
                         "artifact_ids": list(record.artifact_ids), "provider_call_id": record.provider_call_id,
                         "available_at": record.available_at.isoformat(),
                         "published_at": record.published_at.isoformat() if getattr(record, "published_at", None) else None,
                         "retrieved_at": record.retrieved_at.isoformat(),
                         "ingested_at": record.ingested_at.isoformat(),
                         "availability_basis": record.availability_basis,
                         "snapshot": datasets[record.dataset.value]["snapshot"]}
        return m.value, eid

    def fact(name, value, unit, inputs, formula, window):
        inputs = list(dict.fromkeys(inputs))
        item = {"name": name, "value": str(value), "unit": unit, "inputs": inputs,
                "formula": formula, "window": window,
                "available_at": max(evidence[i]["available_at"] for i in inputs)}
        item["id"] = digest(item)
        facts.append(item)
        return item

    def rows(name):
        return sorted(datasets.get(name, {}).get("records", []), key=lambda r: r["period"])

    def series(name):
        result = []
        for row in rows(name):
            value, eid = source(row, "close")
            if value is None or value <= 0:
                gaps.append(name + ":missing_or_nonpositive_close")
                return []
            result.append((row["period"], value, eid))
        if len(result) < 2:
            gaps.append(name + ":at_least_two_visible_closes_required")
            return []
        return result

    with localcontext() as ctx:
        ctx.prec = 34
        prices = series("market_daily")
        if prices:
            window = [prices[0][0], prices[-1][0]]
            if window != [datasets["market_daily"]["start"], datasets["market_daily"]["end"]]:
                gaps.append("market_daily:requested_boundary_not_observed")
            fact("observed_price_change", prices[-1][1] / prices[0][1] - 1, "ratio",
                 [prices[0][2], prices[-1][2]], "last_close / first_close - 1; unadjusted", window)
            peak, drawdown = prices[0][1], Decimal(0)
            for _, price, _ in prices:
                peak = max(peak, price)
                drawdown = max(drawdown, 1 - price / peak)
            fact("observed_max_drawdown", drawdown, "ratio", [p[2] for p in prices],
                 "max(1 - close / running_max(close)); observed unadjusted closes", window)
            if "adjustment_factor" in datasets:
                factors = {r["period"]: source(r, "factor") for r in rows("adjustment_factor")}
                if all(p[0] in factors and factors[p[0]][0] is not None and factors[p[0]][0] > 0 for p in prices):
                    first, last = prices[0], prices[-1]
                    value = last[1] * factors[last[0]][0] / (first[1] * factors[first[0]][0]) - 1
                    fact("factor_adjusted_price_change", value, "ratio",
                         [first[2], last[2], factors[first[0]][1], factors[last[0]][1]],
                         "(last_close * last_factor) / (first_close * first_factor) - 1; not total return", window)
                else:
                    gaps.append("adjustment_factor:missing_or_invalid_aligned_factor")
            if "trade_calendar" in datasets:
                calendar = rows("trade_calendar")
                open_days = {r["period"] for r in calendar if dict(r["attributes"]).get("is_open") == "1"
                             and window[0] <= r["period"] <= window[1]}
                if not open_days or open_days != {p[0] for p in prices}:
                    gaps.append("market_daily:calendar_alignment_not_verified")
            else:
                gaps.append("market_daily:calendar_not_supplied")
            if "index_daily" in datasets:
                index = series("index_daily")
                if index and [p[0] for p in index] == [p[0] for p in prices]:
                    br = index[-1][1] / index[0][1] - 1
                    fact("benchmark_price_change", br, "ratio", [index[0][2], index[-1][2]],
                         "last_index_close / first_index_close - 1; price index", window)
                    fact("price_change_difference", prices[-1][1] / prices[0][1] - 1 - br, "ratio",
                         [prices[0][2], prices[-1][2], index[0][2], index[-1][2]],
                         "stock_unadjusted_price_change - benchmark_price_change; not alpha", window)
                else:
                    gaps.append("index_daily:exact_trading_date_alignment_required")
        for dataset in ("financial_income", "financial_balance", "financial_cashflow"):
            if dataset not in datasets:
                continue
            values = rows(dataset)
            if not values:
                gaps.append(dataset + ":no_visible_financial_period")
                continue
            latest = values[-1]
            for metric in latest["metrics"]:
                value, eid = source(latest, metric["name"])
                if value is None:
                    gaps.append(dataset + ":missing:" + metric["name"])
                else:
                    fact(dataset + "." + metric["name"], value, metric["unit"], [eid],
                         "identity; latest visible report period; preserve source basis", [latest["period"], latest["period"]])
            if dataset == "financial_income":
                for name in ("revenue", "net_income_parent"):
                    current, ceid = source(latest, name)
                    year = int(latest["period"][:4]) - 1
                    prior = next((r for r in values if r["period"] == str(year) + latest["period"][4:]), None)
                    if prior:
                        previous, peid = source(prior, name)
                        if current is not None and previous is not None and previous > 0:
                            fact(name + "_yoy", current / previous - 1, "ratio", [peid, ceid],
                                 "current_same_period / prior_year_same_period - 1; positive base required",
                                 [prior["period"], latest["period"]])
                        else:
                            gaps.append(name + ":yoy_missing_or_nonpositive_base")
                    else:
                        gaps.append(name + ":yoy_prior_year_period_not_visible")
    for name, result in datasets.items():
        if result["status"] != "available":
            gaps.append(name + ":no_visible_data")
        gaps.extend(name + ":" + w for w in result["warnings"])
    return {"facts": facts, "evidence": evidence, "gaps": sorted(set(gaps))}
