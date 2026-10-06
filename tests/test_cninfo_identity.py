"""Synthetic identity/security tests; these fixtures are not live source validation."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from tempfile import TemporaryDirectory
import unittest

from stock_research.domains import DomainDataset, DomainRequest, Subject
from stock_research.errors import PermissionDenied, ProviderSchemaError, ValidationError
from stock_research.models import AccessContext, QueryContext
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.cninfo_identity import QualifiedCNInfoIdentity, TABLE, GENERAL, MEMBERS, PILOT, STATEMENTS
from stock_research.providers.documents import CNInfoAnnouncementProvider
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.memory import MemoryRepository

CAPTURED = datetime(2026,10,1,12,tzinfo=timezone.utc)
SCOPE = 'synthetic-identity-test'


def manifest():
    proofs=[{'url':TABLE,'evidence_kind':'rendered_official_dom_projection','observed_at':CAPTURED.isoformat(),
             'header':['序号','证券简称','上市日期','旧代码','新代码'],
             'rows':[['1','雷特科技','2022/12/6','832110','920110']]}]
    proofs += [{'url':url,'statement':STATEMENTS[url],'evidence_kind':'rendered_official_dom_projection',
                'observed_at':CAPTURED.isoformat()} for url in (GENERAL,MEMBERS,PILOT)]
    return {'schema':'cninfo-qualified-identity-v1','scope':SCOPE,'proofs':proofs,
            'fixture':'synthetic, not official evidence',
            'approved_requests':[{'code':'920110','old_code':'832110','org_id':'synthetic-org',
                'cutover_date':'2025-10-09','start_date':'2025-04-10','end_date':'2025-04-12','selector':'合成年报'}]}


def identity(doc=None):
    content=json.dumps(doc or manifest(),ensure_ascii=False).encode('utf8')
    return QualifiedCNInfoIdentity(content,hashlib.sha256(content).hexdigest())


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=ArtifactStore(self.temp.name)
        self.req=DomainRequest(Subject('equity','920110','BSE'),DomainDataset.ANNOUNCEMENT,date(2025,4,10),date(2025,4,12),'合成年报')
        self.row={'secCode':'832110','announcementId':'12345','announcementTitle':'合成年报',
                  'announcementTime':int(datetime(2025,4,11,tzinfo=timezone(timedelta(hours=8))).timestamp()*1000),
                  'adjunctUrl':'finalpage/2025-04-11/12345.PDF'}

    def fake(self,url,timeout,form=None,kind='json'):
        if url.endswith('szse_stock.json'):return {'stockList':[{'code':'920110','orgId':'synthetic-org'}]}
        if kind=='pdf':return b'%PDF synthetic identity fixture, not financial truth'
        return {'totalAnnouncement':1,'announcements':[self.row]}

    def test_legacy_rejects_old_code_and_qualified_source_preserves_raw_identity(self):
        with self.assertRaises(ProviderSchemaError):
            CNInfoAnnouncementProvider(self.store,self.fake,lambda:CAPTURED).fetch(self.req,SCOPE,5)
        qualified=identity()
        record=CNInfoAnnouncementProvider(self.store,self.fake,lambda:CAPTURED,qualified).fetch(self.req,SCOPE,5)[0]
        archive=json.loads(self.store.get(SCOPE,record.artifact_id))
        self.assertEqual(archive['rows'][0]['secCode'],'832110')
        self.assertEqual(record.subject.code,'920110')
        self.assertEqual(record.available_at,CAPTURED)
        self.assertEqual(archive['identity_qualification']['reviewed_manifest_utf8'].encode('utf8'),qualified.manifest_bytes)
        self.assertEqual(record.provider_version,'p18-identity-1')

    def test_hash_pin_timezone_cutover_and_ambiguity_rejected(self):
        with self.assertRaises(ValidationError):QualifiedCNInfoIdentity(b'{}','0'*64)
        for mutate in (
            lambda d:d['proofs'][0].update(observed_at='2026-10-01T12:00:00'),
            lambda d:d['approved_requests'][0].update(cutover_date='2025-05-06'),
            lambda d:d['approved_requests'].append(dict(d['approved_requests'][0])),
            lambda d:d['proofs'][0]['rows'].append(list(d['proofs'][0]['rows'][0]))):
            doc=manifest();mutate(doc)
            with self.assertRaises(ValidationError):identity(doc)

    def test_scope_window_org_subject_code_and_observation_boundaries(self):
        q=identity();mapping={'code':'920110','orgId':'synthetic-org'}
        for scope,req,org,row in (
            ('wrong',self.req,mapping,self.row),
            (SCOPE,self.req,{'code':'920110','orgId':'other'},self.row),
            (SCOPE,DomainRequest(self.req.subject,self.req.dataset,date(2025,4,9),self.req.end,self.req.selector),mapping,self.row),
            (SCOPE,self.req,mapping,{**self.row,'secCode':'832111'}),
            (SCOPE,self.req,mapping,{**self.row,'secCode':[]}),
            (SCOPE,self.req,mapping,{**self.row,'announcementTime':True}),
            (SCOPE,self.req,mapping,{**self.row,'announcementTime':int(CAPTURED.timestamp()*1000)})):
            with self.subTest(scope=scope,row=row),self.assertRaises(ProviderSchemaError):q.validate(req,scope,org,row)
        with self.assertRaises(ProviderSchemaError):q.lineage(CAPTURED-timedelta(microseconds=1))
        clone=q.document;clone['scope']='changed';self.assertEqual(q.document['scope'],SCOPE)

    def test_qualified_index_proof_read_requires_visible_authorized_record(self):
        record=CNInfoAnnouncementProvider(self.store,self.fake,lambda:CAPTURED,identity()).fetch(self.req,SCOPE,5)[0]
        repo=MemoryRepository();snap=repo.commit(SCOPE,(record,))
        with ProviderExecutor() as executor:
            service=DataService(ProviderRegistry(),executor,repo,self.store)
            access=AccessContext(SCOPE,frozenset({'cninfo'}));ctx=QueryContext(access,snap.snapshot_id,CAPTURED)
            self.assertIn(b'identity_qualification',service.evidence(self.req,ctx,record.record_id))
            for bad in (QueryContext(access,snap.snapshot_id,CAPTURED-timedelta(microseconds=1)),
                        QueryContext(AccessContext(SCOPE,frozenset({'tushare'})),snap.snapshot_id,CAPTURED),
                        QueryContext(AccessContext('wrong',access.allowed_providers),snap.snapshot_id,CAPTURED)):
                with self.assertRaises(PermissionDenied):service.evidence(self.req,bad,record.record_id)


if __name__=='__main__':unittest.main()
