"""Fixed Decimal formulas and full input lineage; never executable expressions.

The legacy full calculation keeps its original ordering. Domain operators share
the same producer, but never execute another domain's production calculations.
"""
from decimal import Decimal, localcontext

from ..errors import IntegrityError, ValidationError
from ..models import DataRecord, digest


FINANCIAL_DATASETS = frozenset({"financial_income", "financial_balance", "financial_cashflow"})
MARKET_DATASETS = frozenset({"market_daily", "trade_calendar", "adjustment_factor"})


class _Calculation:
    def __init__(self, datasets, evidence=None):
        self.datasets = datasets
        self.evidence, self.facts, self.gaps = dict(evidence or {}), [], []

    def source(self, row, metric):
        record = DataRecord.from_dict(row)
        m = next(m for m in record.metrics if m.name == metric)
        eid = digest({"record": record.record_id, "metric": metric})
        source = {"id": eid, "kind": "source", "record_id": record.record_id,
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
                  "snapshot": self.datasets[record.dataset.value]["snapshot"]}
        prior = self.evidence.get(eid)
        if prior is not None:
            if {k: v for k, v in prior.items() if k != "tool_call_id"} != source:
                raise IntegrityError("calculation source identity conflict")
        else:
            self.evidence[eid] = source
        return m.value, eid

    def fact(self, name, value, unit, inputs, formula, window):
        inputs = list(dict.fromkeys(inputs))
        item = {"name": name, "value": str(value), "unit": unit, "inputs": inputs,
                "formula": formula, "window": window,
                "available_at": max(self.evidence[i]["available_at"] for i in inputs)}
        item["id"] = digest(item)
        self.facts.append(item)
        return item

    def rows(self, name):
        return sorted(self.datasets.get(name, {}).get("records", []), key=lambda r: r["period"])

    def series(self, name):
        result = []
        for row in self.rows(name):
            value, eid = self.source(row, "close")
            if value is None or value <= 0:
                self.gaps.append(name + ":missing_or_nonpositive_close")
                return []
            result.append((row["period"], value, eid))
        if len(result) < 2:
            self.gaps.append(name + ":at_least_two_visible_closes_required")
            return []
        return result

    def market(self, *, price=True, factor=True, benchmark=True):
        prices = self.series("market_daily")
        if not prices:
            return
        window = [prices[0][0], prices[-1][0]]
        if price:
            if window != [self.datasets["market_daily"]["start"], self.datasets["market_daily"]["end"]]:
                self.gaps.append("market_daily:requested_boundary_not_observed")
            self.fact("observed_price_change", prices[-1][1] / prices[0][1] - 1, "ratio",
                      [prices[0][2], prices[-1][2]], "last_close / first_close - 1; unadjusted", window)
            peak, drawdown = prices[0][1], Decimal(0)
            for _, value, _ in prices:
                peak = max(peak, value)
                drawdown = max(drawdown, 1 - value / peak)
            self.fact("observed_max_drawdown", drawdown, "ratio", [p[2] for p in prices],
                      "max(1 - close / running_max(close)); observed unadjusted closes", window)
        if factor and "adjustment_factor" in self.datasets:
            factors = {r["period"]: self.source(r, "factor") for r in self.rows("adjustment_factor")}
            if all(p[0] in factors and factors[p[0]][0] is not None and factors[p[0]][0] > 0 for p in prices):
                first, last = prices[0], prices[-1]
                value = last[1] * factors[last[0]][0] / (first[1] * factors[first[0]][0]) - 1
                self.fact("factor_adjusted_price_change", value, "ratio",
                          [first[2], last[2], factors[first[0]][1], factors[last[0]][1]],
                          "(last_close * last_factor) / (first_close * first_factor) - 1; not total return", window)
            else:
                self.gaps.append("adjustment_factor:missing_or_invalid_aligned_factor")
        if price:
            if "trade_calendar" in self.datasets:
                calendar = self.rows("trade_calendar")
                open_days = {r["period"] for r in calendar if dict(r["attributes"]).get("is_open") == "1"
                             and window[0] <= r["period"] <= window[1]}
                if not open_days or open_days != {p[0] for p in prices}:
                    self.gaps.append("market_daily:calendar_alignment_not_verified")
            else:
                self.gaps.append("market_daily:calendar_not_supplied")
        if benchmark:
            self.benchmark(prices)

    def benchmark(self, prices, stock_change=None):
        if "index_daily" not in self.datasets:
            return
        index = self.series("index_daily")
        if index and [p[0] for p in index] == [p[0] for p in prices]:
            window = [prices[0][0], prices[-1][0]]
            br = index[-1][1] / index[0][1] - 1
            self.fact("benchmark_price_change", br, "ratio", [index[0][2], index[-1][2]],
                      "last_index_close / first_index_close - 1; price index", window)
            change = stock_change if stock_change is not None else prices[-1][1] / prices[0][1] - 1
            self.fact("price_change_difference", change - br, "ratio",
                      [prices[0][2], prices[-1][2], index[0][2], index[-1][2]],
                      "stock_unadjusted_price_change - benchmark_price_change; not alpha", window)
        else:
            self.gaps.append("index_daily:exact_trading_date_alignment_required")

    def financial(self, *, snapshot=True, yoy=True):
        for dataset in ("financial_income", "financial_balance", "financial_cashflow"):
            if dataset not in self.datasets:
                continue
            values = self.rows(dataset)
            if not values:
                self.gaps.append(dataset + ":no_visible_financial_period")
                continue
            latest = values[-1]
            if snapshot:
                for metric in latest["metrics"]:
                    value, eid = self.source(latest, metric["name"])
                    if value is None:
                        self.gaps.append(dataset + ":missing:" + metric["name"])
                    else:
                        self.fact(dataset + "." + metric["name"], value, metric["unit"], [eid],
                                  "identity; latest visible report period; preserve source basis", [latest["period"], latest["period"]])
            if yoy and dataset == "financial_income":
                for name in ("revenue", "net_income_parent"):
                    current, ceid = self.source(latest, name)
                    year = int(latest["period"][:4]) - 1
                    prior = next((r for r in values if r["period"] == str(year) + latest["period"][4:]), None)
                    if prior:
                        previous, peid = self.source(prior, name)
                        if current is not None and previous is not None and previous > 0:
                            self.fact(name + "_yoy", current / previous - 1, "ratio", [peid, ceid],
                                      "current_same_period / prior_year_same_period - 1; positive base required",
                                      [prior["period"], latest["period"]])
                        else:
                            self.gaps.append(name + ":yoy_missing_or_nonpositive_base")
                    else:
                        self.gaps.append(name + ":yoy_prior_year_period_not_visible")

    def output(self, *, warnings=True):
        if warnings:
            self.gaps.extend(dataset_gaps(self.datasets))
        return {"facts": self.facts, "evidence": self.evidence, "gaps": sorted(set(self.gaps))}


