"""Freeze a larger QA sample from hash-checked current metadata before values."""
import hashlib
import json
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

from stock_research.models import utcnow
from stock_research.storage.artifacts import ArtifactStore

ROOT = Path('.artifacts/p17_20261001/formal_discovery')
PLAN = Path('evaluation/p17_20261001_formal_plan.json')
SEED = 'phase1-formal-20261001-v1'
PILOT = {'600000.SH', '688590.SH', '000001.SZ', '300750.SZ', '600519.SH', '920118.BJ'}


def load(root, index):
    run = json.loads((root/'run.json').read_text(encoding='utf8'))
    item = run['results'][index]
    assert item['status'] == 'collected'
    body = json.loads(ArtifactStore(root/'artifacts').get(run['scope'], item['artifact_id']))
    source = {'root': str(root/'artifacts'), 'scope': run['scope'], 'artifact_id': item['artifact_id'],
              'run_path': str(root/'run.json'), 'run_sha256': hashlib.sha256((root/'run.json').read_bytes()).hexdigest()}
    return body, source


def ranked(rows, label):
    return sorted(rows, key=lambda r: (hashlib.sha256((SEED+'|'+label+'|'+r['ts_code']).encode()).hexdigest(), r['ts_code']))


def main():
    if PLAN.exists(): raise ValueError('formal plan exists; refusing overwrite')
    basic, source_basic = load(ROOT, 0)
    halt, source_halt = load(ROOT, 1)
    titles, source_titles = load(ROOT, 2)
    liquid, source_liquid = load(ROOT/'liquidity_2026-09-24/decimal_fixed', 0)
    stocks = [dict(zip(basic['fields'], r)) for r in basic['items']]
    assert len({r['ts_code'] for r in stocks}) == len(stocks) == 5572
    eligible = [r for r in stocks if r['list_date'] and r['list_date'] <= '20240918' and r['ts_code'] not in PILOT]
    bycode = {r['ts_code']: r for r in eligible}
    selected, used = [], set()

    def add(row, stratum, note):
        assert row['ts_code'] not in used and row['ts_code'] not in PILOT
        used.add(row['ts_code'])
        selected.append({**row, 'symbol': row['symbol'], 'stratum': stratum, 'selection_note': note})

    for row in ranked([r for r in eligible if r['industry'] == '银行'], 'bank')[:2]:
        add(row, 'bank', 'Two SHA-ranked current bank-industry records; current industry is not historical classification')
    groups = [('SSE', '主板'), ('SSE', '科创板'), ('SZSE', '创业板'), ('BSE', '北交所')]
    for ex, market in groups:
        candidates = [r for r in eligible if r['exchange'] == ex and r['market'] == market and '20240601' <= r['list_date'] <= '20240918']
        row = sorted(candidates, key=lambda r: (r['list_date'], r['ts_code']), reverse=True)[0]
        add(row, 'new_listing', 'Latest metadata listing date between 2024-06-01 and first window; official listing-date proof pending')
    for code in ('600301.SH', '000016.SZ'):
        assert any(r[0] == code for r in halt['items'])
        assert any(r['secCode'] == code[:6] and ('股票' in r['announcementTitle'] or
                   '控制权' in r['announcementTitle']) for r in titles['rows'])
        add(bycode[code], 'halt_candidate', 'Fixed SSE/SZSE stock-halt candidates from suspend_d plus CNINFO titles; actual dates require PDF proof')
    volumes = {r[0]: Decimal(r[2]) for r in liquid['items'] if r[2] is not None}
    for ex in ('SSE', 'BSE'):
        candidates = [r for r in eligible if r['exchange'] == ex and r['ts_code'] not in used and volumes.get(r['ts_code'], Decimal(0)) > 0]
        row = min(candidates, key=lambda r: (volumes[r['ts_code']], r['ts_code']))
        add(row, 'low_volume_proxy', 'Lowest positive Tushare volume on 2026-09-24 in current eligible exchange population; selection metadata, not independent truth')
    populations = {}
    for ex, market in [('SSE','主板'), ('SSE','科创板'), ('SZSE','主板'), ('SZSE','创业板'), ('BSE','北交所')]:
        label = ex+':'+market
        candidates = [r for r in eligible if r['exchange'] == ex and r['market'] == market and r['ts_code'] not in used]
        populations[label] = len(candidates)
        for row in ranked(candidates, label)[:3]:
            add(row, 'board_draw:'+label, 'First three by SHA256(seed|board|ts_code), excluding pilot and previously selected special strata')
    assert len(selected) == len(used) == 25
    sse = json.loads(Path('evaluation/p17_20261001_sse_reference_plan.json').read_text(encoding='utf8'))
    szse = json.loads(Path('evaluation/p17_20261001_szse_reference_plan.json').read_text(encoding='utf8'))
    szse['fields']['volume']['tolerance'] = '50'
    plan = {'version': '20261001-v1', 'created_at': utcnow().isoformat(), 'scope': 'p17-formal-20261001',
        'reference_scope': 'p17-formal-reference-20261001', 'seed': SEED, 'population_sources': [source_basic, source_halt, source_titles, source_liquid],
        'current_population_count': len(stocks), 'eligible_count': len(eligible), 'board_draw_pool_counts': populations,
        'selection_bias': 'Currently L-listed stocks only; surviving-universe bias, current names/industry, SHA deterministic draw not iid certification. No whole-market confidence bound claimed.',
        'pilot_excluded': sorted(PILOT), 'securities': selected,
        'daily_windows': [dict(w, dates=days) for w, days in zip(sse['windows'], [
            ['2024-09-18','2024-09-19','2024-09-20','2024-09-23','2024-09-24','2024-09-25','2024-09-26','2024-09-27','2024-09-30'],
            ['2026-09-15','2026-09-16','2026-09-17','2026-09-18','2026-09-21','2026-09-22','2026-09-23','2026-09-24']])],
        'calendar_note': 'Same frozen pilot sessions; 2026-09-25 official Mid-Autumn closure, not a missing daily observation.',
        'financial_periods': ['2024-12-31','2025-03-31','2025-06-30'],
        'financial_fields': ['revenue','total_revenue','net_income_parent'],
        'potential_market_cells': 25*17*6, 'financial_cells':25*3*3,
        'missing_rules': 'All registered security/date/field and financial period/field cells remain enumerated. Missing provider, missing reference, NULL, and unproved halt are distinct; no replacement or denominator removal. Officially proved non-trading halt may later be a separately reported expected absence, never numeric match.',
        'financial_reference_rules': 'CNINFO/exchange original consolidated cumulative type-1 report of same version, exact printed field and units; no revenue/total-revenue alias. No reference means unverified.',
        'historical_pit_note': 'Ordinary Tushare values observed_at. Historical-version qualification is a separate gate, not provided by historical dates here.',
        'min_interval_seconds':2.5, 'max_attempts':1, 'attempt_timeout':15, 'total_timeout':20,
        'sse_reference': {k:sse[k] for k in ('params','renderer_path','renderer_sha256','page_url','fields')},
        'szse_reference': {k:szse[k] for k in ('url','page_url','params','source_sha256','fields')},
        'bse_reference': {'status':'not_available', 'note':'No verified accessible official historical endpoint; keep all cells unverified'},
        'halt_pdf_references': [r for r in titles['rows'] if r['secCode'] in {'600301','000016'} and ('股票' in r['announcementTitle'] or '控制权' in r['announcementTitle'])],
        'gates': {'suggested_numeric_accuracy':'0.995','require_reported_missing_strata':True, 'whole_phase1_complete':False}}
    paths = ['scripts/prepare_p17_formal_plan.py','scripts/run_p17_formal.py','scripts/check_p17_formal_market.py','scripts/exchange_http.py',
             'src/stock_research/providers/tushare.py','src/stock_research/providers/executor.py','src/stock_research/service.py']
    plan['code_sha256'] = {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
    with PLAN.open('x',encoding='utf8') as stream: json.dump(plan,stream,ensure_ascii=False,indent=2)
    print(json.dumps({'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),'securities':len(selected),'strata':dict(Counter(r['stratum'] for r in selected)),
                      'market_cells':plan['potential_market_cells'],'financial_cells':plan['financial_cells']},ensure_ascii=False))


if __name__ == '__main__': main()
