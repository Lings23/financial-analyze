"""Replay a single official block-trade diagnostic; never change quality scores."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT = Path('.artifacts/p17_20261001/szse_history_discovery')
OUTPUT = ROOT / 'block-diagnosis.json'
EXPECTED = {
    'block-probe.json': '01724210cf4b874d5605d94121f92774a9a8455cfd46c6f30e3b6f0d7c9ed277',
    'block-detail-probe.json': 'e7b714b82c226005c1b58be8274e1790432d058cc6151ca97c323b4396a25150',
}


def number(value):
    result = Decimal(value.replace(',', ''))
    assert result.is_finite()
    return result


def check():
    sources = {}
    for name, expected in EXPECTED.items():
        data = (ROOT/name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected
        sources[name] = json.loads(data)
    summary = next(t for t in sources['block-probe.json'] if t['metadata']['tabkey'] == 'tab1')
    detail = sources['block-detail-probe.json'][0]
    for tab, expected_count in [(summary, 1), (detail, 4)]:
        m = tab['metadata']
        assert tab['error'] is None and m['pageno'] == m['pagecount'] == 1
        assert m['recordcount'] == len(tab['data']) == expected_count
    row = summary['data'][0]
    assert row['zqdm'] == '300750' and row['dqrq'] == '2024-09-26'
    assert '万股' in summary['metadata']['footer'] and '万元' in summary['metadata']['footer']
    assert '万股' in detail['metadata']['footer'] and '万元' in detail['metadata']['footer']
    for trade in detail['data']:
        assert trade['zqdh'] == row['zqdm'] and trade['cjrq'] == row['dqrq']
    qty = number(row['cjsl']) * 10000
    amount = number(row['cjje']) * 10000
    assert sum(number(t['cjgsnew']) * 10000 for t in detail['data']) == qty
    assert sum(number(t['cjjenew']) * 10000 for t in detail['data']) == amount
    base_path = Path('.artifacts/p17_20261001/szse_archive/comparison.json')
    gap_path = Path('.artifacts/p17_20261001/szse_archive_gap/comparison.json')
    cells = {(c['group'],c['code'],c['date'],c['field']): c
             for c in json.loads(base_path.read_bytes())['cells']}
    for c in json.loads(gap_path.read_bytes())['cells']:
        key = c['group'],c['code'],c['date'],c['field']
        assert cells[key]['status'] == 'missing_reference' and cells[key]['record_id'] == c['record_id']
        cells[key] = c
    mismatches = [c for c in cells.values() if c['status'] == 'mismatch']
    assert len(cells) == 540 and len(mismatches) == 99
    by_field = Counter(c['field'] for c in mismatches)
    signs = Counter('positive' if Decimal(c['difference']) > 0 else 'negative' for c in mismatches)
    residuals = {}
    for field, block in [('volume',qty),('amount',amount)]:
        c = cells['original','300750','2024-09-26',field]
        deficit = Decimal(c['reference']) - Decimal(c['actual'])
        residuals[field] = {'all_trade_reference_minus_tushare':str(deficit),
                            'printed_block_total':str(block),
                            'unresolved_after_subtracting_printed_block_total':str(deficit-block)}
        assert deficit-block > Decimal(c['tolerance'])
    return {'checked_at':datetime.now(timezone.utc).isoformat(), 'source_sha256':EXPECTED,
            'comparison_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [base_path,gap_path]},
            'code':row['zqdm'],'date':row['dqrq'],'complete_agreement_trade_rows':4,
            'printed_summary_equals_printed_detail_sums':True,'residuals':residuals,
            'strict_registered_cells':540,'strict_matches':441,'strict_mismatches':99,
            'mismatches_by_field':dict(by_field),'mismatch_signs':dict(signs),
            'financial_values_or_tolerances_modified':False,'quality_scores_upgraded':False,
            'historical_publication_not_upgraded':True,'phase1_complete':False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only',action='store_true')
    args = parser.parse_args()
    report = check()
    if args.verify_only:
        old = json.loads(OUTPUT.read_bytes())
        assert {k:v for k,v in old.items() if k!='checked_at'} == {k:v for k,v in report.items() if k!='checked_at'}
    else:
        with OUTPUT.open('x',encoding='utf-8') as stream:
            json.dump(report,stream,indent=2)
    print(json.dumps(report))
    return 0  # Evidence verification only; quality failures remain in their comparison.


if __name__ == '__main__':
    raise SystemExit(main())
