"""Authorized official-PDF references, independent of Tushare numeric answers.

Candidate extraction does not read the new provider values. Ambiguity stays open;
only separately reviewed source cells can be compared by the scoring command.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess

from accept_phase2_real import write
from phase3_followup import sha
from prepare_p17_formal_financial_values import NUM, compact
from stock_research.domains import DomainDataset, DomainRequest, Subject
from stock_research.models import AccessContext, PITMode, QueryContext
from stock_research.providers.base import ProviderRegistry
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository


ROOT = Path('.artifacts/phase3/fullscope-20261003/cashflow-reference')
FORMAL = Path('.artifacts/p17_20261001/formal')
SOURCES = ((FORMAL / 'financial_references/collection.json',
            Path('evaluation/p17_20261001_formal_financial_reference_plan.json')),
           (FORMAL / 'bse_qualified_references/collection.json',
            Path('evaluation/p17_20261001_bse_qualified_reference_plan.json')))


def sources():
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text().strip())
    for path, plan_path in SOURCES:
        collection = json.loads(path.read_bytes())
        assert collection['plan_sha256'] == sha(plan_path)
        service = DataService(ProviderRegistry(), None, db, ArtifactStore(path.parent / 'artifacts'))
        access = AccessContext(collection['scope'], frozenset({'cninfo'}))
        cutoff = datetime.fromisoformat(collection['finished_at']) + timedelta(seconds=1)
        for entry in collection['requests']:
            q = entry['request']
            if q['period'] != '2025-06-30':
                continue
            request = DomainRequest(Subject('equity', q['code'], q['exchange']), DomainDataset.ANNOUNCEMENT,
                                    date.fromisoformat(q['start_date']), date.fromisoformat(q['end_date']), q['selector'])
            context = QueryContext(access, entry['snapshot_id'], cutoff, PITMode.SYSTEM) if entry.get('snapshot_id') else None
            if context is None:
                continue
            records = {r.record_id: r for r in service.query(request, context).records}
            for f in entry.get('files', []):
                if any(w in f['title'] for w in ('摘要', '更正', '取消', '提示')):
                    continue
                record = records[f['record_id']]
                content = service.evidence(request, context, record.record_id, f['sha256'])
                assert content == Path(f['path']).read_bytes() and sha(f['path']) == f['sha256']
                assert record.source_url == f['source_url']
                service.evidence(request, context, record.record_id, f['source_index_artifact'])
                yield q, {**f, 'collection': str(path), 'collection_sha256': sha(path),
                          'scope': access.scope, 'snapshot': entry['snapshot_id']}


def extract(output_path):
    output_path.mkdir(parents=True, exist_ok=False)
    candidates, diagnostics = [], []
    for q, f in sources():
        text = subprocess.run(['pdftotext', '-enc', 'UTF-8', '-layout', f['path'], '-'],
                              capture_output=True, check=True, timeout=20).stdout.decode('utf8')
        pages = text.split('\f')
        lines = [(i+1, line) for i, page in enumerate(pages) for line in page.splitlines()]
        heads = [i for i, (_, line) in enumerate(lines)
                 if re.fullmatch(r'(?:[（(]?[\d一二三四五六七八九十]+[）)]?[、.．]?)?合并(?:及银行)?现金流量表(?:\(续\)|（续）)?', compact(line))]
        for head in heads:
            end = min(head + 160, len(lines))
            for i in range(head+1, end):
                if re.search(r'(母公司现金流量表|母公司所有者权益变动表|合并所有者权益变动表|合并及银行股东权益)', compact(lines[i][1])):
                    end = i
                    break
            header = compact('\n'.join(line for _, line in lines[head:head+16]))
            period_ok = '2025' in header and any(s in header for s in ('1-6月', '半年度', '上半年', '6月30日止六个月', '1月1日至2025年6月30日'))
            multiplier = '1000' if '千元' in header else '10000' if '万元' in header else '1' if re.search(r'单位[:：](?:人民币)?元|人民币元', header) else None
            for i in range(head, end):
                page, line = lines[i]
                norm = compact(line)
                if not re.match(r'^经营活动(?:产生(?:/\(使用\))?)?的?现金流', norm):
                    continue
                row = line.strip()
                # Only numbers and the unfinished label may continue this row.
                for j in range(i+1, min(i+4, end)):
                    if len(NUM.findall(row)) >= 2 and '现金流量净额' in compact(NUM.sub('', row)):
                        break
                    tail = lines[j][1]
                    if lines[j][0] != page:
                        break
                    if re.fullmatch(r'[\d,.()（）+\-−－\s]+', tail.strip()) or compact(tail) in ('量净额', '净额', '额'):
                        row += ' ' + tail.strip()
                    else:
                        break
                numbers = NUM.findall(row)
                diagnostics.append({'code': q['code'], 'page': page, 'header_page': lines[head][0],
                                    'header': header, 'row': row, 'period_ok': period_ok, 'multiplier': multiplier,
                                    'source': f})
                columns_ok = len(numbers) == 2 or (len(numbers) == 4 and '合并及银行现金流量表' in header and '本集团' in header and '本行' in header and header.index('本集团') < header.index('本行'))
                if not period_ok or not multiplier or not columns_ok or '现金流量净额' not in compact(NUM.sub('', row)):
                    continue
                printed = numbers[0]
                decimal = printed.replace(',', '').replace('−', '-').replace('－', '-')
                if decimal.startswith('(') and decimal.endswith(')'):
                    decimal = '-' + decimal[1:-1]
                amount = Decimal(decimal)
                candidates.append({'code': q['code'], 'exchange': q['exchange'], 'period': q['period'],
                                   'field': 'operating_cashflow', 'printed': printed, 'decimal': str(amount),
                                   'multiplier': multiplier, 'value_cny': str(amount * Decimal(multiplier)),
                                   'tolerance_cny': str(Decimal(1).scaleb(amount.as_tuple().exponent) * Decimal(multiplier) / 2),
                                   'pdf_page': page, 'header_page': lines[head][0], 'header_excerpt': header,
                                   'row_excerpt': row, 'source': f})
    # Duplicate heading windows on the same physical row are one candidate.
    unique = {(c['code'], c['source']['sha256'], c['pdf_page'], c['row_excerpt']): c for c in candidates}
    candidates = list(unique.values())
    output = {'policy': 'official consolidated H1 table; first current-period column; independent of provider values; machine-assisted candidates require review',
              'parser_sha256': sha(__file__),
              'source_hashes': {str(p): sha(p) for pair in SOURCES for p in pair},
              'candidates': candidates, 'diagnostics': diagnostics, 'provider_values_read': False, 'network_calls': 0}
    write(output_path / 'candidates.json', output)
    print(json.dumps({'candidates': len(candidates), 'codes': len(set(c['code'] for c in candidates)),
                      'candidate_sha256': sha(output_path / 'candidates.json')}))
    for c in diagnostics:
        print(json.dumps({k: c[k] for k in ('code', 'page', 'header_page', 'row', 'period_ok', 'multiplier')}, ensure_ascii=False))


def inspect_missing():
    saved = json.loads((ROOT / 'candidates.json').read_bytes())
    found = {c['code'] for c in saved['candidates']}
    for q, f in sources():
        if q['code'] in found:
            continue
        text = subprocess.run(['pdftotext', '-enc', 'UTF-8', '-layout', f['path'], '-'],
                              capture_output=True, check=True, timeout=20).stdout.decode('utf8')
        print(json.dumps({'code': q['code'], 'source': f['path']}, ensure_ascii=False))
        for n, page in enumerate(text.split('\f'), 1):
            lines = page.splitlines()
            for i, line in enumerate(lines):
                if re.search(r'合并.*现金流量表|经营活动产生的现金|经营活动现金流量', compact(line)):
                    print(json.dumps({'page': n, 'nearby': '\n'.join(lines[max(0, i-2):i+4])}, ensure_ascii=False))


def render_samples():
    selected = {'601009': (105,), '601528': (77,), '920510': (44, 45), '688570': (70, 71), '603207': (65, 66)}
    target = ROOT / 'visual'
    target.mkdir(exist_ok=False)
    renders = []
    for q, f in sources():
        for page in selected.get(q['code'], ()):
            prefix = target / (q['code'] + '-' + str(page))
            subprocess.run(['pdftoppm', '-f', str(page), '-l', str(page), '-scale-to', '1600', '-singlefile', '-png', f['path'], str(prefix)],
                           capture_output=True, check=True, timeout=30)
            renders.append({'code': q['code'], 'page': page, 'source': f, 'render': str(prefix) + '.png'})
    write(target / 'manifest.json', {'renders': renders})
    print(json.dumps({'rendered_pages': len(renders)}))


def freeze_review():
    path = ROOT / 'multiline/candidates.json'
    saved = json.loads(path.read_bytes())
    candidates = saved['candidates']
    assert len(candidates) == len({c['code'] for c in candidates}) == 24
    # This row's label starts on page 70 and ends at the top of page 71.
    # Both pages were rendered and visually read before provider comparison.
    d = next(d for d in saved['diagnostics'] if d['code'] == '688570' and d['page'] == 70
             and '经营活动产生的现金流' in d['row'])
    assert NUM.findall(d['row']) == ['-51,487,764.16', '-60,952,978.72']
    candidates = candidates + [{'code': '688570', 'exchange': 'SSE', 'period': '2025-06-30',
                'field': 'operating_cashflow', 'printed': '-51,487,764.16', 'decimal': '-51487764.16',
                'multiplier': '1', 'value_cny': '-51487764.16', 'tolerance_cny': '0.005',
                'pdf_page': 70, 'header_page': 70, 'header_excerpt': d['header'], 'row_excerpt': d['row'],
                'continuation_page': 71, 'continuation_label': '量净额', 'source': d['source']}]
    manifest = json.loads((ROOT / 'visual/manifest.json').read_bytes())
    assert len(manifest['renders']) == 8
    for r in manifest['renders']:
        assert Path(r['render']).is_file()
    review = {'candidate_sha256': sha(path), 'review_type': 'machine_assisted_source_review_not_expert_blind',
              'policy': '25 consolidated cumulative H1 operating cashflow cells; current-period first column; bank group not bank-only; yuan conversion and half-last-digit source precision; no provider answer used to select a number',
              'visual_pages_reviewed': [{'code': r['code'], 'page': r['page'], 'pdf_sha256': r['source']['sha256']} for r in manifest['renders']],
              'all_24_text_headers_and_rows_reviewed': True, 'cross_page_manual_source_cell': '688570',
              'provider_values_read_during_reference_extraction': False, 'references': candidates}
    write(ROOT / 'review.json', review)
    print(json.dumps({'frozen_reference_cells': len(candidates), 'review_sha256': sha(ROOT / 'review.json')}))


def compare(verify_only):
    from phase3_enriched_audit import captured_service
    review_path = ROOT / 'review.json'
    review = json.loads(review_path.read_bytes())
    assert review['candidate_sha256'] == sha(ROOT / 'multiline/candidates.json')
    authorized = {f['sha256']: (q, f) for q, f in sources()}
    svc, access, capture = captured_service()
    cutoff = datetime.fromisoformat(capture['finished_at']) + timedelta(microseconds=1)
    results = []
    for ref in review['references']:
        q, f = authorized[ref['source']['sha256']]
        assert f == ref['source'] and ref['period'] == q['period']
        text = subprocess.run(['pdftotext', '-enc', 'UTF-8', '-layout', f['path'], '-'],
                              capture_output=True, check=True, timeout=20).stdout.decode('utf8')
        pages = text.split('\f')
        header_span = compact(''.join(pages[ref['header_page']-1:ref['header_page']+1]))
        assert ref['header_excerpt'] in header_span
        assert compact(ref['row_excerpt']) in compact(pages[ref['pdf_page']-1])
        if 'continuation_page' in ref:
            assert ref['continuation_label'] in compact(pages[ref['continuation_page']-1])
        assert NUM.findall(ref['row_excerpt'])[0] == ref['printed']
        item = next(r for r in capture['results'] if r['query']['code'] == ref['code'] and r['query']['dataset'] == 'financial_cashflow')
        request = DomainRequest(Subject('equity', ref['code'], ref['exchange']), DomainDataset.CASHFLOW,
                                date(2025, 6, 30), date(2025, 6, 30))
        context = QueryContext(access, item['snapshot'], cutoff, PITMode.SYSTEM)
        records = svc.query(request, context).records
        assert len(records) == 1
        record = records[0]
        svc.evidence(request, context, record.record_id)
        actual = next(m.value for m in record.metrics if m.name == 'operating_cashflow')
        expected = Decimal(ref['decimal']) * Decimal(ref['multiplier'])
        assert str(expected) == ref['value_cny']
        delta = None if actual is None else actual - expected
        results.append({'code': ref['code'], 'period': ref['period'], 'actual': str(actual),
                        'expected': str(expected), 'difference': None if delta is None else str(delta),
                        'tolerance_cny': ref['tolerance_cny'],
                        'match': delta is not None and abs(delta) <= Decimal(ref['tolerance_cny']),
                        'provider_record': record.record_id, 'provider_snapshot': item['snapshot'],
                        'reference': ref})
    assert len(results) == len({r['code'] for r in results}) == 25
    result = {'review_sha256': sha(review_path), 'capture_sha256': sha('.artifacts/phase3/fullscope-20261003/domains/result.json'),
              'registered_cells': 25, 'matched': sum(r['match'] for r in results),
              'missing': sum(r['difference'] is None for r in results), 'comparisons': results,
              'review_type': review['review_type'], 'expert_blind': False, 'historical_availability_upgraded': False,
              'source_domain_and_formula_quality_not_overall_research_acceptance': True,
              'new_provider_or_model_network_calls': 0}
    if verify_only:
        assert result == json.loads((ROOT / 'comparison.json').read_bytes())
    else:
        write(ROOT / 'comparison.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'comparisons'}))
    if not all(r['match'] for r in results):
        raise SystemExit(2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--inspect-missing', action='store_true')
    parser.add_argument('--render-samples', action='store_true')
    parser.add_argument('--freeze-review', action='store_true')
    parser.add_argument('--compare', action='store_true')
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT)
    args = parser.parse_args()
    if args.inspect_missing:
        inspect_missing()
    elif args.render_samples:
        render_samples()
    elif args.freeze_review:
        freeze_review()
    elif args.compare or args.verify_only:
        compare(args.verify_only)
    else:
        extract(args.output)
