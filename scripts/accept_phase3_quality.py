"""Authorized bounded DeepSeek acceptance. Freeze messages before dispatch; no retries.

Protocol/relevance, substantive evidence coverage and general research quality are
separate denominators. No new financial Provider calls and no source truth claims.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from accept_phase2_real import service, read_inputs, write, oracle
from accept_phase3_event import inputs as event_inputs
from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.model_adapters.chat import ChatHTTPTransport, ChatModelAdapter, load_model_config
from stock_research.models import AccessContext, digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.context import study_messages
from stock_research.research.report import markdown
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudyRequest, StudySpec
from phase3_benchmark_gate import precheck_cases, require_valid_precheck


ROOT = Path('.artifacts/phase3/quality-20261002')
LIMITS = {'max_dispatches':29, 'max_token_reservations':350000, 'max_seconds':1500}


class ReceiptModel(ChatModelAdapter):
    """Bounded model-only audit receipt; never persist credentials or HTTP headers."""
    def __init__(self, config, transport, receipt_path):
        super().__init__(config, transport)
        self.receipt_path=receipt_path

    def complete(self, *args, **kwargs):
        result=super().complete(*args, **kwargs)
        safe=asdict(result)
        encoded=json.dumps(safe,ensure_ascii=False)
        if any(self.config.api_key in v for v in safe.values() if isinstance(v,str)):
            safe={'withheld':'credential_reflection'}
        elif len(encoded.encode('utf-8'))>16384:
            safe={'withheld':'receipt_size_limit'}
        write(self.receipt_path,safe)
        return result


def quality_checks(report, *, visible_highlights=None):
    facts = {f['id']:f for f in report['facts']}
    ids = report['model'].get('highlights', []) if visible_highlights is None else visible_highlights
    selected = [facts[f] for f in ids if f in facts]
    names = {f['name'] for f in selected}
    available = {f['name'] for f in facts.values()}
    market = lambda n: n.startswith('observed_') or n in {'factor_adjusted_price_change','benchmark_price_change','price_change_difference','event_observed_price_change'}
    financial = lambda n: n.startswith('financial_') or n.endswith('_yoy')
    redundant = any({a['name'],b['name']} == {'financial_income.revenue','financial_income.total_revenue'}
                    and Decimal(a['value']) == Decimal(b['value']) and a['unit'] == b['unit'] and a['window'] == b['window']
                    for i,a in enumerate(selected) for b in selected[i+1:])
    hypotheses = {h['id']:h for h in report['hypotheses']}
    picked = report['model'].get('hypotheses', [])
    decisive = {h for h,v in hypotheses.items() if v['status'] != 'insufficient'}
    rendered = markdown(report)
    return {'verified_model':report['model']['status']=='verified',
            'nonempty_facts':bool(facts),
            'market_covered_when_available':not any(market(n) for n in available) or any(market(n) for n in names),
            'financial_covered_when_available':not any(financial(n) for n in available) or any(financial(n) for n in names),
            'no_equal_revenue_redundancy':not redundant,
            'decisive_hypothesis_selected_when_available':not decisive or bool(set(picked)&decisive),
            'selected_hypothesis_evidence_highlighted':not decisive or any(set(hypotheses[h]['claim_ids'])&{f['id'] for f in selected}
                                                                         for h in picked if h in decisive),
            'event_test_selected':report['request']['objective']!='event_review' or 'event_chronology' in picked,
            'claim_verification':report['verification']['status']=='verified',
            'no_causal_upgrade':report['synthesis']['causal_conclusion']=='not_established',
            'all_hypotheses_and_counterevidence_retained':all(h['title'] in rendered and all(c in rendered for c in h['claim_ids']) for h in hypotheses.values()),
            'coverage_explained':'覆盖尚未认证' in rendered,
            'insufficient_explained':not report['synthesis']['insufficient'] or '证据不足' in rendered}


def source_context(case):
    if case['kind']=='real_scoped_catalogue':
        from phase3_followup import source_context as scoped_context
        return scoped_context(case)
    if case['kind']=='real_formal':
        return service(), AccessContext(case['scope'], frozenset({'tushare'}))
    if case['kind']=='real_qualified_event':
        _,_,svc,access=event_inputs()
        return svc,access
    if case['kind']=='real_archived_income_projection':
        from phase3_archive_quality import replay_projection
        return replay_projection(case['projection_path'], case['projection_sha256'])
    raise IntegrityError('unknown frozen quality source kind')


def prepare_baseline():
    if (ROOT/'baseline-manifest.json').exists():
        raise IntegrityError('manifest is immutable; use a new benchmark location')
    corpus=json.loads(Path('evaluation/phase3_real_cases_20261002.json').read_bytes())
    cases=[]
    groups=[('real_formal',item,Path('.artifacts/phase3/real-initial')/(item['id']+'.json'),corpus['scope'])
            for item in corpus['cases'] if item['request']['bindings'][0]['start']=='2026-09-15']
    events=json.loads(Path('evaluation/phase3_event_cases_20261002.json').read_bytes())
    groups += [('real_qualified_event',item,Path('.artifacts/phase3/event-initial')/(item['id']+'.json'),events['scope'])
               for item in events['cases'] if item['expected_anchor']=='verified']
    for kind,item,path,scope in groups:
        report=json.loads(path.read_bytes())
        request=StudyRequest.from_dict(report['request'])
        case={'id':item['id'],'kind':kind,'scope':scope,'request':request.to_dict(),'source_report_sha256':digest(report)}
        svc,access=source_context(case)
        # Fresh authorized PIT queries before freezing external content.
        inputs=read_inputs(svc,request,access)
        case['input_hash']=digest({k:[r.to_dict() for r in rows] for k,rows in inputs.items()})
        case.update(facts_hash=digest(report['facts']), hypotheses_hash=digest(report['hypotheses']),
                    anchor_hash=digest(report['event_anchor']), messages=study_messages(report,request,StudySpec().context_bytes,version='single-research-v1')[0])
        cases.append(case)
    assert len(cases)==29
    precheck = precheck_cases(cases, source_context)
    write(ROOT/'baseline-contract-precheck.json', precheck)
    require_valid_precheck(cases, precheck)
    manifest={'rubric_version':'phase3-selection-quality-v1','model':'deepseek-v4-flash-0731',
              'endpoint':'test_api.txt configured HTTPS endpoint only','criteria':list(quality_checks(report)),
              'threshold_task_quality':0.85,'max_dispatches':len(cases),'root_limits':LIMITS,
              'output_tokens':512,'cases':cases,
              'general_research_certified':False,'financial_provider_network_calls':0,
              'benchmark_contract_version':'benchmark-contract/v1','contract_precheck_sha256':digest(precheck)}
    path=ROOT/'baseline-manifest.json'
    write(path,manifest)
    print(json.dumps({'prepared_calls':len(cases),'manifest_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'root_limits':LIMITS}))


def budget(store, limits=LIMITS):
    root_id='31022026000000000000000000000001'
    try:
        state=store.read('phase3-quality',root_id)
    except PermissionDenied:
        state={'dispatches':0,'reserved':0,'deadline':(utcnow()+timedelta(seconds=limits['max_seconds'])).isoformat(),
               'limits':limits,'intents':[]}
        store.append('phase3-quality',root_id,state)
    if state['limits']!=limits:
        raise IntegrityError('root campaign budget changed')
    return root_id,state


def live(manifest_path,output,*,root=ROOT,limits=LIMITS):
    manifest=json.loads(manifest_path.read_bytes())
    manifest_sha=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert manifest['model']=='deepseek-v4-flash-0731' and manifest['max_dispatches']==len(manifest['cases'])<=limits['max_dispatches']
    assert len({c['id'] for c in manifest['cases']})==len(manifest['cases'])
    assert manifest['root_limits']==limits
    output.mkdir(parents=True,exist_ok=False)
    config=load_model_config()
    assert config.model==manifest['model']
    if 'endpoint_sha256' in manifest:
        assert hashlib.sha256(config.endpoint.encode()).hexdigest()==manifest['endpoint_sha256']
    spec=StudySpec(**manifest.get('spec',{'version':manifest.get('spec_version','single-research-v1')}))
    upstream=ChatHTTPTransport()
    root_store=CheckpointStore(root/'root-budget')
    root_id,state=budget(root_store,limits)
    results=[]
    with root_store.lock('phase3-quality',root_id):
        state=root_store.read('phase3-quality',root_id)
        if state.get('manifest_sha256',manifest_sha)!=manifest_sha:
            raise IntegrityError('root campaign manifest changed')
        state['manifest_sha256']=manifest_sha
        for case in manifest['cases']:
            if any(i['case']==case['id'] for i in state['intents']):
                raise IntegrityError('paid campaign intent already exists; no redispatch')
            if utcnow()>=datetime.fromisoformat(state['deadline']):
                raise IntegrityError('root quality deadline exceeded')
            svc,access=source_context(case)
            request=StudyRequest.from_dict(case['request'])
            data=read_inputs(svc,request,access)
            assert digest({k:[r.to_dict() for r in rows] for k,rows in data.items()})==case['input_hash']
            dispatched=False
            def transport(cfg,payload,timeout):
                nonlocal dispatched
                if dispatched or cfg.endpoint!=config.endpoint or payload['model']!=manifest['model'] or payload['messages']!=case['messages']:
                    raise IntegrityError('frozen outbound content or dispatch differs')
                if payload['max_tokens']!=manifest['output_tokens']:
                    raise IntegrityError('campaign output budget changed')
                reservation=sum(len(m['content'].encode('utf-8')) for m in payload['messages'])+256+payload['max_tokens']
                remaining=(datetime.fromisoformat(state['deadline'])-utcnow()).total_seconds()
                if state['dispatches']>=limits['max_dispatches'] or state['reserved']+reservation>limits['max_token_reservations'] or remaining<=0:
                    raise IntegrityError('root quality budget exceeded')
                dispatched=True
                state['dispatches']+=1; state['reserved']+=reservation
                state['intents'].append({'case':case['id'],'manifest_sha256':manifest_sha,
                                        'messages_hash':digest(payload['messages']),'reservation':reservation,'usage':'unknown_until_receipt'})
                root_store.append('phase3-quality',root_id,state)
                write(output/('dispatch-'+str(state['dispatches'])+'.json'),state['intents'][-1])
                return upstream(cfg,payload,min(timeout,30,remaining))
            model=(ReceiptModel(config,transport,output/('receipt-'+case['id']+'.json'))
                   if manifest.get('save_bounded_model_receipts') else ChatModelAdapter(config,transport))
            report=StudyRuntime(svc,CheckpointStore(output/'runs'),model,spec).run(request,access)
            checks=quality_checks(report)
            checks.update(facts_unchanged=digest(report['facts'])==case['facts_hash'],
                          hypotheses_unchanged=digest(report['hypotheses'])==case['hypotheses_hash'],
                          anchor_unchanged=digest(report['event_anchor'])==case['anchor_hash'])
            decisive=sum(h['status']!='insufficient' for h in report['hypotheses'])
            write(output/(case['id']+'.json'),report)
            (output/(case['id']+'.md')).write_text(markdown(report),encoding='utf-8')
            results.append({'case':case['id'],'cohort':case.get('cohort','legacy'),'passed':all(checks.values()),'checks':checks,'model':report['model'],
                            'substantive_tests_completed':decisive,'requested_hypotheses':len(report['hypotheses']),
                            'research_status':report['research_status'],'report_hash':digest(report)})
            if dispatched:
                state['intents'][-1]['measured_tokens']=report['model'].get('total_tokens')
                state['intents'][-1]['receipt_status']=report['model']['status']
                root_store.append('phase3-quality',root_id,state)
            print(json.dumps({'case':case['id'],'passed':all(checks.values()),'model_status':report['model']['status'],
                              'substantive_tests_completed':decisive}),flush=True)
    result={'kind':'live_deepseek_bounded_phase3_quality','manifest_sha256':manifest_sha,
            'rubric_version':manifest['rubric_version'],'tasks_total':len(results),'tasks_passed':sum(r['passed'] for r in results),
            'task_quality_rate':sum(r['passed'] for r in results)/len(results),'threshold_task_quality':manifest['threshold_task_quality'],
            'live_model_verified':sum(r['model']['status']=='verified' for r in results),
            'substantive_tests_completed':sum(r['substantive_tests_completed'] for r in results),
            'requested_hypotheses':sum(r['requested_hypotheses'] for r in results),
            'root_dispatches':state['dispatches'],'root_tokens_reserved':state['reserved'],
            'known_measured_tokens':sum(r['model'].get('total_tokens') or 0 for r in results),
            'unknown_usage_calls':sum(r['model'].get('total_tokens') is None for r in results),
            'financial_provider_network_calls':0,'general_phase3_quality_certified':False,'cases':results}
    result['cohorts']={name:{'tasks':sum(c['cohort']==name for c in results),
                             'passed':sum(c['cohort']==name and c['passed'] for c in results)}
                        for name in sorted({c['cohort'] for c in results})}
    result['cohort_thresholds_passed']=all(result['cohorts'][name]['passed']/result['cohorts'][name]['tasks']>=threshold
                                           for name,threshold in manifest.get('cohort_thresholds',{}).items())
    write(output/'result.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='cases'}))


def replay(manifest_path,directory,output):
    manifest=json.loads(manifest_path.read_bytes())
    saved=json.loads((directory/'result.json').read_bytes())
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest()==saved['manifest_sha256']
    output.mkdir(parents=True,exist_ok=False)
    config=load_model_config()
    dispatches=0
    def forbid(*args,**kwargs):
        nonlocal dispatches
        dispatches+=1
        raise AssertionError('quality replay attempted network dispatch')
    checked=[]
    for case in manifest['cases']:
        report=json.loads((directory/(case['id']+'.json')).read_bytes())
        svc,access=source_context(case)
        request=StudyRequest.from_dict(case['request'])
        runtime=StudyRuntime(svc,CheckpointStore(directory/'runs'),ChatModelAdapter(config,forbid),
                             StudySpec(**manifest.get('spec',{'version':manifest.get('spec_version','single-research-v1')})))
        assert runtime.run(request,access,resume=report['run_id'])==report
        assert digest(report)==next(r['report_hash'] for r in saved['cases'] if r['case']==case['id'])
        data=read_inputs(svc,request,access)
        if 'independent_expected' in case:
            from fractions import Fraction
            expected={n:Fraction(*v) for n,v in case['independent_expected'].items()}
        else:
            expected,_=oracle(data)
        from decimal import Decimal
        from fractions import Fraction
        facts={f['name']:f for f in report['facts']}
        assert set(expected)==set(facts)
        assert all(abs(Fraction(Decimal(facts[n]['value']))-v)<Fraction(1,10**28) for n,v in expected.items())
        try:
            runtime.run(request,AccessContext(access.scope,frozenset({'denied-source'})),resume=report['run_id'])
        except PermissionDenied:
            pass
        else:
            raise AssertionError('revoked source allowed')
        checked.append({'case':case['id'],'numeric_claims':len(facts),'evidence':len(report['evidence']),'replay_identical':True})
    result={'tasks':len(checked),'numeric_claims':sum(r['numeric_claims'] for r in checked),'evidence':sum(r['evidence'] for r in checked),
            'identical_replays':len(checked),'revocation_checks':len(checked),'model_dispatches':dispatches,'cases':checked}
    write(output/'result.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='cases'}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--manifest',type=Path,default=ROOT/'baseline-manifest.json')
    parser.add_argument('--replay',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.prepare: prepare_baseline()
    elif args.live: live(args.manifest,args.output)
    else: replay(args.manifest,args.replay,args.output)
