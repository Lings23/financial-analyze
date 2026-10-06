"""Synthetic security/version regressions; these are not financial ground truth."""
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research_fixtures import fixture, FixtureModel, BundleFixtureModel
from study_fixtures import study_request, with_event, add_domain
from stock_research.errors import PermissionDenied, ValidationError, IntegrityError
from stock_research.models import AccessContext, QueryContext
from stock_research.research.context import study_messages, SYSTEM_V2, SYSTEM_V1
from stock_research.research.scoped import SourceGrant, ScopedReadService
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudySpec
from stock_research.research.selection import selection_options
import json
import sys
from stock_research.model_adapters.chat import ModelConfig

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from accept_phase3_quality import ReceiptModel


class RevisionTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.f = fixture(Path(temp.name))
        self.request = study_request(self.f)
        self.access = AccessContext('explicit-recipient', self.f.access.allowed_providers)
        self.grants = [SourceGrant(self.f.service, self.f.access, b.snapshot,
                                  self.request.data_request(b), b.provider) for b in self.request.bindings]
        self.svc = ScopedReadService(self.access.scope, lambda: self.grants)
        self.binding = self.request.bindings[0]
        self.query = self.request.data_request(self.binding)
        self.ctx = QueryContext(self.access, self.binding.snapshot, self.request.as_of, self.request.mode)

    def test_explicit_composition_rechecks_grants_on_completed_replay(self):
        runtime = StudyRuntime(self.svc, self.f.store)
        report = runtime.run(self.request, self.access)
        self.assertTrue(report['facts'])
        self.assertEqual(runtime.run(self.request, self.access, resume=report['run_id']), report)
        self.grants.clear()
        with self.assertRaises(PermissionDenied):
            runtime.run(self.request, self.access, resume=report['run_id'])

    def test_recipient_provider_window_and_ambiguous_grants_are_denied(self):
        for ctx in (replace(self.ctx, access=self.f.access),
                    replace(self.ctx, access=AccessContext(self.access.scope, frozenset({'denied'})))):
            with self.assertRaises(PermissionDenied): self.svc.query(self.query, ctx)
        with self.assertRaises(PermissionDenied):
            self.svc.query(replace(self.query, start=self.query.start-timedelta(days=1)), self.ctx)
        self.grants.append(self.grants[0])
        with self.assertRaises(PermissionDenied): self.svc.query(self.query, self.ctx)

    def test_composed_evidence_requires_live_grant_and_original_owner(self):
        row = self.svc.query(self.query, self.ctx).records[0]
        self.assertTrue(self.svc.evidence(self.query, self.ctx, row.record_id, row.artifact_id))
        with self.assertRaises(PermissionDenied):
            self.svc.evidence(self.query, self.ctx, row.record_id, '0'*64)
        self.grants.clear()
        with self.assertRaises(PermissionDenied): self.svc.evidence(self.query, self.ctx, row.record_id)

    def test_composed_reads_preserve_pit_and_source_hash_validation(self):
        rows = self.svc.query(self.query, self.ctx).records
        before = min(r.available_at for r in rows)-timedelta(microseconds=1)
        self.assertFalse(self.svc.query(self.query, replace(self.ctx, as_of_date=before)).records)
        row = rows[0]
        self.f.artifacts._path(self.f.access.scope, row.artifact_id).write_bytes(b'corrupt')
        with self.assertRaises(IntegrityError): self.svc.query(self.query, self.ctx)

    def test_v2_version_changes_prompt_and_binds_checkpoint(self):
        old = StudyRuntime(self.f.service, self.f.store, spec=StudySpec(version='single-research-v1'))
        report = old.run(self.request, self.f.access)
        v1 = study_messages(report, self.request, 12000, version='single-research-v1')[0]
        v2 = study_messages(report, self.request, 12000, version='single-research-v2')[0]
        self.assertEqual(v1[0]['content'], SYSTEM_V1)
        self.assertEqual(v2[0]['content'], SYSTEM_V2)
        self.assertEqual(v1[1], v2[1])  # Facts, states, aliases and evidence unchanged.
        with self.assertRaises(PermissionDenied):
            StudyRuntime(self.f.service, self.f.store).run(self.request, self.f.access, resume=report['run_id'])
        self.assertEqual(old.run(self.request, self.f.access, resume=report['run_id']), report)
        with self.assertRaises(ValidationError): StudySpec(version='unknown')

    def test_v2_does_not_rewrite_a_legal_but_low_quality_model_selection(self):
        model = FixtureModel('{"highlights":["F1"],"hypotheses":["financial_deterioration"],"assessment":"descriptive_research_only"}')
        report = StudyRuntime(self.f.service, self.f.store, model,StudySpec(version='single-research-v2')).run(self.request, self.f.access)
        self.assertEqual(report['model']['status'], 'verified')
        self.assertEqual(report['model']['highlights'], [report['facts'][0]['id']])

    def test_v3_candidate_preserves_financial_counterevidence_and_domain_coverage(self):
        report = StudyRuntime(self.f.service,self.f.store,BundleFixtureModel()).run(self.request,self.f.access)
        selected = set(report['model']['highlights'])
        h = next(h for h in report['hypotheses'] if h['id']=='financial_deterioration')
        self.assertTrue(set(h['claim_ids']) <= selected)
        self.assertTrue(set(h['counterevidence_claim_ids']) <= selected)
        self.assertIn(next(f['id'] for f in report['facts'] if f['name']=='observed_price_change'),selected)
        self.assertEqual(report['model']['status'],'verified')

    def test_v3_rejects_missing_evidence_without_rewriting_or_retry(self):
        model=FixtureModel('{"highlights":["F1"],"hypotheses":["financial_deterioration"],"assessment":"descriptive_research_only"}')
        report=StudyRuntime(self.f.service,self.f.store,model).run(self.request,self.f.access)
        self.assertEqual(report['model']['status'],'rejected_or_failed')
        self.assertEqual(model.calls,1)
        self.assertNotIn('highlights',report['model'])

    def test_v3_event_candidate_contains_event_price_claim_not_just_general_price(self):
        request,_=with_event(self.f,date_only=True)
        report=StudyRuntime(self.f.service,self.f.store,BundleFixtureModel()).run(request,self.f.access)
        selected={f['name'] for f in report['facts'] if f['id'] in report['model']['highlights']}
        self.assertIn('event_observed_price_change',selected)
        self.assertTrue(any(n.startswith('financial_') for n in selected))
        self.assertEqual(report['model']['hypotheses'],['event_chronology'])

    def test_v3_candidates_are_bounded_and_do_not_promote_insufficient(self):
        request=replace(self.request,hypotheses=('mechanical_adjustment',))
        report=StudyRuntime(self.f.service,self.f.store,BundleFixtureModel()).run(request,self.f.access)
        self.assertEqual(report['hypotheses'][0]['status'],'insufficient')
        self.assertEqual(report['research_status'],'evidence_incomplete')
        options=selection_options(report,request)
        self.assertTrue(1<=len(options)<=5)
        self.assertTrue(all(1<=len(o['highlights'])<=3 for o in options))

    def receipt(self,content,key='synthetic-private-key'):
        path=self.f.artifacts.root.parent/'receipt.json'
        cfg=ModelConfig('https://example.invalid/v1',key)
        def transport(*args):
            return {'model':cfg.model,'choices':[{'message':{'role':'assistant','content':content},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12},'untrusted_extra':'not archived'}
        model=ReceiptModel(cfg,transport,path)
        model.complete([{'role':'user','content':'synthetic'}])
        return json.loads(path.read_bytes())

    def test_receipt_retains_invalid_selection_for_diagnosis_without_response_extras(self):
        receipt=self.receipt('{"wrong_key":"bad model answer"}')
        self.assertEqual(receipt['content'],'{"wrong_key":"bad model answer"}')
        self.assertNotIn('untrusted_extra',receipt)
        self.assertEqual(receipt['total_tokens'],12)

    def test_receipt_never_persists_reflected_model_credential(self):
        self.assertEqual(self.receipt('synthetic-private-key'),{'withheld':'credential_reflection'})

    def test_receipt_catches_credentials_that_json_escapes(self):
        self.assertEqual(self.receipt('test-"-key',key='test-"-key'),{'withheld':'credential_reflection'})
