"""Preregistered second repair: all v2 tasks plus six unseen comparison windows."""
import argparse
from dataclasses import replace
from datetime import date
import json
from pathlib import Path

from accept_phase3_quality import live, replay
from phase3_followup import ROOT as V2_ROOT, prepare, audit, pool, sha
from stock_research.research.contracts import Binding
from stock_research.research.study_contracts import StudyRequest, StudySpec

ROOT=V2_ROOT/'v3'
LIMITS={'max_dispatches':43,'max_token_reservations':600000,'max_seconds':2400}


def cases():
    previous=json.loads((V2_ROOT/'model-manifest.json').read_bytes())
    for item in previous['cases']:
        yield {**item,'previous_cohort':item['cohort'],'cohort':'regression_v2'}
    index=next(r for r in pool()['p18'][2]['results'] if r['request']['dataset']=='index_daily')
    for item in previous['cases']:
        if not item['id'].startswith('catalogue-'): continue
        old=StudyRequest.from_dict(item['request'])
        bindings=[replace(b,start=date(2024,9,18),end=date(2024,9,27)) if b.dataset=='market_daily' else b
                  for b in old.bindings if b.dataset in {'market_daily','financial_income'}]
        bindings.append(Binding('index_daily',index['snapshot_id'],'tushare',date(2024,9,18),date(2024,9,27)))
        request=replace(old,bindings=tuple(bindings),benchmark='000300.SH',hypotheses=('market_direction',))
        yield {'id':'transfer-'+old.security.symbol,'kind':'real_scoped_catalogue','cohort':'window_transfer',
               'scope':item['scope'],'source_files':item['source_files'],'request':request.to_dict(),
               'routes':{'market_daily':'pilot','financial_income':'pilot','index_daily':'p18'}}


if __name__=='__main__':
    p=argparse.ArgumentParser(); action=p.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare',action='store_true'); action.add_argument('--audit',action='store_true')
    action.add_argument('--live',action='store_true'); action.add_argument('--replay',type=Path)
    p.add_argument('--manifest',type=Path,default=ROOT/'model-manifest.json')
    p.add_argument('--output',type=Path); p.add_argument('--expected-manifest-sha256')
    a=p.parse_args()
    if a.prepare:
        prepare(a.manifest,selected_cases=cases(),spec=StudySpec(context_bytes=24000,max_tokens=28000),
                root=ROOT,limits=LIMITS,previous_manifest=V2_ROOT/'model-manifest.json')
    elif not a.output: p.error('output required')
    elif a.audit: audit(a.manifest,a.output)
    elif a.live:
        if not a.expected_manifest_sha256 or sha(a.manifest)!=a.expected_manifest_sha256:
            p.error('live dispatch requires reviewed exact manifest SHA256')
        live(a.manifest,a.output,root=ROOT,limits=LIMITS)
    else: replay(a.manifest,a.replay,a.output)
