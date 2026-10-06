"""Audit the original research gates without equating selection with completion."""
from collections import Counter
import json
from pathlib import Path

from accept_phase2_real import write
from stock_research.models import digest, utcnow


ROOT=Path('.artifacts/phase3/fullscope-20261003')


def audit():
    source=Path('.artifacts/phase3/followup-20261002/v3/live')
    result=json.loads((source/'result.json').read_bytes())
    levels={'L3':{'tasks':0,'research_completed':0},'L5':{'tasks':0,'research_completed':0}}
    missing=Counter(); rows=[]
    for case in result['cases']:
        report=json.loads((source/(case['case']+'.json')).read_bytes())
        assert digest(report)==case['report_hash']
        level='L5' if report['request']['objective']=='event_review' else 'L3'
        complete=report['research_status']=='tests_completed' and case['passed']
        levels[level]['tasks']+=1; levels[level]['research_completed']+=complete
        missing.update(h['id'] for h in report['hypotheses'] if h['status']=='insufficient')
        rows.append({'case':case['case'],'level':level,'selection_passed':case['passed'],
                     'research_status':report['research_status'],'substantive_complete':complete})
    for v in levels.values():
        v['observed_completion_rate']=v['research_completed']/v['tasks']
        v['meets_85_percent_completion']=v['observed_completion_rate']>=0.85
    out={'checked_at':utcnow().isoformat(),'full_goal_completed':False,
         'prior_turn_classification':'progress: implemented repairs and obtained real v2/v3 evidence',
         'selection_proxy_success':{'passed':result['tasks_passed'],'total':result['tasks_total']},
         'substantive_completion_by_level':levels,'missing_hypotheses':dict(missing),
         'expert_independent_research_reference':'missing',
         'global_esr_and_hallucination_certification':'not_proven_by_id_selection_or_fraction_checks',
         'requirements':[
             {'id':'L3_L5_success','status':'incomplete','required':'independent real research success >=85%, separately by level'},
             {'id':'ESR','status':'unverified','required':'source-backed semantic support >=98%; lineage alone is insufficient'},
             {'id':'Hallucination','status':'unverified','required':'independent report-claim evaluation <=1%; constrained IDs alone insufficient'},
             {'id':'anchors','status':'partial','required':'100% required anchors within the actual task scope'},
             {'id':'evidence_gaps','status':'incomplete','required':'repair original missing inputs without removing hard cases or backdating'},
             {'id':'mechanisms','status':'verified_prior_run','required':'authorization/PIT/immutable snapshots/bounded calls; 227/227 dedicated tests'}],
         'cases':rows}
    write(ROOT/'completion-audit.json',out)
    print(json.dumps({k:v for k,v in out.items() if k!='cases'}))


if __name__=='__main__': audit()
