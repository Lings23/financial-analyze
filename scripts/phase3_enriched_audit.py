"""Same 25 securities, unchanged five tests, newly observed domain supplements.

Offline only. Original requests, cutoffs, scores and snapshots remain immutable.
Fresh-process replay reauthorizes both original archive and supplemental sources.
"""
import argparse
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta
from fractions import Fraction
import json
from pathlib import Path

from accept_phase2_real import read_inputs, write
from phase3_archive_quality import replay_projection
from phase3_followup import independent_expected, sha, verify_expected
from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.models import AccessContext, DataRecord, PITMode, QueryContext, digest
from stock_research.providers.base import ProviderRegistry
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.contracts import Binding
from stock_research.research.report import markdown
from stock_research.research.scoped import ScopedReadService, SourceGrant
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudyRequest, StudySpec
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.memory import MemoryRepository
from phase3_benchmark_gate import precheck_cases, require_valid_precheck


ROOT = Path('.artifacts/phase3/fullscope-20261003')
CAPTURE = ROOT / 'domains'
ORIGINAL = Path('.artifacts/phase3/quality-20261002/proposed-model-manifest.json')
PREVIOUS = Path('.artifacts/phase3/followup-20261002/v3/live')
SCOPE = 'phase3-fullscope-supplement-20261003'
SPEC = StudySpec(context_bytes=24000, max_tokens=28000)
DOMAINS = ('adjustment_factor', 'financial_cashflow', 'index_daily')


def captured_service():
    saved = json.loads((CAPTURE / 'result.json').read_bytes())
    plan = json.loads((CAPTURE / 'plan.json').read_bytes())
    assert saved['plan_sha256'] == sha(CAPTURE / 'plan.json')
    assert plan['source_manifest_sha256'] == sha(ORIGINAL)
    assert len(saved['results']) == len(plan['queries']) == 51
    assert saved['provider_stats']['attempts'] == 51 and saved['provider_stats']['retries'] == 0
    repo = MemoryRepository()
    for i, item in enumerate(saved['results'], 1):
        assert item == json.loads((CAPTURE / f'capture-{i}.json').read_bytes())
        assert item['query'] == plan['queries'][i-1]
        assert json.loads((CAPTURE / f'intent-{i}.json').read_bytes())['query'] == item['query']
        if item['status'] != 'captured':
            raise IntegrityError('supplemental source unavailable; keep the original case')
        rows = tuple(DataRecord.from_dict(r) for r in item['records'])
        if repo.commit(saved['scope'], rows).snapshot_id != item['snapshot']:
            raise IntegrityError('supplemental snapshot differs')
    return (DataService(ProviderRegistry(), None, repo, ArtifactStore(CAPTURE / 'artifacts')),
            AccessContext(saved['scope'], frozenset({'tushare'})), saved)


def source_context(case, captured):
    svc, access = replay_projection(case['original']['projection_path'], case['original']['projection_sha256'])
    original = StudyRequest.from_dict(case['original']['request'])
    old_data = read_inputs(svc, original, access)
    assert digest({k: [r.to_dict() for r in v] for k, v in old_data.items()}) == case['original']['input_hash']
    request = StudyRequest.from_dict(case['request'])
    grants = []
    for b in request.bindings:
        owner, owner_access = (captured[0], captured[1]) if b.dataset in DOMAINS else (svc, access)
        grants.append(SourceGrant(owner, owner_access, b.snapshot, request.data_request(b), b.provider))
    return ScopedReadService(SCOPE, lambda: tuple(grants)), AccessContext(SCOPE, frozenset({'tushare'})), old_data


def expectations(data, request):
    values, hypotheses, anchor = independent_expected(data, request)
    return {'values': {k: [v.numerator, v.denominator] for k, v in values.items()},
            'hypotheses': hypotheses, 'anchor': anchor}


def verify(report, expected):
    verify_expected(report, {k: Fraction(*v) for k, v in expected['values'].items()},
                    expected['hypotheses'], expected['anchor'])
    assert report['model']['status'] == 'disabled'


