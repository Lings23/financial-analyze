"""Bounded candidate construction from verified IDs, before model selection.

The model ranks complete evidence bundles. This is an explicit product contract,
not post-hoc repair of a model answer or a change to the acceptance rubric.
"""
from decimal import Decimal


def selection_options(computed, request):
    facts = computed['facts']
    aliases = {f['id']: f'F{i+1}' for i,f in enumerate(facts)}
    by_id = {f['id']: f for f in facts}
    market = lambda f: f['name'].startswith('observed_') or f['name'] in {
        'factor_adjusted_price_change','benchmark_price_change','price_change_difference','event_observed_price_change'}
    financial = lambda f: f['name'].startswith('financial_') or f['name'].endswith('_yoy')
    hypotheses = computed['hypotheses']
    decisive = [h for h in hypotheses if h['status'] != 'insufficient']
    if request.objective == 'event_review':
        focuses = [h for h in hypotheses if h['id']=='event_chronology']
        # If the event lacks evidence but another test is decisive, retain both.
        extra = decisive[:1] if focuses[0]['status']=='insufficient' else []
    else:
        focuses = decisive or hypotheses[:1]
        extra = []
    options = []
    for focus in focuses:
        selected = list(dict.fromkeys(c for h in [focus,*extra] for c in h['claim_ids']))
        for predicate in (market, financial):
            if not any(predicate(by_id[c]) for c in selected):
                candidate = next((f['id'] for f in facts if predicate(f)), None)
                if candidate: selected.append(candidate)
        if not selected and facts: selected.append(facts[0]['id'])
        if not 1 <= len(selected) <= 3: continue
        chosen = [by_id[c] for c in selected]
        duplicate_revenue = any({a['name'],b['name']} == {'financial_income.revenue','financial_income.total_revenue'}
                                and Decimal(a['value'])==Decimal(b['value']) and a['window']==b['window'] and a['unit']==b['unit']
                                for i,a in enumerate(chosen) for b in chosen[i+1:])
        if duplicate_revenue: continue
        options.append({'highlights':[aliases[c] for c in selected],
                        'hypotheses':list(dict.fromkeys(h['id'] for h in [focus,*extra])),
                        'assessment':'descriptive_research_only'})
    return options
