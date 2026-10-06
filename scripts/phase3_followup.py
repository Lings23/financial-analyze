"""Frozen Phase 3 v2 regression and independent-security catalogue acceptance.

No network in prepare/audit. Real model execution is a separate bounded command.
Independent exact arithmetic is frozen before the model sees any task.
"""
import argparse
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from accept_phase2_real import write, read_inputs, oracle
from accept_phase3_quality import source_context as legacy_source, quality_checks
from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.model_adapters.chat import load_model_config
from stock_research.models import AccessContext, DataRecord, PITMode, QueryContext, Security, digest, utcnow
from stock_research.providers.base import ProviderRegistry
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.context import study_messages
from stock_research.research.contracts import Binding
from stock_research.research.report import markdown
from stock_research.research.scoped import SourceGrant, ScopedReadService
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudyRequest, StudySpec
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.memory import MemoryRepository
from stock_research.storage.postgres import PostgresRepository
from phase3_benchmark_gate import precheck_cases, require_valid_precheck


ROOT = Path('.artifacts/phase3/followup-20261002')
OLD = Path('.artifacts/phase3/quality-20261002')
SPEC = StudySpec(version='single-research-v2',context_bytes=24000, max_tokens=28000)
LIMITS = {'max_dispatches':37, 'max_token_reservations':500000, 'max_seconds':2100}
SCOPE = 'phase3-explicit-scoped-followup-20261002'
SOURCE_FILES = [Path('.artifacts/p17_20260930/run.json'), Path('.artifacts/p18_20261001/attempt2.json'),
                Path('.artifacts/p17_20261001/release_date/run.json'),
                Path('evaluation/p17_20261001_release_date_plan.json'), ROOT/'event-prices/result.json']


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pool():
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text().strip())
    result = {}
    for name, path, scope, artifacts in (
        ('pilot', SOURCE_FILES[0], 'p17-validation-20260930', '.artifacts/p17_20260930/artifacts'),
        ('p18', SOURCE_FILES[1], 'p18-validation-20261001', '.artifacts/p18_20261001/artifacts'),
        ('qualified', SOURCE_FILES[2], 'p17-qualified-cninfo-20261001', '.artifacts/p17_20261001/release_date/artifacts')):
        run = json.loads(path.read_bytes())
        result[name] = (DataService(ProviderRegistry(), None, db, ArtifactStore(artifacts)),
                        AccessContext(scope, frozenset({'cninfo'} if name=='qualified' else {'tushare'})), run)
    saved = json.loads(SOURCE_FILES[-1].read_bytes())
    repo = MemoryRepository()
    for item in saved['results']:
        if item['status'] != 'captured': raise IntegrityError('event market capture unavailable')
        rows = tuple(DataRecord.from_dict(r) for r in item['records'])
        if repo.commit(saved['scope'], rows).snapshot_id != item['snapshot']:
            raise IntegrityError('captured event snapshot differs')
    result['event_prices'] = (DataService(ProviderRegistry(), None, repo, ArtifactStore(ROOT/'event-prices/artifacts')),
                             AccessContext(saved['scope'], frozenset({'tushare'})), saved)
    return result


def source_context(case):
    if case['kind'] != 'real_scoped_catalogue': return legacy_source(case)
    if case['scope'] != SCOPE or any(sha(p)!=v for p,v in case['source_files'].items()):
        raise IntegrityError('scoped corpus source identity differs')
    sources = pool()
    request = StudyRequest.from_dict(case['request'])
    grants = []
    for b in request.bindings:
        svc, access, _ = sources[case['routes'][b.dataset]]
        grants.append(SourceGrant(svc, access, b.snapshot, request.data_request(b), b.provider))
    return ScopedReadService(SCOPE, lambda: tuple(grants)), AccessContext(SCOPE, frozenset({'tushare','cninfo'}))


