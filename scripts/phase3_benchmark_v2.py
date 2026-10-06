"""New immutable Phase 3 capability campaign. No old request or score is rewritten.

prepare -> freeze -> plan-dispatch -> live is an explicit one-way protocol.
The fixed source roster is reused validation material, never claimed to be blind.
"""
import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

from phase3_contract_audit import FrozenSources, ROOT, read, sha
from phase3_benchmark_gate import snapshot_metadata, write_new
from phase3_benchmark_v2_contract import VERSION, DATE_ALIGNMENT, validate_cases, freeze_benchmark
from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.models import AccessContext, QueryContext, digest, utcnow
from stock_research.research.scoped import ScopedReadService, SourceGrant
from stock_research.research.study_contracts import StudyRequest, StudySpec
from stock_research.research.study import StudyRuntime
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.context import study_messages
from stock_research.research.report import markdown
from stock_research.model_adapters.chat import ChatHTTPTransport, ChatModelAdapter, load_model_config

OUT = ROOT / '.artifacts/phase3/benchmark-v2-20261004'
PLANNING = ROOT / '.artifacts/phase3/benchmark-v2-20261004-planning'
SPEC = StudySpec(version='single-research-v5', context_bytes=24000, max_tokens=28000)
CUTOFF = '2026-10-04T00:00:00+08:00'
RULES = {
    'mechanical_adjustment': 'Complete aligned positive factors: differing endpoint factors => supported, equal => unsupported; otherwise lawful insufficient with exact input-based diagnosis.',
    'market_direction': 'Exact full-date alignment, nonzero changes: same sign => supported, opposite => unsupported; zero/missing/unmatched => insufficient; never interpolate.',
    'financial_deterioration': 'Same-period positive-base revenue and parent profit YoY: both negative supported, one negative conflicted, neither unsupported; unavailable/nonpositive input => explicit insufficient, never zero-fill.',
    'cashflow_divergence': 'Same cumulative consolidated period: positive parent profit with negative operating cashflow supported, otherwise unsupported; missing/unequal periods insufficient.',
    'absolute_profit_change': 'profit-change/v1: current same-period parent profit minus prior-year parent profit, signed CNY; >0 supported, <=0 unsupported; missing input insufficient. Never divide by nonpositive base.',
    'event_chronology': 'Exact pinned qualified event/version and real strictly before/after closes => supported; no causal impact assertion.',
}


class CampaignSources:
    def __init__(self):
        self.frozen = FrozenSources()
        self.paths = {}
        for base in self.frozen.service.artifacts.stores:
            # ReadArtifactStores stores ArtifactStore objects, not paths.
            for path in base.root.rglob('*'):
                if path.is_file():
                    self.paths.setdefault(path.name, path)

    def context(self, case):
        request = StudyRequest.from_dict(case['request'])
        grants = []
        for binding in request.bindings:
            owner = case['source_scopes'][binding.dataset]
            if (owner, binding.snapshot) not in self.frozen.snapshots:
                raise IntegrityError('new case references unknown immutable snapshot')
            grants.append(SourceGrant(self.frozen.service, AccessContext(owner, frozenset({binding.provider})),
                binding.snapshot, request.data_request(binding), binding.provider))
        return ScopedReadService(case['scope'], lambda: tuple(grants)), AccessContext(case['scope'],
            frozenset(binding.provider for binding in request.bindings))

    def inputs(self, case):
        service, access = self.context(case)
        request = StudyRequest.from_dict(case['request'])
        datasets, metadata, paths, snapshots = {}, {}, {}, {}
        for binding in request.bindings:
            narrowed = AccessContext(access.scope, frozenset({binding.provider}))
            context = QueryContext(narrowed, binding.snapshot, request.as_of, request.mode)
            result = service.query(request.data_request(binding), context)
            datasets[binding.dataset] = {'provider': binding.provider, 'snapshot': binding.snapshot,
                                         'records': [row.to_dict() for row in result.records]}
            metadata[binding.dataset] = snapshot_metadata(service, request, binding, narrowed)
            owner = metadata[binding.dataset]['owner_scope']
            members = self.frozen.repository.read(owner, binding.snapshot)
            snapshots[(owner, binding.snapshot)] = {'owner_scope': owner, 'snapshot': binding.snapshot,
                'record_ids': sorted({row.record_id for row in members}), 'records': [row.to_dict() for row in members]}
            for row in members:
                for artifact_id in row.artifact_ids:
                    p = self.paths[artifact_id]
                    if sha(p) != artifact_id:
                        raise IntegrityError('raw source hash differs')
                    paths[artifact_id] = p.relative_to(ROOT).as_posix()
        return {'schema': 'phase3-frozen-authorized-inputs/v2', 'case_id': case['id'],
            'request': case['request'], 'scope': access.scope, 'datasets': datasets,
            'binding_metadata': metadata, 'artifact_paths': paths, 'snapshots': list(snapshots.values())}