def dataset_gaps(datasets):
    gaps = []
    for name, result in datasets.items():
        if result["status"] != "available":
            gaps.append(name + ":no_visible_data")
        gaps.extend(name + ":" + warning for warning in result["warnings"])
    return gaps


def calculate(datasets):
    """Compatibility wrapper: unchanged complete production ordering and gaps."""
    calculation = _Calculation(datasets)
    with localcontext() as ctx:
        ctx.prec = 34
        calculation.market()
        calculation.financial()
    return calculation.output()


def calculate_financial(datasets, operators=None):
    operators = frozenset({"financial_snapshot", "income_yoy"} if operators is None else operators)
    if not operators or not operators <= {"financial_snapshot", "income_yoy"}:
        raise ValidationError("unknown financial production operator")
    calculation = _Calculation({k: v for k, v in datasets.items() if k in FINANCIAL_DATASETS})
    with localcontext() as ctx:
        ctx.prec = 34
        calculation.financial(snapshot="financial_snapshot" in operators, yoy="income_yoy" in operators)
    return calculation.output()


def calculate_market(datasets, operators=None):
    operators = frozenset({"market_price_window", "factor_adjusted_window"} if operators is None else operators)
    if not operators or not operators <= {"market_price_window", "factor_adjusted_window"}:
        raise ValidationError("unknown market production operator")
    calculation = _Calculation({k: v for k, v in datasets.items() if k in MARKET_DATASETS})
    with localcontext() as ctx:
        ctx.prec = 34
        calculation.market(price="market_price_window" in operators,
                           factor="factor_adjusted_window" in operators, benchmark=False)
    return calculation.output()


def calculate_cross_domain(datasets, market_result):
    """Produce only benchmark Claims, reusing the consumed market price Claim."""
    calculation = _Calculation(datasets, market_result["evidence"])
    price_claim = next((f for f in market_result["facts"] if f["name"] == "observed_price_change"), None)
    if price_claim is not None:
        # Input conversion/lineage reuse is not a second market Claim producer.
        prices = [(r["period"], Decimal(next(m["value"] for m in r["metrics"] if m["name"] == "close")),
                   digest({"record": DataRecord.from_dict(r).record_id, "metric": "close"}))
                  for r in calculation.rows("market_daily")]
        with localcontext() as ctx:
            ctx.prec = 34
            calculation.benchmark(prices, Decimal(price_claim["value"]))
    return calculation.output(warnings=False)