def independent_expected(data, request):
    """Source-based Fraction formulas and hypothesis rules; no production calculators."""
    expected, _ = oracle(data)
    metric = lambda r,n: next(m.value for m in r.metrics if m.name==n)
    prices = sorted(data['market_daily'], key=lambda r:r.period)
    if 'observed_price_change' in expected:
        factor = {r.period:metric(r,'factor') for r in data.get('adjustment_factor',())}
        if factor and all(factor.get(r.period) is not None and factor[r.period]>0 for r in prices):
            expected['factor_adjusted_price_change'] = (Fraction(metric(prices[-1],'close'))*Fraction(factor[prices[-1].period])
                / (Fraction(metric(prices[0],'close'))*Fraction(factor[prices[0].period]))-1)
        index = sorted(data.get('index_daily',()), key=lambda r:r.period)
        if index and [r.period for r in index]==[r.period for r in prices] and all(metric(r,'close') and metric(r,'close')>0 for r in index):
            expected['benchmark_price_change']=Fraction(metric(index[-1],'close'))/Fraction(metric(index[0],'close'))-1
            expected['price_change_difference']=expected['observed_price_change']-expected['benchmark_price_change']
    for dataset in ('financial_balance','financial_cashflow'):
        rows=data.get(dataset,())
        if rows:
            latest=max(rows,key=lambda r:r.period)
            expected.update({dataset+'.'+m.name:Fraction(m.value) for m in latest.metrics if m.value is not None})
    anchor=next((r for rows in data.values() for r in rows if r.record_id==request.event_record_id),None)
    anchor_expected={'status':'insufficient'}
    if anchor and anchor.availability_basis=='verified_release_date':
        pre=[r for r in prices if r.period<anchor.release_date]
        post=[r for r in prices if r.period>anchor.release_date]
        anchor_expected={'status':'verified','release_date':anchor.release_date.isoformat(),
                         'precision':'date_conservative_next_day'}
        if pre and post and all(metric(r,'close') is not None and metric(r,'close')>0 for r in (pre[-1],post[-1])):
            expected['event_observed_price_change']=Fraction(metric(post[-1],'close'))/Fraction(metric(pre[-1],'close'))-1
            anchor_expected['price_window']=[pre[-1].period.isoformat(),post[-1].period.isoformat()]
    statuses={}
    for h in request.hypotheses:
        status='insufficient'
        if h=='financial_deterioration' and {'revenue_yoy','net_income_parent_yoy'}<=expected.keys():
            flags=[expected[n]<0 for n in ('revenue_yoy','net_income_parent_yoy')]
            status='supported' if all(flags) else 'conflicted' if any(flags) else 'unsupported'
        elif h=='mechanical_adjustment' and 'factor_adjusted_price_change' in expected:
            status='supported' if factor[prices[0].period]!=factor[prices[-1].period] else 'unsupported'
        elif h=='market_direction' and 'benchmark_price_change' in expected:
            v=expected['observed_price_change']*expected['benchmark_price_change']
            status='supported' if v>0 else 'unsupported' if v<0 else 'insufficient'
        elif h=='cashflow_divergence' and {'financial_income.net_income_parent','financial_cashflow.operating_cashflow'}<=expected.keys():
            if max(r.period for r in data['financial_income'])==max(r.period for r in data['financial_cashflow']):
                status='supported' if expected['financial_income.net_income_parent']>0 and expected['financial_cashflow.operating_cashflow']<0 else 'unsupported'
        elif h=='event_chronology' and 'event_observed_price_change' in expected: status='supported'
        statuses[h]=status
    return expected,statuses,anchor_expected


