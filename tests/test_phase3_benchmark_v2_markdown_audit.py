"""Synthetic inventory checks; mechanical agreement is never semantic truth."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from phase3_benchmark_v2_markdown_audit import audit_markdown


class MarkdownInventoryTests(unittest.TestCase):
    def report(self):
        return {'facts': [{'id': 'a' * 64, 'value': '-0.01234', 'unit': 'ratio'}],
                'hypotheses': [], 'evidence': {}}

    def test_full_text_is_preserved_and_no_mechanical_pass_is_issued(self):
        source = '## 可核查数值\n\n价格变化 -1.23%，引用 `' + 'a' * 64 + '`。\n'
        result = audit_markdown(self.report(), source)
        self.assertEqual([line['text'] for line in result['lines']], source.splitlines())
        self.assertTrue(result['all_lines_included'])
        self.assertFalse(result['full_text_read'])
        self.assertTrue(all(not line['manual_read'] for line in result['lines']))
        self.assertIsNone(result['semantic_pass'])
        self.assertIsNone(result['task_completion_supported'])
        self.assertTrue(result['lines'][2]['display_consistency'][0]['representation_found'])
        self.assertFalse(result['lines'][2]['display_consistency'][0]['is_source_verification'])

    def test_unregistered_claim_and_causal_language_are_only_review_prompts(self):
        source = '## 结论\n事件导致公司利润增长 50%。\n引用 `' + 'b' * 64 + '`。'
        result = audit_markdown(self.report(), source)
        self.assertIn('causal_language', result['potential_additional_claims_or_language_issues'][0]['triggers'])
        self.assertIn('number_without_inline_hash_reference', result['potential_additional_claims_or_language_issues'][0]['triggers'])
        self.assertIn('unregistered_reference', result['potential_additional_claims_or_language_issues'][1]['triggers'])
        self.assertIsNone(result['semantic_pass'])

    def test_negated_causal_language_stays_for_manual_context_review(self):
        result = audit_markdown(self.report(), '事件后上涨不构成因果估计。')
        flag = result['potential_additional_claims_or_language_issues'][0]
        self.assertTrue(flag['explicit_negation_or_limitation'])
        self.assertEqual(flag['semantic_verdict'], 'pending_independent_full_text_review')

    def test_wrong_display_value_is_detected_without_claiming_source_error(self):
        source = '## 可核查数值\n价格变化 -2.00%，引用 `' + 'a' * 64 + '`。'
        result = audit_markdown(self.report(), source)
        self.assertFalse(result['lines'][1]['display_consistency'][0]['representation_found'])
        self.assertIsNone(result['semantic_pass'])


if __name__ == '__main__':
    unittest.main()
