"""Pure context measurements for M3 traces; never model input or policy decisions.

The before-compaction baseline is versioned: for catalogue prompts it substitutes
the complete original request/checks/typed Observations for the compact context,
keeping the exact same system and control strings. It is a measured counterfactual,
not an estimate of token usage or a claim about old protocol wire sizes. Legacy
prompts are measured as-is. Unknown fine-grained savings remain null.
"""
from copy import deepcopy
import json
import re

from ..errors import ValidationError
from ..models import canonical_json, digest
from .dynamic_contracts import DynamicRequest, required_checks, text_bytes


SCHEMA = "context-telemetry/v1"
CONTEXT_LIMIT_BYTES = 12000


def _bytes(value):
    return text_bytes(canonical_json(value))


def _text(value, *, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_./:-]{1,128}", value) is None:
        raise ValidationError("invalid context telemetry identity or category")


def _tokens(input_tokens, output_tokens, total_tokens):
    values = (input_tokens, output_tokens, total_tokens)
    if any(value is not None and (type(value) is not int or value < 0) for value in values):
        raise ValidationError("invalid context telemetry token receipt")
    if all(value is not None for value in values) and input_tokens + output_tokens != total_tokens:
        raise ValidationError("context telemetry token receipt does not add up")


def build_context_telemetry(messages, metadata, observations, request, *, run_id,
                            parent_run_id=None, child_run_id=None, agent_role="single",
                            domain="research", turn_id, route_type="dynamic_single",
                            parallel_group_id=None, parallel_width=1, limit_bytes=CONTEXT_LIMIT_BYTES,
                            model_dispatched=False, context_budget_exceeded=False,
                            status="prepared", stop_reason=None, input_tokens=None,
                            output_tokens=None, total_tokens=None):
    """Measure exact supplied wire and canonical counts without changing either.

    Fine-grained byte buckets count canonical serialized values (excluding JSON
    key/separator framing). They need not sum to total_context_bytes; the framing
    remainder is explicitly reported. Claim is the repository's numeric Fact
    object, so the two count fields deliberately agree.
    """
    for value in (run_id, agent_role, domain, route_type, status):
        _text(value)
    for value in (parent_run_id, child_run_id, parallel_group_id, stop_reason):
        _text(value, nullable=True)
    if (not isinstance(request, DynamicRequest) or type(metadata) is not dict
            or type(messages) is not list or len(messages) != 2
            or type(turn_id) is not int or turn_id < 1
            or type(parallel_width) is not int or not 1 <= parallel_width <= 2
            or type(limit_bytes) is not int or not 1 <= limit_bytes <= CONTEXT_LIMIT_BYTES
            or type(model_dispatched) is not bool or type(context_budget_exceeded) is not bool):
        raise ValidationError("invalid context telemetry measurement")
    if (any(type(message) is not dict or set(message) != {"role", "content"}
            or type(message["content"]) is not str for message in messages)
            or [message["role"] for message in messages] != ["system", "user"]):
        raise ValidationError("invalid context telemetry messages")
    _tokens(input_tokens, output_tokens, total_tokens)
    try:
        payload = json.loads(messages[1]["content"])
    except (ValueError, TypeError):
        raise ValidationError("context telemetry requires a structured model view") from None
    if type(payload) is not dict or type(payload.get("control")) is not dict:
        raise ValidationError("context telemetry requires typed control")
    after = sum(text_bytes(message["content"]) for message in messages)
    if metadata.get("bytes") != after or metadata.get("message_sha256") != digest(messages):
        raise ValidationError("context telemetry differs from the prepared wire")
    if context_budget_exceeded != (after > limit_bytes):
        raise ValidationError("context telemetry overflow flag differs from measured wire")
    if model_dispatched and context_budget_exceeded:
        raise ValidationError("an over-budget context cannot be dispatched")

    observations = list(observations)
    derived = [observation for observation in observations if observation.get("kind") == "derived"]
    latest = next((observation for observation in derived if observation["tool"] == "hypotheses"),
                  derived[0] if derived else None)
    all_facts = latest["facts"] if latest else {}
    all_evidence = latest["evidence"] if latest else {}
    context = payload.get("context")
    dedup_saved = lazy_saved = None
    if type(context) is dict:
        from .dynamic_context import build_catalog, encode_view, expand_view, view_catalog
        expanded = expand_view(context)
        before_payload = deepcopy(payload)
        before_payload["context"] = {"request": request.to_dict(), "observations": observations,
                                     "required_checks": required_checks(request)}
        before = text_bytes(messages[0]["content"]) + _bytes(before_payload)
        baseline = "same_system_control_full_typed_catalog_payload/v1"
        dedup_saved = _bytes(expanded) - _bytes(context)
        # Measure only the Evidence table disclosure difference at the same stage,
        # rather than changing controls or allowing telemetry to choose an action.
        catalog = build_catalog(request, sorted(observations, key=lambda item: item["tool"]),
                                required_checks(request), scope="telemetry-measurement",
                                run_id="0" * 32)
        full = expand_view(view_catalog(catalog, scope="telemetry-measurement", run_id="0" * 32,
                                       current_stage="verification"))
        full_current = deepcopy(expanded)
        full_current["evidence"] = full["evidence"]
        full_wire = encode_view(full_current)
        if context.get("schema") == "dynamic-context-view/v2":
            from .dynamic_context_metadata import encode_metadata_view
            full_wire = encode_metadata_view(full_wire)
        lazy_saved = _bytes(full_wire) - _bytes(context)
        visible_facts, visible_evidence = len(context["facts"]), len(context["evidence"])
        scope_value = context["range"]
        facts_value = context["facts"]
        evidence_value = {"catalog_ids": context["catalog_ids"]["evidence"],
                          "evidence": context["evidence"]}
        observations_value = {key: context[key] for key in ("observations", "source_datasets", "verification", "gaps")}
        schema_value = {key: context[key] for key in ("schema", "columns", "symbols", "gap_table")}
        if context.get("schema") == "dynamic-context-view/v2":
            schema_value["list_table"] = context["list_table"]
    else:
        before = after
        baseline = "legacy_exact_wire/v1"
        state = payload.get("derived_state") or {}
        visible_facts, visible_evidence = len(state.get("facts", {})), len(state.get("evidence", {}))
        scope_value = {key: payload[key] for key in ("security", "cutoff", "pit_mode", "objective", "bound_windows") if key in payload}
        facts_value = state.get("facts", {})
        evidence_value = state.get("evidence", {})
        observations_value = payload.get("observations", [])
        schema_value = payload.get("protocol_version", "single-dynamic-v1")
    system_bytes = text_bytes(messages[0]["content"])
    buckets = {
        "system_bytes": system_bytes,
        "question_bytes": _bytes(payload["control"].get("question", "")),
        "plan_bytes": _bytes(payload["control"].get("plan", [])),
        "schema_bytes": _bytes(schema_value),
        "scope_metadata_bytes": _bytes(scope_value),
        "facts_bytes": _bytes(facts_value),
        # Fact and Claim are the same canonical objects; avoid counting twice.
        "claims_bytes": 0,
        "evidence_refs_bytes": _bytes(evidence_value),
        "observations_bytes": _bytes(observations_value),
        "delegation_results_bytes": _bytes(payload.get("delegation_results", [])),
        "other_control_bytes": _bytes({key: value for key, value in payload["control"].items()
                                         if key not in {"question", "plan"}}),
    }
    saved = before - after
    return {
        "schema": SCHEMA, "run_id": run_id, "parent_run_id": parent_run_id,
        "child_run_id": child_run_id, "agent_role": agent_role, "domain": domain,
        "turn_id": turn_id, "route_type": route_type,
        "parallel_group_id": parallel_group_id, "parallel_width": parallel_width,
        "context_limit_bytes": limit_bytes,
        "context_before_compaction_bytes": before, "context_after_compaction_bytes": after,
        "total_context_bytes": after, "context_saved_bytes": saved,
        "context_saved_ratio": saved / before if before else 0,
        "before_compaction_baseline": baseline,
        "byte_bucket_semantics": "serialized_values_without_key_separator_framing/v1",
        **buckets, "unbucketed_framing_bytes": after - sum(buckets.values()),
        "visible_fact_count": visible_facts, "visible_claim_count": visible_facts,
        "visible_evidence_count": visible_evidence,
        "total_fact_count": len(all_facts), "total_claim_count": len(all_facts),
        "total_evidence_count": len(all_evidence),
        "dedup_saved_bytes": dedup_saved,
        "reference_compaction_saved_bytes": None,
        "observation_externalization_saved_bytes": None,
        "lazy_disclosure_saved_bytes": lazy_saved,
        "control_text_saved_bytes": None,
        "input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens,
        "model_dispatched": model_dispatched, "context_budget_exceeded": context_budget_exceeded,
        "status": status, "stop_reason": stop_reason, "message_sha256": digest(messages),
    }