def prepare():
    if (ROOT / 'enriched-manifest.json').exists():
        raise IntegrityError('manifest is immutable; use a new benchmark location')
    output = ROOT / 'enriched-prepare'
    output.mkdir(parents=True, exist_ok=False)
    captured = captured_service()
    cutoff = datetime.fromisoformat(captured[2]['finished_at']) + timedelta(microseconds=1)
    originals = [c for c in json.loads(ORIGINAL.read_bytes())['cases'] if c['kind'] == 'real_archived_income_projection']
    assert len(originals) == 25
    cases = []
    for old in originals:
        original = StudyRequest.from_dict(old['request'])
        extra = [r for r in captured[2]['results'] if r['query']['case'] in {old['id'], 'shared-benchmark'}]
        assert len(extra) == 3
        bindings = original.bindings + tuple(Binding(r['query']['dataset'], r['snapshot'], 'tushare',
                    date.fromisoformat(r['query']['start']), date.fromisoformat(r['query']['end'])) for r in extra)
        request = replace(original, as_of=cutoff, bindings=bindings, benchmark='000300.SH')
        assert request.hypotheses == original.hypotheses and request.event_record_id == original.event_record_id
        case = {'id': old['id'], 'original': old, 'request': request.to_dict()}
        cases.append(case)
    precheck = precheck_cases(cases, lambda case: source_context(case, captured)[:2])
    write(output / 'contract-precheck.json', precheck)
    require_valid_precheck(cases, precheck)
    for case in cases:
        old = case['original']
        original = StudyRequest.from_dict(old['request'])
        request = StudyRequest.from_dict(case['request'])
        svc, access, old_data = source_context(case, captured)
        data = read_inputs(svc, request, access)
        for dataset, rows in old_data.items():
            assert data[dataset] == rows
        expected = expectations(data, request)
        old_expected = expectations(old_data, original)
        assert all(expected['values'][k] == v for k, v in old_expected['values'].items())
        previous = json.loads((PREVIOUS / (old['id'] + '.json')).read_bytes())
        assert digest(previous['facts']) == old['facts_hash']
        case.update(expected=expected, original_hypotheses=old_expected['hypotheses'],
                    input_hash=digest({k: [r.to_dict() for r in v] for k, v in data.items()}),
                    previous_report_sha256=sha(PREVIOUS / (old['id'] + '.json')))
        # Commit the independent arithmetic and unchanged original inputs before Runtime.
        write(output / (old['id'] + '-expected.json'), case)
        report = StudyRuntime(svc, CheckpointStore(output / 'runs'), spec=SPEC).run(request, access)
        verify(report, expected)
        case.update(facts_hash=digest(report['facts']), hypotheses_hash=digest(report['hypotheses']),
                    anchor_hash=digest(report['event_anchor']))
        write(output / (old['id'] + '.json'), report)
        (output / (old['id'] + '.md')).write_text(markdown(report), encoding='utf-8')
    manifest = {'kind': 'new_cutoff_supplement_same_original_25_securities', 'spec': {
                    'version': SPEC.version, 'context_bytes': SPEC.context_bytes, 'max_tokens': SPEC.max_tokens},
                'original_manifest_sha256': sha(ORIGINAL), 'capture_sha256': sha(CAPTURE / 'result.json'),
                'original_scores_modified': False, 'model_dispatches': 0, 'provider_network_calls': 0,
                'cases': cases, 'benchmark_contract_version':'benchmark-contract/v1',
                'contract_precheck_sha256':digest(precheck)}
    write(ROOT / 'enriched-manifest.json', manifest)
    print(json.dumps({'cases': len(cases), 'manifest_sha256': sha(ROOT / 'enriched-manifest.json'),
                      'new_cutoff': cutoff.isoformat(), 'new_model_dispatches': 0}))