def candidates():
    original=json.loads((OLD/'proposed-model-manifest.json').read_bytes())
    for case in original['cases']:
        yield {**case, 'cohort':'regression', 'prior_case_id':case['id']}
    sources=pool()
    pilot=sources['pilot'][2]; p18=sources['p18'][2]; qualified=sources['qualified'][2]
    cutoff=utcnow()
    pilot_snapshot=pilot['results'][-1]['snapshot_id']
    source_hashes={str(p):sha(p) for p in SOURCE_FILES}
    for symbol,exchange in (('600000','SSE'),('688590','SSE'),('000001','SZSE'),('300750','SZSE'),('920118','BSE'),('600519','SSE')):
        recent=symbol=='300750'
        start,end=('2026-09-15','2026-09-25') if recent else ('2024-09-18','2024-09-30')
        bindings=[Binding('market_daily',pilot_snapshot,'tushare',date.fromisoformat(start),date.fromisoformat(end)),
                  Binding('financial_income',pilot_snapshot,'tushare',date(2024,12,31),date(2024,12,31))]
        routes={'market_daily':'pilot','financial_income':'pilot'}
        hypotheses=[]
        for dataset,hypothesis in (('index_daily','market_direction'),('adjustment_factor','mechanical_adjustment'),
                                    ('financial_cashflow','cashflow_divergence')):
            if dataset=='index_daily' and recent: continue
            match=next((r for r in p18['results'] if r['request']['dataset']==dataset and
                        (r['request']['code']==symbol or dataset=='index_daily') and
                        (dataset=='financial_cashflow' or r['request']['start']==start)),None)
            if match:
                q=match['request']; bindings.append(Binding(dataset,match['snapshot_id'],'tushare',date.fromisoformat(q['start']),date.fromisoformat(q['end'])))
                routes[dataset]='p18'; hypotheses.append(hypothesis)
        request=StudyRequest(Security(symbol,exchange),cutoff,PITMode.SYSTEM,tuple(bindings),
                             None if recent else '000300.SH',hypotheses=tuple(hypotheses))
        yield {'id':'catalogue-'+symbol,'kind':'real_scoped_catalogue','cohort':'new_catalogue','scope':SCOPE,
               'request':request.to_dict(),'routes':routes,'source_files':source_hashes}
    for item in sources['event_prices'][2]['results']:
        snapshot=qualified['first_snapshot'] if item['label']=='original' else qualified['final_snapshot']
        bindings=(Binding('market_daily',item['snapshot'],'tushare',date.fromisoformat(item['start']),date.fromisoformat(item['end'])),
                  Binding('financial_income',snapshot,'cninfo',date(2024,12,31),date(2024,12,31)))
        base=StudyRequest(Security('300122','SZSE'),cutoff,PITMode.SYSTEM,bindings,hypotheses=('event_chronology',))
        svc,access,_=sources['qualified']
        r=svc.query(base.data_request(bindings[1]),QueryContext(access,snapshot,cutoff,PITMode.SYSTEM)).records
        if len(r)!=1: raise IntegrityError('event anchor is not unique')
        request=replace(base,objective='event_review',event_record_id=r[0].record_id)
        yield {'id':'retrospective-'+item['label'],'kind':'real_scoped_catalogue','cohort':'new_catalogue','scope':SCOPE,
               'request':request.to_dict(),'routes':{'market_daily':'event_prices','financial_income':'qualified'},'source_files':source_hashes}


