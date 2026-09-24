"""Email finder, listing salary extraction, and the email route in the tracker.

All companies, domains and addresses here are fictional (.test TLD).
No network access: fetcher, searcher and MX resolver are fakes."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from findmejob.emailfinder import (EmailFinder, EmailHunt, FinderInput, doh_mx_resolver,
                                   duckduckgo_searcher, extract_emails)
from findmejob.models import JobPosting
from findmejob.pipeline import enrich_from_listing
from findmejob.salary import extract_salary_text
from findmejob.tracker import Tracker
from findmejob.verification import CompanyVerification

DOMAIN = "northwind-trading.test"


def site(pages):
    """Fake fetcher: dict of url -> html. Unknown URLs raise like a 404."""
    def fetch(url):
        if url in pages:
            return pages[url]
        raise OSError("404")
    return fetch


def mx_live(*domains):
    return lambda d: d in domains


def no_results(query):
    return []


class TestExtractEmails(unittest.TestCase):
    def test_reads_mailto_plain_and_bracketed_forms(self):
        text = ('<a href="mailto:hr@northwind-trading.test?subject=CV">HR</a> '
                'or careers [at] northwind-trading [dot] test, jobs@northwind-trading.test.')
        self.assertEqual(extract_emails(text), [
            "hr@northwind-trading.test", "careers@northwind-trading.test", "jobs@northwind-trading.test"])

    def test_rejects_noise(self):
        text = "logo@2x.png noreply@northwind-trading.test user@example.com a1b2c3d4e5f6a7b8c9@x.test"
        self.assertEqual(extract_emails(text), [])

    def test_does_not_invent_from_prose(self):
        # "apply at northwind-trading.test" must not become an address
        self.assertEqual(extract_emails("Apply at northwind-trading.test dot com today"), [])


class TestEmailFinder(unittest.TestCase):
    def test_contact_page_address_is_verified(self):
        pages = {
            f"https://{DOMAIN}/": '<a href="/about/contact-team">Contact</a>',
            f"https://{DOMAIN}/about/contact-team": "Write to careers@northwind-trading.test",
        }
        finder = EmailFinder(fetcher=site(pages), searcher=no_results, mx_resolver=mx_live(DOMAIN))
        hunt = finder.run(FinderInput(company="Northwind Trading", official_domain=DOMAIN,
                                      domain_confirmed=True))
        self.assertEqual(hunt.status, "found")
        best = hunt.best()
        self.assertEqual(best.address, "careers@northwind-trading.test")
        self.assertEqual(best.source_url, f"https://{DOMAIN}/about/contact-team")
        self.assertTrue(best.verified)
        self.assertEqual(best.role, "careers")

    def test_prefers_hiring_inbox_over_general(self):
        pages = {f"https://{DOMAIN}/contact": "info@northwind-trading.test | hr@northwind-trading.test"}
        finder = EmailFinder(fetcher=site(pages), searcher=no_results, mx_resolver=mx_live(DOMAIN))
        hunt = finder.run(FinderInput(company="Northwind Trading", official_domain=DOMAIN,
                                      domain_confirmed=True))
        self.assertEqual(hunt.best().address, "hr@northwind-trading.test")

    def test_never_guesses_when_nothing_is_published(self):
        finder = EmailFinder(fetcher=site({f"https://{DOMAIN}/": "no contact details"}),
                             searcher=no_results, mx_resolver=mx_live(DOMAIN))
        hunt = finder.run(FinderInput(company="Northwind Trading", official_domain=DOMAIN,
                                      domain_confirmed=True))
        self.assertEqual(hunt.emails, [])   # no careers@/hr@ fabricated
        self.assertEqual(hunt.status, "no_verified_address")
        self.assertEqual(hunt.missing_methods(), [])
        self.assertEqual([m.name for m in hunt.methods],
                         ["listing", "official_site", "web_search", "linkedin", "registry", "mx", "pattern"])

    def test_skipped_methods_mean_incomplete_not_none(self):
        finder = EmailFinder(fetcher=site({f"https://{DOMAIN}/": "nothing"}), searcher=None,
                             mx_resolver=mx_live(DOMAIN))
        hunt = finder.run(FinderInput(company="Northwind Trading", official_domain=DOMAIN,
                                      domain_confirmed=True))
        self.assertEqual(hunt.status, "incomplete")
        self.assertEqual(hunt.missing_methods(), ["web_search", "linkedin", "registry"])
        self.assertIn("still to run", hunt.summary())

    def test_unknown_domain_keeps_hunt_incomplete(self):
        finder = EmailFinder(fetcher=site({}), searcher=no_results, mx_resolver=mx_live())
        hunt = finder.run(FinderInput(company="Northwind Trading"))
        self.assertEqual(hunt.status, "incomplete")
        self.assertIn("official_site", hunt.missing_methods())

    def test_unconfirmed_domain_is_not_verified(self):
        pages = {f"https://{DOMAIN}/contact": "careers@northwind-trading.test"}
        finder = EmailFinder(fetcher=site(pages), searcher=no_results, mx_resolver=mx_live(DOMAIN))
        hunt = finder.run(FinderInput(company="Northwind Trading", official_domain=DOMAIN))
        self.assertEqual(len(hunt.emails), 1)
        self.assertFalse(hunt.emails[0].verified)
        self.assertNotEqual(hunt.status, "found")

    def test_search_result_on_other_site_is_not_verified(self):
        def search(q):
            return [{"url": "https://jobs-directory.test/northwind",
                     "title": "Northwind", "snippet": "careers@northwind-trading.test"}]
        finder = EmailFinder(fetcher=site({}), searcher=search, mx_resolver=mx_live(DOMAIN))
        hunt = finder.run(FinderInput(company="Northwind Trading", official_domain=DOMAIN,
                                      domain_confirmed=True))
        found = [e for e in hunt.emails if e.address == "careers@northwind-trading.test"]
        self.assertTrue(found)
        self.assertFalse(found[0].verified)
        self.assertIn("not published on the listing or the official site", found[0].notes)

    def test_lookalike_and_free_mail_need_review(self):
        pages = {f"https://{DOMAIN}/contact":
                 "hr@northwind-trading-careers.test or northwind.hiring@gmail.com"}
        finder = EmailFinder(fetcher=site(pages), searcher=no_results,
                             mx_resolver=mx_live("northwind-trading-careers.test", "gmail.com"))
        hunt = finder.run(FinderInput(company="Northwind Trading", official_domain=DOMAIN,
                                      domain_confirmed=True))
        self.assertEqual(hunt.verified(), [])
        notes = " ".join(n for e in hunt.emails for n in e.notes)
        self.assertIn("lookalike", notes)
        self.assertIn("free-mail", notes)

    def test_dead_mx_blocks_verification(self):
        pages = {f"https://{DOMAIN}/contact": "careers@northwind-trading.test"}
        finder = EmailFinder(fetcher=site(pages), searcher=no_results, mx_resolver=lambda d: False)
        hunt = finder.run(FinderInput(company="Northwind Trading", official_domain=DOMAIN,
                                      domain_confirmed=True))
        self.assertEqual(hunt.verified(), [])
        self.assertIn("no MX record", hunt.emails[0].notes[0])

    def test_failed_mx_lookup_is_unknown_not_negative(self):
        pages = {f"https://{DOMAIN}/contact": "careers@northwind-trading.test"}
        finder = EmailFinder(fetcher=site(pages), searcher=no_results, mx_resolver=lambda d: None)
        hunt = finder.run(FinderInput(company="Northwind Trading", official_domain=DOMAIN,
                                      domain_confirmed=True))
        self.assertEqual(hunt.status, "incomplete")
        self.assertIn("mx", hunt.missing_methods())

    def test_listing_address_is_verified_without_domain(self):
        finder = EmailFinder(fetcher=site({}), searcher=no_results,
                             mx_resolver=mx_live("fabrikam-talent.test"))
        hunt = finder.run(FinderInput(company="Confidential client",
                                      listing_text="Send your CV to cv@fabrikam-talent.test",
                                      listing_url="https://board.test/job/1"))
        self.assertEqual(hunt.status, "found")
        self.assertEqual(hunt.best().source_url, "https://board.test/job/1")

    def test_supplied_linkedin_and_registry_pages_count(self):
        pages = [{"method": "linkedin", "url": "https://www.linkedin.com/company/northwind-test",
                  "text": "Recruiting: talent@northwind-trading.test"},
                 {"method": "registry", "url": "https://registry.test/northwind", "text": "no email"}]
        finder = EmailFinder(fetcher=site({}), searcher=None, mx_resolver=mx_live(DOMAIN))
        hunt = finder.run(FinderInput(company="Northwind Trading", official_domain=DOMAIN,
                                      domain_confirmed=True, supplied_pages=pages))
        by_name = {m.name: m for m in hunt.methods}
        self.assertEqual(by_name["linkedin"].status, "found")
        self.assertEqual(by_name["registry"].status, "empty")
        # found on LinkedIn, not the official site: kept as a lead, not verified
        self.assertFalse(hunt.emails[0].verified)

    def test_routes_feed_company_verification(self):
        pages = {f"https://{DOMAIN}/careers": "careers@northwind-trading.test"}
        finder = EmailFinder(fetcher=site(pages), searcher=no_results, mx_resolver=mx_live(DOMAIN))
        hunt = finder.run(FinderInput(company="Northwind Trading", official_domain=DOMAIN,
                                      domain_confirmed=True))
        cv = CompanyVerification.from_dict({"company": "Northwind Trading",
                                            "official_domain": DOMAIN, "routes": hunt.to_routes()})
        self.assertEqual(cv.validate(), [])
        self.assertEqual(cv.best_route().value, "careers@northwind-trading.test")

    def test_round_trip(self):
        hunt = EmailFinder(fetcher=site({}), searcher=no_results, mx_resolver=mx_live()).run(
            FinderInput(company="X", listing_text="a@b-co.test"))
        again = EmailHunt.from_dict(json.loads(json.dumps(hunt.to_dict())))
        self.assertEqual(again.to_dict(), hunt.to_dict())


class TestAdapters(unittest.TestCase):
    def test_doh_resolver(self):
        ok = json.dumps({"Status": 0, "Answer": [{"type": 15, "data": "10 mx.northwind-trading.test."}]})
        self.assertTrue(doh_mx_resolver(DOMAIN, fetch=lambda u: ok))
        self.assertFalse(doh_mx_resolver(DOMAIN, fetch=lambda u: json.dumps({"Status": 3})))
        self.assertFalse(doh_mx_resolver(DOMAIN, fetch=lambda u: json.dumps({"Status": 0})))
        self.assertIsNone(doh_mx_resolver(DOMAIN, fetch=lambda u: (_ for _ in ()).throw(OSError())))

    def test_duckduckgo_parser(self):
        page = ('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fnorthwind-trading.test%2Fcontact">'
                'Contact</a><a class="result__snippet">email careers@northwind-trading.test</a>')
        hits = duckduckgo_searcher(fetch=lambda u: page)("northwind")
        self.assertEqual(hits[0]["url"], "https://northwind-trading.test/contact")
        self.assertIn("careers@northwind-trading.test", hits[0]["snippet"])


class TestSearchFailures(unittest.TestCase):
    def test_blocked_search_is_error_not_empty(self):
        blocked = duckduckgo_searcher(fetch=lambda u: "<html>please verify you are human</html>")
        finder = EmailFinder(fetcher=site({f"https://{DOMAIN}/": "nothing"}), searcher=blocked,
                             mx_resolver=mx_live(DOMAIN))
        hunt = finder.run(FinderInput(company="Northwind Trading", official_domain=DOMAIN,
                                      domain_confirmed=True))
        self.assertEqual(hunt.status, "incomplete")   # never "no_verified_address"
        self.assertEqual(hunt.missing_methods(), ["web_search", "linkedin", "registry"])

    def test_genuine_no_results(self):
        self.assertEqual(duckduckgo_searcher(fetch=lambda u: '<div class="no-results">No results.</div>')("x"), [])

    def test_searxng(self):
        from findmejob.emailfinder import searxng_searcher
        body = json.dumps({"results": [{"url": "https://northwind-trading.test/c", "title": "C",
                                        "content": "hr@northwind-trading.test"}]})
        hits = searxng_searcher("https://search.test", fetch=lambda u: body)("x")
        self.assertEqual(hits[0]["snippet"], "hr@northwind-trading.test")


class TestListingEnrichment(unittest.TestCase):
    def test_salary_sentence_is_extracted_verbatim(self):
        text = ("We post revenue of AED 5 billion. Requirements: 5+ years experience. "
                "Salary: AED 18,000 - 20,000 per month + visa.")
        self.assertEqual(extract_salary_text(text), "Salary: AED 18,000 - 20,000 per month + visa.")
        self.assertEqual(extract_salary_text("Compensation: 120k-140k USD base.\nApply now."),
                         "Compensation: 120k-140k USD base.")
        self.assertEqual(extract_salary_text("Pay: $40 - $55 per hour"), "Pay: $40 - $55 per hour")

    def test_no_salary_means_empty(self):
        self.assertEqual(extract_salary_text("Minimum 7 years in marketing. Team of 12."), "")
        self.assertEqual(extract_salary_text("We raised USD 20 million last year."), "")

    def test_enrich_populates_salary_and_emails(self):
        jobs = [JobPosting(title="Marketing Lead", company="Northwind Trading", url="https://board.test/1",
                           description="Package: QAR 15,000 monthly. Email hr@northwind-trading.test"),
                JobPosting(title="Analyst", company="Y", salary_text="from source", description="Salary AED 9,000 per month")]
        res = enrich_from_listing(jobs)
        self.assertEqual(res, {"salary": 1, "emails": 1})
        self.assertEqual(jobs[0].salary_text, "Package: QAR 15,000 monthly.")
        self.assertEqual(jobs[0].contact_emails, ["hr@northwind-trading.test"])
        self.assertEqual(jobs[1].salary_text, "from source")   # source value is never overwritten


class TestTrackerEmailRoute(unittest.TestCase):
    def setUp(self):
        self.tracker = Tracker(Path(tempfile.mkdtemp()) / "t.db")
        self.job = JobPosting(title="Marketing Lead", company="Northwind Trading", url="https://board.test/1")
        self.tracker.upsert_job(self.job)
        self.tracker.set_status(self.job.id, "applied")

    def _hunt(self, published=True):
        pages = {f"https://{DOMAIN}/contact": "careers@northwind-trading.test" if published else "none"}
        return EmailFinder(fetcher=site(pages), searcher=no_results, mx_resolver=mx_live(DOMAIN)).run(
            FinderInput(company="Northwind Trading", official_domain=DOMAIN, domain_confirmed=True))

    def test_stage_counts_and_retry_queue(self):
        self.assertEqual(self.tracker.email_stage_counts()["applied_hunt_incomplete"], 1)
        self.assertEqual(self.tracker.jobs_needing_email_hunt(), [self.job.id])
        self.tracker.set_email_hunt(self.job.id, self._hunt())
        self.assertEqual(self.tracker.email_stage_counts()["applied_email_pending"], 1)
        self.assertEqual(self.tracker.jobs_needing_email_hunt(), [])
        self.tracker.set_email_outcome(self.job.id, "failed", "bounced")
        self.assertEqual(self.tracker.jobs_needing_email_hunt(), [self.job.id])  # failed -> fresh hunt
        self.tracker.set_email_hunt(self.job.id, self._hunt())
        self.assertEqual(self.tracker.email_summary(self.job.id)["outcome"], "pending")
        self.tracker.set_email_outcome(self.job.id, "sent", "msg-123")
        self.tracker.set_email_hunt(self.job.id, self._hunt())            # re-run keeps 'sent'
        self.assertEqual(self.tracker.email_stage_counts()["applied_email_sent"], 1)
        row = self.tracker.list_jobs()[0]
        self.assertEqual(row["email"]["address"], "careers@northwind-trading.test")

    def test_sent_needs_proof_and_verified_address(self):
        self.tracker.set_email_hunt(self.job.id, self._hunt(published=False))
        with self.assertRaises(ValueError):
            self.tracker.set_email_outcome(self.job.id, "sent", "msg-1")
        self.tracker.set_email_hunt(self.job.id, self._hunt())
        with self.assertRaises(ValueError):
            self.tracker.set_email_outcome(self.job.id, "sent", "")
        self.assertEqual(self.tracker.email_stage_counts()["applied_email_pending"], 1)

    def test_no_verified_address_after_full_hunt(self):
        self.tracker.set_email_hunt(self.job.id, self._hunt(published=False))
        self.assertEqual(self.tracker.email_stage_counts()["applied_no_verified_address"], 1)


class TestEmailsCommand(unittest.TestCase):
    def test_cli_runs_hunt_and_records_outcome(self):
        from findmejob import cli
        from findmejob.config import scaffold
        root = Path(tempfile.mkdtemp())
        scaffold(root)
        from findmejob.config import load_config
        tracker = Tracker(load_config(root).db_path)
        job = JobPosting(title="Marketing Lead", company="Northwind Trading", url="https://board.test/1")
        tracker.upsert_job(job)
        tracker.set_status(job.id, "applied")
        pages = {f"https://{DOMAIN}/contact": "careers@northwind-trading.test"}
        fake = EmailFinder(fetcher=site(pages), searcher=no_results, mx_resolver=mx_live(DOMAIN))
        with mock.patch("findmejob.emailfinder.finder_from_config", return_value=fake):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli.main(["--dir", str(root), "emails", "--job", job.id,
                               "--domain", DOMAIN, "--confirmed"])
        self.assertEqual(rc, 0)
        self.assertIn("VERIFIED", out.getvalue())
        self.assertIn("careers@northwind-trading.test", out.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--dir", str(root), "emails", "--job", job.id,
                                       "--outcome", "sent", "--proof", "msg-1"]), 0)
        self.assertEqual(Tracker(load_config(root).db_path).email_summary(job.id)["outcome"], "sent")


if __name__ == "__main__":
    unittest.main()
