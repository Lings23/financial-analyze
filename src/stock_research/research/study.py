"""Phase 3 bounded Single Research: plan, evidence, tests, synthesis, verification."""
import json
from decimal import Decimal, localcontext

from ..errors import IntegrityError, ValidationError
from ..models import digest
from .calculation import calculate
from .context import study_messages
from .hypotheses import CATALOGUE, diagnose_insufficiency, event_anchor, event_prices, test_hypotheses
from .runtime import BudgetExceeded, ResearchRuntime, _unique_object
from .study_contracts import StudyRequest, StudySpec
from .verification import FORMULAS, eid, verify
from .selection import selection_options
from .profit_change import add_profit_change_claim


def calculate_study_claims(datasets, request, *, profit_change=False):
    """Shared deterministic business calculation; no model, reads or planning."""
    computed = calculate(datasets)
    anchor = event_anchor(datasets, request)
    pair = event_prices(datasets, anchor)
    if pair and any(f["name"] == "observed_price_change" for f in computed["facts"]):
        a, b = pair
        inputs = [eid(a, "close"), eid(b, "close")]
        with localcontext() as ctx:
            ctx.prec = 34
            v = Decimal(computed["evidence"][inputs[-1]]["value"]) / Decimal(computed["evidence"][inputs[0]]["value"]) - 1
        fact = {"name": "event_observed_price_change", "value": str(v), "unit": "ratio",
                "inputs": inputs, "window": [a["period"], b["period"]],
                "formula": FORMULAS["event_observed_price_change"],
                "available_at": max([computed["evidence"][e]["available_at"] for e in inputs]
                                    + [anchor["available_at"]])}
        fact["id"] = digest(fact)
        computed["facts"].append(fact)
    computed["event_anchor"] = anchor
    if profit_change:
        add_profit_change_claim(computed, datasets, request)
    return computed


