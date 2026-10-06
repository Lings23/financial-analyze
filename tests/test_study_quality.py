"""Synthetic tests of the independent quality rubric; no model/provider validation."""
from pathlib import Path
from dataclasses import replace
from datetime import date
import sys
from tempfile import TemporaryDirectory
import unittest

from research_fixtures import fixture
from study_fixtures import study_request, with_event
from stock_research.research.study import StudyRuntime
from stock_research.research.report import markdown, displayed_highlights, study_supplements
from stock_research.models import digest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from accept_phase3_quality import quality_checks


class StudyQualityTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.f=fixture(Path(temp.name))
        self.report=StudyRuntime(self.f.service,self.f.store).run(study_request(self.f),self.f.access)

    def select(self,names,hypotheses):
        self.report['model']={'status':'verified','highlights':[f['id'] for f in self.report['facts'] if f['name'] in names],
                              'hypotheses':hypotheses}

    def test_valid_ids_alone_do_not_meet_research_quality(self):
        self.select({'financial_income.revenue','financial_income.total_revenue','financial_income.net_income_parent'},
                    ['financial_deterioration'])
        checks=quality_checks(self.report)
        self.assertTrue(checks['verified_model'])
        self.assertFalse(checks['market_covered_when_available'])
        self.assertFalse(checks['no_equal_revenue_redundancy'])
        self.assertFalse(checks['selected_hypothesis_evidence_highlighted'])

    def test_informative_selection_covers_both_domains_and_hypothesis_evidence(self):
        self.select({'observed_price_change','revenue_yoy','net_income_parent_yoy'},['financial_deterioration'])
        self.assertTrue(all(quality_checks(self.report).values()))

    def test_equal_revenue_aliases_compare_numeric_values(self):
        self.select({'observed_price_change','financial_income.revenue','financial_income.total_revenue'},['financial_deterioration'])
        for fact in self.report['facts']:
            if fact['name']=='financial_income.total_revenue': fact['value']='100.000'
        self.assertFalse(quality_checks(self.report)['no_equal_revenue_redundancy'])

    def test_event_review_requires_the_requested_test_in_model_selection(self):
        request,_=with_event(self.f)
        self.report=StudyRuntime(self.f.service,self.f.store).run(request,self.f.access)
        self.select({'event_observed_price_change'},[])
        self.assertFalse(quality_checks(self.report)['event_test_selected'])

    def test_system_supplement_preserves_original_answer_and_counterevidence(self):
        self.select({'observed_price_change'},['financial_deterioration'])
        before=digest(self.report)
        added=study_supplements(self.report)
        self.assertEqual({f['name'] for f in added},{'revenue_yoy','net_income_parent_yoy'})
        hypothesis=next(h for h in self.report['hypotheses'] if h['id']=='financial_deterioration')
        self.assertEqual({f['id'] for f in added},set(hypothesis['claim_ids']))
        self.assertTrue(set(hypothesis['counterevidence_claim_ids']) <= {f['id'] for f in added})
        rendered=markdown(self.report)
        self.assertIn('## 系统核对重点',rendered)
        self.assertIn('不是模型选择',rendered)
        self.assertEqual(digest(self.report),before)
        self.assertFalse(quality_checks(self.report)['financial_covered_when_available'])
        visible=displayed_highlights(self.report)[0]+added
        self.assertTrue(all(quality_checks(self.report,visible_highlights=[f['id'] for f in visible]).values()))

    def test_complete_model_selection_needs_no_system_supplement(self):
        self.select({'observed_price_change','revenue_yoy','net_income_parent_yoy'},['financial_deterioration'])
        self.assertFalse(study_supplements(self.report))
        self.assertNotIn('## 系统核对重点',markdown(self.report))

    def test_missing_yoy_does_not_become_a_fabricated_test_or_value(self):
        request=study_request(self.f)
        request=replace(request,bindings=tuple(replace(b,start=date(2024,1,1)) if b.dataset=='financial_income'
                                              else b for b in request.bindings))
        self.report=StudyRuntime(self.f.service,self.f.store).run(request,self.f.access)
        self.select({'observed_price_change'},['financial_deterioration'])
        added=study_supplements(self.report)
        self.assertEqual({f['name'] for f in added},{'financial_income.revenue','financial_income.net_income_parent'})
        self.assertEqual(next(h['status'] for h in self.report['hypotheses'] if h['id']=='financial_deterioration'),'insufficient')

    def test_supplement_requires_verified_study_and_preserves_overview(self):
        self.select({'observed_price_change'},['financial_deterioration'])
        self.report['verification']['status']='not_completed'
        self.assertFalse(study_supplements(self.report))
        self.report['verification']['status']='verified'
        self.report['model']['status']='failed'
        self.assertFalse(study_supplements(self.report))
        self.report['model']['status']='verified'
        self.report['schema']='single-overview/v1'
        self.assertFalse(study_supplements(self.report))
