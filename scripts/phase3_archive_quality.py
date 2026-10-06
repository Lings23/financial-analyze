"""Explicit quality repair from real pinned archive, stored in a reference repository.

No production database writes and no new financial Provider calls. Every replay
revalidates the original source authorization, pinned bytes and exact projection.
"""
from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path

from accept_phase2_real import service, read_inputs, write, oracle
from stock_research.errors import IntegrityError
from stock_research.models import AccessContext, QueryContext, digest, utcnow
from stock_research.research.archive import project_archived_income
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.context import study_messages
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudyRequest, StudySpec
from stock_research.service import DataService
from stock_research.storage.memory import MemoryRepository
from phase3_benchmark_gate import precheck_cases, require_valid_precheck


def projection_service(svc, access, original, ingestion):
    data=read_inputs(svc,original,access)
    expanded, projected, provenance=project_archived_income(svc,original,access,ingested_at=ingestion)
    records=tuple(data['market_daily'])+projected
    repo=MemoryRepository()
    snapshot=repo.commit(access.scope,records)
    request=replace(original,as_of=max(original.as_of,ingestion),bindings=tuple(
        replace(b,snapshot=snapshot.snapshot_id,start=expanded.start,end=expanded.end)
        if b.dataset=='financial_income' else replace(b,snapshot=snapshot.snapshot_id) for b in original.bindings))
    # Explicit reference repository for the acceptance prototype, not an implicit
    # production persistence fallback. Artifact reads still use original authorized scope.
    reference=DataService(svc.registry,None,repo,svc.artifacts)
    return reference,request,records,provenance


def replay_projection(path, expected_sha):
    path=Path(path)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected_sha:
        raise IntegrityError('frozen projection file changed')
    saved=json.loads(path.read_bytes())
    original=StudyRequest.from_dict(saved['source_request'])
    access=AccessContext(saved['scope'],frozenset({'tushare'}))
    svc=service()
    reference,request,records,provenance=projection_service(svc,access,original,datetime.fromisoformat(saved['projection_ingested_at']))
    if (digest([r.to_dict() for r in records])!=saved['records_hash'] or request.to_dict()!=saved['projected_request']
            or provenance!=saved['provenance']):
        raise IntegrityError('authorized archive projection differs')
    return reference,access