def candidate(identity, level, question, request, owners, *, stratum, event=None,
              mandatory=None, diagnostics=None, allow_insufficient=False):
    if 'absolute_profit_change' in request['hypotheses']:
        request['hypothesis_version'] = 'profit-change/v1'
    expected = {'hypotheses': {hid: {'rule': RULES[hid],
                'permitted_statuses': ['supported', 'unsupported', 'conflicted', 'insufficient'],
                'insufficient_allowed_only_when': ('independent frozen source oracle proves the declared data/precondition limitation'
                    if allow_insufficient else 'no expected insufficiency; missing a checkable result is failure')}
                for hid in request['hypotheses']},
                'mandatory_fact_names': mandatory or [], 'diagnostic_codes': diagnostics or [],
                'full_fact_set': 'All independently computable facts from every requested dataset must be present.',
                'no_blanket_refusal_pass': True, 'allow_source_proven_insufficiency': allow_insufficient,
                'counterevidence': 'All facts opposing each selected hypothesis must be retained.',
                'model': 'one fixed-model selection attempt must validate; all required tests stay in final report'}
    return {'id': identity, 'case_id': identity, 'version': 'benchmark-v2/1', 'level': level,
        'research_question': question, 'stratum': stratum, 'scope': 'phase3-benchmark-v2-20261004/' + identity,
        'request': request, 'source_scopes': owners, 'event': event,
        'split': 'validation', 'novelty': {'new_case_id': True, 'new_request': True,
            'new_security': False, 'new_source_records': False, 'used_for_case_or_prompt_tuning': False,
            'underlying_material_previously_development_or_quality_checked': True, 'blind': False},
        'expected_behavior': expected, 'success_criteria': ['Correct complete source-bound facts and requested hypothesis states/counterevidence.',
            'Answer the preregistered research question with all mandatory metrics or the specifically authorized source-proven limitation.',
            'No unregistered unsupported Markdown facts, causal upgrades, future closes, or unauthorized reads.',
            'Fixed DeepSeek model, one attempt, validated focus selection; no score-changing retry.'],
        'contract_version': VERSION, 'date_alignment_policy': DATE_ALIGNMENT, 'source_hashes': {}}


