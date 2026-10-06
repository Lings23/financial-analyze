"""Freeze a reviewed real-document qualification from authorized P1.8 evidence.

No live network, no Tushare values. This is an explicit two-document review, not
an automatic claim that every CNINFO announcement qualifies for historical PIT.
"""
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
import subprocess

from run_p18_acceptance import request
from stock_research.models import AccessContext, QueryContext, PITMode
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

ROOT = Path('.artifacts/p17_20261001/release_date')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / 'qualification.json'
    if path.exists():
        raise ValueError('qualification already frozen; refusing overwrite')
    run = json.loads(Path('.artifacts/p18_20261001/attempt2.json').read_bytes())
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text().strip())
    source_artifacts = ArtifactStore('.artifacts/p18_20261001/artifacts')
    access = AccessContext(run['scope'], frozenset({'cninfo'}))
    ctx = QueryContext(access, run['last_snapshot_id'], datetime.fromisoformat(run['finished_at']) + timedelta(seconds=1), PITMode.SYSTEM)
    specs = [
        ('original', '1223198218', '2025-04-22', 0, '3f742977322d9b166f606376becb4597a6dd630a637db3285c17c441fb137065',
         {'revenue': ('26069711361.44', 8), 'net_income_parent': ('2018478513.91', 8)}),
        ('correction', '1225212850', '2026-04-28', 1, 'c55fbe422327818533fe53f0d9e079194c793980e0cd9567836e1e938b272fb8',
         {'revenue': ('26048900498.27', 8), 'net_income_parent': ('2005803553.96', 9)}),
    ]
    versions = []
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(), executor, db, source_artifacts)
        for label, ann, release, order, pdf_sha, values in specs:
            item = next(x for x in run['results'] if x['request']['provider'] == 'cninfo'
                        and x['request']['code'] == '300122' and x['request']['start'] == release)
            req = request(item['request'])
            row = next(r for r in service.query(req, ctx).records if dict(r.attributes)['announcement_id'] == ann)
            pdf_id = dict(row.attributes)['pdf_artifact_id']
            assert pdf_id == pdf_sha
            pdf = service.evidence(req, ctx, row.record_id, pdf_id)
            index = service.evidence(req, ctx, row.record_id, row.artifact_id)
            pdf_path = ROOT / (pdf_id + '.pdf')
            index_path = ROOT / (row.artifact_id + '.json')
            for target, content in ((pdf_path, pdf), (index_path, index)):
                with target.open('xb') as stream:
                    stream.write(content)
            field_evidence = {}
            for field, (value, page) in values.items():
                text = subprocess.run(['pdftotext', '-enc', 'UTF-8', '-layout', '-f', str(page),
                                       '-l', str(page), str(pdf_path), '-'], capture_output=True, check=True, timeout=15).stdout.decode('utf8')
                assert value in text.replace(',', '').replace(' ', '')
                if label == 'original':
                    assert '2024' in text and '归属于上市公司股东的净利润' in text and '营业收入' in text
                else:
                    assert ('对合并利润表的影响' in text and '2024' in text) if page == 8 else '归属于母公司所有者的净' in text
                    original_value = specs[0][-1][field][0]
                    assert original_value in text.replace(',', '').replace(' ', '')
                field_evidence[field] = {'pdf_page': page, 'column': '2024 年' if label == 'original' else '调整后金额',
                    'financial_context': '2024 年年度合并利润表；归母口径',
                    'original_amount': specs[0][-1][field][0], 'printed_amount_cny': value}
            versions.append({'label': label, 'symbol': '300122', 'exchange': 'SZSE', 'period': '2024-12-31',
                'release_date': release, 'announcement_id': ann, 'revision_order': order, 'pdf_page_one_based': 8,
                'pdf': {'path': pdf_path.name, 'sha256': pdf_id, 'url': row.source_url},
                'index': {'path': index_path.name, 'sha256': row.artifact_id},
                'field_evidence': field_evidence,
                'values_cny': {**{f: val[0] for f, val in values.items()}, 'total_revenue': None},
                'review_notes': 'Official CNINFO index binds date, symbol, announcement ID and exact PDF. Original 2024 annual summary amounts equal the correction document disclosed column. Correction uses 2024 consolidated income adjusted column, not parent-only income or later 2025 comparative amounts. Index midnight is date precision only.',
                'imported_from': {'scope': run['scope'], 'snapshot': run['last_snapshot_id'], 'record': row.record_id}})
    qualification = {'schema': 'cninfo_income_qualification_v1', 'release_precision': 'date',
        'basis': 'consolidated_cumulative_cny', 'security_scope': ['SZSE:300122'],
        'versions': versions, 'reviewed_at': datetime.now().astimezone().isoformat(),
        'limitations': ['not intraday release evidence', 'not market-wide qualification',
                        'total_revenue remains missing', 'no Tushare response backdating']}
    with path.open('x', encoding='utf8') as stream:
        json.dump(qualification, stream, ensure_ascii=False, indent=2)
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    plan = {'schema': 'p17_release_date_plan_v1', 'scope': 'p17-qualified-cninfo-20261001',
        'qualification_path': str(path), 'qualification_sha256': pin,
        'dataset': 'financial_income', 'symbol': '300122', 'exchange': 'SZSE', 'period': '2024-12-31',
        'public_cutoffs_local': ['2025-04-22T23:59:59.999999+08:00', '2025-04-23T00:00:00+08:00',
            '2026-04-28T23:59:59.999999+08:00', '2026-04-29T00:00:00+08:00'],
        'expected_labels': [None, 'original', 'original', 'correction'],
        'system_historical_count': 0, 'network_calls': 0,
        'required_checks': ['field-specific original PDF page', 'date boundary', 'correction selection',
            'source and scope authorization', 'attached artifact access', 'old snapshot immutable',
            'persistent database restart replay', 'legacy P1.7 and P1.8 replay']}
    plan_path = Path('evaluation/p17_20261001_release_date_plan.json')
    with plan_path.open('x', encoding='utf8') as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'qualified_documents': len(versions), 'independently_transcribed_fields': 4,
                      'qualification_sha256': pin, 'plan_sha256': hashlib.sha256(plan_path.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