def telemetry_result(record, *, model_dispatched, status, stop_reason=None,
                     input_tokens=None, output_tokens=None, total_tokens=None):
    """Return a receipt update; preserve the immutable prepared measurement."""
    if type(record) is not dict or record.get("schema") != SCHEMA or type(model_dispatched) is not bool:
        raise ValidationError("invalid prepared context telemetry")
    _text(status)
    _text(stop_reason, nullable=True)
    _tokens(input_tokens, output_tokens, total_tokens)
    if model_dispatched and record.get("context_budget_exceeded"):
        raise ValidationError("an over-budget context cannot be dispatched")
    return {**deepcopy(record), "model_dispatched": model_dispatched, "status": status,
            "stop_reason": stop_reason, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "total_tokens": total_tokens}


def overflow_context_telemetry(request, available_tools, observations, checks, plan, *,
                               max_bytes=CONTEXT_LIMIT_BYTES, message_kwargs=None, **lineage):
    """Measure a rejected wire only; never return messages for dispatch.

    A measurement-only reconstruction bypasses the builder's exception so a
    rejected turn has exact byte telemetry. The execution cap remains max_bytes;
    the reconstructed messages cannot escape this function.
    """
    from .dynamic_protocol import dynamic_messages
    messages, metadata = dynamic_messages(request, available_tools, observations, checks, plan,
                                          4_000_000, **(message_kwargs or {}))
    return build_context_telemetry(messages, metadata, observations, request, limit_bytes=max_bytes,
        model_dispatched=False, context_budget_exceeded=True, status="context_budget_exceeded",
        stop_reason="dynamic_context_budget_exceeded", **lineage)