def prepare(path, *, selected_cases=None, spec=SPEC, root=ROOT, limits=LIMITS, previous_manifest=None):
    if path.exists(): raise IntegrityError('manifest is immutable')
    selected_cases = list(candidates() if selected_cases is None else selected_cases)
    precheck = precheck_cases(selected_cases, source_context)
    # Complete precheck is retained even when an invalid batch is refused.
    write(root/'contract-precheck.json', precheck)
    require_valid_precheck(selected_cases, precheck)
    cases=[]
    for case in selected_cases:
        svc,access=source_context(case); request=StudyRequest.from_dict(case['request'])
        data=read_inputs(svc,request,access)
        expected,hs,anchor=independent_expected(data,request)
        # Persist expectations BEFORE Runtime calculations and before any model call.
        write(root/'expected'/(case['id']+'.json'), {'values':{n:[v.numerator,v.denominator] for n,v in expected.items()},
                                                  'hypotheses':hs,'anchor':anchor})
        report=StudyRuntime(svc,CheckpointStore(root/'prepare-runs'),spec=spec).run(request,access)
        verify_expected(report,expected,hs,anchor)
        if 'facts_hash' in case:
            for key,value in (('facts_hash',report['facts']),('hypotheses_hash',report['hypotheses']),('anchor_hash',report['event_anchor'])):
                if digest(value)!=case[key]: raise IntegrityError('legacy facts or tests changed')
        messages,view=study_messages(report,request,spec.context_bytes,version=spec.version)
        case.update(input_hash=digest({k:[r.to_dict() for r in rows] for k,rows in data.items()}),
                    facts_hash=digest(report['facts']),hypotheses_hash=digest(report['hypotheses']),anchor_hash=digest(report['event_anchor']),
                    messages=messages,independent_expected={n:[v.numerator,v.denominator] for n,v in expected.items()},
                    expected_hypotheses=hs,expected_anchor=anchor,context_bytes=view['bytes'])
        write(root/'prepared-reports'/(case['id']+'.json'),report)
        (root/'prepared-reports'/(case['id']+'.md')).write_text(markdown(report),encoding='utf-8')
        cases.append(case)
    assert len(cases)==limits['max_dispatches']
    manifest={'rubric_version':'phase3-selection-quality-v1','spec_version':spec.version,
              'spec':{'version':spec.version,'context_bytes':spec.context_bytes,'max_tokens':spec.max_tokens},
              'model':spec.model,'endpoint':'test_api.txt configured HTTPS endpoint only','threshold_task_quality':0.85,
              'cohort_thresholds':{name:0.85 for name in sorted({c['cohort'] for c in cases})},'max_dispatches':len(cases),
              'root_limits':limits,'output_tokens':spec.output_tokens,'cases':cases,
              'design_sha256':sha('docs/PHASE3_V3_DESIGN_20261002.md' if spec.version=='single-research-v3' else 'docs/PHASE3_FOLLOWUP_DESIGN_20261002.md'),
              'previous_manifest_sha256':sha(previous_manifest or OLD/'proposed-model-manifest.json'),
              'financial_provider_calls_before_freeze':2,'general_research_certified':False}
    manifest['benchmark_contract_version'] = 'benchmark-contract/v1'
    manifest['contract_precheck_sha256'] = digest(precheck)
    config=load_model_config()
    assert config.model==spec.model
    manifest['endpoint_sha256']=hashlib.sha256(config.endpoint.encode()).hexdigest()
    if spec.version=='single-research-v3': manifest['save_bounded_model_receipts']=True
    write(path,manifest)
    print(json.dumps({'cases':len(cases),'manifest_sha256':sha(path),'root_limits':limits,
                      'max_context_bytes':max(c['context_bytes'] for c in cases),
                      'token_reservations':sum(c['context_bytes']+256+512 for c in cases)}))


def verify_expected(report,expected,hs,anchor):
    actual={f['name']:Fraction(Decimal(f['value'])) for f in report['facts']}
    assert set(actual)==set(expected) and all(abs(actual[n]-v)<Fraction(1,10**28) for n,v in expected.items())
    assert {h['id']:h['status'] for h in report['hypotheses']}==hs
    assert report['event_anchor']['status']==anchor['status']
    if anchor['status']=='verified':
        assert all(report['event_anchor'][k]==anchor[k] for k in ('precision','release_date'))
    if 'price_window' in anchor:
        assert next(f['window'] for f in report['facts'] if f['name']=='event_observed_price_change')==anchor['price_window']
    assert report['verification']['status']=='verified'


