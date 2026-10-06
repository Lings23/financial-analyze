"""Offline report repair with original live-model scores and receipts preserved."""
import argparse
import hashlib
import json
from pathlib import Path

from accept_phase2_real import write
from accept_phase3_quality import ROOT, quality_checks, source_context
from stock_research.model_adapters.chat import ChatModelAdapter, load_model_config
from stock_research.models import digest
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.report import markdown, displayed_highlights, study_supplements
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudyRequest, StudySpec


def evaluate(manifest_path,directory,output):
    manifest=json.loads(manifest_path.read_bytes())
    saved=json.loads((directory/'result.json').read_bytes())
    manifest_sha=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert manifest_sha==saved['manifest_sha256']
    contract=json.loads((ROOT/'presentation-contract.json').read_bytes())
    assert digest(contract)=='c6e3fa2bc515da2b58680d94882796751b015a228a842387896cb8a80dc2e1fb'
    authorization=json.loads((ROOT/'authorization-approved.json').read_bytes())
    assert authorization['manifest_sha256']==manifest_sha
    state=CheckpointStore(ROOT/'root-budget').read('phase3-quality','31022026000000000000000000000001')
    assert state['dispatches']==29==len(state['intents'])==len({i['case'] for i in state['intents']})
    assert state['manifest_sha256']==manifest_sha
    output.mkdir(parents=True,exist_ok=False)
    calls=0
    def forbid(*args,**kwargs):
        nonlocal calls
        calls+=1
        raise AssertionError('offline presentation repair attempted a paid dispatch')
    config=load_model_config()
    cases=[]
    for case in manifest['cases']:
        original=directory/(case['id']+'.json')
        raw=original.read_bytes()
        report=json.loads(raw)
        recorded=next(c for c in saved['cases'] if c['case']==case['id'])
        assert digest(report)==recorded['report_hash']
        svc,access=source_context(case)
        runtime=StudyRuntime(svc,CheckpointStore(directory/'runs'),ChatModelAdapter(config,forbid),
                             StudySpec(version='single-research-v1'))
        assert runtime.run(StudyRequest.from_dict(case['request']),access,resume=report['run_id'])==report
        raw_checks=quality_checks(report)
        assert all(v==recorded['checks'][k] for k,v in raw_checks.items())
        shown,_=displayed_highlights(report)
        added=study_supplements(report)
        visible=shown+added
        display_checks=quality_checks(report,visible_highlights=[f['id'] for f in visible])
        expected=set(contract['required_supplements'].get(case['id'],[]))
        assert expected<={f['name'] for f in added}
        assert {f['id'] for f in added}<={f['id'] for f in report['facts']}
        rendered=markdown(report)
        assert not added or '不是模型选择' in rendered and all(f['id'] in rendered for f in added)
        assert digest(report)==recorded['report_hash'] and original.read_bytes()==raw
        (output/(case['id']+'.md')).write_text(rendered,encoding='utf-8')
        cases.append({'case':case['id'],'original_report_sha256':hashlib.sha256(raw).hexdigest(),
                      'raw_model_quality_passed':recorded['passed'],'presentation_passed':all(display_checks.values()),
                      'presentation_checks':display_checks,'system_supplement_ids':[f['id'] for f in added],
                      'system_supplement_names':[f['name'] for f in added],'raw_report_unchanged':True})
    result={'kind':'offline_system_supplement_report_quality','tasks':len(cases),
            'original_model_tasks_passed':saved['tasks_passed'],'original_model_quality_rate':saved['task_quality_rate'],
            'presentation_tasks_passed':sum(c['presentation_passed'] for c in cases),
            'reports_with_system_supplements':sum(bool(c['system_supplement_ids']) for c in cases),
            'raw_model_score_preserved':True,'immutable_reports_verified':len(cases),
            'model_dispatches':calls,'live_campaign_dispatches':state['dispatches'],
            'live_token_receipts_sum':sum(i['measured_tokens'] for i in state['intents']),
            'financial_provider_network_calls':0,'general_phase3_quality_certified':False,'cases':cases}
    assert result['live_token_receipts_sum']==saved['known_measured_tokens']
    write(output/'result.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='cases'}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',type=Path,default=ROOT/'proposed-model-manifest.json')
    parser.add_argument('--directory',type=Path,default=ROOT/'live-approved')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    evaluate(args.manifest,args.directory,args.output)