def build_cases(sources):
    proposals = read(PLANNING / 'candidate-proposals.json')
    cases = []
    for position, proposal in enumerate(proposals['L3']):
        request = json.loads(json.dumps(proposal['candidate_request']))
        request['as_of'] = CUTOFF
        request['mode'] = 'public' if position % 2 else 'system'
        symbol = request['symbol']
        if symbol != '000016':
            for binding in request['bindings']:
                if binding['dataset'] in {'market_daily', 'adjustment_factor', 'index_daily'}:
                    binding.update(start='2026-09-16', end='2026-09-24')
        owners = {g['dataset']: g['owner_scope'] for g in proposal['source_grants']}
        mandatory = ['financial_income.net_income_parent']
        if symbol != '000016':
            mandatory += ['observed_price_change', 'observed_max_drawdown']
        cases.append(candidate('b2-l3-roster-' + symbol, 'L3', proposal['question'], request, owners,
            stratum=proposal['stratum'], mandatory=mandatory, allow_insufficient=True))
    # Source-sign stratification is fixed before any Agent run, not chosen by Agent outcomes.
    negative = []
    for case in cases:
        income = sources.inputs(case)['datasets']['financial_income']['records']
        prior = next(r for r in income if r['period'] == '2024-06-30')
        value = next(m['value'] for m in prior['metrics'] if m['name'] == 'net_income_parent')
        if value is not None and __import__('decimal').Decimal(value) <= 0:
            negative.append(case)
    for original in negative:
        request = json.loads(json.dumps(original['request']))
        request['hypotheses'] = ['absolute_profit_change']
        cases.append(candidate('b2-l3-nonpositive-' + request['symbol'], 'L3',
            '在非正上年基数下核对同报告期归母净利润金额增加或减少；报告人民币绝对差额，不计算亏损百分比同比。',
            request, original['source_scopes'], stratum='nonpositive_base_signed_amount',
            mandatory=['financial_income.absolute_profit_change']))
    for symbol in ('000531', '601009'):
        original = next(case for case in cases if case['id'] == 'b2-l3-roster-' + symbol)
        request = json.loads(json.dumps(original['request']))
        request['hypotheses'] = ['financial_deterioration']
        for binding in request['bindings']:
            if binding['dataset'] == 'financial_income':
                binding.update(start='2024-03-31', end='2025-03-31')
        cases.append(candidate('b2-l3-missing-prior-' + symbol, 'L3',
            '核对2025Q1同期财务变化；若合法快照没有2024Q1基数，明确报告缺少同报告期证据，禁止补零或使用H1替代。',
            request, original['source_scopes'], stratum='legitimate_missing_report_period',
            mandatory=['financial_income.net_income_parent'], diagnostics=['missing_report_period'], allow_insufficient=True))
    for proposal in proposals['L5']:
        request = {'symbol': '300122', 'exchange': 'SZSE', 'as_of': proposal['proposed_cutoff'],
            'mode': proposal['pit_mode'], 'benchmark': None, 'objective': 'event_review',
            'hypotheses': ['event_chronology'], 'event_record_id': proposal['event_record_id'],
            'bindings': [{'dataset': 'market_daily', 'snapshot': proposal['market_snapshot'], 'provider': 'tushare',
                         'start': proposal['before_window'][0], 'end': proposal['after_window'][1]},
                        {'dataset': 'financial_income', 'snapshot': proposal['event_snapshot'], 'provider': 'cninfo',
                         'start': '2024-12-31', 'end': '2024-12-31'}]}
        owners = {'market_daily': proposal['market_owner_scope'], 'financial_income': proposal['event_owner_scope']}
        selected = sources.frozen.repository.read(proposal['event_owner_scope'], proposal['event_snapshot'])
        row = next(row.to_dict() for row in selected if row.record_id == proposal['event_record_id'])
        event = {'record_id': proposal['event_record_id'], 'event_type': proposal['event_type'],
            'dataset': 'financial_income', 'source': {key: row.get(key) for key in ('provider', 'source_url', 'source_key')},
            'version': {key: row.get(key) for key in ('provider_version', 'revision_id')},
            'release_precision': 'date_conservative_next_day', 'before_window': proposal['before_window'],
            'after_window': proposal['after_window'], 'market_dataset': 'market_daily', 'snapshot': proposal['market_snapshot']}
        identity = proposal['proposed_case_id'].replace('v2-L5-', 'b2-l5-')
        cases.append(candidate(identity, 'L5', '复核指定' + proposal['event_type'] + '及明确版本的披露顺序、实际事前事后收盘和描述性价格变化；不推断因果。',
            request, owners, stratum='revision_and_capture_cutoff_boundary', event=event,
            mandatory=['event_observed_price_change', 'observed_price_change']))
    event_case = json.loads(json.dumps(next(case for case in cases if case['id'] == 'b2-l5-original-narrow-public')))
    event_case.update(id='b2-l3-explicit-event', case_id='b2-l3-explicit-event', level='L3',
        scope='phase3-benchmark-v2-20261004/b2-l3-explicit-event', stratum='single_stock_explicit_event',
        research_question='单股年度报告复核：核实明确原始版本、排除披露日含糊收盘，展示事前事后实际观察价格及累计归母利润；不推断公告导致涨跌。')
    event_case['request']['objective'] = 'single_stock_research'
    event_case['expected_behavior']['mandatory_fact_names'].append('financial_income.net_income_parent')
    cases.append(event_case)
    return cases


