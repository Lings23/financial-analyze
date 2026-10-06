import json
import time
import uuid
from datetime import datetime, timedelta

from ..errors import IntegrityError, PermissionDenied, ValidationError
from ..models import canonical_json, digest, utcnow
from .calculation import calculate
from .contracts import AgentSpec, DOMAINS, TOOLS
from .tools import ToolExecutor, ToolRegistry


class BudgetExceeded(ValidationError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("duplicate model output key")
        result[key] = value
    return result


def validate_model_result(result, spec, reservation):
    """Shared runtime validation independent of the transport's own validation."""
    usage = (result.prompt_tokens, result.completion_tokens, result.total_tokens)
    if (result.returned_model != spec.model or result.requested_model != spec.model
            or result.finish_reason != "stop" or any(type(v) is not int or v < 0 for v in usage)
            or type(result.latency_ms) is not int or result.latency_ms < 0
            or result.total_tokens != result.prompt_tokens + result.completion_tokens
            or result.completion_tokens > spec.output_tokens or result.total_tokens > reservation):
        raise ValidationError("model identity, completion or token accounting invalid")


def model_messages(facts):
    """Exact reviewable outbound content; no source bodies, credentials or tenant identifiers."""
    candidates = {f"F{i+1}": {k: f[k] for k in ("name", "value", "unit", "window")}
                  for i, f in enumerate(facts)}
    return [
        {"role": "system", "content":
         'Select up to three distinct fact IDs most useful for a stock overview. '
         'Return only JSON: {"highlights":["F1"],"assessment":"descriptive_only"}. '
         'Use only supplied IDs. Do not add prose, numbers, recommendations or causal claims.'},
        {"role": "user", "content": canonical_json(candidates)}]


class ResearchRuntime:
    """Fixed Fast state machine: read -> calculate -> select evidence -> verify -> report.

    Model output cannot create facts, change tools, execute code, or expand permissions.
    A paid call is checkpointed BEFORE dispatch and never automatically retried.
    """
    def __init__(self, service, checkpoints, model=None, spec=None, *, granted_tools=TOOLS,
                 cancelled=None, now=utcnow, monotonic=time.monotonic):
        self.service, self.checkpoints, self.model = service, checkpoints, model
        self.spec = spec or AgentSpec()
        self.granted = frozenset(granted_tools)
        self.cancelled = cancelled or (lambda: False)
        self.now, self.monotonic = now, monotonic

    def run(self, request, access, *, resume=None):
        run = resume or uuid.uuid4().hex
        with self.checkpoints.lock(access.scope, run):
            binding = digest({"request": request.to_dict(), "spec": self.spec.identity,
                              "model_enabled": self.model is not None})
            if resume:
                state = self.checkpoints.read(access.scope, run)
                if state["binding"] != binding:
                    raise PermissionDenied("resume request or agent configuration differs")
            else:
                state = {"run_id": run, "binding": binding, "request": request.to_dict(),
                         "spec_version": self.spec.version, "phase": "planned", "outputs": {},
                         "tools_used": 0, "tokens_reserved": 0, "model_attempts": 0,
                         "deadline": (self.now() + timedelta(seconds=self.spec.max_seconds)).isoformat(),
                         "trace": [], "model": {"status": "not_called" if self.model is not None else "disabled"},
                         "report": None, **self._initial_fields(request)}
                self.checkpoints.append(access.scope, run, state)
            executor = ToolExecutor(self.service, ToolRegistry(), self.spec, self.granted, request, access)
            plan = [name for name in ("market", "financial", "benchmark", "announcement", "news")
                    if any(DOMAINS[b.dataset] == name for b in request.bindings)]
            # Validate all grants even for completed replay. Trusted CLI scope is not remote auth.
            for name in [*plan, "calculation"]:
                executor.registry.authorize(name, self.spec, self.granted)
            for b in request.bindings:
                if b.provider not in access.allowed_providers:
                    raise PermissionDenied("research source authorization was revoked")
            if self.model is not None and self.model.config.model != self.spec.model:
                raise ValidationError("configured model differs from agent spec")
            remaining = (datetime.fromisoformat(state["deadline"]) - self.now()).total_seconds()
            stop_at = self.monotonic() + max(0, remaining)

            def event(kind, **fields):
                state["trace"].append({"seq": len(state["trace"]), "run_id": run,
                                       "time": self.now().isoformat(), "event": kind, **fields})
                self.checkpoints.append(access.scope, run, state)

            def check():
                if self.cancelled():
                    raise BudgetExceeded("cancelled")
                if self.monotonic() >= stop_at or self.now() >= datetime.fromisoformat(state["deadline"]):
                    raise BudgetExceeded("deadline_exceeded")

            def reserve_tool(name):
                check()
                if state["tools_used"] >= self.spec.max_tools:
                    raise BudgetExceeded("tool_budget_exceeded")
                state["tools_used"] += 1
                event("tool_started", tool=name, tool_call_id=f"{run}:{state['tools_used']}", wave=1)

            # Every reuse re-queries the pinned source with current authorization and verifies all
            # artifact bytes. Stored reports are never an authorization bypass.
            if state["report"] is not None:
                for name, saved in state["outputs"].items():
                    fresh, _ = executor.execute(name)
                    if digest(fresh) != digest(saved):
                        raise IntegrityError("checkpoint source result differs from pinned snapshot")
                self._validate_replay(state, request)
                return state["report"]
            sources_validated = False
            try:
                check()
                for name, saved in state["outputs"].items():
                    check()
                    fresh, _ = executor.execute(name)
                    check()
                    if digest(fresh) != digest(saved):
                        raise IntegrityError("checkpoint source result differs from pinned snapshot")
                sources_validated = True
                for name in plan:
                    if name in state["outputs"]:
                        continue
                    reserve_tool(name)
                    output, reused = executor.execute(name)
                    check()  # Discard late results.
                    state["outputs"][name] = output
                    state["phase"] = "reading"
                    event("tool_finished", tool=name, tool_call_id=f"{run}:{state['tools_used']}", result_hash=digest(output), dedup=reused,
                          datasets=sorted(output), records=sum(len(x["records"]) for x in output.values()))
                datasets = {k: v for output in state["outputs"].values() for k, v in output.items()}
                if "calculated" not in state:
                    reserve_tool("calculation")
                    state["calculated"] = self._calculate(datasets, request)
                    for evidence in state["calculated"]["evidence"].values():
                        domain = "market" if evidence["basis"] in {"unadjusted_daily", "raw_adjustment_factor"} else "benchmark" if evidence["basis"] == "price_index_daily" else "financial"
                        evidence["tool_call_id"] = next(e["tool_call_id"] for e in reversed(state["trace"])
                                                        if e["event"] == "tool_finished" and e["tool"] == domain)
                    check()
                    state["phase"] = "computed"
                    event("calculation_finished", evidence_ids=sorted(state["calculated"]["evidence"]),
                          claim_ids=[f["id"] for f in state["calculated"]["facts"]])
                    for kind, fields in self._calculation_events(state["calculated"]):
                        event(kind, **fields)
                if self.model is not None and state["calculated"]["facts"]:
                    if state["model_attempts"]:
                        # Crash after intent, during transport or before result commit: unknown outcome.
                        if state["model"]["status"] == "pending":
                            state["model"] = {"status": "unknown_outcome_no_replay"}
                    else:
                        check()
                        messages = self._model_messages(state["calculated"], request)
                        # UTF-8 byte ceiling plus message framing reserve, NOT a measured tokenizer count.
                        reservation = sum(len(m["content"].encode("utf-8")) for m in messages) + 256 + self.spec.output_tokens
                        if state["tokens_reserved"] + reservation > self.spec.max_tokens:
                            raise BudgetExceeded("model_input_budget_exceeded")
                        state["tokens_reserved"] += reservation
                        state["model_attempts"] = 1
                        state["model"] = {"status": "pending"}
                        state["phase"] = "model_pending"
                        event("model_started", requested_model=self.spec.model, token_reservation=reservation, turn=1)
                        measured = {}
                        try:
                            result = self.model.complete(messages, max_tokens=self.spec.output_tokens,
                                                         timeout=min(120, max(0.001, stop_at-self.monotonic())))
                            measured = {"prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
                                        "total_tokens": result.total_tokens, "latency_ms": result.latency_ms}
                            check()
                            validate_model_result(result, self.spec, reservation)
                            if len(result.content) > 8192:
                                raise ValidationError("model selection too large")
                            choice = self._model_choice(result.content, state["calculated"], request)
                            state["model"] = {"status": "verified", "requested_model": result.requested_model,
                                              "returned_model": result.returned_model, "prompt_tokens": result.prompt_tokens,
                                              "completion_tokens": result.completion_tokens, "total_tokens": result.total_tokens,
                                              "latency_ms": result.latency_ms,
                                              **choice}
                        except Exception as exc:
                            state["model"] = {"status": "rejected_or_failed", "error_type": type(exc).__name__, **measured}
                            if isinstance(exc, BudgetExceeded):
                                state["stop_reason"] = str(exc)
                        event("model_finished", **state["model"])
                check()
                self._finish(state, request, model_required=self.model is not None)
                event("report_verified", status=state["report"]["status"], report_hash=digest(state["report"]))
            except BudgetExceeded as exc:
                state["stop_reason"] = str(exc)
                if state["model"]["status"] == "pending":
                    state["model"] = {"status": "unknown_outcome_no_replay"}
                if sources_validated:
                    self._finish(state, request, model_required=self.model is not None)
                else:
                    # A stopped revalidation cannot publish cached facts or document metadata.
                    stopped = {k: v for k, v in state.items() if k != "calculated"}
                    stopped["outputs"] = {}
                    self._finish(stopped, request, model_required=self.model is not None)
                    state["report"], state["phase"] = stopped["report"], stopped["phase"]
                event("run_stopped", reason=str(exc), report_hash=digest(state["report"]))
            return state["report"]

    def _calculate(self, datasets, request):
        return calculate(datasets)

    def _initial_fields(self, request):
        return {}

    def _calculation_events(self, computed):
        return []

    def _validate_replay(self, state, request):
        pass

    def _model_messages(self, computed, request):
        return model_messages(computed["facts"])

    def _model_choice(self, content, computed, request):
        candidates = {f"F{i+1}": f["id"] for i, f in enumerate(computed["facts"])}
        choice = json.loads(content, object_pairs_hook=_unique_object)
        if (not isinstance(choice, dict) or set(choice) != {"highlights", "assessment"}
                or choice["assessment"] != "descriptive_only"
                or not isinstance(choice["highlights"], list)
                or not 1 <= len(choice["highlights"]) <= min(3, len(candidates))
                or any(not isinstance(x, str) or x not in candidates for x in choice["highlights"])
                or len(set(choice["highlights"])) != len(choice["highlights"])):
            raise ValidationError("model output violates evidence selection contract")
        return {"highlights": [candidates[x] for x in choice["highlights"]]}

    def _finish(self, state, request, *, model_required):
        computed = state.get("calculated", {"facts": [], "evidence": {}, "gaps": ["calculation_not_completed"]})
        facts, evidence = computed["facts"], computed["evidence"]
        for f in facts:
            if not f["inputs"] or any(i not in evidence or evidence[i]["value"] is None for i in f["inputs"]):
                raise IntegrityError("numeric fact has missing lineage")
            if any(datetime.fromisoformat(evidence[i]["available_at"]) > request.as_of for i in f["inputs"]):
                raise IntegrityError("future evidence in report")
        missing = any("no_visible" in gap or "missing_or_nonpositive_close" in gap
                      or "at_least_two" in gap or ":missing:" in gap or "alignment_required" in gap
                      or "invalid_aligned_factor" in gap for gap in computed["gaps"])
        partial = (not facts or missing or "stop_reason" in state
                   or model_required and state["model"]["status"] != "verified")
        state["phase"] = "completed"
        documents = []
        for output in state["outputs"].values():
            for dataset, result in output.items():
                if dataset not in {"announcement", "news_recent"}:
                    continue
                for row in result["records"]:
                    attrs = dict(row["attributes"])
                    documents.append({"dataset": dataset, "title": attrs["title"],
                                      "record_id": digest({k: v for k, v in row.items() if k != "ingested_at"}),
                                      "snapshot": result["snapshot"], "source_url": row["source_url"],
                                      "available_at": row["available_at"], "artifact_id": row["artifact_id"],
                                      "body_artifact_id": attrs.get("pdf_artifact_id", attrs.get("body_artifact_id")),
                                      "role": "untrusted_source_index_not_causal_evidence"})
        state["report"] = {"schema": "single-overview/v1", "run_id": state["run_id"],
                           "status": "partial" if partial else "completed", "request": request.to_dict(),
                           "coverage": "not_verified", **computed, "documents": documents,
                           "model": state["model"], "stop_reason": state.get("stop_reason"),
                           "usage": {"tool_calls": state["tools_used"], "model_attempts": state["model_attempts"],
                                     "tokens_reserved": state["tokens_reserved"], "financial_provider_network_calls": 0},
                           "trace": list(state["trace"]),
                           "limitations": ["Observed close statistics are not total return or complete-window certification.",
                                           "Recent documents are visible only after capture; no causal inference.",
                                           "Model selects existing evidence; it does not generate numeric facts."]}
