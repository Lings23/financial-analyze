"""Recheck locked original-text qualifications; preserve initial missing report."""
from datetime import date
import hashlib
import json
from pathlib import Path
import subprocess

from stock_research.models import utcnow
from stock_research.storage.artifacts import ArtifactStore

ROOT = Path('.artifacts/p17_20261001/formal')
RULE = Path('evaluation/p17_20261001_formal_strata_qualification.json')


def main():
    rule = json.loads(RULE.read_bytes()); plan_path = Path('evaluation/p17_20261001_formal_plan.json')
    assert rule['formal_plan_sha256'] == hashlib.sha256(plan_path.read_bytes()).hexdigest()
    plan = json.loads(plan_path.read_bytes()); comparison = json.loads((ROOT/'comparison.json').read_text(encoding='utf8'))
    assert rule['initial_comparison_sha256'] == hashlib.sha256((ROOT/'comparison.json').read_bytes()).hexdigest()
    cache = {}
    def verify(source):
        if 'artifact_root' in source:
            data = ArtifactStore(source['artifact_root']).get(source['scope'],source['pdf_sha256'])
            assert Path(source['path']).read_bytes() == data
        else: data = Path(source['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == source['pdf_sha256']
        for proof in source['proofs']:
            key = source['path'],proof['page']
            if key not in cache:
                cache[key] = ''.join(subprocess.run(['pdftotext','-enc','UTF-8','-layout','-f',str(proof['page']),
                    '-l',str(proof['page']),source['path'],'-'],capture_output=True,check=True,timeout=15).stdout.decode('utf8').split())
            assert all(''.join(a.split()) in cache[key] for a in proof['anchors'])
    listings = []
    for item in rule['listings']:
        verify(item['source']); security = next(s for s in plan['securities'] if s['symbol'] == item['symbol'])
        assert item['listing_date'].replace('-','') == security['list_date'] and security['stratum'] == 'new_listing'
        age = (date.fromisoformat(plan['daily_windows'][0]['start'])-date.fromisoformat(item['listing_date'])).days
        assert 0 <= age <= 90
        listings.append({'symbol':item['symbol'],'listing_date':item['listing_date'],'age_days_at_first_window':age,
                         'source_sha256':item['source']['pdf_sha256']})
    qualified = []
    for item in rule['halts']:
        for source in item['sources']: verify(source)
        days = set(item['absent_dates']); assert days <= set(plan['daily_windows'][1]['dates'])
        cells = [c for c in comparison['market_cells'] if c['symbol'] == item['symbol'] and c['date'] in days]
        assert len(cells) == len(days)*6 and all(c['status'] == 'missing_provider_and_reference' for c in cells)
        qualified.extend({'symbol':item['symbol'],'date':day,'fields':6,'status':'officially_qualified_expected_absence'} for day in sorted(days))
    total = sum(e['fields'] for e in qualified)
    assert total == 72
    output = {'checked_at':utcnow().isoformat(),'qualification_sha256':hashlib.sha256(RULE.read_bytes()).hexdigest(),
              'listing_qualifications':listings,'unverified_listing_symbols':['920016'],
              'qualified_absence_dates':qualified,'qualified_absence_cells':total,
              'initial_market_matched':comparison['market_matched'],'remaining_numeric_market_reference_missing':942,
              'absences_are_not_numeric_matches':True,'ordinary_providers_still_observed_at':True,
              'initial_comparison_preserved':True,'phase1_complete':False}
    target = ROOT/'strata-qualification.json'
    if target.exists():
        prior = json.loads(target.read_text(encoding='utf8'))
        assert {k:v for k,v in prior.items() if k != 'checked_at'} == {k:v for k,v in output.items() if k != 'checked_at'}
    else:
        with target.open('x',encoding='utf8') as stream: json.dump(output,stream,ensure_ascii=False,indent=2)
    print(json.dumps(output,ensure_ascii=False))


if __name__ == '__main__': main()
