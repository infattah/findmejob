import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from findmejob.benchmark import run_replay_benchmark
from findmejob.dedupe import dedupe_batch
from findmejob.pipeline import run_search
from findmejob.evidence import evaluate_requirements
from findmejob.liveness import check_job_liveness, check_listing
from findmejob.models import JobPosting, Profile
from findmejob.signal_adapter import build_signals
from findmejob.sources.ashby import AshbySource
from findmejob.tracker import Tracker
from findmejob.verification import CompanyVerification

ROOT=Path(__file__).parent.parent
PROFILE=Profile(summary="Performance marketer with 7+ years in marketing overall. Hands-on performance marketing, paid media, demand generation, pipeline, attribution, CAC and LTV.", skills=["Google Ads", "Meta Ads", "Marketing automation"])

class TrialSixEvidenceRegressions(unittest.TestCase):
    def test_mc_saatchi_range_uses_floor_and_overall_marketing_tenure(self):
        job=JobPosting(title="Marketing Manager", company="M+C Saatchi", description="ABOUT YOU\n- 4-6+ years' experience in marketing")
        item=evaluate_requirements(PROFILE,job).items[0]
        self.assertEqual("strong",item.status)
        self.assertEqual(0,evaluate_requirements(PROFILE,job).hard_missing)

    def test_lndmrk_preferred_section_never_creates_hard_gaps(self):
        job=JobPosting(title="Marketing Lead",company="Lndmrk",description="Requirements\n- 6-10+ years in marketing\nPreferred\n- Experience in real estate, proptech, or SaaS platforms\n- Familiarity with both B2B and B2C growth strategies")
        report=evaluate_requirements(PROFILE,job)
        self.assertEqual("strong",report.items[0].status)
        self.assertTrue(all(i.preferred and not i.hard for i in report.items[1:]))
        self.assertEqual(0,report.hard_missing)

    def test_vidrush_company_copy_and_responsibilities_are_not_requirements(self):
        job=JobPosting(title="Marketing Manager",company="VidRush",description="About us\nVidRush is an AI-native video production platform that replaces an entire video team with coordinated AI agents.\nResponsibilities\n- Create and adapt content that fits the native voice of each platform\nRequirements\n- 3-7 years in performance or growth marketing\nDesirable\n- Familiarity with the SaaS or creator-tools landscape")
        report=evaluate_requirements(PROFILE,job)
        text=" | ".join(i.requirement for i in report.items)
        self.assertNotIn("AI-native video production",text)
        self.assertNotIn("native voice",text)
        self.assertTrue(report.items[-1].preferred)
        self.assertFalse(report.items[-1].hard)

    def test_what_would_amaze_us_is_preferred(self):
        job=JobPosting(title="Brand Marketing Manager",company="Ziina",description="Requirements\n- 5+ years in brand marketing\nWhat would amaze us\n- You have fintech influencer experience")
        report=evaluate_requirements(PROFILE,job)
        self.assertTrue(report.items[-1].preferred)
        self.assertFalse(report.items[-1].hard)

class TrialSixLivenessRegressions(unittest.TestCase):
    def test_teamtailor_inactive_phrase_is_expired(self):
        body="<button>Apply now</button>This position is no longer active"+"x"*1000
        self.assertEqual("expired",check_listing("https://x.test/j",lambda *_:(200,body))[0])

    def test_ashby_structured_alive_requires_listed_and_apply_url(self):
        payload={"jobs":[{"id":"a","title":"Marketing Lead","location":{"name":"Dubai"},"jobUrl":"https://jobs.ashbyhq.com/x/a","applyUrl":"https://jobs.ashbyhq.com/x/a/application","isListed":True,"descriptionPlain":"Requirements\n- 5+ years in marketing"}]}
        with patch("findmejob.sources.ashby.http_json",return_value=payload): job=AshbySource({"board":"x"}).fetch()[0]
        self.assertEqual(("alive","Ashby posting API: isListed=true and applyUrl present"),check_job_liveness(job))

    def test_ashby_unlisted_is_expired_and_ambiguous_is_unknown(self):
        base={"id":"a","title":"Marketing Lead","location":{"name":"Dubai"},"jobUrl":"https://jobs.ashbyhq.com/x/a","descriptionPlain":"Requirements\n- 5+ years in marketing"}
        with patch("findmejob.sources.ashby.http_json",return_value={"jobs":[{**base,"isListed":False}]}): closed=AshbySource({"board":"x"}).fetch()[0]
        self.assertEqual("expired",check_job_liveness(closed)[0])
        with patch("findmejob.sources.ashby.http_json",return_value={"jobs":[{**base,"isListed":True}]}): ambiguous=AshbySource({"board":"x"}).fetch()[0]
        self.assertEqual("",ambiguous.source_liveness)

