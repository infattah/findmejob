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

class ReviewerRequestedDedupeRegressions(unittest.TestCase):
    def test_wrapper_similarity_is_order_independent(self):
        # This pair has enough repetitive structure to exercise SequenceMatcher's
        # directional heuristics while representing the same underlying posting.
        base=("Own paid media, growth campaigns, Meta, Google, CAC, ROAS, attribution, pipeline and reporting. "*5)
        a=JobPosting(title="Performance and Growth Specialist",company="Recruiter A",location="Bahrain",url="https://a.test/1",description=base+"Apply through Recruiter A.")
        b=JobPosting(title="Performance And Growth Specialist",company="Client B",location="Bahrain",url="https://b.test/2",description=base+"Apply through Client B.")
        self.assertEqual(1,len(dedupe_batch([a,b])[0]))
        self.assertEqual(1,len(dedupe_batch([b,a])[0]))

    def test_same_title_city_and_recruiter_boilerplate_do_not_merge(self):
        boiler=("Our recruiter supports leading clients and offers equal opportunity, benefits, interview support and application guidance. "*3)
        a=JobPosting(title="Marketing Manager",company="Client A",location="Dubai",url="https://a.test/1",description=boiler+"Own retail loyalty, in-store promotions and franchise launches across the UAE.")
        b=JobPosting(title="Marketing Manager",company="Client B",location="Dubai",url="https://b.test/2",description=boiler+"Own cybersecurity field events, channel partners and enterprise pipeline across META.")
        self.assertEqual(2,len(dedupe_batch([a,b])[0]))
        self.assertEqual(2,len(dedupe_batch([b,a])[0]))

class ReviewerRequestedAshbyRefreshRegressions(unittest.TestCase):
    def _job(self, status="alive", checked=1000.0):
        return JobPosting(title="Marketing Lead",company="Acme",url="https://jobs.ashbyhq.com/acme/job-1",source="ashby:acme",apply_url="https://jobs.ashbyhq.com/acme/job-1/application",source_liveness=status,source_liveness_detail="Ashby fixture",source_liveness_checked_at=checked)

    def test_fresh_hint_is_bounded_and_accepted(self):
        called=[]
        self.assertEqual("alive",check_job_liveness(self._job(),now=1100,json_opener=lambda *_: called.append(1))[0])
        self.assertEqual([],called)

    def test_stale_alive_hint_rechecks_and_observes_unlisted(self):
        data={"jobs":[{"jobUrl":"https://jobs.ashbyhq.com/acme/job-1","isListed":False}]}
        self.assertEqual("expired",check_job_liveness(self._job(),now=2000,json_opener=lambda *_:data)[0])

    def test_stale_hint_rechecks_and_missing_job_is_expired(self):
        self.assertEqual("expired",check_job_liveness(self._job(),now=2000,json_opener=lambda *_:{"jobs":[]})[0])

    def test_stale_hint_rechecks_and_ambiguous_or_failure_is_unknown(self):
        ambiguous={"jobs":[{"jobUrl":"https://jobs.ashbyhq.com/acme/job-1","isListed":True}]}
        self.assertEqual("unknown",check_job_liveness(self._job(),now=2000,json_opener=lambda *_:ambiguous)[0])
        def fail(*_): raise TimeoutError()
        self.assertEqual("unknown",check_job_liveness(self._job(),now=2000,json_opener=fail)[0])

class ProfessionNeutralTenureRegression(unittest.TestCase):
    def test_overall_engineering_tenure_grounds_engineering_requirement(self):
        profile=Profile(summary="Software engineer with 9+ years in software engineering overall. Python, distributed systems and cloud platforms.")
        job=JobPosting(title="Senior Software Engineer",company="Acme",description="Requirements\n- 7+ years in software engineering")
        item=evaluate_requirements(profile,job).items[0]
        self.assertEqual("strong",item.status)
        self.assertEqual(0,evaluate_requirements(profile,job).hard_missing)

    def test_unrelated_engineering_tenure_does_not_ground_marketing(self):
        profile=Profile(summary="Software engineer with 9+ years in software engineering overall.")
        job=JobPosting(title="Marketing Manager",company="Acme",description="Requirements\n- 7+ years in marketing")
        self.assertNotEqual("strong",evaluate_requirements(profile,job).items[0].status)

class FinalReviewDedupeAdversarialRegressions(unittest.TestCase):
    def _pair(self):
        template=("Our recruiter supports leading clients. Equal opportunity, application guidance and interview support. "*8)
        retail=("Own retail loyalty campaigns, in-store promotions, franchise launches, shopper marketing, merchandising and store traffic across the UAE. "*3)
        cyber=("Own cybersecurity field events, enterprise channel partners, MSSP pipeline, security buyer campaigns, partner enablement and threat research webinars. "*3)
        a=JobPosting(title="Marketing Manager",company="Same Employer",location="Dubai",url="https://ats.test/req-101",description=template+retail)
        b=JobPosting(title="Marketing Manager",company="Same Employer",location="Dubai",url="https://ats.test/req-202",description=template+cyber)
        return a,b

    def test_same_employer_title_location_distinct_requisitions_stay_separate_both_orders(self):
        a,b=self._pair()
        self.assertEqual(2,len(dedupe_batch([a,b])[0]))
        self.assertEqual(2,len(dedupe_batch([b,a])[0]))

    def test_long_recruiter_template_cannot_swamp_retail_vs_cybersecurity_duties(self):
        a,b=self._pair()
        self.assertIsNone(__import__("findmejob.dedupe",fromlist=["find_duplicate"]).find_duplicate(a,[b]))
        self.assertIsNone(__import__("findmejob.dedupe",fromlist=["find_duplicate"]).find_duplicate(b,[a]))

class FinalReviewAshbyMalformedPayloadRegressions(unittest.TestCase):
    def _stale(self,checked=1000):
        return JobPosting(title="Role",company="Acme",url="https://jobs.ashbyhq.com/acme/job-1",source="ashby:acme",source_liveness="alive",source_liveness_detail="old",source_liveness_checked_at=checked)

    def test_error_and_malformed_payloads_are_unknown(self):
        shapes=({"error":"rate limited"},{"jobs":None},[],{"jobs":"bad"},{"jobs":[None]})
        for payload in shapes:
            with self.subTest(payload=payload):
                self.assertEqual("unknown",check_job_liveness(self._stale(),now=2000,json_opener=lambda *_,p=payload:p)[0])

    def test_transport_and_api_failures_are_unknown(self):
        import urllib.error
        for error in (TimeoutError(),urllib.error.HTTPError("u",429,"rate",{},None),ValueError("bad json")):
            def fail(*_,e=error): raise e
            with self.subTest(error=type(error).__name__):
                self.assertEqual("unknown",check_job_liveness(self._stale(),now=2000,json_opener=fail)[0])

    def test_future_dated_hint_is_not_trusted(self):
        payload={"jobs":[{"jobUrl":"https://jobs.ashbyhq.com/acme/job-1","isListed":False}]}
        self.assertEqual("expired",check_job_liveness(self._stale(checked=3000),now=2000,json_opener=lambda *_:payload)[0])

    def test_only_valid_board_omission_can_expire(self):
        self.assertEqual("expired",check_job_liveness(self._stale(),now=2000,json_opener=lambda *_:{"jobs":[]})[0])
        self.assertEqual("unknown",check_job_liveness(self._stale(),now=2000,json_opener=lambda *_:{"error":"rate limited"})[0])