def prepare():
    if (OUT / 'benchmark-manifest.json').exists():
        raise IntegrityError('formal benchmark already frozen; new version required')
    sources = CampaignSources()
    cases = build_cases(sources)
    (OUT / 'inputs').mkdir(exist_ok=False)
    for case in cases:
        inputs = sources.inputs(case)
        p = OUT / 'inputs' / (case['id'] + '.json')
        write_new(p, inputs)
        case['input_path'] = p.relative_to(ROOT).as_posix()
        case['input_sha256'] = sha(p)
        case['security'] = case['request']['exchange'] + ':' + case['request']['symbol']
        case['cutoff'] = case['request']['as_of']
        case['PIT'] = case['request']['mode']
        case['datasets'] = [binding['dataset'] for binding in case['request']['bindings']]
        case['snapshots'] = {binding['dataset']: binding['snapshot'] for binding in case['request']['bindings']}
        case['hypotheses'] = case['request']['hypotheses']
        case['source_hashes'] = {**sources.frozen.input_hashes, case['input_path']: case['input_sha256'],
            **{path: artifact_id for artifact_id, path in inputs['artifact_paths'].items()}}
    write_new(OUT / 'candidate-cases.json', {'cases': cases, 'selection': 'Full fixed25 roster modulo9 topics, all source-nonpositive strata, two explicit missing-Q1 checks, four pinned event/window/PIT cases, one L3 explicit event. No Agent output used.',
        'splits': {'development': 'Synthetic mechanism fixtures only; not financial truth.', 'validation': len(cases),
                   'independent_test': 0, 'blind': False}})
    validation = validate_cases(cases, sources.context)
    write_new(OUT / 'contract-validation.json', validation)
    implementation = {p.relative_to(ROOT).as_posix(): sha(p) for p in (ROOT / 'src').rglob('*.py')}
    for p in ('scripts/phase3_benchmark_v2.py', 'scripts/phase3_benchmark_v2_contract.py', 'scripts/phase3_benchmark_gate.py'):
        implementation[p] = sha(ROOT / p)
    protocol = {'model': SPEC.model, 'spec': {**asdict(SPEC), 'allowed_tools': sorted(SPEC.allowed_tools),
               'visible_tools': sorted(SPEC.visible_tools)}, 'spec_identity': SPEC.identity,
        'implementation_files': implementation, 'prompt_version': 'single-research-v5; v3 complete evidence bundle prompt',
        'max_dispatches': len(cases), 'max_token_reservations': len(cases) * SPEC.max_tokens,
        'campaign_seconds': len(cases) * 60, 'one_attempt_per_case': True,
        'thresholds': {'L3': .85, 'L5': .85, 'ESR': .98, 'hallucination': .01, 'critical_anchor': 1},
        'ESR_denominator': 'All source-assessable numeric, hypothesis, required-anchor and additional Markdown fact claim occurrences; all unknowns separately retained.',
        'official_accuracy': 'All numeric inputs independently matched to frozen official source/version; partial/unknown never promoted to certified accuracy.',
        'task_success': 'Correct complete request-specific checks including preregistered source-proven insufficiency, independent support/Markdown audit and validated one-attempt model selection.',
        'required_check_completion': 'Every required hypothesis answered correctly under preregistered behavior, including a justified expected insufficient; decisive-check completion also reported separately.',
        'split_policy': 'No independent_test/true blind cases available from present frozen corpus; all formal cases are validation, no broad generalization certificate.'}
    freeze_benchmark(OUT / 'benchmark-manifest.json', cases, validation,
        benchmark_version='phase3-benchmark-v2-20261004/1', implementation_version=SPEC.version,
        parent_manifest_sha256=sha(ROOT / '.artifacts/phase3/fullscope-20261003/review-pack/manifest.json'),
        source_context=sources.context, protocol=protocol)
    print(json.dumps({'frozen': True, 'cases': len(cases), 'valid': validation['valid_case_count'],
        'levels': dict(Counter(case['level'] for case in cases)), 'manifest_sha256': sha(OUT / 'benchmark-manifest.json')}))


