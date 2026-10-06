"""Extract conservative independent candidates from original consolidated tables.

Does not read Tushare values. Missing/ambiguous units, headings or rows are left
unverified. Candidates still require a separate source review before scoring.
"""
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess

from stock_research.models import utcnow

ROOT = Path('.artifacts/p17_20261001/formal')
TARGET = ROOT/'financial_values/candidates.json'
NUM = re.compile(r'(?<![\d.])\(?[-−－]?\d[\d,]*\.\d+\)?|(?<![\d.])\(?[-−－]?\d{1,3}(?:,\d{3})+\)?')


def compact(text): return re.sub(r'\s+','',text).replace('－','-').replace('—','-').replace('–','-')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label')
    parser.add_argument('--collection',type=Path,default=ROOT/'financial_references/collection.json')
    args = parser.parse_args()
    global TARGET
    if args.label:
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,30}',args.label): raise ValueError('invalid candidate label')
        TARGET = TARGET.parent/args.label/'candidates.json'
    if TARGET.exists(): raise ValueError('independent candidates exist; refusing overwrite')
    collection_path = args.collection
    if not collection_path.resolve().is_relative_to(ROOT.resolve()): raise ValueError('candidate source outside frozen formal evidence')
    collection = json.loads(collection_path.read_text(encoding='utf8'))
    output = {'created_at':utcnow().isoformat(),'collection_sha256':hashlib.sha256(collection_path.read_bytes()).hexdigest(),
        'parser_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'policy':'Independent source candidates only. No Tushare values read. Require actual consolidated table, explicit units/period and unique row. No bank revenue alias, no number searching against provider result. Review before scoring.',
        'periods':[]}
    for e in collection['requests']:
        req = e['request']; row = {'code':req['code'],'exchange':req['exchange'],'period':req['period'],
                                  'values':{},'missing':{},'status':e['status']}
        possible = {name:[] for name in req['fields']}
        for f in e.get('files',[]):
            if any(word in f['title'] for word in ['摘要','更正','取消','提示']): continue
            pdf = Path(f['path']); assert hashlib.sha256(pdf.read_bytes()).hexdigest() == f['sha256']
            text = subprocess.run(['pdftotext','-enc','UTF-8','-layout',str(pdf),'-'],capture_output=True,check=True,timeout=20).stdout.decode('utf8')
            pages = text.split('\f'); lines = [(i+1,l) for i,p in enumerate(pages) for l in p.splitlines()]
            heads = [n for n,(_,l) in enumerate(lines) if re.fullmatch(r'(?:[（(]?[\d一二三四五六七八九十]+[）)]?[、.．]?)?合并利润表',compact(l))]
            for head in heads:
                end = min(head+200,len(lines))
                for n in range(head+1,end):
                    if re.search(r'(?:母公司利润表|合并现金流量表|母公司现金流量表)',compact(lines[n][1])):
                        end = n; break
                header = compact('\n'.join(l for _,l in lines[head:head+14]))
                heading_page = compact(pages[lines[head][0]-1])
                year = req['period'][:4]
                generic_quarter = ('本期发生额' in header and any(year+'年'+s in heading_page for s in ('第一季度报告','一季度报告')))
                if year not in header and not generic_quarter: continue
                if req['period'].endswith('03-31') and not (generic_quarter or any(s in header for s in ('1-3月','第一季度','一季度'))): continue
                if req['period'].endswith('06-30') and not any(s in header for s in ('1-6月','半年度','上半年')): continue
                if '千元' in header: multiplier = Decimal(1000)
                elif '万元' in header: multiplier = Decimal(10000)
                elif re.search(r'单位[:：](?:人民币)?元|人民币元',header): multiplier = Decimal(1)
                else: continue
                for n in range(head,end):
                    page,line = lines[n]; normalized = compact(line)
                    field = None
                    if re.match(r'^(?:一[、.．])?营业总收入',normalized): field='total_revenue'
                    elif re.match(r'^(?:一[、.．])?(?:其中[:：])?营业收入',normalized): field='revenue'
                    elif re.match(r'^(?:[（(][\d一二三四][）)]|[\d一二三四][、.．])?归属于母公司(?:股东|所有者)的?净',normalized): field='net_income_parent'
                    if field is None: continue
                    row_lines = [line]
                    for j in range(n+1,min(n+10,end)):
                        joined=' '.join(row_lines)
                        label=compact(NUM.sub('',joined))
                        if len(NUM.findall(joined)) >= 2 and (field != 'net_income_parent' or re.search(r'净(?:利润|亏损)',label)): break
                        other_page,other_line=lines[j];other=compact(other_line)
                        if other_page != page: break
                        if other:
                            # Only a numeric-only continuation or a split profit
                            # label can belong to this row. Never borrow a later
                            # expense/revenue row merely because it has numbers.
                            numeric_only=re.fullmatch(r'[\d,.()（）+\-−－\s]+',other_line.strip())
                            split_label=field=='net_income_parent' and re.match(r'^(?:利润|亏损|润|损)(?:[（(]|$)',other)
                            if not (numeric_only or split_label): break
                            row_lines.append(other_line)
                    search_line = ' '.join(row_lines)
                    if field == 'net_income_parent' and not re.search(r'净(?:利润|亏损)',compact(NUM.sub('',search_line))): continue
                    numbers = NUM.findall(search_line)
                    if len(numbers) < 2: continue  # Need both period columns, no narrative-only number.
                    printed = numbers[0]; value = printed.replace(',','').replace('−','-').replace('－','-')
                    if value.startswith('(') and value.endswith(')'): value = '-'+value[1:-1]
                    number = Decimal(value)
                    quantum = Decimal(1).scaleb(number.as_tuple().exponent)*multiplier
                    possible[field].append({'printed':printed,'decimal':str(number),'multiplier':str(multiplier),
                        'value_cny':str(number*multiplier),'tolerance_cny':str(quantum/2),
                        'pdf_page':page,'header_page':lines[head][0],'header_excerpt':header,
                        'row_excerpt':search_line.strip(),'source':f})
        for name, candidates in possible.items():
            unique = {(c['value_cny'],c['source']['sha256'],c['pdf_page']) for c in candidates}
            if len(unique) == 1: row['values'][name] = candidates[0]
            else: row['missing'][name] = {'reason':'ambiguous_candidates' if candidates else 'no_qualified_table_row',
                                         'candidate_count':len(candidates),'candidates':candidates}
        output['periods'].append(row)
    periods=len(collection['requests'])
    assert 1 <= periods <= 75 and len(output['periods']) == periods
    assert sum(len(r['values'])+len(r['missing']) for r in output['periods']) == periods*3
    TARGET.parent.mkdir(parents=True,exist_ok=True)
    with TARGET.open('x',encoding='utf8') as stream: json.dump(output,stream,ensure_ascii=False,indent=2)
    print(json.dumps({'periods':periods,'candidate_values':sum(len(r['values']) for r in output['periods']),
        'unverified':sum(len(r['missing']) for r in output['periods']),
        'counts_by_field':dict(Counter(k for r in output['periods'] for k in r['values'])),
        'candidates_sha256':hashlib.sha256(TARGET.read_bytes()).hexdigest(),'scored':0}))


if __name__ == '__main__': main()