class StudyRuntime(ResearchRuntime):
    def __init__(self, service, checkpoints, model=None, spec=None, **kwargs):
        super().__init__(service, checkpoints, model, spec or StudySpec(), **kwargs)
        if not isinstance(self.spec, StudySpec):
            raise ValidationError("study requires a bounded StudySpec")

    def run(self, request, access, **kwargs):
        if not isinstance(request, StudyRequest):
            raise ValidationError("study requires a StudyRequest")
        if "absolute_profit_change" in request.hypotheses and self.spec.version != "single-research-v5":
            raise ValidationError("profit amount research requires single-research-v5")
        return super().run(request, access, **kwargs)

    def _initial_fields(self, request):
        return {"research_plan": [{"hypothesis_id": h, "required_evidence": CATALOGUE[h][1],
                                    "test_rule": CATALOGUE[h][2]} for h in request.hypotheses]}

    def _calculation_events(self, computed):
        return [("hypotheses_tested", {"results": {h["id"]: h["status"] for h in computed["hypotheses"]}}),
                ("claims_verified", computed["verification"])]

    def _calculate(self, datasets, request):
        computed = calculate_study_claims(datasets, request, profit_change=self.spec.version == "single-research-v5")
        computed["hypotheses"] = test_hypotheses(computed, datasets, request)
        if self.spec.version in {"single-research-v4", "single-research-v5"}:
            computed["insufficiency_diagnostics"] = diagnose_insufficiency(computed, datasets, request)
        computed["research_plan"] = [{"hypothesis_id": h, "required_evidence": CATALOGUE[h][1],
                                       "test_rule": CATALOGUE[h][2]} for h in request.hypotheses]
        computed["verification"] = verify(computed, datasets, request)
        computed["context"] = {"status": "not_prepared"}
        if self.model is not None and computed["facts"]:
            try:
                _, computed["context"] = study_messages(computed, request, self.spec.context_bytes, version=self.spec.version)
                computed["context"]["status"] = "prepared"
            except ValidationError:
                computed["context"] = {"status": "over_budget", "byte_budget": self.spec.context_bytes,
                                       "source_bodies_included": 0, "omitted_claims": 0}
        return computed

    def _model_messages(self, computed, request):
        try:
            return study_messages(computed, request, self.spec.context_bytes, version=self.spec.version)[0]
        except ValidationError:
            raise BudgetExceeded("study_context_budget_exceeded") from None

    def _model_choice(self, content, computed, request):
        choice = json.loads(content, object_pairs_hook=_unique_object)
        facts = {f"F{i+1}": f["id"] for i, f in enumerate(computed["facts"])}
        hypotheses = {h["id"] for h in computed["hypotheses"]}
        if not isinstance(choice, dict) or set(choice) != {"highlights", "hypotheses", "assessment"} or choice["assessment"] != "descriptive_research_only":
            raise ValidationError("model violates study selection contract")
        for key, allowed in (("highlights", facts), ("hypotheses", hypotheses)):
            items = choice[key]
            if (not isinstance(items, list) or not 1 <= len(items) <= min(3, len(allowed))
                    or any(type(i) is not str or i not in allowed for i in items)
                    or len(set(items)) != len(items)):
                raise ValidationError("unknown or duplicate study selection")
        if self.spec.version in {"single-research-v3", "single-research-v4", "single-research-v5"} and choice not in selection_options(computed, request):
            raise ValidationError("model did not select a complete supplied evidence bundle")
        return {"highlights": [facts[i] for i in choice["highlights"]], "hypotheses": choice["hypotheses"]}

    def _finish(self, state, request, *, model_required):
        datasets = {k: v for output in state["outputs"].values() for k, v in output.items()}
        if "calculated" in state:
            computed = state["calculated"]
            computed["verification"] = verify(computed, datasets, request)
            if self.spec.version in {"single-research-v4", "single-research-v5"}:
                if computed.get("insufficiency_diagnostics") != diagnose_insufficiency(computed, datasets, request):
                    raise IntegrityError("study insufficiency diagnostics differ")
        super()._finish(state, request, model_required=model_required)
        report = state["report"]
        if self.spec.version in {"single-research-v4", "single-research-v5"}:
            report["diagnostics_version"] = "study-insufficiency-v1"
        report["schema"] = "single-research/v1"
        report.setdefault("event_anchor", {"status": "insufficient", "reason": "calculation_not_completed"})
        report.setdefault("hypotheses", [])
        report.setdefault("research_plan", [{"hypothesis_id": h, "required_evidence": CATALOGUE[h][1],
                                              "test_rule": CATALOGUE[h][2]} for h in request.hypotheses])
        report.setdefault("verification", {"status": "not_completed", "numeric_claims": 0})
        report.setdefault("context", {"status": "not_prepared"})
        report["research_status"] = ("stopped" if report["stop_reason"] else
                                     "evidence_incomplete" if not report["facts"] or
                                     any(h["status"] == "insufficient" for h in report["hypotheses"]) else
                                     "tests_completed")
        if report["research_status"] != "tests_completed":
            report["status"] = "partial"
        report["synthesis"] = {"supported": [h["id"] for h in report["hypotheses"] if h["status"] == "supported"],
                               "unsupported": [h["id"] for h in report["hypotheses"] if h["status"] == "unsupported"],
                               "conflicted": [h["id"] for h in report["hypotheses"] if h["status"] == "conflicted"],
                               "insufficient": [h["id"] for h in report["hypotheses"] if h["status"] == "insufficient"],
                               "causal_conclusion": "not_established"}
        report["limitations"] = ["Hypothesis support concerns predeclared descriptive tests, not causes or investment advice.",
                                 "Observed documents are not verified publication-time anchors or extracted body facts.",
                                 "All conclusions retain unverified coverage and source accuracy boundaries."]

    def _validate_replay(self, state, request):
        datasets = {k: v for output in state["outputs"].values() for k, v in output.items()}
        report = state["report"]
        if self.spec.version in {"single-research-v4", "single-research-v5"} and (
                report.get("diagnostics_version") != "study-insufficiency-v1"
                or report.get("schema") != "single-research/v1"):
            raise IntegrityError("study replay diagnostic schema differs")
        if self.spec.version in {"single-research-v4", "single-research-v5"}:
            if report.get("insufficiency_diagnostics", []) != diagnose_insufficiency(report, datasets, request):
                raise IntegrityError("study replay diagnostics differ")
            if report["verification"]["status"] == "verified" and "insufficiency_diagnostics" not in report:
                raise IntegrityError("study replay diagnostics are missing")
        if report["verification"]["status"] == "verified":
            verified = verify(report, datasets, request)
            if verified != report["verification"]:
                raise IntegrityError("study replay verification differs")
        if report["model"]["status"] == "verified":
            known_facts = {f["id"] for f in report["facts"]}
            if (not set(report["model"]["highlights"]) <= known_facts
                    or not set(report["model"]["hypotheses"]) <= set(request.hypotheses)):
                raise IntegrityError("study replay model selections differ")
            if self.spec.version in {"single-research-v3", "single-research-v4", "single-research-v5"}:
                aliases = {f['id']: f'F{i+1}' for i,f in enumerate(report['facts'])}
                choice = {'highlights':[aliases[c] for c in report['model']['highlights']],
                          'hypotheses':report['model']['hypotheses'], 'assessment':'descriptive_research_only'}
                if choice not in selection_options(report, request):
                    raise IntegrityError("study replay selection bundle differs")
