"""Classify remaining original-task gaps from authorized immutable inputs."""
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import argparse
import json
from pathlib import Path

from accept_phase2_real import read_inputs, write
from phase3_enriched_audit import ROOT, ORIGINAL, PREVIOUS, captured_service, source_context
from phase3_followup import sha
from stock_research.models import digest
from stock_research.research.study_contracts import StudyRequest


def audit(output):
    manifest = json.loads((ROOT / 'enriched-manifest.json').read_bytes())
    captured = captured_service()
    rows = []
    for case in manifest['cases']:
        svc, access, _ = source_context(case, captured)
        request = StudyRequest.from_dict(case['request'])
        data = read_inputs(svc, request, access)
        assert digest({k: [r.to_dict() for r in v] for k, v in data.items()}) == case['input_hash']
        gaps = []
        for hid, state in case['expected']['hypotheses'].items():
            if state != 'insufficient':
                continue
            detail = {'hypothesis': hid}
            if hid == 'event_chronology':
                assert request.event_record_id is None
                detail.update(reason='original_request_has_no_event_record_id',
                              resolution='explicit event identity, qualified release evidence and matching pre/post prices; choosing an arbitrary filing changes the task')
            elif hid == 'financial_deterioration':
                latest = max(data['financial_income'], key=lambda r: r.period)
                prior_date = date(latest.period.year-1, latest.period.month, latest.period.day)
                prior = next((r for r in data['financial_income'] if r.period == prior_date), None)
                bases = []
                for name in ('revenue', 'net_income_parent'):
                    now = next(m.value for m in latest.metrics if m.name == name)
                    base = None if prior is None else next(m.value for m in prior.metrics if m.name == name)
                    if now is None or base is None or base <= 0:
                        bases.append({'field': name, 'current': None if now is None else str(now),
                                      'base': None if base is None else str(base),
                                      'base_record': None if prior is None else prior.record_id})
                assert bases
                detail.update(reason='missing_or_nonpositive_yoy_input', inputs=bases,
                              resolution='missing input needs qualified source; a nonpositive base cannot satisfy the unchanged positive-base yoy contract')
            else:
                prices = sorted(data['market_daily'], key=lambda r: r.period)
                closes = [next(m.value for m in r.metrics if m.name == 'close') for r in prices]
                stock_dates = [r.period.isoformat() for r in prices]
                if len(prices) < 2 or any(v is None or v <= 0 for v in closes):
                    detail.update(reason='insufficient_valid_visible_closes', stock_dates=stock_dates,
                                  closes=[None if v is None else str(v) for v in closes],
                                  resolution='real valid observations for the unchanged window; do not invent prices or trim the task')
                elif hid == 'market_direction':
                    index_dates = sorted(r.period.isoformat() for r in data['index_daily'])
                    if stock_dates != index_dates:
                        detail.update(reason='exact_date_alignment_missing', stock_dates=stock_dates, index_dates=index_dates,
                                      stock_missing_dates=sorted(set(index_dates)-set(stock_dates)),
                                      resolution='legitimate missing observations or a separately approved different comparison rule; no forward-fill or silent intersection')
                    else:
                        detail.update(reason='zero_change_has_no_direction')
                else:
                    raise AssertionError('unexpected factor gap needs diagnosis')
            gaps.append(detail)
        rows.append({'case': case['id'], 'gaps': gaps})
    originals = json.loads(ORIGINAL.read_bytes())
    events = []
    for case in originals['cases']:
        if case['kind'] == 'real_archived_income_projection':
            continue
        report_path = PREVIOUS / (case['id'] + '.json')
        report = json.loads(report_path.read_bytes())
        assert report['event_anchor']['status'] == 'verified'
        assert report['research_status'] == 'evidence_incomplete'
        request = StudyRequest.from_dict(case['request'])
        released = date.fromisoformat(report['event_anchor']['release_date'])
        first_possible_post_close = datetime.combine(released + timedelta(days=1), time(15), timezone(timedelta(hours=8)))
        market = next(b for b in request.bindings if b.dataset == 'market_daily')
        events.append({'case': case['id'], 'request': case['request'], 'report_sha256': sha(report_path),
                       'reason': 'no_qualified_pre_and_post_prices_visible_at_original_cutoff',
                       'bound_market_provider': market.provider, 'release_date': released.isoformat(),
                       'earliest_possible_post_close': first_possible_post_close.isoformat(),
                       'cutoff_precedes_any_possible_post_close': request.as_of < first_possible_post_close,
                       'market_window_ends_before_any_post_close': market.end <= released,
                       'resolution': 'actual historical price-version publication proof; current observations cannot be backdated'})
    assert len(events) == 4
    result = {'manifest_sha256': sha(ROOT / 'enriched-manifest.json'), 'audit_script_sha256': sha(__file__),
              'supplemental_25_remaining_gaps': sum(len(r['gaps']) for r in rows),
              'reason_counts': dict(Counter(g['reason'] for r in rows for g in r['gaps'])),
              'original_event_tasks_unresolved': len(events),
              'independent_expert_reference': 'user explicitly reports none',
              'full_goal_completed': False, 'model_or_provider_dispatches': 0,
              'cases': rows, 'historical_events': events}
    write(output, result)
    print(json.dumps({k: v for k, v in result.items() if k not in {'cases', 'historical_events'}}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'remaining-gaps-rechecked.json')
    audit(parser.parse_args().output)
