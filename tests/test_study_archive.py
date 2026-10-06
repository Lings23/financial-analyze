"""Synthetic archive/PIT mechanisms only; never real financial truth."""
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from helpers import SECURITY, ts
from stock_research.errors import IntegrityError, PermissionDenied, ValidationError, ProviderSchemaError
from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.tushare import TushareProvider
from stock_research.research.archive import project_archived_income
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.contracts import Binding
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudyRequest
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.memory import MemoryRepository


class StudyArchiveTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name); self.artifacts=ArtifactStore(self.root/'artifacts')
        self.capture=ts('2025-05-01T10:00:00'); self.ingestion=ts('2025-06-01T10:00:00')
        self.access=AccessContext('synthetic-archive',frozenset({'tushare'}))
        self.response={'code':0,'data':{'fields':list(TushareProvider.INCOME_FIELDS),'items':[
            ['600000.SH','20250401','20250401','20241231','1','100','100','5'],
            ['600000.SH','20240401','20240401','20231231','1','80','80','10']]}}
        self.network_calls=0
        def transport(*args):
            self.network_calls+=1
            return self.response
        provider=TushareProvider('synthetic-token-no-real-credentials',self.artifacts,transport,lambda:self.capture)
        original=DataRequest(SECURITY,Dataset.FINANCIAL_INCOME,date(2024,6,1),date(2024,12,31))
        self.anchor=replace(provider.fetch(original,self.access.scope,1)[0],quality_flags=('synthetic_fixture','historical_release_not_verified'))
        self.repo=MemoryRepository(); snapshot=self.repo.commit(self.access.scope,(self.anchor,))
        self.request=StudyRequest(SECURITY,ts('2025-05-02T00:00:00'),PITMode.SYSTEM,(
            Binding('market_daily',snapshot.snapshot_id,'tushare',date(2025,4,1),date(2025,4,3)),
            Binding('financial_income',snapshot.snapshot_id,'tushare',original.start,original.end)))
        self.svc=DataService(ProviderRegistry(),None,self.repo,self.artifacts)
        self.network_calls=0  # Only the injected setup transport ran; projection has no transport.

    def project(self,request=None,access=None,**kwargs):
        return project_archived_income(self.svc,request or self.request,access or self.access,
                                      ingested_at=kwargs.get('ingested_at',self.ingestion))

    def alter_body(self,mutate):
        body=json.loads(self.artifacts.get(self.access.scope,self.anchor.artifact_id))
        mutate(body)
        aid=self.artifacts.put(self.access.scope,body)
        self.anchor=replace(self.anchor,artifact_id=aid)
        snapshot=self.repo.commit(self.access.scope,(self.anchor,))
        self.request=replace(self.request,bindings=tuple(replace(b,snapshot=snapshot.snapshot_id) for b in self.request.bindings))

    def test_projection_uses_pinned_archive_and_preserves_old_snapshot(self):
        old_id=self.request.bindings[0].snapshot
        old=self.repo.read(self.access.scope,old_id)
        expanded,rows,proof=self.project()
        self.assertEqual((expanded.start,expanded.end),(date(2023,12,31),date(2024,12,31)))
        self.assertEqual(len(rows),2)
        self.assertEqual(self.repo.read(self.access.scope,old_id),old)
        self.assertEqual(self.network_calls,0)
        for row in rows:
            self.assertEqual(row.available_at,self.capture)
            self.assertEqual(row.retrieved_at,self.capture)
            self.assertEqual(row.ingested_at,self.ingestion)
            self.assertEqual(row.availability_basis,'observed_at')
            self.assertEqual(row.artifact_id,self.anchor.artifact_id)
            self.assertEqual(row.provider_call_id,self.anchor.provider_call_id)
            self.assertIn('synthetic_fixture',row.quality_flags)
            self.assertIsNone(row.published_at)
        self.assertFalse(proof['historical_release_verified'])
        self.assertEqual(next(r for r in rows if r.period==self.anchor.period).metrics,self.anchor.metrics)

    def test_actual_ingestion_system_visibility_and_no_historical_backfill(self):
        expanded,rows,_=self.project()
        snapshot=self.repo.commit(self.access.scope,rows)
        def query(cutoff,mode):
            return self.svc.query(expanded,QueryContext(self.access,snapshot.snapshot_id,cutoff,mode)).records
        self.assertFalse(query(self.request.as_of,PITMode.SYSTEM))
        self.assertEqual(len(query(self.ingestion,PITMode.SYSTEM)),2)
        self.assertFalse(query(ts('2024-05-01T00:00:00'),PITMode.PUBLIC))
        self.assertEqual(len(query(self.request.as_of,PITMode.PUBLIC)),2)

    def test_every_read_requires_source_and_scope_authorization(self):
        for denied in (AccessContext(self.access.scope,frozenset({'denied-source'})),
                       AccessContext('other-scope',frozenset({'tushare'}))):
            with self.subTest(scope=denied.scope), self.assertRaises(PermissionDenied):
                self.project(access=denied)

    def test_projection_rejects_naive_or_backdated_ingestion(self):
        for moment in (ts('2025-04-01T00:00:00'),self.ingestion.replace(tzinfo=None)):
            with self.subTest(moment=moment), self.assertRaises(ValidationError):
                self.project(ingested_at=moment)

    def test_projection_requires_visible_observed_v2_anchor(self):
        with self.assertRaises(ValidationError):
            self.project(request=replace(self.request,as_of=ts('2025-04-01T00:00:00')))
        anchor=replace(self.anchor,provider_version='1')
        snapshot=self.repo.commit(self.access.scope,(anchor,))
        request=replace(self.request,bindings=tuple(replace(b,snapshot=snapshot.snapshot_id) for b in self.request.bindings))
        with self.assertRaises(ValidationError):
            self.project(request=request)

    def test_archive_security_schema_and_capture_must_match_anchor(self):
        for key,value in (('fields',[]),('response_row_count',9),('finished_at',self.ingestion.isoformat()),
                          ('params',{'ts_code':'000001.SZ','report_type':'1'}),('archive_schema','old')):
            with self.subTest(key=key):
                saved=self.anchor; request=self.request
                self.alter_body(lambda b:b.update({key:value}))
                with self.assertRaises(IntegrityError): self.project()
                self.anchor=saved; self.request=request

    def test_changed_anchor_values_are_rejected(self):
        self.alter_body(lambda b:b['items'][0].__setitem__(5,'999'))
        with self.assertRaises(IntegrityError): self.project()

    def test_unfiltered_prior_rows_are_validated_before_use(self):
        for index,value in ((0,'000001.SZ'),(1,'20270101'),(4,'2'),(5,'NaN')):
            with self.subTest(index=index):
                saved=self.anchor; request=self.request
                self.alter_body(lambda b:b['items'][1].__setitem__(index,value))
                with self.assertRaises((IntegrityError,ProviderSchemaError)): self.project()
                self.anchor=saved; self.request=request

    def test_missing_prior_is_retained_as_insufficient(self):
        self.alter_body(lambda b:(b['items'].pop(),b.update(response_row_count=1)))
        _,rows,_=self.project()
        self.assertEqual(len(rows),1)

    def test_expanded_snapshot_enables_exact_yoy_and_conflict(self):
        expanded,rows,_=self.project()
        snapshot=self.repo.commit(self.access.scope,rows)
        request=replace(self.request,as_of=self.ingestion,bindings=tuple(
            replace(b,snapshot=snapshot.snapshot_id,start=expanded.start,end=expanded.end) if b.dataset=='financial_income'
            else replace(b,snapshot=snapshot.snapshot_id) for b in self.request.bindings))
        report=StudyRuntime(self.svc,CheckpointStore(self.root/'runs')).run(request,self.access)
        facts={f['name']:f['value'] for f in report['facts']}
        self.assertEqual(facts['revenue_yoy'],'0.25')
        self.assertEqual(facts['net_income_parent_yoy'],'-0.5')
        self.assertEqual(next(h['status'] for h in report['hypotheses'] if h['id']=='financial_deterioration'),'conflicted')
        self.assertEqual(report['verification']['status'],'verified')
