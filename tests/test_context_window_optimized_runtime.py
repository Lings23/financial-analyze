"""Synthetic v6.1 compatibility/restore mechanisms; no live provider validation."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import test_context_verification_decoupling as v4
import test_context_window_runtime as v6
import test_context_window_security as security
from test_dynamic import SequenceModel, completed_actions
from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.models import digest
from stock_research.research.context_window_metadata import decode_window_metadata_view
from stock_research.research.dynamic_contracts import ParallelParentSpec

VERSION = 'dynamic-parent-parallel-v6.1'


class OptimizedWindowRuntimeTests(unittest.TestCase):
    runtime = v4.VerificationDisclosureTests.runtime
    inputs = v4.VerificationDisclosureTests.inputs
    grant_service = v4.VerificationDisclosureTests.grant_service
    rewrite_history = v4.VerificationDisclosureTests.rewrite_history
    research_signature = staticmethod(v4.VerificationDisclosureTests.research_signature)

    def setUp(self):
        v4.VerificationDisclosureTests.setUp(self)
        self.spec = ParallelParentSpec(version=VERSION)

    def complete(self, *, request=None, service=None, version=VERSION):
        return v4.VerificationDisclosureTests.complete(self, request=request, service=service, version=version)

    @staticmethod
    def expanded_messages(messages):
        copied = deepcopy(messages)
        payload = json.loads(copied[1]['content'])
        payload['context'] = decode_window_metadata_view(payload['context'])
        copied[1]['content'] = json.dumps(payload,ensure_ascii=False)
        return copied

    def decide_pages(self, turn, messages):
        return v6.WindowRuntimeTests.decide_pages(self,turn,self.expanded_messages(messages))

    page_report = v6.WindowRuntimeTests.page_report

    def decide_one_page(self, turn, messages):
        return security.WindowSecurityTests.decide_one_page(self,turn,self.expanded_messages(messages))

    complete_page = security.WindowSecurityTests.complete_page
    fault_run = security.WindowSecurityTests.fault_run

    def test_actual_paid_wire_decodes_original_descriptor_without_changing_full_state(self):
        from stock_research.research.context_window import rebuild_window
        model=SequenceModel(completed_actions())
        report=self.runtime(model).run(self.request,self.f.access,run_id=v6.RUN)
        self.assertEqual(report['status'],'completed')
        states=self.f.store.history(self.f.access.scope,v6.RUN)
        paid={s['decisions'][-1]['turn']:s for s in states
              if s['trace'] and s['trace'][-1]['event']=='model_started'}
        compact=0
        for turn,wire in enumerate(model.messages,1):
            payload=json.loads(wire[1]['content'])
            compact+=payload['context']['schema']=='dynamic-context-window/v2'
            raw=decode_window_metadata_view(payload['context'])
            saved=paid[turn]
            catalog=saved['context_store']['catalogs'][raw['catalog_ref']]
            self.assertEqual(raw,rebuild_window(catalog,saved['context']['window'],
                scope=self.f.access.scope,run_id=v6.RUN))
            self.assertEqual(saved['context']['bytes'],sum(len(m['content'].encode()) for m in wire))
            self.assertEqual(saved['context']['message_sha256'],digest(wire))
            self.assertEqual(saved['context']['window_admission_mode'],'legacy_window_envelope/v1')
        self.assertGreater(compact,0)
        self.assertEqual(report['context_archive']['window_metadata_contract'],'exact_window_metadata/v1')

    def test_raw_table_tamper_after_rehashed_checkpoint_cannot_dispatch(self):
        report,_=self.complete()
        def mutate(states):
            for saved in states:
                if saved.get('context') and 'window_wire_schema' in saved['context']:
                    saved['context']['window_codec_applied']=not saved['context']['window_codec_applied']
        self.rewrite_history(report['run_id'],mutate)
        model=SequenceModel([])
        with self.assertRaises((IntegrityError,PermissionDenied)):
            self.runtime(model).run(self.request,self.f.access,resume=report['run_id'])
        self.assertEqual(model.calls,0)


for _name in (
    'test_two_working_set_replacements_keep_complete_verifier_and_zero_append_replay',
    'test_same_parent_explicit_child_v3_direct_serial_parallel_paths_preserve_quality_and_replay',
    'test_completed_replay_reauthorizes_scope_provider_grants_and_unchanged_snapshot',
    'test_completed_replay_refuses_underlying_artifact_tamper_without_model_or_append',
    'test_original_verifier_rejects_rehashed_value_source_reference_time_and_omission',
    'test_lawful_insufficient_requires_actual_verification_and_preserves_all_gaps',
    'test_current_recovered_calculation_cannot_omit_an_executed_source',
    'test_unknown_paid_result_never_replays_or_releases_reserved_usage',
):
    setattr(OptimizedWindowRuntimeTests,_name,getattr(v6.WindowRuntimeTests,_name))

for _name in (
    'test_started_and_pre_receipt_faults_stop_unknown_without_model_or_read_replay',
    'test_after_receipt_fault_retains_atomic_selection_coverage_and_stops_without_replay',
    'test_coordinated_rehash_cannot_change_committed_receipt_boundary_before_next_paid_turn',
    'test_precommit_intent_budget_must_match_its_already_charged_tool_trace',
):
    setattr(OptimizedWindowRuntimeTests,_name,getattr(security.WindowSecurityTests,_name))


if __name__=='__main__':
    unittest.main()