class TrialSixDedupeAndDomain(unittest.TestCase):
    def test_pipeline_retains_primary_and_apply_routes(self):
        td=tempfile.TemporaryDirectory(); tracker=Tracker(Path(td.name)/"x.db")
        job=JobPosting(title="Marketing Lead",company="Acme",url="https://jobs.example/acme/1",apply_url="https://apply.example/acme/1",source="ashby:acme",description="Requirements\n- 5+ years in marketing")
        cfg=type("C",(),{"search":{"sources":[]},"policy":{},"paths":{},"resolve":lambda self,x:Path(x)})()
        with patch("findmejob.pipeline.fetch_all",return_value=([job],[])):
            run_search(cfg,tracker)
        urls={x["url"] for x in tracker.links(job.id)}
        self.assertEqual({job.url,job.apply_url},urls)
        tracker.close(); td.cleanup()

    def test_qureos_burjline_wrappers_merge_and_keep_source_pair(self):
        desc=("Own paid media and growth campaigns across Meta and Google, optimise CAC and ROAS, report attribution and pipeline. "*4)
        a=JobPosting(title="Performance and Growth Specialist",company="Qureos client",location="Bahrain",url="https://qureosinc.teamtailor.com/jobs/8297918",source="qureos",description=desc)
        b=JobPosting(title="Performance And Growth Specialist",company="Burjline Builders",location="Bahrain",url="https://burjline.teamtailor.com/jobs/8303695",source="burjline",description=desc)
        unique,dupes=dedupe_batch([a,b])
        self.assertEqual(1,len(unique)); self.assertEqual([(a,b)],dupes)

    def _signals(self,description):
        td=tempfile.TemporaryDirectory(); tracker=Tracker(Path(td.name)/"x.db")
        job=JobPosting(title="Marketing Manager",company="Acme",location="Dubai",url="https://x.test",description=description)
        tracker.upsert_job(job); tracker.set_liveness(job.id,"alive","fixture")
        tracker.set_verification(job.id,CompanyVerification(company="Acme",status="review"))
        signals=build_signals(profile=PROFILE,job=job,policy={},role_keywords=["marketing manager"],tracker=tracker)
        tracker.close(); td.cleanup(); return signals

    def test_horizon_cybersecurity_is_not_direct_from_generic_evidence(self):
        s=self._signals("Requirements\n- 6+ years in B2B cybersecurity marketing")
        self.assertEqual("mismatch",s.domain_transferability)

    def test_generic_marketing_without_industry_requirement_is_transferable(self):
        s=self._signals("Requirements\n- 5+ years in marketing")
        self.assertEqual("transferable",s.domain_transferability)

class TrialSixReplayBenchmark(unittest.TestCase):
    def test_trials_1_6_replay_exercises_real_signal_production(self):
        result=run_replay_benchmark(ROOT/"tests/fixtures/trials_1_6_replay.json")
        self.assertEqual(8,result.total)
        self.assertEqual(8,result.correct)
        self.assertEqual(0,result.zero_tolerance_failures)

if __name__ == "__main__": unittest.main()
