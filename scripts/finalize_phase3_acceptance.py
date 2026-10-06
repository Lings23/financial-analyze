"""Read-only closing audit of approved manifests, paid ledgers and model receipts."""
import json
from pathlib import Path

from accept_phase2_real import write
from accept_phase3_quality import quality_checks
from phase3_followup import sha
from stock_research.models import digest
from stock_research.research.checkpoints import CheckpointStore


ROOT=Path('.artifacts/phase3/followup-20261002')


def audit():
    campaigns=[]
    for root,directory,replay in ((ROOT,ROOT/'live-v2',ROOT/'live-v2-replay'),
                                   (ROOT/'v3',ROOT/'v3/live',ROOT/'v3/live-replay')):
        path=root/'model-manifest.json'
        manifest=json.loads(path.read_bytes()); expected_sha=sha(path)
        approved=json.loads((root/'authorization-approved.json').read_bytes())
        saved=json.loads((directory/'result.json').read_bytes())
        replay_result=json.loads((replay/'result.json').read_bytes())
        state=CheckpointStore(root/'root-budget').read('phase3-quality','31022026000000000000000000000001')
        assert approved['manifest_sha256']==saved['manifest_sha256']==state['manifest_sha256']==expected_sha
        assert state['dispatches']==len(state['intents'])==len(manifest['cases'])==approved['max_calls']
        assert len({i['case'] for i in state['intents']})==state['dispatches']
        assert state['reserved']==sum(i['reservation'] for i in state['intents'])<=approved['token_reservation_cap']
        assert replay_result['identical_replays']==len(manifest['cases']) and replay_result['model_dispatches']==0
        receipts=0; tokens={'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}; full_tasks=0
        for case in manifest['cases']:
            report=json.loads((directory/(case['id']+'.json')).read_bytes())
            recorded=next(r for r in saved['cases'] if r['case']==case['id'])
            intent=next(i for i in state['intents'] if i['case']==case['id'])
            assert digest(report)==recorded['report_hash']
            assert all(recorded['checks'][k]==v for k,v in quality_checks(report).items())
            assert intent['messages_hash']==digest(case['messages']) and intent['manifest_sha256']==expected_sha
            assert intent['measured_tokens']==report['model']['total_tokens']
            for k in tokens: tokens[k]+=report['model'][k]
            full_tasks+=report['research_status']=='tests_completed'
            if manifest.get('save_bounded_model_receipts'):
                receipt=json.loads((directory/('receipt-'+case['id']+'.json')).read_bytes())
                assert receipt['requested_model']==receipt['returned_model']==manifest['model']
                choice=json.loads(receipt['content'])
                assert choice in json.loads(case['messages'][1]['content'])['selection_options']
                aliases={f'F{i+1}':f['id'] for i,f in enumerate(report['facts'])}
                assert [aliases[a] for a in choice['highlights']]==report['model']['highlights']
                assert choice['hypotheses']==report['model']['hypotheses']
                assert receipt['total_tokens']==intent['measured_tokens']
                receipts+=1
        assert tokens['total_tokens']==saved['known_measured_tokens']
        campaigns.append({'version':manifest['spec_version'],'manifest_sha256':expected_sha,
                          'dispatches':state['dispatches'],'reserved_tokens':state['reserved'],**tokens,
                          'selection_tasks_passed':saved['tasks_passed'],'substantive_complete_tasks':full_tasks,
                          'receipt_checks':receipts,'identical_replays':replay_result['identical_replays'],
                          'numeric_claims':replay_result['numeric_claims'],'evidence':replay_result['evidence'],
                          'cohorts':saved['cohorts'],'cohort_thresholds_passed':saved['cohort_thresholds_passed']})
    latest=campaigns[-1]
    assert latest['dispatches']==latest['selection_tasks_passed']==latest['receipt_checks']==43
    assert latest['substantive_complete_tasks']==14 and latest['cohort_thresholds_passed']
    providers=json.loads((ROOT/'event-prices/result.json').read_bytes())['provider_stats']
    assert providers['attempts']==2 and providers['retries']==0
    result={'bounded_catalogue_and_selection_acceptance_passed':True,
            'scope':'fixed hypothesis catalogue; existing real regression, explicit six-security/eight-task extension and six-window transfer',
            'total_this_followup_model_dispatches':sum(c['dispatches'] for c in campaigns),
            'total_this_followup_measured_tokens':sum(c['total_tokens'] for c in campaigns),
            'financial_provider_attempts':2,'retries':0,'model_substitutions':0,
            'historical_23_of_29_preserved':True,'v2_31_of_37_preserved':True,
            'historical_insufficient_hypotheses_still_insufficient':110,
            'general_phase3_quality_certified':False,'expert_blind_quality_certified':False,
            'source_accuracy_certified_by_this_audit':False,'campaigns':campaigns}
    write(ROOT/'final-acceptance.json',result)
    print(json.dumps(result))


if __name__=='__main__': audit()
