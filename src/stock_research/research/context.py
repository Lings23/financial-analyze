"""Deterministic, lossless bounded model view. Source text is never a prompt."""
from ..errors import ValidationError
from ..models import canonical_json, digest
from .selection import selection_options


SYSTEM_V1 = ('Select up to three fact IDs as highlights and up to three hypothesis IDs for review. '
          'All statuses and tests are supplied and cannot be changed. Support is descriptive, never causal. '
          'Return only JSON: {"highlights":["F1"],"hypotheses":["financial_deterioration"],'
          '"assessment":"descriptive_research_only"}. Use only supplied IDs; no prose, numbers, tools or recommendations.')

SYSTEM_V2 = ('Select one to three supplied fact IDs and one to three supplied hypothesis IDs. '
          'When both market and financial facts exist, include at least one from each. '
          'Prefer hypotheses whose status is supported, unsupported or conflicted over insufficient; '
          'include a cited supporting or counterevidence fact for at least one chosen decisive test. '
          'Do not select equal revenue and total_revenue aliases for the same unit and period. '
          'For event_review include event_chronology even when its evidence is insufficient. '
          'All supplied statuses, numeric values and causal limits are fixed. Support is descriptive, never causal. '
          'Return only JSON: {"highlights":["F1"],"hypotheses":["financial_deterioration"],'
          '"assessment":"descriptive_research_only"}. Use only supplied IDs; no prose, numbers, tools or recommendations.')

SYSTEM = ('Choose the most useful complete evidence bundle from selection_options. '
          'Return exactly ONE of those JSON objects, copied without changes. '
          'Do not return the option index, a surrounding list, markdown or explanations. '
          'The bundles already include available market/financial coverage and the cited evidence '
          'of their selected tests. All facts, hypotheses and counterevidence remain in the report. '
          'The supplied statuses are fixed descriptive results; never infer causation or recommendations.')


def study_messages(computed, request, max_bytes, *, version="single-research-v3"):
    # Full source binding/version identities remain in the local Evidence store. The model
    # receives references and fixed typed fields; provider-controlled IDs are hashed.
    aliases = {eid: f"E{i+1}" for i, eid in enumerate(sorted(computed["evidence"]))}
    facts = {f"F{i+1}": {**{k: f[k] for k in ("name", "value", "unit", "window", "available_at")},
                           "evidence_ids": [aliases[e] for e in f["inputs"]]}
             for i, f in enumerate(computed["facts"])}
    used = {e for f in computed["facts"] for e in f["inputs"]}
    evidence = {aliases[e]: {**{k: computed["evidence"][e][k] for k in
                               ("metric", "value", "unit", "period", "basis", "available_at", "availability_basis")},
                            "source_version_ref": digest({k: computed["evidence"][e][k] for k in
                                ("provider", "provider_version", "revision_id", "snapshot", "record_id")})}
                for e in sorted(used)}
    fid = {f["id"]: f"F{i+1}" for i, f in enumerate(computed["facts"])}
    hypotheses = {h["id"]: {k: h[k] for k in ("status", "reason", "conclusion_strength")} |
                  {"claim_ids": [fid[c] for c in h["claim_ids"]],
                   "counterevidence_claim_ids": [fid[c] for c in h["counterevidence_claim_ids"]]}
                  for h in computed["hypotheses"]}
    anchor = {k: computed["event_anchor"][k] for k in
              ("status", "reason", "precision", "boundary_date", "release_date", "disclosed_at")
              if k in computed["event_anchor"]}
    payload = {"security": request.security.canonical_symbol, "cutoff": request.as_of.isoformat(),
               "pit_mode": request.mode.value, "objective": request.objective,
               "facts": facts, "evidence": evidence, "hypotheses": hypotheses,
               "event_anchor": anchor, "coverage": "not_verified", "causal_claim": False}
    if version not in {"single-research-v1", "single-research-v2", "single-research-v3", "single-research-v4", "single-research-v5"}:
        raise ValidationError("unknown study instruction version")
    # v4 adds local structured diagnostics, retaining the v3 model selection contract.
    system = {"single-research-v1":SYSTEM_V1,"single-research-v2":SYSTEM_V2,
              "single-research-v3":SYSTEM,"single-research-v4":SYSTEM,"single-research-v5":SYSTEM}[version]
    if version in {"single-research-v3", "single-research-v4", "single-research-v5"}:
        payload['selection_options'] = selection_options(computed, request)
        if not payload['selection_options']:
            raise ValidationError("no complete bounded selection candidate")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": canonical_json(payload)}]
    size = sum(len(m["content"].encode("utf-8")) for m in messages)
    if size > max_bytes:
        raise ValidationError("study context exceeds lossless byte budget")
    return messages, {"strategy": "typed_reference_view_no_source_text", "bytes": size,
                      "byte_budget": max_bytes, "message_sha256": digest(messages),
                      "facts_included": len(facts), "evidence_included": len(evidence),
                      "hypotheses_included": len(hypotheses), "source_bodies_included": 0,
                      "omitted_claims": 0}