def audit(path,output):
    manifest=json.loads(path.read_bytes()); output.mkdir(parents=True,exist_ok=False)
    spec=StudySpec(**manifest['spec'])
    results=[]
    for case in manifest['cases']:
        svc,access=source_context(case); request=StudyRequest.from_dict(case['request'])
        data=read_inputs(svc,request,access)
        assert digest({k:[r.to_dict() for r in rows] for k,rows in data.items()})==case['input_hash']
        runtime=StudyRuntime(svc,CheckpointStore(output/'runs'),spec=spec)
        report=runtime.run(request,access)
        verify_expected(report,{n:Fraction(*v) for n,v in case['independent_expected'].items()},case['expected_hypotheses'],case['expected_anchor'])
        assert digest(report['facts'])==case['facts_hash'] and digest(report['hypotheses'])==case['hypotheses_hash']
        assert study_messages(report,request,spec.context_bytes,version=spec.version)[0]==case['messages']
        assert runtime.run(request,access,resume=report['run_id'])==report
        try: runtime.run(request,AccessContext(access.scope,frozenset({'denied'})),resume=report['run_id'])
        except PermissionDenied: pass
        else: raise AssertionError('provider revocation failed')
        if isinstance(svc,ScopedReadService):
            grants=svc.current_grants
            svc.current_grants=lambda: grants()[1:]
            try: runtime.run(request,access,resume=report['run_id'])
            except PermissionDenied: pass
            else: raise AssertionError('scope grant revocation failed')
            svc.current_grants=grants
        if data['market_daily']:
            before=min(r.available_at for r in data['market_daily'])-timedelta(microseconds=1)
            b=next(b for b in request.bindings if b.dataset=='market_daily')
            assert not svc.query(request.data_request(b),QueryContext(access,b.snapshot,before,request.mode)).records
        write(output/(case['id']+'.json'),report)
        (output/(case['id']+'.md')).write_text(markdown(report),encoding='utf-8')
        results.append({'case':case['id'],'cohort':case['cohort'],'numeric_claims':len(report['facts']),
                        'evidence':len(report['evidence']),'hypotheses':case['expected_hypotheses'],
                        'research_status':report['research_status'],'replay_identical':True,'revocation_denied':True})
    catalogue=[c for c in results if c['cohort']=='new_catalogue']
    result={'manifest_sha256':sha(path),'tasks':len(results),'numeric_claims':sum(r['numeric_claims'] for r in results),
            'evidence':sum(r['evidence'] for r in results),'identical_replays':len(results),'revocation_checks':len(results),
            'new_catalogue_tasks':len(catalogue),'new_catalogue_tests_completed':sum(c['research_status']=='tests_completed' for c in catalogue),
            'new_catalogue_hypotheses':sum(len(c['hypotheses']) for c in catalogue),
            'new_catalogue_decisive':sum(v!='insufficient' for c in catalogue for v in c['hypotheses'].values()),
            'model_dispatches':0,'financial_provider_network_calls':0,'general_phase3_quality_certified':False,'cases':results}
    write(output/'result.json',result); print(json.dumps({k:v for k,v in result.items() if k!='cases'}))


if __name__=='__main__':
    p=argparse.ArgumentParser(); action=p.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare',action='store_true'); action.add_argument('--audit',action='store_true')
    action.add_argument('--live',action='store_true'); action.add_argument('--replay',type=Path)
    p.add_argument('--manifest',type=Path,default=ROOT/'model-manifest.json'); p.add_argument('--output',type=Path)
    p.add_argument('--expected-manifest-sha256',help='required for live dispatch; pins the reviewed exact manifest')
    a=p.parse_args()
    if a.prepare: prepare(a.manifest)
    elif not a.output: p.error('output required')
    elif a.audit: audit(a.manifest,a.output)
    else:
        from accept_phase3_quality import live,replay
        if a.live:
            if not a.expected_manifest_sha256 or sha(a.manifest)!=a.expected_manifest_sha256:
                p.error('live dispatch requires the reviewed exact manifest SHA256')
            live(a.manifest,a.output,root=ROOT,limits=LIMITS)
        else: replay(a.manifest,a.replay,a.output)