def checked_manifest():
    manifest = read(OUT / 'benchmark-manifest.json')
    for path, expected in manifest['evaluation_protocol']['implementation_files'].items():
        if sha(ROOT / path) != expected:
            raise IntegrityError('frozen Agent implementation changed')
    for case in manifest['cases']:
        if sha(ROOT / case['input_path']) != case['input_sha256']:
            raise IntegrityError('frozen inputs changed')
    return manifest


def plan_dispatch():
    manifest = checked_manifest()
    sources = CampaignSources()
    validation = validate_cases(manifest['cases'], sources.context)
    if validation != manifest['contract_validation']:
        raise IntegrityError('current authorized input contract differs')
    plans = []
    for case in manifest['cases']:
        inputs = sources.inputs(case)
        if digest(inputs) != digest(read(ROOT / case['input_path'])):
            raise IntegrityError('source inputs changed after formal freeze')
        # Case freeze precedes any Agent calculation. Preview cannot change cases/expectations.
        computed = StudyRuntime(None, None, spec=SPEC)._calculate(inputs['datasets'], StudyRequest.from_dict(case['request']))
        messages, context = study_messages(computed, StudyRequest.from_dict(case['request']), SPEC.context_bytes, version=SPEC.version)
        plans.append({'case_id': case['id'], 'messages': messages, 'message_sha256': digest(messages),
                      'context': context, 'max_output_tokens': SPEC.output_tokens})
    config = load_model_config()
    if config.model != SPEC.model:
        raise IntegrityError('configured model differs from fixed model')
    write_new(OUT / 'model-dispatch-plan.json', {'manifest_sha256': sha(OUT / 'benchmark-manifest.json'),
        'endpoint_sha256': hashlib.sha256(config.endpoint.encode()).hexdigest(), 'model': SPEC.model,
        'max_dispatches': len(plans), 'max_token_reservations': manifest['evaluation_protocol']['max_token_reservations'], 'cases': plans})
    print(json.dumps({'planned_dispatches': len(plans), 'plan_sha256': sha(OUT / 'model-dispatch-plan.json'),
        'total_context_bytes': sum(plan['context']['bytes'] for plan in plans)}))


class RawReceiptModel(ChatModelAdapter):
    def __init__(self, config, transport, path):
        super().__init__(config, transport)
        self.path = path

    def complete(self, *args, **kwargs):
        response = super().complete(*args, **kwargs)
        receipt = asdict(response)
        if self.config.api_key in json.dumps(receipt, ensure_ascii=False):
            receipt = {'withheld': 'credential_reflection'}
        write_new(self.path, receipt)
        return response