def prepare(path,root_limits):
    if path.exists():
        raise IntegrityError('manifest is immutable; use a new benchmark location')
    corpus=json.loads(Path('evaluation/phase3_real_cases_20261002.json').read_bytes())
    root=path.parent/(path.stem+'-projections')
    root.mkdir(parents=True,exist_ok=False)
    svc=service(); access=AccessContext(corpus['scope'],frozenset({'tushare'}))
    staged=[]
    for item in corpus['cases']:
        if item['request']['bindings'][0]['start']!='2026-09-15': continue
        original=StudyRequest.from_dict(item['request'])
        ingestion=utcnow()
        reference,request,records,provenance=projection_service(svc,access,original,ingestion)
        staged.append((item,original,ingestion,reference,request,records,provenance))
    candidates=[{'id':item['id'],'scope':access.scope,'request':request.to_dict()}
                for item,original,ingestion,reference,request,records,provenance in staged]
    sources={item['id']:(reference,access) for item,original,ingestion,reference,request,records,provenance in staged}
    precheck=precheck_cases(candidates,lambda case:sources[case['id']])
    write(path.parent / (path.stem + '-contract-precheck.json'),precheck)
    require_valid_precheck(candidates,precheck)
    cases=[]
    for item,original,ingestion,reference,request,records,provenance in staged:
        target=root/(item['id']+'.json')
        write(target,{'kind':'real_pinned_archive_projection_reference','scope':access.scope,'source_request':original.to_dict(),
                      'projection_ingested_at':ingestion.isoformat(),'projected_request':request.to_dict(),
                      'records_hash':digest([r.to_dict() for r in records]),'records':[r.to_dict() for r in records],
                      'provenance':provenance,'financial_provider_network_calls':0})
        data=read_inputs(reference,request,access)
        expected,_=oracle(data)
        original_expected,_=oracle(read_inputs(svc,original,access))
        assert all(expected[k]==v for k,v in original_expected.items())
        report=StudyRuntime(reference,CheckpointStore(path.parent/(path.stem+'-offline-runs'))).run(request,access)
        # Oracle is exact arithmetic from source-bound projected inputs, independent
        # of the production Decimal formulas. Frozen before any real-model dispatch.
        expected_state='insufficient'
        if {'revenue_yoy','net_income_parent_yoy'}<=set(expected):
            declines=[expected[n]<0 for n in ('revenue_yoy','net_income_parent_yoy')]
            expected_state='supported' if all(declines) else 'conflicted' if any(declines) else 'unsupported'
        actual=next(h for h in report['hypotheses'] if h['id']=='financial_deterioration')
        assert actual['status']==expected_state
        write(root/(item['id']+'-offline-report.json'),report)
        cases.append({'id':item['id'],'kind':'real_archived_income_projection','scope':access.scope,'request':request.to_dict(),
                      'source_report_sha256':digest(report),'projection_path':str(target),'projection_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                      'input_hash':digest({k:[r.to_dict() for r in rows] for k,rows in data.items()}),
                      'facts_hash':digest(report['facts']),'hypotheses_hash':digest(report['hypotheses']),
                      'anchor_hash':digest(report['event_anchor']),'messages':study_messages(report,request,StudySpec().context_bytes)[0],
                      'expected_financial_hypothesis':expected_state,'independent_expected':{k:[v.numerator,v.denominator] for k,v in expected.items()}})
    assert len(cases)==25
    manifest={'rubric_version':'phase3-selection-quality-v1','model':'deepseek-v4-flash-0731','endpoint':'test_api.txt configured HTTPS endpoint only',
              'threshold_task_quality':0.85,'max_dispatches':25,'root_limits':root_limits,'output_tokens':512,'cases':cases,
              'general_research_certified':False,'financial_provider_network_calls':0,'repair':'explicit pinned income archive projection, no backdated ingestion',
              'benchmark_contract_version':'benchmark-contract/v1','contract_precheck_sha256':digest(precheck)}
    write(path,manifest)
    print(json.dumps({'prepared_projection_calls':len(cases),'new_financial_provider_calls':0,
                      'financial_hypotheses':{s:sum(c['expected_financial_hypothesis']==s for c in cases) for s in ('supported','unsupported','conflicted','insufficient')},
                      'manifest_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}))


def audit(path, output):
    """Rebuild projections from authorized archives in a fresh process, no network."""
    from decimal import Decimal
    from fractions import Fraction
    from stock_research.errors import PermissionDenied
    from stock_research.research.report import markdown
    manifest=json.loads(path.read_bytes())
    output.mkdir(parents=True,exist_ok=False)
    cases=[]
    for case in manifest['cases']:
        reference,access=replay_projection(case['projection_path'],case['projection_sha256'])
        request=StudyRequest.from_dict(case['request'])
        data=read_inputs(reference,request,access)
        runtime=StudyRuntime(reference,CheckpointStore(output/'runs'))
        report=runtime.run(request,access)
        expected={k:Fraction(*v) for k,v in case['independent_expected'].items()}
        actual={f['name']:Fraction(Decimal(f['value'])) for f in report['facts']}
        assert set(actual)==set(expected)
        assert all(abs(actual[n]-v)<Fraction(1,10**28) for n,v in expected.items())
        assert digest(report['facts'])==case['facts_hash'] and digest(report['hypotheses'])==case['hypotheses_hash']
        assert StudyRuntime(reference,CheckpointStore(output/'runs')).run(request,access,resume=report['run_id'])==report
        try:
            runtime.run(request,AccessContext(access.scope,frozenset({'denied-source'})),resume=report['run_id'])
        except PermissionDenied:
            pass
        else:
            raise AssertionError('revoked archive source allowed')
        # SYSTEM cutoff before the actual projection ingestion must hide all new income rows.
        original=StudyRequest.from_dict(json.loads(Path(case['projection_path']).read_bytes())['source_request'])
        binding=next(b for b in request.bindings if b.dataset=='financial_income')
        prior=reference.query(request.data_request(binding),QueryContext(access,binding.snapshot,original.as_of,original.mode))
        assert not prior.records
        write(output/(case['id']+'.json'),report)
        (output/(case['id']+'.md')).write_text(markdown(report),encoding='utf-8')
        cases.append({'case':case['id'],'numeric_claims':len(actual),'evidence':len(report['evidence']),
                      'financial_hypothesis':case['expected_financial_hypothesis'],'replay_identical':True,
                      'revocation_denied':True,'system_before_projection_invisible':True})
    result={'tasks':len(cases),'numeric_claims':sum(c['numeric_claims'] for c in cases),
            'evidence':sum(c['evidence'] for c in cases),'identical_replays':len(cases),'revocation_checks':len(cases),
            'projection_pit_checks':len(cases),'model_dispatches':0,'financial_provider_network_calls':0,
            'financial_hypotheses':{s:sum(c['financial_hypothesis']==s for c in cases) for s in ('supported','unsupported','conflicted','insufficient')},
            'general_phase3_quality_certified':False,'cases':cases}
    write(output/'result.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='cases'}))


if __name__=='__main__':
    import argparse
    from accept_phase3_quality import LIMITS
    parser=argparse.ArgumentParser()
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare',action='store_true')
    action.add_argument('--audit',action='store_true')
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.prepare:
        prepare(args.manifest,LIMITS)
    elif args.output:
        audit(args.manifest,args.output)
    else:
        parser.error('--audit requires --output')