def audit(output):
    path = ROOT / 'enriched-manifest.json'
    manifest = json.loads(path.read_bytes())
    assert manifest['original_manifest_sha256'] == sha(ORIGINAL)
    assert manifest['capture_sha256'] == sha(CAPTURE / 'result.json')
    output.mkdir(parents=True, exist_ok=False)
    captured = captured_service()
    results = []
    for case in manifest['cases']:
        svc, access, _ = source_context(case, captured)
        request = StudyRequest.from_dict(case['request'])
        data = read_inputs(svc, request, access)
        assert digest({k: [r.to_dict() for r in v] for k, v in data.items()}) == case['input_hash']
        assert expectations(data, request) == case['expected']
        runtime = StudyRuntime(svc, CheckpointStore(output / 'runs'), spec=StudySpec(**manifest['spec']))
        report = runtime.run(request, access)
        verify(report, case['expected'])
        assert digest(report['facts']) == case['facts_hash']
        assert digest(report['hypotheses']) == case['hypotheses_hash']
        assert digest(report['event_anchor']) == case['anchor_hash']
        assert runtime.run(request, access, resume=report['run_id']) == report
        current = svc.current_grants
        grants = current()
        for i in range(len(grants)):
            svc.current_grants = lambda i=i: grants[:i] + grants[i+1:]
            try:
                runtime.run(request, access, resume=report['run_id'])
            except PermissionDenied:
                pass
            else:
                raise AssertionError('source grant revocation did not block replay')
        svc.current_grants = current
        original = StudyRequest.from_dict(case['original']['request'])
        pit_checks = 0
        for b in request.bindings:
            if b.dataset not in DOMAINS:
                continue
            before = min(r.available_at for r in data[b.dataset]) - timedelta(microseconds=1)
            for cutoff in (original.as_of, before):
                for mode in (PITMode.PUBLIC, PITMode.SYSTEM):
                    assert not svc.query(request.data_request(b), QueryContext(access, b.snapshot, cutoff, mode)).records
                    pit_checks += 1
        previous_path = PREVIOUS / (case['id'] + '.json')
        assert sha(previous_path) == case['previous_report_sha256']
        rows = {r.record_id: r for values in data.values() for r in values}
        for ev in report['evidence'].values():
            row = rows[ev['record_id']]
            metric = next(m for m in row.metrics if m.name == ev['metric'])
            assert ev['value'] == (None if metric.value is None else str(metric.value))
            assert ev['unit'] == metric.unit and tuple(ev['artifact_ids']) == row.artifact_ids
            assert ev['provider_call_id'] == row.provider_call_id
            assert ev['snapshot'] == next(b.snapshot for b in request.bindings if b.dataset == row.dataset.value)
        write(output / (case['id'] + '.json'), report)
        (output / (case['id'] + '.md')).write_text(markdown(report), encoding='utf-8')
        results.append({'case': case['id'], 'research_status': report['research_status'],
                        'numeric_claims': len(report['facts']), 'evidence': len(report['evidence']),
                        'original_hypotheses': case['original_hypotheses'],
                        'supplemental_hypotheses': case['expected']['hypotheses'],
                        'remaining_gaps': {h['id']: h['reason'] for h in report['hypotheses'] if h['status'] == 'insufficient'},
                        'unchanged_original_inputs_and_scores': True, 'replay_identical': True,
                        'grant_revocations_denied': len(grants), 'pit_checks': pit_checks})
    original_states = Counter(v for c in results for v in c['original_hypotheses'].values())
    supplemental_states = Counter(v for c in results for v in c['supplemental_hypotheses'].values())
    missing = Counter(h for c in results for h in c['remaining_gaps'])
    result = {'manifest_sha256': sha(path), 'tasks': len(results), 'hypotheses': sum(original_states.values()),
              'original_hypothesis_states': dict(original_states), 'supplemental_hypothesis_states': dict(supplemental_states),
              'remaining_insufficient_by_hypothesis': dict(missing),
              'completed_tasks': sum(c['research_status'] == 'tests_completed' for c in results),
              'numeric_claims_verified': sum(c['numeric_claims'] for c in results),
              'evidence_verified': sum(c['evidence'] for c in results), 'identical_replays': len(results),
              'grant_revocations_denied': sum(c['grant_revocations_denied'] for c in results),
              'pit_checks': sum(c['pit_checks'] for c in results), 'model_dispatches': 0, 'provider_network_calls': 0,
              'original_scores_modified': False, 'general_phase3_quality_certified': False,
              'expert_reference_available': False, 'cases': results}
    write(output / 'result.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare', action='store_true')
    action.add_argument('--audit', type=Path)
    args = parser.parse_args()
    if args.prepare:
        prepare()
    else:
        audit(args.audit)
