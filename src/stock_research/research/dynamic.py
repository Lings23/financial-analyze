"""Bounded dynamic Single strategy on the shared research runtime infrastructure.

JSON text actions are application-level tool calling. No native tool_calls, provider
refresh, code execution, recursive child agents, or model-generated financial facts.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from types import MappingProxyType
import uuid

from ..errors import IntegrityError, PermissionDenied, ValidationError
from ..models import AccessContext, DataRecord, canonical_json, digest, aware
from .contracts import DOMAINS
from .dynamic_contracts import (DYNAMIC_TOOLS, SOURCE_TOOLS, FINANCIAL_DATASETS, MARKET_DATASETS, AGENT_TOOLS, DynamicRequest,
                                DynamicSpec, FinancialRequest, FinancialParentSpec,
                                FinancialChildSpec, DomainParentSpec, MarketRequest, MarketChildSpec, ParallelParentSpec, required_checks)
from .dynamic_protocol import (dynamic_messages, observe_tool, parse_action, validate_finish_rejection,
                               context_next_stage)
from .hypotheses import diagnose_insufficiency, test_hypotheses
from .runtime import BudgetExceeded, ResearchRuntime, validate_model_result
from .study import calculate_study_claims
from .tools import ToolExecutor, ToolRegistry, ToolSpec
from .verification import verify


class DynamicToolRegistry(ToolRegistry):
    def __init__(self):
        self.tools = MappingProxyType({name: ToolSpec(name, input_contract="dynamic-action/v1; bound references only")
                                       for name in DYNAMIC_TOOLS | AGENT_TOOLS})


class DynamicRuntime(ResearchRuntime):
    """Same registry/executor, sources, verifier, checkpoint and model core; new strategy."""
    def __init__(self, service, checkpoints, model=None, spec=None, **kwargs):
        self.child_spec = kwargs.pop("child_spec", None) or FinancialChildSpec(model=(spec or DynamicSpec()).model)
        domains = isinstance(spec, DomainParentSpec)
        self.child_specs = kwargs.pop("domain_child_specs", None)
        if self.child_specs is not None and not domains:
            raise ValidationError("domain child specs require DomainParentSpec")
        self.child_specs = dict(self.child_specs) if self.child_specs is not None else {
            "financial": self.child_spec, "market": MarketChildSpec(model=(spec or DynamicSpec()).model)}
        allowed_delegation = {"financial", "market"} if domains else {"financial"}
        allowed_datasets = FINANCIAL_DATASETS | MARKET_DATASETS if domains else FINANCIAL_DATASETS
        self.delegated_tools = frozenset(kwargs.pop("delegated_tools", allowed_delegation))
        self.delegated_datasets = frozenset(kwargs.pop("delegated_datasets", allowed_datasets))
        self.parent_run_id = kwargs.pop("parent_run_id", None)
        self.inherited_deadline = kwargs.pop("inherited_deadline", None)
        self.authorize_parent = kwargs.pop("authorize_parent", None)
        # Observation-only lineage; it is never placed in model messages or grants.
        self.telemetry_lineage = kwargs.pop("telemetry_lineage", None)
        if (not isinstance(self.child_spec, FinancialChildSpec)
                or not self.delegated_tools <= allowed_delegation
                or not self.delegated_datasets <= allowed_datasets
                or domains and (set(self.child_specs) != {"financial", "market"}
                    or not isinstance(self.child_specs["financial"], FinancialChildSpec)
                    or not isinstance(self.child_specs["market"], MarketChildSpec))):
            raise ValidationError("invalid financial delegation policy")
        self.child_specs = MappingProxyType(self.child_specs)
        if self.inherited_deadline is not None:
            aware(self.inherited_deadline)
        kwargs.setdefault("granted_tools", DYNAMIC_TOOLS | AGENT_TOOLS)
        super().__init__(service, checkpoints, model, spec or DynamicSpec(), **kwargs)
        if not isinstance(self.spec, DynamicSpec):
            raise ValidationError("dynamic strategy requires DynamicSpec")
        if isinstance(self.spec, FinancialParentSpec) and self.child_spec.model != self.spec.model:
            raise ValidationError("parent and child must use the same configured model")
        if domains and any(child_spec.model != self.spec.model for child_spec in self.child_specs.values()):
            raise ValidationError("domain children must use the same configured model")

    def _setup(self, request, access):
        if not isinstance(request, DynamicRequest):
            raise ValidationError("dynamic strategy requires DynamicRequest")
        if (isinstance(self.spec, FinancialChildSpec) != isinstance(request, FinancialRequest)
                or isinstance(self.spec, MarketChildSpec) != isinstance(request, MarketRequest)):
            raise ValidationError("financial child request and spec must agree")
        if isinstance(self.spec, (FinancialChildSpec, MarketChildSpec)) and (not self.parent_run_id or self.inherited_deadline is None):
            raise ValidationError("financial child requires a bound parent deadline")
        if self.authorize_parent is not None and not self.authorize_parent():
            raise PermissionDenied("parent delegation was revoked")
        registry = DynamicToolRegistry()
        available = sorted(({DOMAINS[b.dataset] for b in request.bindings} |
                            {"calculation", "hypotheses", "verification"}) &
                           self.spec.visible_tools & self.spec.allowed_tools & self.granted)
        if isinstance(self.spec, FinancialParentSpec):
            for domain in (("financial", "market") if isinstance(self.spec, DomainParentSpec) else ("financial",)):
                child_spec = self._role_spec(domain)
                if (domain in available
                        and domain in self.delegated_tools & child_spec.allowed_tools & child_spec.visible_tools
                        and domain + "_child" in self.spec.visible_tools & self.spec.allowed_tools & self.granted
                        and any(DOMAINS[b.dataset] == domain and b.dataset in self.delegated_datasets for b in request.bindings)):
                    available.append(domain + "_child")
            available.sort()
        if self.model is not None and self.model.config.model != self.spec.model:
            raise ValidationError("configured model differs from dynamic spec")
        if any(b.provider not in access.allowed_providers for b in request.bindings):
            raise PermissionDenied("dynamic source authorization was revoked")
        return ToolExecutor(self.service, registry, self.spec, self.granted, request, access), available

    @staticmethod
    def _requirements(request):
        return required_checks(request)

    def preview(self, request, access, *, run_id=None):
        """First decision only: validate trusted bindings/grants, no tool/model dispatch."""
        executor, available = self._setup(request, access)
        for name in available:
            executor.registry.authorize(name, self.spec, self.granted)
        return dynamic_messages(request, available, [], self._requirements(request), [],
                                self.spec.context_bytes, version=self.spec.version,
                                **({"context_scope": access.scope, "context_run_id": run_id or "0" * 32}
                                   if self._context_enabled() else {}))[0]

    def _context_enabled(self):
        return isinstance(self.spec, DomainParentSpec) and self.spec.version in {
            "dynamic-parent-domains-v2", "dynamic-parent-parallel-v1", "dynamic-parent-parallel-v2", "dynamic-parent-parallel-v3"}

    def _parallel_enabled(self):
        return isinstance(self.spec, ParallelParentSpec)

    def _parent_headroom(self, state, *, additional_tools=0):
        """Keep the entire remaining local Parent envelope out of Child allocations."""
        remaining = {"decisions": self.spec.max_decisions - state["model_attempts"],
                     "tools": self.spec.max_tools - state["tools_used"] - additional_tools,
                     "tokens": self.spec.max_tokens - state["tokens_accounted"]}
        checks = self._check_results(state, DynamicRequest.from_dict(state["request"]))
        pending = sum(c["status"] == "not_completed" and c["id"] in {
            "calculation", "hypotheses", "verification"} for c in checks)
        if remaining["decisions"] < pending + 1 or remaining["tools"] < pending or remaining["tokens"] <= 0:
            raise BudgetExceeded("parent_completion_budget_unavailable")
        return remaining

    @staticmethod
    def _catalog_refs(view):
        return sorted(ref for group in view["catalog_ids"].values() for ref in group)

    def _build_catalog(self, state, request, access):
        from .dynamic_context import build_catalog
        observations = [state["observations"][name] for name in sorted(state["observations"])]
        return build_catalog(request, observations, state["requirements"],
                             scope=access.scope, run_id=state["run_id"])

    def _context_arguments(self, state, access):
        arguments = {"context_scope": access.scope, "context_run_id": state["run_id"],
                     "context_refs": state["context_store"]["requested_refs"]}
        if self.spec.version in {"dynamic-parent-parallel-v2", "dynamic-parent-parallel-v3"}:
            arguments["parent_execution_checks"] = self._check_results(
                state, DynamicRequest.from_dict(state["request"]))
        return arguments

    def _context_parse_arguments(self, state, request, access):
        if not self._context_enabled():
            return {}
        from .dynamic_context import view_catalog
        catalog = self._build_catalog(state, request, access)
        view = view_catalog(catalog, scope=access.scope, run_id=state["run_id"], current_stage="calculation")
        return {"context_catalog_ref": catalog["catalog_ref"], "context_known_refs": self._catalog_refs(view)}

    def _validate_context_history(self, history, state, request, access, available):
        """After source reauthorization, reconstruct every persisted paid context.

        Catalogs are append-only objects in the existing checkpoint namespace. Each
        object must match an actual paid decision's authoritative current observations.
        No cached hash grants access or replaces business verification.
        """
        if not self._context_enabled():
            return
        from .dynamic_context import decode_catalog, resolve_catalog
        expected_binding = digest({"scope": access.scope, "run_id": state["run_id"], "request": request.to_dict()})
        prior_catalogs, prior_disclosures = {}, []
        observed_refs = set()
        for saved in [*history, state]:
            store = saved.get("context_store")
            if (type(store) is not dict or set(store) != {"schema", "binding", "catalogs", "disclosures", "requested_refs"}
                    or store["schema"] != "dynamic-context-store/v1" or store["binding"] != expected_binding
                    or type(store["catalogs"]) is not dict or type(store["disclosures"]) is not list
                    or type(store["requested_refs"]) is not list
                    or any(store["catalogs"].get(ref) != value for ref, value in prior_catalogs.items())
                    or store["disclosures"][:len(prior_disclosures)] != prior_disclosures):
                raise IntegrityError("lossless context history changed its binding or removed an object")
            prior_catalogs, prior_disclosures = store["catalogs"], store["disclosures"]
            events = [e for e in saved["trace"] if e["event"] == "context_disclosed"]
            if store["disclosures"] != [{key: event[key] for key in ("turn", "tool_call_id", "catalog_ref", "refs", "result_ref")}
                                        for event in events]:
                raise IntegrityError("context disclosure ledger differs from its actual reads")
            for disclosed in events:
                turn = disclosed["turn"]
                if type(turn) is not int or not 1 <= turn <= len(saved["decisions"]):
                    raise IntegrityError("context disclosure lacks a paid decision")
                decision = saved["decisions"][turn - 1]
                action = decision.get("action", {})
                starts = [e for e in saved["trace"] if e["event"] == "tool_started"
                          and e["tool_call_id"] == disclosed["tool_call_id"]]
                if (decision["status"] != "verified" or action.get("action") != "disclose"
                        or action.get("catalog_ref") != disclosed["catalog_ref"]
                        or action.get("refs") != disclosed["refs"]
                        or decision.get("context_catalog_ref") != disclosed["catalog_ref"]
                        or len(starts) != 1 or starts[0]["tool"] != "context_disclosure"
                        or starts[0]["turn"] != turn or starts[0]["seq"] >= disclosed["seq"]):
                    raise IntegrityError("context disclosure differs from its authorized action")
                catalog = store["catalogs"].get(disclosed["catalog_ref"])
                if catalog is None or digest(resolve_catalog(catalog, disclosed["refs"], scope=access.scope,
                        run_id=state["run_id"], catalog_ref=disclosed["catalog_ref"])) != disclosed["result_ref"]:
                    raise IntegrityError("context disclosure result differs from its immutable objects")
            for finished in (e for e in saved["trace"] if e["event"] == "tool_finished"
                             and e["tool"] == "context_disclosure"):
                reads = [e for e in events if e["tool_call_id"] == finished["tool_call_id"]]
                if (len(reads) != 1 or reads[0]["seq"] >= finished["seq"]
                        or reads[0]["result_ref"] != finished["result_hash"]
                        or reads[0]["catalog_ref"] != finished["catalog_ref"]):
                    raise IntegrityError("context read completion differs from its receipt")
            expected_requested = store["disclosures"][-1]["refs"] if store["disclosures"] else []
            # Business tool observations invalidate the prior disclosure selection.
            last_read = next((e for e in reversed(saved["trace"]) if e["event"] in {"context_disclosed", "tool_finished"}), None)
            if last_read is not None and last_read["event"] == "tool_finished" and last_read["tool"] != "context_disclosure":
                expected_requested = []
            if store["requested_refs"] != expected_requested:
                raise IntegrityError("context selection differs from its committed action")
            if not saved["trace"] or saved["trace"][-1]["event"] != "model_started":
                continue
            decision = saved["decisions"][-1]
            catalog = self._build_catalog(saved, request, access)
            ref = catalog["catalog_ref"]
            if store["catalogs"].get(ref) != catalog or decision.get("context_catalog_ref") != ref:
                raise IntegrityError("paid context catalog differs from authorized observations")
            decode_catalog(catalog, scope=access.scope, run_id=state["run_id"], catalog_ref=ref)
            order = decision.get("context_observation_order", list(saved["observations"]))
            if len(order) != len(set(order)) or set(order) != set(saved["observations"]):
                raise IntegrityError("telemetry observation order differs from paid context")
            observations = [saved["observations"][name] for name in order]
            messages, metadata = dynamic_messages(request, available, observations,
                saved["requirements"], saved["plans"][-1]["steps"] if saved["plans"] else [], self.spec.context_bytes,
                decision=decision["turn"], protocol_error=saved.get("protocol_error"), version=self.spec.version,
                finish_rejection=saved.get("finish_rejection"),
                delegation_results=[{"tool": c["domain"] + "_child", "domain": c["domain"],
                    "status": c["status"], "result_ref": c["result_ref"]} for c in saved["child_results"]],
                **self._context_arguments(saved, access))
            if digest(messages) != decision["message_sha256"] or saved["context"] != {"status": "prepared", **metadata}:
                raise IntegrityError("paid context wire view or disclosure metadata changed")
            observed_refs.add(ref)
        # The current decision is committed before a catalog is persisted. There
        # are no uncharged or unaddressable catalog objects in the namespace.
        committed = {d.get("context_catalog_ref") for d in state["decisions"]}
        if None in committed or set(state["context_store"]["catalogs"]) != committed:
            raise IntegrityError("context store contains an unbound catalog object")
        # Every referenced historic catalog was reconstructed from its paid intent.
        if not committed <= observed_refs:
            raise IntegrityError("context history lacks an authoritative paid view")

    def _validate_telemetry_history(self, history, state, request, access, available):
        """Reproduce measurements from paid checkpoint wires, after reauthorization."""
        if "context_telemetry" not in state:
            return
        from .context_telemetry import build_context_telemetry
        measured = {}
        for saved in history:
            if not saved["trace"] or saved["trace"][-1]["event"] != "model_started":
                continue
            decision = saved["decisions"][-1]
            record = decision.get("context_telemetry")
            if not isinstance(record, dict):
                raise IntegrityError("paid turn lacks context telemetry")
            order = decision.get("context_observation_order", list(saved["observations"]))
            if len(order) != len(set(order)) or set(order) != set(saved["observations"]):
                raise IntegrityError("telemetry observation order differs from paid context")
            observations = [saved["observations"][name] for name in order]
            messages, metadata = dynamic_messages(request, available, observations,
                saved["requirements"], saved["plans"][-1]["steps"] if saved["plans"] else [], self.spec.context_bytes,
                decision=decision["turn"], protocol_error=saved.get("protocol_error"), version=self.spec.version,
                finish_rejection=saved.get("finish_rejection"),
                **({"delegation_results": [{"tool": c["domain"] + "_child", "domain": c["domain"],
                    "status": c["status"], "result_ref": c["result_ref"]} for c in saved["child_results"]]}
                    if isinstance(self.spec, DomainParentSpec) else {}),
                **(self._context_arguments(saved, access) if self._context_enabled() else {}))
            lineage = {k: record[k] for k in ("run_id", "parent_run_id", "child_run_id", "agent_role", "domain",
                       "turn_id", "route_type", "parallel_group_id", "parallel_width")}
            expected = build_context_telemetry(messages, metadata, observations, request,
                                               limit_bytes=self.spec.context_bytes, **lineage)
            if expected != record or digest(messages) != decision["message_sha256"]:
                raise IntegrityError("context telemetry differs from the actual paid wire")
            measured[decision["turn"]] = expected
        mutable = {"model_dispatched", "status", "stop_reason", "input_tokens", "output_tokens", "total_tokens"}
        for decision in state["decisions"]:
            record = decision.get("context_telemetry")
            original = measured.get(decision["turn"])
            if (not original or not record or any(record.get(k) != v for k, v in original.items() if k not in mutable)
                    or record != state["context_telemetry"][decision["turn"] - 1]
                    or any(record[k] != decision.get(field) for k, field in (
                        ("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens"), ("total_tokens", "total_tokens")))):
                raise IntegrityError("context telemetry receipt or measurement changed")

    def _role_spec(self, domain):
        if domain not in {"financial", "market"} or domain == "market" and not isinstance(self.spec, DomainParentSpec):
            raise PermissionDenied("domain delegation is outside the parent spec")
        return self.child_specs[domain] if isinstance(self.spec, DomainParentSpec) else self.child_spec

    @staticmethod
    def _datasets(state, names=None):
        return {k: v for name, output in state["outputs"].items()
                if names is None or name in names for k, v in output.items()}

    @staticmethod
    def _current(state):
        return digest(state["outputs"])

    def _validate_ledger(self, state, request):
        if (state.get("schema") != "dynamic-state/v1" or state.get("requirements") != self._requirements(request)
                or state.get("request") != request.to_dict()
                or state.get("spec_version") != self.spec.version):
            raise IntegrityError("dynamic state contract differs")
        decisions = state["decisions"]
        if (len(decisions) != state["model_attempts"] or len(decisions) > self.spec.max_decisions
                or any(d["turn"] != i + 1 for i, d in enumerate(decisions))
                or any(type(state[k]) is not int or state[k] < 0 for k in
                       ("model_attempts", "tools_used", "tokens_reserved"))
                or state["tools_used"] > self.spec.max_tools
                or state["tokens_reserved"] != sum(d["token_reservation"] for d in decisions)):
            raise IntegrityError("dynamic budget ledger differs")
        accounted = sum(d.get("total_tokens", d["token_reservation"]) for d in decisions)
        if (state["tokens_accounted"] != accounted or accounted > self.spec.max_tokens
                or any(type(d["token_reservation"]) is not int or d["token_reservation"] <= 0 for d in decisions)):
            raise IntegrityError("dynamic token ledger differs")
        for d in decisions:
            if "total_tokens" in d and (any(type(d.get(k)) is not int or d[k] < 0 for k in
                    ("prompt_tokens", "completion_tokens", "total_tokens"))
                    or d["total_tokens"] != d["prompt_tokens"] + d["completion_tokens"]
                    or d["total_tokens"] > d["token_reservation"]
                    or d["completion_tokens"] > self.spec.output_tokens):
                raise IntegrityError("dynamic measured usage differs")
        if state["tools_used"] != sum(e["event"] == "tool_started" for e in state["trace"]):
            raise IntegrityError("dynamic tool attempt ledger differs")
        intents = [e for e in state["trace"] if e["event"] == "model_started"]
        if len(intents) != len(decisions) or any(
                any(event.get(k) != decision.get(k) for k in ("turn", "token_reservation", "message_sha256"))
                for event, decision in zip(intents, decisions)):
            raise IntegrityError("dynamic paid intent ledger differs")
        for decision in decisions:
            receipts = [e for e in state["trace"] if e["event"] == "model_received" and e["turn"] == decision["turn"]]
            if (len(receipts) > 1 or ("total_tokens" in decision) != bool(receipts)
                    or receipts and receipts[0]["total_tokens"] != decision["total_tokens"]):
                raise IntegrityError("dynamic receipt ledger differs")
        expected_plans = [{"turn": d["turn"], "steps": d["action"]["plan"]}
                          for d in decisions if d["status"] == "verified"]
        if state["plans"] != expected_plans:
            raise IntegrityError("dynamic plan ledger differs")
        for decision in decisions:
            if "rejection" in decision:
                rejection = validate_finish_rejection(decision["rejection"], state["requirements"])
                events = [e for e in state["trace"] if e["event"] == "finish_rejected" and e["turn"] == decision["turn"]]
                if (self.spec.version == "single-dynamic-v1" or decision.get("action", {}).get("action") != "finish"
                        or len(events) != 1 or events[0]["rejection"] != rejection):
                    raise IntegrityError("dynamic finish rejection ledger differs")
        if state["pending_action"] is not None and (
                not decisions or decisions[-1]["status"] != "verified"
                or state["pending_action"] != decisions[-1].get("action")):
            raise IntegrityError("dynamic pending action differs from committed decision")
        if state["pending_tool"] is not None:
            starts = [e for e in state["trace"] if e["event"] == "tool_started"]
            if (not starts or not state["pending_action"] or
                    state["pending_tool"] != {k: starts[-1][k] for k in ("tool", "tool_call_id")}
                    or state["pending_tool"]["tool"] != ("context_disclosure" if self._context_enabled()
                        and state["pending_action"].get("action") == "disclose" else state["pending_action"].get("tool"))):
                raise IntegrityError("dynamic pending tool differs from committed intent")
        if isinstance(self.spec, FinancialParentSpec):
            self._validate_root_ledger(state)

    def _validate_root_ledger(self, state):
        from .root_budget import validate_root_budget
        ledger = state["root_budget"]
        validate_root_budget(ledger)
        if (ledger["root_run_id"] != state["run_id"] or ledger["limits"] != {
                "decisions": self.spec.root_max_decisions, "tools": self.spec.root_max_tools,
                "tokens": self.spec.root_max_tokens}):
            raise IntegrityError("root budget differs from parent spec")
        domains = isinstance(self.spec, DomainParentSpec)
        if domains and (ledger["schema"] != "root-budget/v2" or ledger["max_children"] != self.spec.max_children):
            if not self._parallel_enabled() or ledger["schema"] != "root-budget/v3" or ledger["max_children"] != self.spec.max_children:
                raise IntegrityError("domain root child limit differs from parent spec")
        if self._parallel_enabled():
            from .parallel import validate_groups
            validate_groups(state)
        expected, children, origins = [], {c["child_run_id"]: c for c in state["child_results"]}, {}
        if len(children) != len(state["child_results"]) or len(children) > (self.spec.max_children if domains else 1):
            raise IntegrityError("serial parent has more than one child result")
        reserved_domains = set()
        for event in state["trace"]:
            kind = event["event"]
            item = None
            if kind == "model_started":
                item = {"kind": "parent_model_reserved", "intent_id": f"{state['run_id']}:model:{event['turn']}",
                    "token_reservation": event["token_reservation"], "message_sha256": event["message_sha256"]}
            elif kind == "model_received" or kind == "model_finished" and event["status"] in {"invalid_receipt", "unknown_outcome_no_replay"}:
                decision = state["decisions"][event["turn"] - 1]
                usage = ({k: decision[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
                         if kind == "model_received" else None)
                item = {"kind": "parent_model_settled", "intent_id": f"{state['run_id']}:model:{event['turn']}", "usage": usage}
            elif kind == "tool_started":
                item = {"kind": "parent_tool_consumed", "tool_call_id": event["tool_call_id"]}
            elif kind == "child_reserved":
                domain = event.get("domain", "financial")
                child_spec = self._role_spec(domain)
                if domains and (domain in reserved_domains or event.get("domain") != domain):
                    raise IntegrityError("domain child was reserved more than once")
                reserved_domains.add(domain)
                if event["limits"] != {"decisions": child_spec.max_decisions,
                        "tools": child_spec.max_tools, "tokens": child_spec.max_tokens}:
                    raise IntegrityError("child allocation differs from child spec")
                if not event.get("parallel_group_id"):
                    item = {"kind": "child_reserved", "child_run_id": event["child_run_id"], "limits": event["limits"]}
                    if "headroom" in event:
                        item["headroom"] = event["headroom"]
            elif kind == "parallel_group_reserved":
                item = {"kind": "children_reserved", "group_id": event["parallel_group_id"],
                        "allocations": event["allocations"], "headroom": event["headroom"]}
            elif kind == "child_finished":
                child = children.get(event["child_run_id"])
                if child is None or child["result_ref"] != event["result_ref"]:
                    raise IntegrityError("child settlement lacks its structured receipt")
                if domains and child.get("domain") != event.get("domain"):
                    raise IntegrityError("child settlement domain differs")
                usage = child["usage"]
                item = {"kind": "child_settled", "child_run_id": event["child_run_id"], "usage": {
                    "decisions": usage["model_attempts"], "tools": usage["tool_calls"],
                    **{k: usage[k] for k in ("tokens_accounted", "tokens_reserved", "total_tokens", "unknown_usage_calls")}}}
            elif kind == "tool_finished" and event["tool"] in SOURCE_TOOLS:
                origins.pop(event["tool"], None)
            elif kind == "tool_finished" and event["tool"] in AGENT_TOOLS:
                matching = [c for c in children.values() if c["tool_call_id"] == event["tool_call_id"]]
                domain = event["tool"].removesuffix("_child")
                if (len(matching) != 1 or not matching[0]["source_tool_call_id"]
                        or domains and matching[0].get("domain") != domain):
                    raise IntegrityError("child imported evidence lacks a read call")
                origins[domain] = matching[0]["source_tool_call_id"]
            if item is not None:
                expected.append({"seq": len(expected), **item})
        if expected != ledger["events"] or origins != state["source_origins"]:
            raise IntegrityError("root reservations or evidence origins differ from runtime intents")
        local_reads = {e["tool_call_id"]: e["tool"] for e in state["trace"]
                       if e["event"] == "tool_finished" and e["tool"] in SOURCE_TOOLS}
        record_domains = {DataRecord.from_dict(row).record_id: DOMAINS[dataset]
                          for dataset, result in self._datasets(state).items() for row in result["records"]}
        for evidence in state.get("calculated", {}).get("evidence", {}).values():
            domain = record_domains.get(evidence.get("record_id"))
            local_read = domain is not None and local_reads.get(evidence.get("tool_call_id")) == domain
            child_read = any(child.get("domain", "financial") == domain
                and ref["tool_call_id"] == evidence.get("tool_call_id") and ref["record_id"] == evidence["record_id"]
                for child in children.values() for ref in child["evidence_refs"])
            if not local_read and not child_read:
                raise IntegrityError("parent evidence points outside its authorized read")

    def _verify_computed(self, state, request):
        if "calculated" not in state:
            return {"status": "not_completed", "numeric_claims": 0}
        computed = state["calculated"]
        datasets = self._datasets(state, state["computed_sources"])
        checking = deepcopy(computed)
        # The mandatory verifier may recompute expectations, but never publishes an
        # unperformed hypothesis tool or marks that required execution as completed.
        if state.get("hypotheses_revision") != state.get("calculated_revision"):
            checking["hypotheses"] = test_hypotheses(checking, datasets, request)
        if computed.get("insufficiency_diagnostics") != diagnose_insufficiency(checking, datasets, request):
            raise IntegrityError("dynamic insufficiency diagnostics differ")
        return verify(checking, datasets, request)

    def _check_results(self, state, request):
        current = state.get("calculated_revision") == self._current(state)
        checked = {h["id"]: h["status"] for h in state.get("calculated", {}).get("hypotheses", [])}
        results = []
        for item in state["requirements"]:
            if item.startswith("read:"):
                status = "passed" if item[5:] in state["outputs"] else "not_completed"
            elif item.startswith("binding:"):
                status = "insufficient"
            elif item == "calculation":
                status = "passed" if current else "not_completed"
            elif item == "hypotheses":
                status = "passed" if current and state.get("hypotheses_revision") == state.get("calculated_revision") else "not_completed"
            elif item == "verification":
                status = "passed" if current and state.get("verified_revision") == state.get("calculated_revision") else "not_completed"
            else:
                status = ("not_completed" if item[11:] not in checked or not current else
                          "insufficient" if checked[item[11:]] == "insufficient" else "passed")
            results.append({"id": item, "status": status})
        return results

    def _child_context(self, request, access, run, deadline, domain="financial"):
        """Intersect trusted delegation, live parent tools, ChildSpec and source policy."""
        child_spec = self._role_spec(domain)
        request_type, datasets = ((FinancialRequest, FINANCIAL_DATASETS) if domain == "financial" else
                                  (MarketRequest, MARKET_DATASETS))
        child_request = request_type.from_parent(request, self.delegated_datasets & datasets)
        effective = self.granted & self.spec.allowed_tools & self.spec.visible_tools & self.delegated_tools
        effective &= child_spec.allowed_tools & child_spec.visible_tools
        if domain not in effective:
            raise PermissionDenied("domain child delegation is not authorized")
        providers = frozenset(b.provider for b in child_request.bindings) & access.allowed_providers
        child_access = AccessContext(access.scope, providers)
        child = DynamicRuntime(self.service, self.checkpoints, self.model, child_spec,
            granted_tools=effective, cancelled=self.cancelled, now=self.now, monotonic=self.monotonic,
            parent_run_id=run, inherited_deadline=datetime.fromisoformat(deadline),
            authorize_parent=lambda: (domain in (self.granted & self.spec.allowed_tools &
                self.spec.visible_tools & self.delegated_tools) and domain + "_child" in
                (self.granted & self.spec.allowed_tools & self.spec.visible_tools)))
        if self._parallel_enabled():
            child.telemetry_lineage = {"parallel_group_id": None, "parallel_width": 1,
                                       "route_type": "delegated_child"}
        return child, child_request, child_access

    def _finish_child(self, state, request, finish_reason):
        domain = "market" if isinstance(self.spec, MarketChildSpec) else "financial"
        outputs = {} if state.get("withheld") else deepcopy(state["outputs"].get(domain, {}))
        checks = self._check_results(state, request) if not state.get("withheld") else [
            {"id": item, "status": "not_completed"} for item in state["requirements"]]
        performed = all(c["status"] == "passed" for c in checks)
        available = bool(outputs) and all(r["records"] and r["status"] == "available" for r in outputs.values())
        status = ("partial" if state.get("stop_reason") or not performed else
                  "completed" if available and finish_reason == "completed" else "insufficient")
        read_calls = [e["tool_call_id"] for e in state["trace"] if e["event"] == "tool_finished"]
        refs = [{"record_id": DataRecord.from_dict(row).record_id,
                 "artifact_sha256": row["artifact_id"], "snapshot": result["snapshot"],
                 "tool_call_id": read_calls[-1]} for _, result in sorted(outputs.items()) for row in result["records"]]
        state["report"] = {"schema": domain + "-child-result/v1", "run_id": state["run_id"],
            "parent_run_id": self.parent_run_id, "status": status, "stop_reason": state.get("stop_reason"),
            "request_ref": digest(request.to_dict()), "source_result_ref": digest(outputs),
            "source_results": outputs, "evidence_refs": refs, "required_checks": checks,
            "source_tool_call_id": read_calls[-1] if read_calls else None,
            "deadline": state["deadline"], "trace": deepcopy(state["trace"]),
            "usage": {"model_attempts": state["model_attempts"], "tool_calls": state["tools_used"],
                      "tokens_accounted": state["tokens_accounted"], "tokens_reserved": state["tokens_reserved"],
                      "total_tokens": sum(d.get("total_tokens", 0) for d in state["decisions"]),
                      "unknown_usage_calls": sum("total_tokens" not in d for d in state["decisions"])}}
        if domain == "market":
            state["report"]["domain"] = domain
        if "context_telemetry" in state:
            state["report"]["context_telemetry"] = deepcopy(state["context_telemetry"])
            state["report"]["trace_stratum"] = domain + "_child"
        state["finish_reason"], state["phase"] = finish_reason, "completed"

    @staticmethod
    def _child_summary(report, parent_run_id, tool_call_id, domain=None):
        if (report.get("schema") != (domain or "financial") + "-child-result/v1"
                or report.get("parent_run_id") != parent_run_id
                or domain == "market" and report.get("domain") != domain):
            raise IntegrityError("child returned an unbound result")
        summary = {"schema": report["schema"], "child_run_id": report["run_id"],
            "parent_run_id": parent_run_id, "tool_call_id": tool_call_id,
            **{key: deepcopy(report[key]) for key in ("status", "stop_reason", "request_ref", "source_result_ref",
                "evidence_refs", "required_checks", "usage", "deadline", "source_tool_call_id")}, "result_ref": digest(report)}
        if domain is not None:
            summary["domain"] = domain
        return summary

    def _finish_dynamic(self, state, request, *, finish_reason=None):
        if isinstance(self.spec, (FinancialChildSpec, MarketChildSpec)):
            self._finish_child(state, request, finish_reason)
            return
        if state.get("withheld"):
            safe = deepcopy(state)
            safe.pop("withheld", None)
            safe["outputs"], safe["observations"] = {}, {}
            for key in ("calculated", "calculated_revision", "hypotheses_revision", "verified_revision"):
                safe.pop(key, None)
            self._finish_dynamic(safe, request, finish_reason=finish_reason)
            state["report"], state["phase"] = safe["report"], safe["phase"]
            state["finish_reason"] = finish_reason
            return
        verified = self._verify_computed(state, request)
        checks = self._check_results(state, request)
        complete = bool(state.get("calculated", {}).get("facts")) and all(c["status"] == "passed" for c in checks)
        if finish_reason == "completed" and not complete:
            state["stop_reason"] = ("required_checks_not_completed" if any(c["status"] == "not_completed" for c in checks)
                                    else "evidence_insufficient")
        elif finish_reason == "insufficient":
            state["stop_reason"] = "model_reported_insufficient"
        # Reuse the shared exact facts, lineage, document-index and report construction.
        self._finish(state, request, model_required=True)
        report = state["report"]
        report.update(schema="dynamic-research/v1", execution_strategy="dynamic",
                      required_checks=checks, verification=verified,
                      plans=deepcopy(state["plans"]), decisions=deepcopy(state["decisions"]))
        report.setdefault("hypotheses", [])
        report.setdefault("event_anchor", {"status": "insufficient", "reason": "calculation_not_completed"})
        report.setdefault("context", state.get("context", {"status": "not_prepared"}))
        report["status"] = ("completed" if complete and finish_reason == "completed" and not state.get("stop_reason") else
                            "insufficient" if finish_reason == "insufficient" or state.get("stop_reason") == "evidence_insufficient" else "partial")
        report["research_status"] = "tests_completed" if report["status"] == "completed" else (
            "evidence_incomplete" if report["status"] == "insufficient" else "stopped")
        report["synthesis"] = {s: [h["id"] for h in report["hypotheses"] if h["status"] == s]
                               for s in ("supported", "unsupported", "conflicted", "insufficient")}
        report["synthesis"]["causal_conclusion"] = "not_established"
        report["usage"].update(tokens_accounted=state["tokens_accounted"],
                               total_tokens=sum(d.get("total_tokens", 0) for d in state["decisions"]),
                               unknown_usage_calls=sum("total_tokens" not in d for d in state["decisions"]))
        report["limitations"] = ["模型计划仅为控制记录，不是财务事实；数值和假设由受限工具生成。",
                                 "严格 JSON 文本动作为应用层工具调用；未使用原生 function calling。",
                                 "仅支持可信清单绑定的描述性检验；不作因果结论，来源准确性及覆盖未认证。"]
        if isinstance(self.spec, FinancialParentSpec):
            from .root_budget import root_usage
            report["child_results"] = deepcopy(state.get("child_results", []))
            report["root_budget"] = root_usage(state["root_budget"])
            report["child_evidence_links"] = [{"evidence_id": eid, "child_run_id": child["child_run_id"],
                "record_id": evidence["record_id"], "tool_call_id": evidence["tool_call_id"]}
                for eid, evidence in sorted(report["evidence"].items()) for child in report["child_results"]
                if any(ref["record_id"] == evidence["record_id"] and ref["tool_call_id"] == evidence["tool_call_id"]
                       for ref in child["evidence_refs"])]
        if isinstance(self.spec, DomainParentSpec):
            report["routes"] = []
            reservations = {event["tool_call_id"]: event["child_run_id"] for event in state["trace"]
                            if event["event"] == "child_reserved"}
            for event in state["trace"]:
                if event["event"] != "tool_started":
                    continue
                name = event["tool"]
                route = {"turn": event["turn"], "tool": name, "tool_call_id": event["tool_call_id"],
                    "mode": "delegated" if name in AGENT_TOOLS else "direct",
                    "domain": name.removesuffix("_child") if name in AGENT_TOOLS else name if name in SOURCE_TOOLS else "research"}
                if event["tool_call_id"] in reservations:
                    route["child_run_id"] = reservations[event["tool_call_id"]]
                report["routes"].append(route)
        if self._context_enabled():
            report["context_archive"] = {"schema": "dynamic-context-archive/v1",
                "catalog_refs": sorted(state["context_store"]["catalogs"]),
                "disclosures": deepcopy(state["context_store"]["disclosures"]),
                "authoritative_facts_preserved": len(report["facts"]),
                "authoritative_evidence_preserved": len(report["evidence"])}
        if self._parallel_enabled():
            report["parallel_groups"] = deepcopy(state.get("parallel_groups", []))
        if "context_telemetry" in state:
            report["context_telemetry"] = deepcopy(state["context_telemetry"])
            report["trace_stratum"] = ("parallel_2_child" if state.get("parallel_groups") else
                "parent_2_child" if len(state.get("child_results", [])) == 2 else
                "parent_1_child" if state.get("child_results") else
                "parent_direct" if isinstance(self.spec, FinancialParentSpec) else "dynamic_single")
        state["finish_reason"] = finish_reason

    def run(self, request, access, *, resume=None, run_id=None):
        if self.model is None or self.checkpoints is None:
            raise ValidationError("dynamic execution requires a configured model and checkpoint store")
        executor, available = self._setup(request, access)
        if resume and run_id:
            raise ValidationError("a dynamic run cannot start and resume simultaneously")
        run = resume or run_id or uuid.uuid4().hex
        configuration = {"request": request.to_dict(), "spec": self.spec.identity,
                         "model_enabled": True, "protocol": "dynamic-action/v1"}
        if self.spec.version != "single-dynamic-v1":
            configuration["protocol"] = self.spec.version
        if isinstance(self.spec, FinancialParentSpec):
            configuration["delegation"] = {"tools": sorted(self.delegated_tools),
                "datasets": sorted(self.delegated_datasets), "child_spec": self.child_spec.identity}
        if isinstance(self.spec, DomainParentSpec):
            configuration["delegation"]["domain_specs"] = {domain: child_spec.identity for domain, child_spec in self.child_specs.items()}
        if self._context_enabled():
            configuration["context_policy"] = {"schema": "dynamic-context-store/v1",
                "strategy": "lossless_catalog_lazy_disclosure/v1", "available_tools": available,
                "granted_tools": sorted(self.granted), "scope_ref": digest(access.scope)}
        if isinstance(self.spec, (FinancialChildSpec, MarketChildSpec)):
            configuration["parent"] = {"run_id": self.parent_run_id, "deadline": self.inherited_deadline.isoformat()}
        if self.telemetry_lineage is not None:
            configuration["telemetry_lineage"] = self.telemetry_lineage
        binding = digest(configuration)
        with self.checkpoints.lock(access.scope, run):
            if resume:
                history = self.checkpoints.history(access.scope, run)
                state = history[-1]
                if state["binding"] != binding:
                    raise PermissionDenied("resume request or dynamic configuration differs")
                original = history[0]
                if any(saved.get(k) != original.get(k) for saved in history for k in
                       ("binding", "deadline", "request", "requirements", "schema", "spec_version", "run_id")):
                    raise IntegrityError("dynamic immutable recovery limits differ")
                for earlier, later in zip(history, history[1:]):
                    if (any(later[k] < earlier[k] for k in ("model_attempts", "tools_used", "tokens_reserved"))
                            or later["trace"][:len(earlier["trace"])] != earlier["trace"]):
                        raise IntegrityError("dynamic recovery ledger decreased or trace changed")
                self._validate_ledger(state, request)
                if isinstance(self.spec, FinancialParentSpec):
                    from .root_budget import validate_root_budget
                    validate_root_budget(state["root_budget"], [saved["root_budget"] for saved in history])
                if state.get("security_stopped"):
                    raise PermissionDenied("dynamic run was stopped by a security violation")
            else:
                if run_id:
                    try:
                        self.checkpoints.read(access.scope, run)
                    except PermissionDenied:
                        pass
                    else:
                        raise IntegrityError("child run ID already has a checkpoint")
                deadline = self.now() + timedelta(seconds=self.spec.max_seconds)
                if self.inherited_deadline is not None:
                    deadline = min(deadline, self.inherited_deadline)
                state = {"schema": "dynamic-state/v1", "run_id": run, "binding": binding,
                         "request": request.to_dict(), "spec_version": self.spec.version,
                         "phase": "planned", "outputs": {}, "observations": {}, "plans": [], "decisions": [],
                         "requirements": self._requirements(request), "tools_used": 0, "model_attempts": 0,
                         "tokens_reserved": 0, "tokens_accounted": 0, "no_progress": 0,
                         "completed_actions": [], "pending_action": None, "pending_tool": None,
                         "deadline": deadline.isoformat(),
                         "trace": [], "model": {"status": "not_called"}, "report": None}
                if isinstance(self.spec, FinancialParentSpec):
                    from .root_budget import new_root_budget
                    state["root_budget"] = new_root_budget({"decisions": self.spec.root_max_decisions,
                        "tools": self.spec.root_max_tools, "tokens": self.spec.root_max_tokens}, run,
                        **({"max_children": self.spec.max_children} if isinstance(self.spec, DomainParentSpec) else {}),
                        **({"parallel": True} if self._parallel_enabled() else {}))
                    state["child_results"], state["source_origins"] = [], {}
                if self._parallel_enabled():
                    state["parallel_groups"] = []
                # New runs collect telemetry across Single/direct/delegated paths.
                # Old checkpoint reports contain no such field and replay unchanged.
                state["context_telemetry"] = []
                if self._context_enabled():
                    state["context_store"] = {"schema": "dynamic-context-store/v1",
                        "binding": digest({"scope": access.scope, "run_id": run, "request": request.to_dict()}),
                        "catalogs": {}, "disclosures": [], "requested_refs": []}
                self.checkpoints.append(access.scope, run, state)
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

            def context_lineage():
                child = isinstance(self.spec, (FinancialChildSpec, MarketChildSpec))
                domain = "market" if isinstance(self.spec, MarketChildSpec) else "financial" if child else "research"
                groups = state.get("parallel_groups", [])
                return {"run_id": run, "parent_run_id": self.parent_run_id,
                    "child_run_id": run if child else None,
                    "agent_role": "child" if child else "parent" if isinstance(self.spec, FinancialParentSpec) else "single",
                    "domain": domain, "turn_id": state["model_attempts"] + 1,
                    "route_type": "parallel_2_child" if groups else "parent_2_child" if len(state.get("child_results", [])) == 2 else
                                  "parent_1_child" if state.get("child_results") else
                                  "parent_direct" if isinstance(self.spec, FinancialParentSpec) else "dynamic_single",
                    "parallel_group_id": groups[-1]["parallel_group_id"] if groups else None,
                    "parallel_width": 2 if groups else 1, **(self.telemetry_lineage or {})}

            def record_context_result(decision, *, dispatched=True, status=None, reason=None):
                if "context_telemetry" not in state or "context_telemetry" not in decision:
                    return
                from .context_telemetry import telemetry_result
                record = telemetry_result(decision["context_telemetry"], model_dispatched=dispatched,
                    status=status or decision["status"], stop_reason=reason,
                    input_tokens=decision.get("prompt_tokens"), output_tokens=decision.get("completion_tokens"),
                    total_tokens=decision.get("total_tokens"))
                state["context_telemetry"][record["turn_id"] - 1] = record
                decision["context_telemetry"] = record
                event("context_telemetry_result", **record)

            def revalidate(*, replay=False):
                if self.cancelled():
                    raise BudgetExceeded("cancelled")
                if self.authorize_parent is not None and not self.authorize_parent():
                    raise PermissionDenied("parent delegation was revoked")
                for summary in state.get("child_results", []):
                    domain = summary.get("domain", "financial") if isinstance(self.spec, DomainParentSpec) else "financial"
                    executor.registry.authorize(domain + "_child", self.spec, self.granted)
                    child, child_request, child_access = self._child_context(request, access, run, state["deadline"], domain)
                    if self._parallel_enabled():
                        for group in state.get("parallel_groups", []):
                            node = group["nodes"][domain + "_branch"]
                            if node["child_run_id"] == summary["child_run_id"]:
                                child.inherited_deadline = datetime.fromisoformat(node["deadline"])
                                child.telemetry_lineage = {"parallel_group_id": group["parallel_group_id"],
                                                          "parallel_width": 2, "route_type": "parallel_child"}
                    fresh = child.run(child_request, child_access, resume=summary["child_run_id"])
                    expected = self._child_summary(fresh, run, summary["tool_call_id"],
                        domain=domain if isinstance(self.spec, DomainParentSpec) else None)
                    if expected != summary:
                        raise IntegrityError("child structured result differs from authorized checkpoint")
                for name, saved in state["outputs"].items():
                    if not replay:
                        check()
                    fresh, _ = executor.execute(name, wave="dynamic-revalidation")
                    if not replay:
                        check()
                    if digest(fresh) != digest(saved):
                        raise IntegrityError("dynamic pinned snapshot result changed")
                # Derived permissions are also rechecked on reuse and recovery.
                for name in ("calculation", "hypotheses", "verification"):
                    if name in state["observations"]:
                        executor.registry.authorize(name, self.spec, self.granted)
                self._verify_computed(state, request)
                for name, observation in state["observations"].items():
                    if name in SOURCE_TOOLS:
                        expected = observe_tool(name, state["outputs"][name])
                    elif name == "verification":
                        expected = observe_tool(name, self._verify_computed(state, request))
                    else:
                        computed = deepcopy(state["calculated"])
                        if name == "calculation":
                            computed["hypotheses"] = []
                        expected = observe_tool(name, computed)
                    if expected != observation:
                        raise IntegrityError("dynamic cached Observation differs from authorized evidence")
                if self._context_enabled():
                    self._validate_context_history(self.checkpoints.history(access.scope, run), state,
                                                   request, access, available)
                if resume:
                    self._validate_telemetry_history(self.checkpoints.history(access.scope, run), state,
                                                     request, access, available)

            if state["report"] is not None:
                revalidate(replay=True)
                saved = deepcopy(state["report"])
                self._finish_dynamic(state, request, finish_reason=state.get("finish_reason"))
                # Trace in report is captured before the final checkpoint event.
                state["report"]["trace"] = saved["trace"]
                if state["report"] != saved:
                    raise IntegrityError("dynamic completed report differs")
                return saved
            validated = False
            try:
                check()
                revalidate()
                validated = True
                if state["decisions"] and state["decisions"][-1]["status"] in {"pending", "received"}:
                    state["decisions"][-1]["status"] = "unknown_outcome_no_replay"
                    state["model"] = {"status": "unknown_outcome_no_replay"}
                    raise BudgetExceeded("unknown_model_outcome_no_replay")
                if state["pending_tool"]:
                    raise BudgetExceeded("unknown_tool_outcome_no_replay")
                if state["decisions"] and state["decisions"][-1]["status"] in {"invalid_receipt", "unknown_outcome_no_replay"}:
                    raise BudgetExceeded("unknown_model_outcome_no_replay")
                while True:
                    check()
                    revalidate()
                    if self._parallel_enabled() and state.get("parallel_groups") and state["pending_action"] and state["pending_action"]["action"] == "parallel":
                        from .parallel import execute_group
                        execute_group(self, state, request, access, executor, event, check, state["parallel_groups"][-1])
                        continue
                    if state["pending_action"] is None:
                        if state["model_attempts"] >= self.spec.max_decisions:
                            raise BudgetExceeded("decision_budget_exceeded")
                        message_kwargs = dict(decision=state["model_attempts"] + 1,
                            protocol_error=state.get("protocol_error"), version=self.spec.version,
                            finish_rejection=state.get("finish_rejection"),
                            **({"delegation_results": [{"tool": c["domain"] + "_child", "domain": c["domain"],
                                "status": c["status"], "result_ref": c["result_ref"]} for c in state["child_results"]]}
                                if isinstance(self.spec, DomainParentSpec) else {}),
                            **(self._context_arguments(state, access) if self._context_enabled() else {}))
                        try:
                            messages, context = dynamic_messages(request, available, list(state["observations"].values()),
                                state["requirements"], state["plans"][-1]["steps"] if state["plans"] else [],
                                self.spec.context_bytes, **message_kwargs)
                        except ValidationError:
                            if "context_telemetry" in state:
                                from .context_telemetry import overflow_context_telemetry
                                telemetry = overflow_context_telemetry(request, available, list(state["observations"].values()),
                                    state["requirements"], state["plans"][-1]["steps"] if state["plans"] else [],
                                    max_bytes=self.spec.context_bytes, message_kwargs=message_kwargs, **context_lineage())
                                state["context_telemetry"].append(telemetry)
                                event("context_budget_exceeded", **telemetry)
                            raise BudgetExceeded("dynamic_context_budget_exceeded") from None
                        reservation = sum(len(m["content"].encode("utf-8")) for m in messages) + 256 + self.spec.output_tokens
                        if state["tokens_accounted"] + reservation > self.spec.max_tokens:
                            raise BudgetExceeded("model_input_budget_exceeded")
                        check()
                        turn = state["model_attempts"] = state["model_attempts"] + 1
                        if isinstance(self.spec, FinancialParentSpec):
                            from .root_budget import reserve_parent_model
                            # Reserve before local mutation and the durable paid intent.
                            state["model_attempts"] -= 1
                            state["root_budget"] = reserve_parent_model(state["root_budget"], f"{run}:model:{turn}",
                                                                        reservation, digest(messages))
                            state["model_attempts"] += 1
                        decision = {"turn": turn, "status": "pending", "token_reservation": reservation,
                                    "message_sha256": digest(messages)}
                        if "context_telemetry" in state:
                            from .context_telemetry import build_context_telemetry
                            lineage = context_lineage()
                            lineage["turn_id"] = turn
                            telemetry = build_context_telemetry(messages, context, list(state["observations"].values()), request,
                                limit_bytes=self.spec.context_bytes, **lineage)
                            decision["context_telemetry"] = telemetry
                            decision["context_observation_order"] = list(state["observations"])
                            state["context_telemetry"].append(telemetry)
                        if self._context_enabled():
                            catalog = self._build_catalog(state, request, access)
                            state["context_store"]["catalogs"][catalog["catalog_ref"]] = catalog
                            decision["context_catalog_ref"] = catalog["catalog_ref"]
                        state["decisions"].append(decision)
                        state["tokens_reserved"] += reservation
                        state["tokens_accounted"] += reservation
                        state["phase"] = "model_pending"
                        state["model"] = {"status": "pending"}
                        state["context"] = {"status": "prepared", **context}
                        if "context_telemetry" in decision:
                            event("context_telemetry_prepared", **decision["context_telemetry"])
                        event("model_started", turn=turn, requested_model=self.spec.model,
                              token_reservation=reservation, message_sha256=digest(messages))
                        try:
                            result = self.model.complete(messages, max_tokens=self.spec.output_tokens,
                                timeout=min(120, max(0.001, stop_at - self.monotonic())))
                        except Exception as exc:
                            decision.update(status="unknown_outcome_no_replay", error_type=type(exc).__name__)
                            state["model"] = {"status": "unknown_outcome_no_replay", "error_type": type(exc).__name__}
                            if isinstance(self.spec, FinancialParentSpec):
                                from .root_budget import settle_parent_model
                                state["root_budget"] = settle_parent_model(state["root_budget"], f"{run}:model:{turn}", None)
                            event("model_finished", turn=turn, status=decision["status"], error_type=type(exc).__name__)
                            record_context_result(decision, reason="model_call_failed_no_replay")
                            raise BudgetExceeded("model_call_failed_no_replay") from None
                        try:
                            validate_model_result(result, self.spec, reservation)
                        except ValidationError:
                            decision["status"] = "invalid_receipt"
                            state["model"] = {"status": "rejected"}
                            if isinstance(self.spec, FinancialParentSpec):
                                from .root_budget import settle_parent_model
                                state["root_budget"] = settle_parent_model(state["root_budget"], f"{run}:model:{turn}", None)
                            event("model_finished", turn=turn, status=decision["status"])
                            record_context_result(decision, reason="model_receipt_invalid")
                            raise BudgetExceeded("model_receipt_invalid") from None
                        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "latency_ms"):
                            decision[key] = getattr(result, key)
                        state["tokens_accounted"] += result.total_tokens - reservation
                        if isinstance(self.spec, FinancialParentSpec):
                            from .root_budget import settle_parent_model
                            state["root_budget"] = settle_parent_model(state["root_budget"], f"{run}:model:{turn}",
                                {k: getattr(result, k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")})
                        decision["status"] = "received"
                        event("model_received", turn=turn, total_tokens=result.total_tokens)
                        record_context_result(decision, status="received")
                        check()
                        # Never persist unvalidated response text or reflected credentials.
                        secret = getattr(self.model.config, "api_key", None)
                        if secret and secret in result.content:
                            raise BudgetExceeded("credential_reflection_rejected")
                        try:
                            action = parse_action(result.content, available, state["observations"], version=self.spec.version,
                                                  **self._context_parse_arguments(state, request, access))
                        except (ValidationError, ValueError, TypeError, RecursionError):
                            decision.update(status="invalid_action", error_type="ActionSchemaError")
                            state["model"] = {"status": "rejected", "error_type": "ActionSchemaError"}
                            state["protocol_error"] = "invalid_action"
                            state["no_progress"] += 1
                            event("model_finished", turn=turn, status="invalid_action")
                            record_context_result(decision, reason="invalid_action")
                            if state["no_progress"] >= self.spec.no_progress_limit:
                                raise BudgetExceeded("no_progress")
                            continue
                        if secret and secret in canonical_json(action):
                            raise BudgetExceeded("credential_reflection_rejected")
                        state.pop("protocol_error", None)
                        decision.update(status="verified", action=action)
                        state["pending_action"] = action
                        state["model"] = {"status": "verified", "requested_model": result.requested_model,
                                          "returned_model": result.returned_model, "highlights": [],
                                          "hypotheses": list(request.hypotheses)}
                        state["plans"].append({"turn": turn, "steps": action["plan"]})
                        event("model_finished", turn=turn, status="verified", action=action)
                        record_context_result(decision)
                        event("plan_updated", turn=turn, steps=action["plan"])
                    action = state["pending_action"]
                    # Restored actions pass the same Schema/current-reference gate.
                    action = parse_action(canonical_json(action), available, state["observations"], version=self.spec.version,
                                          **self._context_parse_arguments(state, request, access))
                    check()
                    if action["action"] == "parallel":
                        from .parallel import start_group, execute_group
                        try:
                            group = start_group(self, state, request, access, executor, event)
                        except ValidationError as exc:
                            if isinstance(exc, BudgetExceeded):
                                raise
                            state["pending_action"] = None
                            state["protocol_error"] = "duplicate_no_progress"
                            state["no_progress"] += 1
                            event("repeated_action", tool="parallel", dispatched=False)
                            if state["no_progress"] >= self.spec.no_progress_limit:
                                raise BudgetExceeded("no_progress")
                            continue
                        execute_group(self, state, request, access, executor, event, check, group)
                        continue
                    if action["action"] == "finish":
                        pending = [c["id"] for c in self._check_results(state, request) if c["status"] == "not_completed"]
                        if self.spec.version != "single-dynamic-v1" and pending:
                            rejection = {"code": "required_checks_pending", "pending_checks": pending}
                            state["decisions"][-1]["rejection"] = rejection
                            state["finish_rejection"] = rejection
                            state["pending_action"] = None
                            state["no_progress"] += 1
                            event("finish_rejected", turn=state["model_attempts"], rejection=rejection)
                            if state["no_progress"] >= self.spec.no_progress_limit:
                                raise BudgetExceeded("no_progress")
                            continue
                        state["pending_action"] = None
                        self._finish_dynamic(state, request, finish_reason=action["reason"])
                        check()
                        event("report_verified", status=state["report"]["status"], report_hash=digest(state["report"]))
                        return state["report"]
                    if action["action"] == "disclose":
                        # Context retrieval reuses existing source/derived Registry
                        # grants. It is an accounted read, not a new business tool.
                        from .dynamic_context import resolve_catalog
                        catalog = self._build_catalog(state, request, access)
                        signature = digest({"context_catalog_ref": catalog["catalog_ref"], "refs": action["refs"]})
                        if signature in state["completed_actions"]:
                            state["pending_action"] = None
                            state["no_progress"] += 1
                            state["protocol_error"] = "duplicate_no_progress"
                            event("repeated_action", tool="context_disclosure", dispatched=False)
                            if state["no_progress"] >= self.spec.no_progress_limit:
                                raise BudgetExceeded("no_progress")
                            continue
                        if state["tools_used"] >= self.spec.max_tools:
                            raise BudgetExceeded("tool_budget_exceeded")
                        call_id = f"{run}:{state['tools_used'] + 1}"
                        from .root_budget import consume_parent_tool
                        state["root_budget"] = consume_parent_tool(state["root_budget"], call_id)
                        state["tools_used"] += 1
                        state["pending_tool"] = {"tool": "context_disclosure", "tool_call_id": call_id}
                        event("tool_started", tool="context_disclosure", tool_call_id=call_id, turn=state["model_attempts"])
                        output = resolve_catalog(catalog, action["refs"], scope=access.scope, run_id=run,
                                                 catalog_ref=action["catalog_ref"])
                        check()
                        revalidate()  # Live grants must still permit the returned objects.
                        check()
                        disclosure = {"turn": state["model_attempts"], "tool_call_id": call_id,
                            "catalog_ref": catalog["catalog_ref"], "refs": action["refs"], "result_ref": digest(output)}
                        state["context_store"]["disclosures"].append(disclosure)
                        state["context_store"]["requested_refs"] = action["refs"]
                        event("context_disclosed", **disclosure)
                        state["completed_actions"].append(signature)
                        state["pending_action"] = state["pending_tool"] = None
                        state["no_progress"] = 0
                        state["phase"] = "observed"
                        event("tool_finished", tool="context_disclosure", tool_call_id=call_id,
                              dedup=False, result_hash=digest(output), catalog_ref=catalog["catalog_ref"])
                        continue
                    name = action["tool"]
                    executor.registry.authorize(name, self.spec, self.granted)
                    revision = self._current(state)
                    signature = digest({"tool": name, "refs": sorted(action["refs"]),
                                        "input": None if name in SOURCE_TOOLS or name in AGENT_TOOLS else revision})
                    already_delegated = (isinstance(self.spec, DomainParentSpec) and name in AGENT_TOOLS and any(
                        event["event"] == "child_reserved" and event.get("domain") == name.removesuffix("_child")
                        for event in state["trace"]))
                    if signature in state["completed_actions"] or already_delegated:
                        state["pending_action"] = None
                        state["no_progress"] += 1
                        state["protocol_error"] = "duplicate_no_progress"
                        event("repeated_action", tool=name, dispatched=False)
                        if state["no_progress"] >= self.spec.no_progress_limit:
                            raise BudgetExceeded("no_progress")
                        continue
                    if state["tools_used"] >= self.spec.max_tools:
                        raise BudgetExceeded("tool_budget_exceeded")
                    call_id = f"{run}:{state['tools_used'] + 1}"
                    if isinstance(self.spec, FinancialParentSpec):
                        from .root_budget import consume_parent_tool
                        state["root_budget"] = consume_parent_tool(state["root_budget"], call_id)
                    state["tools_used"] += 1
                    state["pending_tool"] = {"tool": name, "tool_call_id": call_id}
                    event("tool_started", tool=name, tool_call_id=call_id, turn=state["model_attempts"])
                    try:
                        observation_name = name
                        if name in SOURCE_TOOLS:
                            output, reused = executor.execute(name, wave="dynamic")
                            check()
                            state["outputs"][name] = output
                            state.get("source_origins", {}).pop(name, None)
                            for derived in ("calculation", "hypotheses", "verification"):
                                state["observations"].pop(derived, None)
                        elif name in AGENT_TOOLS:
                            if not isinstance(self.spec, FinancialParentSpec):
                                raise PermissionDenied("only the dynamic parent can spawn a financial child")
                            from .root_budget import reserve_child, settle_child
                            domain = name.removesuffix("_child")
                            child, child_request, child_access = self._child_context(request, access, run, state["deadline"], domain)
                            child_spec = self._role_spec(domain)
                            child_run = uuid.uuid4().hex
                            limits = {"decisions": child_spec.max_decisions,
                                      "tools": child_spec.max_tools, "tokens": child_spec.max_tokens}
                            headroom = self._parent_headroom(state) if self._parallel_enabled() else None
                            state["root_budget"] = reserve_child(state["root_budget"], child_run, limits,
                                **({"headroom": headroom} if headroom is not None else {}))
                            state["pending_child"] = {"run_id": child_run, "tool_call_id": call_id,
                                "request_ref": digest(child_request.to_dict()), "limits": limits}
                            event("child_reserved", child_run_id=child_run, tool_call_id=call_id, limits=limits,
                                  request_ref=digest(child_request.to_dict()), root_deadline=state["deadline"],
                                  **({"headroom": headroom} if headroom is not None else {}),
                                  **({"domain": domain} if isinstance(self.spec, DomainParentSpec) else {}))
                            child_report = child.run(child_request, child_access, run_id=child_run)
                            check()  # A late/cancelled child never enters the parent's evidence.
                            usage = child_report["usage"]
                            state["root_budget"] = settle_child(state["root_budget"], child_run,
                                {"decisions": usage["model_attempts"], "tools": usage["tool_calls"],
                                 **{k: usage[k] for k in ("tokens_accounted", "tokens_reserved", "total_tokens", "unknown_usage_calls")}})
                            summary = self._child_summary(child_report, run, call_id,
                                domain=domain if isinstance(self.spec, DomainParentSpec) else None)
                            state["child_results"].append(summary)
                            state["pending_child"] = None
                            event("child_finished", child_run_id=child_run, status=child_report["status"],
                                  result_ref=summary["result_ref"],
                                  **({"domain": domain} if isinstance(self.spec, DomainParentSpec) else {}))
                            if child_report["status"] not in {"completed", "insufficient"}:
                                raise ValidationError("domain child did not complete its required read")
                            output = child_report["source_results"]
                            # Validate before importing: same bound sources, same authorization.
                            fresh, _ = executor.execute(domain, wave="child-import")
                            delegated = {key: result for key, result in fresh.items() if key in self.delegated_datasets}
                            if digest(delegated) != child_report["source_result_ref"] or delegated != output:
                                raise IntegrityError("financial child source result differs from parent binding")
                            check()
                            # Partial delegated datasets cannot satisfy an aggregate financial read.
                            if set(output) != set(fresh):
                                raise ValidationError("financial child delegation does not cover the bound financial read")
                            state["outputs"][domain] = output
                            child_calls = [e["tool_call_id"] for e in child_report["trace"] if e["event"] == "tool_finished"]
                            state["source_origins"][domain] = child_calls[-1]
                            for derived in ("calculation", "hypotheses", "verification"):
                                state["observations"].pop(derived, None)
                            observation_name, reused = domain, False
                        elif name == "calculation":
                            if self._parallel_enabled():
                                from .parallel import gate_stage
                                gate_stage(state, name)
                            output = calculate_study_claims(self._datasets(state), request,
                                profit_change="absolute_profit_change" in request.hypotheses)
                            output["hypotheses"] = []
                            checking = {**output, "hypotheses": test_hypotheses(output, self._datasets(state), request)}
                            output["insufficiency_diagnostics"] = diagnose_insufficiency(checking, self._datasets(state), request)
                            for source in output["evidence"].values():
                                domain = DOMAINS[next(dataset for dataset, result in self._datasets(state).items()
                                                     if any(DataRecord.from_dict(r).record_id == source["record_id"] for r in result["records"]))]
                                source["tool_call_id"] = (state.get("source_origins", {}).get(domain) or
                                    next(e["tool_call_id"] for e in reversed(state["trace"])
                                         if e["event"] == "tool_finished" and e["tool"] == domain))
                            check()
                            state["calculated"] = output
                            state["computed_sources"] = sorted(state["outputs"])
                            state["calculated_revision"] = revision
                            state.pop("hypotheses_revision", None)
                            state.pop("verified_revision", None)
                            state["observations"].pop("hypotheses", None)
                            state["observations"].pop("verification", None)
                            self._verify_computed(state, request)
                            reused = False
                        else:
                            if self._parallel_enabled():
                                from .parallel import gate_stage
                                gate_stage(state, name)
                            if state.get("calculated_revision") != revision:
                                raise ValidationError("calculation must use all current bound results")
                            if name == "hypotheses":
                                output = state["calculated"]
                                output["hypotheses"] = test_hypotheses(output, self._datasets(state), request)
                                output["insufficiency_diagnostics"] = diagnose_insufficiency(output, self._datasets(state), request)
                                state["hypotheses_revision"] = revision
                            else:
                                if state.get("hypotheses_revision") != revision:
                                    raise ValidationError("hypotheses must precede verification")
                                output = self._verify_computed(state, request)
                                state["verified_revision"] = revision
                            reused = False
                        check()
                        state["observations"][observation_name] = observe_tool(observation_name, output)
                        if self._parallel_enabled():
                            from .parallel import complete_stage
                            complete_stage(state, name)
                        if self._context_enabled():
                            state["context_store"]["requested_refs"] = []
                        state["completed_actions"].append(signature)
                        state["pending_tool"] = state["pending_action"] = None
                        state["no_progress"] = 0
                        state.pop("finish_rejection", None)
                        state["phase"] = "observed"
                        event("tool_finished", tool=name, tool_call_id=call_id, dedup=reused,
                              result_hash=digest(output), observation=state["observations"][observation_name])
                    except ValidationError as exc:
                        if isinstance(exc, BudgetExceeded):
                            raise
                        state["pending_tool"] = state["pending_action"] = None
                        state["no_progress"] += 1
                        state["protocol_error"] = "tool_failed"
                        event("tool_failed", tool=name, error_type=type(exc).__name__)
                        if state["no_progress"] >= self.spec.no_progress_limit:
                            raise BudgetExceeded("no_progress")
            except BudgetExceeded as exc:
                state["stop_reason"] = str(exc)
                if state["decisions"]:
                    record_context_result(state["decisions"][-1], reason=str(exc))
                if state["model"]["status"] == "pending":
                    state["model"] = {"status": "unknown_outcome_no_replay"}
                # No extra source read after a deadline/cancellation. Withhold source
                # facts when authorization did not finish or the last operation was late.
                state["withheld"] = not validated or str(exc) in {"cancelled", "deadline_exceeded"}
                self._finish_dynamic(state, request)
                event("run_stopped", reason=str(exc), report_hash=digest(state["report"]))
                return state["report"]
            except (PermissionDenied, IntegrityError) as exc:
                state["security_stopped"] = True
                state["stop_reason"] = "security_violation"
                event("security_stopped", error_type=type(exc).__name__)
                raise
