"""Offline source-bound mechanism checks; never live model/financial truth."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import context_real_pagination_sources as sources
from stock_research.errors import IntegrityError
from stock_research.research.dynamic_contracts import DynamicRequest


@unittest.skipUnless(sources.MANIFEST.is_file(), 'retained local source fixtures not distributed')
class RealPaginationSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = sources.build_task()
        service, access = sources.context(cls.task)
        _, cls.computed, _ = sources.catalogue_observations(service, access,
            DynamicRequest.from_dict(cls.task['request']))

    def test_new_task_preserves_original_four_source_bindings_and_has_independent_full_gold(self):
        old = next(case for case in sources.read(sources.MANIFEST)['cases'] if case['id'] == sources.BASE_CASE_ID)
        actual = self.task['case']
        expected_bindings = [binding for binding in old['request']['bindings'] if binding['dataset'] in sources.DATASETS]
        self.assertEqual(actual['request']['bindings'], expected_bindings)
        self.assertEqual(actual['request']['as_of'], old['request']['as_of'])
        self.assertEqual(actual['request']['mode'], old['request']['mode'])
        self.assertEqual(set(actual['datasets']), sources.DATASETS)
        self.assertNotIn('index_daily', actual['snapshots'])
        self.assertNotIn('market_direction', actual['request']['hypotheses'])
        self.assertEqual(self.task['oracle']['fact_count'], 14)
        self.assertEqual(self.task['oracle']['evidence_count'], 25)
        self.assertTrue(all(self.task['oracle']['selection_checks'].values()))
        self.assertEqual(len(self.task['goal_objects']), 7)
        self.assertTrue({value['name'] for value in self.task['goal_objects'].values()} <
                        {value['name'] for value in self.task['catalog_observations']['O:hypotheses']['facts'].values()})
        self.assertEqual(sources.sha(sources.ROOT / old['input_path']), old['input_sha256'])

    def test_independent_fraction_oracle_rejects_changed_numeric_value_and_missing_claim(self):
        for change in ('value', 'missing'):
            computed = deepcopy(self.computed)
            if change == 'value':
                computed['facts'][0]['value'] = '999999'
            else:
                computed['facts'].pop()
            with self.subTest(change=change), self.assertRaises(IntegrityError):
                sources.independent_oracle(self.task['case'], self.task['inputs'], computed)

    def test_original_input_order_evidence_metadata_and_hypothesis_counterevidence_cannot_change(self):
        for change in ('inputs', 'evidence', 'counterevidence'):
            computed = deepcopy(self.computed)
            if change == 'inputs':
                fact = next(fact for fact in computed['facts'] if len(fact['inputs']) > 1)
                fact['inputs'].reverse()
            elif change == 'evidence':
                next(iter(computed['evidence'].values()))['provider'] = 'forged-provider'
            else:
                computed['hypotheses'][0]['counterevidence_claim_ids'] = ['forged-claim']
            with self.subTest(change=change), self.assertRaises(IntegrityError):
                sources.independent_oracle(self.task['case'], self.task['inputs'], computed)

    def test_snapshot_member_or_recipient_scope_spoof_cannot_qualify_as_real_source(self):
        for change in ('snapshot', 'scope'):
            payload = deepcopy(self.task['inputs'])
            if change == 'snapshot':
                payload['snapshots'][0]['records'].pop()
            else:
                payload['scope'] = 'forged-recipient'
            with self.subTest(change=change), self.assertRaises(IntegrityError):
                sources.independent_oracle(self.task['case'], payload, self.computed)


if __name__ == '__main__':
    unittest.main()