def live():
    manifest = checked_manifest()
    plan = read(OUT / 'model-dispatch-plan.json')
    if plan['manifest_sha256'] != sha(OUT / 'benchmark-manifest.json'):
        raise IntegrityError('dispatch plan belongs to different frozen benchmark')
    config = load_model_config()
    if config.model != plan['model'] or hashlib.sha256(config.endpoint.encode()).hexdigest() != plan['endpoint_sha256']:
        raise IntegrityError('fixed model or endpoint changed')
    directory = OUT / 'live'
    directory.mkdir(exist_ok=False)
    sources = CampaignSources()
    if validate_cases(manifest['cases'], sources.context) != manifest['contract_validation']:
        raise IntegrityError('whole batch contract no longer valid')
    deadline = utcnow() + timedelta(seconds=manifest['evaluation_protocol']['campaign_seconds'])
    ledger = {'manifest_sha256': plan['manifest_sha256'], 'deadline': deadline.isoformat(),
              'dispatches': 0, 'reserved': 0, 'intents': []}
    upstream = ChatHTTPTransport()
    results = []
    for case, item in zip(manifest['cases'], plan['cases']):
        if case['id'] != item['case_id'] or utcnow() >= deadline:
            raise IntegrityError('campaign identity/deadline differs')
        service, access = sources.context(case)
        inputs = sources.inputs(case)
        if digest(inputs) != digest(read(ROOT / case['input_path'])):
            raise IntegrityError('frozen source differs')
        dispatched = False
        def transport(cfg, payload, timeout):
            nonlocal dispatched
            if dispatched or payload['messages'] != item['messages'] or cfg.endpoint != config.endpoint or payload['model'] != plan['model'] or payload['max_tokens'] != SPEC.output_tokens:
                raise IntegrityError('frozen outbound content or attempt differs')
            reservation = sum(len(message['content'].encode()) for message in payload['messages']) + 256 + payload['max_tokens']
            if ledger['dispatches'] >= plan['max_dispatches'] or ledger['reserved'] + reservation > plan['max_token_reservations']:
                raise IntegrityError('campaign budget exceeded')
            dispatched = True
            ledger['dispatches'] += 1
            ledger['reserved'] += reservation
            intent = {'case_id': case['id'], 'message_sha256': item['message_sha256'], 'reservation': reservation,
                      'attempt': 1, 'usage': 'unknown_until_receipt', 'manifest_sha256': plan['manifest_sha256']}
            ledger['intents'].append(intent)
            write_new(directory / ('intent-' + case['id'] + '.json'), intent)
            return upstream(cfg, payload, min(timeout, 30, (deadline - utcnow()).total_seconds()))
        model = RawReceiptModel(config, transport, directory / ('receipt-' + case['id'] + '.json'))
        report = StudyRuntime(service, CheckpointStore(directory / 'runs'), model, SPEC).run(StudyRequest.from_dict(case['request']), access)
        path = directory / (case['id'] + '.json')
        write_new(path, report)
        text_path = directory / (case['id'] + '.md')
        with text_path.open('x', encoding='utf8') as stream:
            stream.write(markdown(report))
        results.append({'case_id': case['id'], 'level': case['level'], 'report_path': path.relative_to(ROOT).as_posix(),
            'report_sha256': sha(path), 'markdown_path': text_path.relative_to(ROOT).as_posix(),
            'markdown_sha256': sha(text_path), 'model': report['model'], 'dispatch_count': int(dispatched), 'output': report})
        print(json.dumps({'case_id': case['id'], 'model_status': report['model']['status'], 'dispatches': ledger['dispatches']}), flush=True)
    write_new(OUT / 'agent-results.json', {'schema': 'phase3-agent-results/v2', 'manifest_sha256': plan['manifest_sha256'],
        'dispatch_plan_sha256': sha(OUT / 'model-dispatch-plan.json'), 'run_protocol': manifest['evaluation_protocol'],
        'campaign_ledger': ledger, 'all_cases_retained': len(results) == len(manifest['cases']), 'cases': results})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare', action='store_true')
    action.add_argument('--plan-dispatch', action='store_true')
    action.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.plan_dispatch:
        plan_dispatch()
    else:
        live()
