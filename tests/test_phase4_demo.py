"""Synthetic demonstration bookkeeping and authorization checks; no live calls."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from research_fixtures import FixtureModel, fixture
from stock_research.errors import IntegrityError, ValidationError
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest
from stock_research.research.dynamic_protocol import bound_required_checks, dynamic_messages

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import phase4_demo as demo


class Phase4DemoTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.f = fixture(self.root / 'synthetic')
        self.request = DynamicRequest.from_dict({**self.f.request.to_dict(),
                                               'hypotheses': ['financial_deterioration'],
                                               'question': 'SYNTHETIC: inspect the bound financial evidence'})
        self.envelope = demo.authorized_envelope(self.f.service, self.f.access, self.request)
        self.messages = DynamicRuntime(self.f.service, None).preview(self.request, self.f.access)
        self.item = {'case_id': 'synthetic-m1', 'request': self.request.to_dict(), 'messages': self.messages,
                     'authorization_envelope': self.envelope}

    def derived_messages(self):
        observations = list(self.envelope['source_observations'].values()) + [self.envelope['all_bound_computable_values']]
        return dynamic_messages(self.request, ['calculation', 'financial', 'hypotheses', 'market', 'verification'],
                                observations, bound_required_checks(self.request), ['SYNTHETIC: verify bound values'],
                                demo.SPEC.context_bytes, decision=2)[0]

    def model(self, content=None, crash=None):
        model = FixtureModel(crash=crash)
        model.config = SimpleNamespace(model=demo.SPEC.model, api_key='synthetic-local-secret')
        if content is not None:
            model.content = content
        return model

    def test_new_tasks_pin_source_scope_window_cutoff_without_rewriting_parents(self):
        cases = []
        for _, parent_id, _ in demo.SELECTION:
            cases.append({'id': parent_id, 'request': self.f.request.to_dict(),
                          'source_scopes': {binding.dataset: self.f.access.scope for binding in self.f.request.bindings},
                          'source_hashes': {'synthetic-source.json': 'a' * 64}})
        original = deepcopy(cases)
        tasks = demo.build_tasks({'cases': cases})
        self.assertEqual(len(tasks), 3)
        self.assertEqual(cases, original)
        for task, parent in zip(tasks, cases):
            self.assertEqual(task['request']['as_of'], parent['request']['as_of'])
            self.assertEqual(task['request']['mode'], parent['request']['mode'])
            self.assertEqual(task['request']['bindings'], parent['request']['bindings'])
            self.assertEqual(task['request']['hypotheses'], ['financial_deterioration'])
            self.assertNotEqual(task['id'], parent['id'])
            self.assertEqual(task['parent_case_id'], parent['id'])
            self.assertTrue(task['success_criteria'])
            self.assertFalse(task['novelty']['blind'])

    def test_first_and_typed_later_messages_match_frozen_authorization_values(self):
        demo.validate_outbound(self.messages, self.item, 1)
        demo.validate_outbound(self.derived_messages(), self.item, 2)
        self.assertEqual(self.envelope['kind'], 'offline_authorization_envelope_not_agent_execution')
        self.assertEqual(self.envelope['model_calls'], 0)
        self.assertEqual(self.envelope['provider_network_calls'], 0)

    def test_outbound_scope_first_message_and_numeric_forgery_rejected(self):
        first = deepcopy(self.messages)
        first[1]['content'] += ' '
        with self.assertRaises(IntegrityError):
            demo.validate_outbound(first, self.item, 1)
        for path in ('cutoff', 'value', 'source_version_ref'):
            with self.subTest(path=path):
                messages = self.derived_messages()
                payload = json.loads(messages[1]['content'])
                if path == 'cutoff':
                    payload['cutoff'] = '2099-01-01T00:00:00+00:00'
                elif path == 'value':
                    next(iter(payload['derived_state']['facts'].values()))['value'] = '999'
                else:
                    next(iter(payload['derived_state']['evidence'].values()))['source_version_ref'] = '0' * 64
                messages[1]['content'] = json.dumps(payload, ensure_ascii=False)
                with self.assertRaises((IntegrityError, ValidationError)):
                    demo.validate_outbound(messages, self.item, 2)

    def test_unknown_usage_stays_reserved_known_usage_reconciles_before_next_call(self):
        messages = [{'content': 'abc'}]
        ledger = demo.RootLedger(max_decisions=3, max_tokens=500)
        first = ledger.reserve('synthetic', messages, 10)
        self.assertEqual(ledger.accounted, 269)
        response = self.model().complete([])
        ledger.settle(first, response)
        self.assertEqual(ledger.accounted, 120)
        second = ledger.reserve('synthetic', messages, 10)
        self.assertEqual(ledger.accounted, 389)
        self.assertEqual(ledger.snapshot()['unknown_usage_calls'], 1)
        with self.assertRaises(ValidationError):
            ledger.reserve('synthetic', messages, 10)
        self.assertEqual(ledger.accounted, 389)
        with self.assertRaises(IntegrityError):
            ledger.settle(first, response)
        self.assertEqual(second['usage_status'], 'unknown')

    def test_invalid_receipts_and_wrong_model_retain_root_reservation(self):
        response = self.model().complete([])
        for invalid in (replace(response, returned_model='other'), replace(response, finish_reason='length'),
                        replace(response, latency_ms=-1), replace(response, total_tokens=999999)):
            with self.subTest(invalid=invalid):
                ledger = demo.RootLedger()
                intent = ledger.reserve('synthetic', self.messages, demo.SPEC.output_tokens)
                reserved = ledger.accounted
                ledger.settle(intent, invalid)
                self.assertEqual(ledger.accounted, reserved)
                self.assertEqual(ledger.snapshot()['unknown_usage_calls'], 1)

    def test_root_decision_limit_prevents_additional_paid_dispatch(self):
        ledger = demo.RootLedger(max_decisions=1)
        ledger.reserve('synthetic', self.messages, demo.SPEC.output_tokens)
        with self.assertRaises(ValidationError):
            ledger.reserve('synthetic', self.messages, demo.SPEC.output_tokens)
        self.assertEqual(ledger.snapshot()['decisions'], 1)

    def test_recording_model_persists_exact_messages_intent_and_known_receipt(self):
        model, ledger = self.model(), demo.RootLedger()
        recording = demo.RecordingModel(model, self.item, ledger, self.root / 'calls')
        result = recording.complete(self.messages, max_tokens=demo.SPEC.output_tokens, timeout=1)
        self.assertEqual(model.calls, 1)
        self.assertEqual(result.total_tokens, 120)
        paths = list((self.root / 'calls').glob('*.json'))
        self.assertEqual(len(paths), 4)
        recorded = json.loads(next(path for path in paths if path.name.startswith('messages')).read_text(encoding='utf-8'))
        self.assertEqual(recorded, self.messages)
        self.assertEqual(ledger.snapshot()['known_tokens'], 120)
        self.assertEqual(ledger.snapshot()['unknown_usage_calls'], 0)

    def test_encoded_credential_reflection_is_withheld_before_receipt_persistence(self):
        secret = 'synthetic-local-secret'
        encoded = ''.join('\\u%04x' % ord(character) for character in secret)
        content = '{"action":"finish","reason":"completed","plan":["' + encoded + '"]}'
        model = self.model(content=content)
        ledger = demo.RootLedger()
        recording = demo.RecordingModel(model, self.item, ledger, self.root / 'calls')
        recording.complete(self.messages, max_tokens=demo.SPEC.output_tokens, timeout=1)
        receipt_path = next((self.root / 'calls').glob('receipt-*.json'))
        raw = receipt_path.read_text(encoding='utf-8')
        self.assertNotIn(secret, raw)
        self.assertNotIn(encoded, raw)
        self.assertEqual(json.loads(raw)['status'], 'withheld')
        self.assertTrue(demo.receipt_reflects_secret({'content': '{"p":"' + encoded + '","p":"safe"}'}, secret))
        self.assertTrue(demo.receipt_reflects_secret({'content': 'malformed JSON with ' + encoded}, secret))

    def test_adapter_exception_records_sanitized_unknown_outcome_without_retry(self):
        model = self.model(crash=ValueError('synthetic-local-secret must never be persisted'))
        ledger = demo.RootLedger()
        recording = demo.RecordingModel(model, self.item, ledger, self.root / 'calls')
        with self.assertRaises(ValueError):
            recording.complete(self.messages, max_tokens=demo.SPEC.output_tokens, timeout=1)
        self.assertEqual(model.calls, 1)
        self.assertEqual(ledger.snapshot()['unknown_usage_calls'], 1)
        combined = ''.join(path.read_text(encoding='utf-8') for path in (self.root / 'calls').glob('*.json'))
        self.assertNotIn('synthetic-local-secret', combined)
        self.assertIn('unknown_outcome', combined)


if __name__ == '__main__':
    unittest.main()
