"""Synthetic report presentation and independently calibrated quality rubric."""
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from research_fixtures import fixture
from stock_research.research.report import display_value, markdown, displayed_highlights

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from accept_phase2_quality import selection_checks


class ResearchQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = fixture(Path(self.temp.name))
        self.report = self.f.runtime.run(self.f.request, self.f.access)

    def test_display_units_negative_values_and_rounding(self):
        for value, unit, expected in (('-0.01726973684210526315789', 'ratio', '-1.73%'),
                                      ('12619215000', 'CNY', '126.19 亿元'),
                                      ('-383328019.43', 'CNY', '-3.83 亿元'),
                                      ('10000', 'CNY', '1.00 万元'), ('12.34', 'CNY', '12.34 元'),
                                      ('1.005', 'CNY', '1.01 元'), ('-1.005', 'CNY', '-1.01 元')):
            with self.subTest(value=value):
                self.assertEqual(display_value({'value': value, 'unit': unit}), expected)

    def test_readable_summary_preserves_exact_report_and_citations(self):
        original = deepcopy(self.report)
        rendered = markdown(self.report)
        self.assertIn('## 概览', rendered)
        self.assertIn('-10.00%', rendered)
        self.assertIn('25.00%', rendered)
        self.assertIn('2025-04-01 → 2025-04-03', rendered)
        self.assertIn('数据覆盖尚未认证', rendered)
        for f in self.report['facts']:
            self.assertIn(f['id'], rendered)
        self.assertEqual(self.report, original)

    def test_no_visible_market_is_not_reported_as_zero_price_change(self):
        f = fixture(Path(self.temp.name) / 'missing', prices=(None, None))
        rendered = markdown(f.runtime.run(f.request, f.access))
        summary = rendered.split('## 概览')[1].split('## 请求')[0]
        self.assertIn('无法计算价格变化', summary)
        self.assertNotIn('价格变化 0.00%', summary)

    def test_unavailable_yoy_has_plain_chinese_explanation(self):
        report = deepcopy(self.report)
        report['gaps'].append('revenue:yoy_prior_year_period_not_visible')
        self.assertIn('缺少上年同报告期基数，无法计算同比', markdown(report))

    def test_rubric_rejects_valid_but_one_domain_only_selection(self):
        report = deepcopy(self.report)
        report['model'] = {'status': 'verified', 'highlights': [report['facts'][0]['id']]}
        checks = selection_checks(report)
        self.assertTrue(checks['valid_existing_claims'])
        self.assertFalse(checks['financial_covered_when_available'])

    def test_rubric_distinguishes_semantic_redundancy_and_equal_values(self):
        report = deepcopy(self.report)
        revenue = next(f for f in report['facts'] if f['name'] == 'financial_income.revenue')
        total = next(f for f in report['facts'] if f['name'] == 'financial_income.total_revenue')
        total['value'] = revenue['value']
        report['model'] = {'status': 'verified', 'highlights': [report['facts'][0]['id'], revenue['id'], total['id']]}
        self.assertFalse(selection_checks(report)['no_equal_revenue_redundancy'])
        total['value'] = '101'
        self.assertTrue(selection_checks(report)['no_equal_revenue_redundancy'])

    def test_rubric_accepts_missing_market_when_only_financial_facts_available(self):
        report = deepcopy(self.report)
        report['facts'] = [f for f in report['facts'] if f['name'] in {'financial_income.revenue', 'financial_income.net_income_parent'}]
        report['model'] = {'status': 'verified', 'highlights': [f['id'] for f in report['facts']]}
        self.assertTrue(all(selection_checks(report).values()))

    def test_rubric_requires_verified_real_selection_and_known_ids(self):
        report = deepcopy(self.report)
        report['model'] = {'status': 'rejected_or_failed', 'highlights': ['unknown']}
        self.assertFalse(selection_checks(report)['verified_model'])
        self.assertFalse(selection_checks(report)['valid_existing_claims'])

    def test_display_merges_equal_income_without_rewriting_failed_raw_selection(self):
        report = deepcopy(self.report)
        revenue = next(f for f in report['facts'] if f['name'] == 'financial_income.revenue')
        total = next(f for f in report['facts'] if f['name'] == 'financial_income.total_revenue')
        total['value'] = revenue['value']
        profit = next(f for f in report['facts'] if f['name'] == 'financial_income.net_income_parent')
        report['model'] = {'status': 'verified', 'highlights': [profit['id'], revenue['id'], total['id']]}
        original = deepcopy(report)
        rendered = markdown(report)
        section = rendered.split('## 模型重点选择')[1].split('## 数据缺口')[0]
        self.assertIn('展示已合并', section)
        self.assertIn('营业收入（累计）', section)
        self.assertNotIn('营业总收入（累计）', section)
        self.assertEqual(report, original)
        self.assertFalse(selection_checks(report)['no_equal_revenue_redundancy'])

    def test_display_keeps_distinct_income_and_same_value_other_metrics(self):
        report = deepcopy(self.report)
        revenue = next(f for f in report['facts'] if f['name'] == 'financial_income.revenue')
        total = next(f for f in report['facts'] if f['name'] == 'financial_income.total_revenue')
        profit = next(f for f in report['facts'] if f['name'] == 'financial_income.net_income_parent')
        profit['value'] = revenue['value']
        total['value'] = '101'
        report['model'] = {'status': 'verified', 'highlights': [revenue['id'], profit['id'], total['id']]}
        self.assertEqual(len(displayed_highlights(report)[0]), 3)
        total['value'] = revenue['value']
        total['window'] = ['2023-12-31', '2023-12-31']
        self.assertEqual(len(displayed_highlights(report)[0]), 3)
