import json, tempfile, unittest
from pathlib import Path
from findmejob.config import Config
from findmejob.models import JobPosting, Profile
from findmejob.pipeline import run_triage, run_tailor
from findmejob.packs import build_pack
from findmejob.tracker import Tracker
from findmejob.verification import CompanyVerification, Evidence, ApplicationRoute

class QualificationIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); root=Path(self.tmp.name)
        (root/'cv.md').write_text('# A\n## Summary\nGrowth marketer with 7+ years experience\n## Skills\n- Google Ads\n- Analytics\n')
        self.cfg=Config(root=root,raw={'profile':{'master_cv':'cv.md'},'search':{'role_keywords':['growth marketing']},'policy':{'locations_include':['Dubai']},'paths':{'db':'db.sqlite','output':'out'}})
        self.t=Tracker(self.cfg.db_path)
    def tearDown(self): self.t.close(); self.tmp.cleanup()
    def job(self, company='Acme', desc='Lead Google Ads and analytics. Requirements\n- Requires 5+ years of experience'):
        j=JobPosting(title='Growth Marketing Manager',company=company,location='Dubai',url='https://acme.test/job',description=desc); self.t.upsert_job(j,verdict='pass'); self.t.conn.commit(); return j
    def verify(self,j):
        self.t.set_verification(j.id,CompanyVerification(company=j.company,status='verified',official_domain='acme.test',evidence=[Evidence('official_website','https://acme.test'),Evidence('linkedin','https://linkedin.com/company/acme'),Evidence('ats','https://acme.test/jobs')],routes=[ApplicationRoute('job_page',j.url,j.url,verified=True)]))
    def test_unverified_never_actionable_and_gates_outputs(self):
        j=self.job(); self.t.set_liveness(j.id,'alive','apply now'); run_triage(self.cfg,self.t)
        self.assertEqual('insufficient_evidence',self.t.qualification(j.id)['decision'])
        self.assertIn('not actionable',run_tailor(self.cfg,self.t,j.id)['error']); self.assertIn('not actionable',build_pack(self.cfg,self.t,j.id)['error'])
    def test_strong_flow_then_expiry_recomputes(self):
        j=self.job(); self.verify(j); self.t.set_liveness(j.id,'alive','apply now'); run_triage(self.cfg,self.t)
        self.assertEqual('strong',self.t.qualification(j.id)['decision']); self.assertNotIn('error',build_pack(self.cfg,self.t,j.id))
        self.t.set_liveness(j.id,'expired','closed'); run_triage(self.cfg,self.t)
        self.assertEqual('stale',self.t.qualification(j.id)['decision'])
    def test_policy_review_precedence_and_persistence(self):
        j=self.job(company='Unknown Casino',desc='We operate gaming venues. Lead acquisition. Requirements\n- Requires 5+ years of experience')
        self.cfg.raw['policy']['sector_exclusions']=['gaming']; self.verify(j); self.t.set_liveness(j.id,'alive','apply now'); run_triage(self.cfg,self.t)
        self.assertEqual('reject',self.t.qualification(j.id)['decision'])
        self.t.close(); self.t=Tracker(self.cfg.db_path); self.assertEqual('reject',self.t.qualification(j.id)['decision'])

    def test_terminal_status_blocks_stale_strong_decision(self):
        from findmejob.qualification import QualificationResult, QualificationSignals
        j=self.job(); self.verify(j); self.t.set_liveness(j.id,'alive','apply now'); run_triage(self.cfg,self.t)
        self.assertEqual('strong',self.t.qualification(j.id)['decision'])
        for status in ('skipped', 'rejected'):
            self.t.set_status(j.id,status,'terminal workflow state')
            self.assertIn(f'tracker status is {status}',self.t.require_strong(j.id))
