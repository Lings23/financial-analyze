"""Real CNINFO qualified date-precision PIT import and immutable offline replay."""
import argparse
from dataclasses import replace
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import subprocess

from stock_research.errors import PermissionDenied
from stock_research.models import AccessContext, DataRequest, Dataset, QueryContext, PITMode, Security, utcnow
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ProviderExecutor
from stock_research.providers.qualified_income import QualifiedCNInfoIncomeProvider
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

ROOT = Path('.artifacts/p17_20261001/release_date')
PLAN = Path('evaluation/p17_20261001_release_date_plan.json')
PLAN_SHA = '50864574806bd5e2c6ef7977593b9d4fd350fd1db2949ad5e805af9ff6106fc9'
CORE = ['src/stock_research/models.py', 'src/stock_research/temporal.py', 'src/stock_research/service.py',
        'src/stock_research/providers/base.py', 'src/stock_research/providers/qualified_income.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(plan, run, db, artifacts):
    if sha(PLAN) != run['plan_sha256'] or sha(plan['qualification_path']) != plan['qualification_sha256']:
        raise AssertionError('frozen plan or qualification changed')
    qualification = json.loads(Path(plan['qualification_path']).read_bytes())
    request = DataRequest(Security(plan['symbol'], plan['exchange']), Dataset.FINANCIAL_INCOME,
                          date.fromisoformat(plan['period']), date.fromisoformat(plan['period']))
    access = AccessContext(plan['scope'], frozenset({'cninfo'}))
    first = db.read(plan['scope'], run['first_snapshot'])
    rows = db.read(plan['scope'], run['final_snapshot'])
    assert len(first) == 1 and len(rows) == 3
    assert list(db.snapshot(plan['scope'], run['first_snapshot']).record_ids) == run['first_record_ids']
    assert list(db.snapshot(plan['scope'], run['final_snapshot']).record_ids) == run['final_record_ids']
    pdf_checks = []
    for version in qualification['versions']:
        pdf = Path(plan['qualification_path']).parent / version['pdf']['path']
        assert sha(pdf) == version['pdf']['sha256']
        for field, evidence in version['field_evidence'].items():
            page = str(evidence['pdf_page'])
            text = subprocess.run(['pdftotext', '-enc', 'UTF-8', '-layout', '-f', page, '-l', page,
                                   str(pdf), '-'], capture_output=True, check=True, timeout=15).stdout.decode('utf8')
            compact = text.replace(',', '').replace(' ', '')
            assert version['values_cny'][field] in compact
            if version['label'] == 'correction':
                assert evidence['original_amount'] in compact
            pdf_checks.append({'version': version['label'], 'field': field, 'page': int(page),
                               'value_cny': version['values_cny'][field], 'pdf_sha256': sha(pdf)})
    cases = []
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(), executor, db, artifacts)
        for cutoff, label in zip(plan['public_cutoffs_local'], plan['expected_labels']):
            context = QueryContext(access, run['final_snapshot'], datetime.fromisoformat(cutoff))
            public = service.query(request, context)
            system = service.query(request, replace(context, mode=PITMode.SYSTEM))
            expected = next((v for v in qualification['versions'] if v['label'] == label), None)
            assert len(public.records) == (1 if expected else 0) and not system.records
            visible_id = None
            if expected:
                row = public.records[0]
                visible_id = row.record_id
                assert row.source_key == expected['announcement_id']
                assert row.published_at is None and row.availability_basis == 'verified_release_date'
                assert row.release_date.isoformat() == expected['release_date']
                assert {m.name: m.raw_value for m in row.metrics} == expected['values_cny']
                assert row.release_evidence_artifact_id == plan['qualification_sha256']
                assert expected['pdf']['sha256'] in row.artifact_ids and expected['index']['sha256'] in row.artifact_ids
                for aid in row.artifact_ids:
                    assert hashlib.sha256(service.evidence(request, context, row.record_id, aid)).hexdigest() == aid
            for row in rows:
                if row.record_id != visible_id:
                    try:
                        service.evidence(request, context, row.record_id)
                    except PermissionDenied:
                        pass
                    else:
                        raise AssertionError('nonselected or invisible version evidence leaked')
            denied = replace(context, access=AccessContext(plan['scope'], frozenset({'tushare'})))
            assert not service.query(request, denied).records
            for row in rows:
                try:
                    service.evidence(request, denied, row.record_id, row.supporting_artifact_ids[0])
                except PermissionDenied:
                    pass
                else:
                    raise AssertionError('unauthorized source attachment leaked')
            wrong = replace(context, access=AccessContext('wrong-release-date-scope', frozenset({'cninfo'})))
            try:
                service.query(request, wrong)
            except PermissionDenied:
                pass
            else:
                raise AssertionError('scope boundary bypassed')
            cases.append({'cutoff': cutoff, 'selected_label': label, 'selected_record_id': visible_id,
                          'public_count': len(public.records), 'system_count': len(system.records),
                          'unauthorized_count': 0, 'wrong_scope_denied': True})
        after = QueryContext(access, run['first_snapshot'], datetime.fromisoformat(run['finished_at']) + timedelta(seconds=1), PITMode.SYSTEM)
        assert service.query(request, after).records == first
        assert service.query(request, replace(after, snapshot_id=run['final_snapshot'])).records[0].source_key == '1225212850'
        for row in rows:
            context = replace(after, snapshot_id=run['final_snapshot'], as_of_date=row.ingested_at - timedelta(microseconds=1))
            if context.as_of_date < min(r.ingested_at for r in rows):
                assert not service.query(request, context).records
    return {'plan_sha256': run['plan_sha256'], 'qualification_sha256': plan['qualification_sha256'],
            'scope': plan['scope'], 'first_snapshot': run['first_snapshot'], 'final_snapshot': run['final_snapshot'],
            'physical_records': len(rows), 'qualified_document_versions': 2, 'pdf_field_checks': pdf_checks,
            'cases': cases, 'old_snapshot_stable': True, 'historical_intraday_release_verified': False,
            'qualified_date_precision_case_passed': True, 'market_wide_historical_pit_verified': False,
            'financial_quality_denominator_unchanged': 666}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    assert sha(PLAN) == PLAN_SHA
    plan = json.loads(PLAN.read_bytes())
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text().strip())
    artifacts = ArtifactStore(ROOT / 'artifacts')
    run_path = ROOT / 'run.json'
    if args.verify_only:
        run = json.loads(run_path.read_bytes())
        report = verify(plan, run, db, artifacts)
        assert report == json.loads((ROOT / 'replay.json').read_bytes())
        print(json.dumps({'replay_passed': True, 'cases': len(report['cases']), 'qualified_versions': 2}))
        return
    if run_path.exists():
        raise ValueError('real run already frozen; refusing overwrite')
    run = {'plan_sha256': PLAN_SHA, 'started_at': utcnow().isoformat(), 'network_calls': 0,
           'code_sha256': {p: sha(p) for p in CORE}}
    req = DataRequest(Security(plan['symbol'], plan['exchange']), Dataset.FINANCIAL_INCOME,
                      date.fromisoformat(plan['period']), date.fromisoformat(plan['period']))
    access = AccessContext(plan['scope'], frozenset({'cninfo'}))
    parent = None
    with ProviderExecutor() as executor:
        for labels in [('original',), None]:
            registry = ProviderRegistry()
            registry.register(QualifiedCNInfoIncomeProvider(plan['qualification_path'], plan['qualification_sha256'],
                                                          artifacts, labels=labels))
            service = DataService(registry, executor, db, artifacts)
            result = service.refresh(req, access, ('cninfo',), parent, False)
            parent = result.snapshot.snapshot_id
            key = 'first' if labels else 'final'
            run[key + '_snapshot'] = parent
            run[key + '_record_ids'] = list(result.snapshot.record_ids)
        run['provider_stats'] = executor.stats.copy()
    run['finished_at'] = utcnow().isoformat()
    with run_path.open('x', encoding='utf8') as stream:
        json.dump(run, stream, indent=2)
    report = verify(plan, run, db, artifacts)
    with (ROOT / 'replay.json').open('x', encoding='utf8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'qualified_versions': 2, 'physical_records': 3, 'cases_passed': len(report['cases']),
                      'final_snapshot': run['final_snapshot'], 'network_calls': 0}))


if __name__ == '__main__':
    main()
