"""Freeze original 85 BSE security-days for official rendered-tooltip QA."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    base_path=Path('evaluation/p17_20261001_formal_plan.json')
    run_path=Path('.artifacts/p17_20261001/formal/run.json')
    base=json.loads(base_path.read_bytes());run=json.loads(run_path.read_bytes())
    plan={'scope':'p17-bse-dom-reference-20261001','created_at':datetime.now(timezone.utc).isoformat(),
          'original_scope':base['scope'],'snapshot_id':run['results'][-1]['snapshot_id'],
          'original_finished_at':run['finished_at'],'original_artifacts':'.artifacts/p17_20261001/formal/artifacts',
          'securities':[s for s in base['securities'] if s['exchange']=='BSE'],
          'windows':base['daily_windows'],'registered_security_days':85,'registered_cells':510,
          'source_basis':'Actual official company daily-K rendered tooltip, with company/date/labels/units. Limited DOM projection, never original HTTP bytes or full-market completeness.',
          'rules':{'open':{'tolerance':'0.005','unit':'CNY'},'close':{'tolerance':'0.005','unit':'CNY'},
                   'high':{'tolerance':'0.005','unit':'CNY'},'low':{'tolerance':'0.005','unit':'CNY'},
                   'volume':{'tolerance':'50','multiplier':'10000','source_unit':'万股'},
                   'amount':{'tolerance':'50','multiplier':'10000','source_unit':'万元'}},
          'precision_basis':'Half printed final step; no proof of rounding/truncation and no post hoc tolerance enlargement.',
          'probe_seen_before_freeze':'920510/2026-09-15 six official tooltip values; not compared with Tushare before this plan.',
          'historical_identity_required_for_2024':True,'historical_publication_not_upgraded':True,
          'baseline_sha256':{str(p):digest(p) for p in [base_path,run_path,Path('.artifacts/p17_20261001/formal/comparison.json'),
                              Path('.artifacts/p17_20261001/szse_archive/extension.json')]},
          'phase1_complete':False}
    assert len(plan['securities'])==5 and sum(len(w['dates']) for w in plan['windows'])*5==85
    path=Path('evaluation/p17_20261001_bse_dom_reference_plan.json')
    with path.open('x',encoding='utf-8') as stream:json.dump(plan,stream,ensure_ascii=False,indent=2)
    print(json.dumps({'plan_sha256':digest(path),'registered_cells':510,'security_days':85}))


if __name__=='__main__':main()
