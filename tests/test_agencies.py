"""Recruitment-agency discovery, validation and tracking.

Every agency, domain, address and place here is fictional (.test TLD,
made-up country "Testland"). No network access: fetcher, searcher, poster,
MX resolver and country resolver are fakes."""
import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

from findmejob.agencies import (Agency, AgencyDiscovery, AgencyRules, AgencyValidator,
                                DiscoveryRequest, build_from_config, decide_status, merge_agencies,
                                name_tokens, nominatim_country_code)
from findmejob.emailfinder import EmailFinder, SearchUnavailable
from findmejob.models import JobPosting
from findmejob.tracker import Tracker

REQ = dict(country="Testland", country_code="TL")
OVERPASS = "https://overpass.test/api/interpreter"


def site(pages, prefixes=None):
    """Fake fetcher: exact url -> text, or url prefix -> text. Else 'unreachable'."""
    prefixes = prefixes or {}

    def fetch(url):
        if url in pages:
            return pages[url]
        for pre, body in prefixes.items():
            if url.startswith(pre):
                return body
        raise OSError("unreachable")
    return fetch


def searcher(results_by_word):
    """Fake search: returns the hits of the first key contained in the query."""
    def search(query):
        for word, hits in results_by_word.items():
            if word in query:
                return hits
        return []
    return search


def blocked(query):
    raise SearchUnavailable("bot check")


def no_results(query):
    return []


def discovery(**kw):
    kw.setdefault("fetcher", site({}))
    kw.setdefault("country_resolver", lambda c: "")
    kw.setdefault("overpass_url", OVERPASS)
    return AgencyDiscovery(**kw)


def validator(pages, mx=("brightpath-talent.test",), search=None, prefixes=None):
    fetch = site(pages, prefixes)
    mx_fn = (lambda d: d in mx) if not callable(mx) else mx
    finder = EmailFinder(fetcher=fetch, searcher=search, mx_resolver=mx_fn)
    return AgencyValidator(fetcher=fetch, searcher=search, mx_resolver=mx_fn, email_finder=finder,
                           clock=lambda: 1000.0)


def methods(run):
    return {m.name: m for m in run.methods}


class TestHelpers(unittest.TestCase):
    def test_name_tokens_drop_legal_and_generic_words(self):
        self.assertEqual(name_tokens("BrightPath Talent Recruitment LLC"), ["brightpath", "talent"])

    def test_title_name_picks_agency_segment(self):
        rules = AgencyRules()
        self.assertEqual(rules.name_from_title("Home | Orbit Staffing Partners - Testland"),
                         "Orbit Staffing Partners")

    def test_aggregator_hosts_are_not_websites(self):
        rules = AgencyRules(aggregator_hosts=["listings.test"])
        self.assertTrue(rules.is_aggregator("www.linkedin.com"))
        self.assertTrue(rules.is_aggregator("city.listings.test"))
        self.assertFalse(rules.is_aggregator("brightpath-talent.test"))

    def test_country_code_passthrough_and_lookup(self):
        self.assertEqual(nominatim_country_code("tl"), "TL")
        fetch = site({}, {"https://nominatim.openstreetmap.org/search?":
                          json.dumps([{"address": {"country_code": "tl"}}])})
        self.assertEqual(nominatim_country_code("Testland", fetch), "TL")
        self.assertEqual(nominatim_country_code("Nowhere", site({})), "")


class TestDiscoveryHonesty(unittest.TestCase):
    def test_unconfigured_methods_are_not_run_with_reasons(self):
        run = discovery().run(DiscoveryRequest(country="Testland"))
        m = methods(run)
        self.assertEqual(m["web_search"].status, "not_run")
        self.assertIn("no search provider", m["web_search"].detail)
        self.assertEqual(m["maps"].status, "not_run")
        self.assertIn("API key", m["maps"].detail)
        self.assertEqual(m["job_boards"].status, "not_run")
        self.assertEqual(m["openstreetmap"].status, "not_run")
        self.assertIn("ISO country code", m["openstreetmap"].detail)
        self.assertEqual(m["tracker"].status, "not_run")
        self.assertEqual(m["supplied"].status, "not_run")
        self.assertEqual(run.agencies, [])
        self.assertIn("not run:", run.summary())
        # nothing that did not run may look like "no agencies"
        self.assertFalse(any(x.status == "empty" for x in run.methods))

    def test_blocked_search_is_an_error_not_empty(self):
        run = discovery(searcher=blocked).run(DiscoveryRequest(**REQ), methods=["web_search", "directories"])
        m = methods(run)
        self.assertEqual(m["web_search"].status, "error")
        self.assertIn("blocked", m["web_search"].detail)
        self.assertEqual(m["directories"].status, "error")

    def test_overpass_outage_is_an_error(self):
        run = discovery().run(DiscoveryRequest(**REQ), methods=["openstreetmap"])
        self.assertEqual(methods(run)["openstreetmap"].status, "error")

    def test_skip_and_select(self):
        run = discovery(searcher=no_results).run(DiscoveryRequest(**REQ), methods=["web_search", "maps"],
                                                 skip=["maps"])
        m = methods(run)
        self.assertEqual(m["web_search"].status, "empty")
        self.assertEqual((m["maps"].status, m["maps"].detail), ("not_run", "skipped by --skip"))
        self.assertEqual(m["directories"].detail, "not selected (--methods)")
        with self.assertRaises(ValueError):
            discovery().run(DiscoveryRequest(**REQ), methods=["carrier_pigeon"])


class TestDiscoveryMethods(unittest.TestCase):
    def test_web_search_keeps_source_and_skips_noise(self):
        hits = [
            {"url": "https://brightpath-talent.test/about", "title": "BrightPath Talent | Recruitment agency in Testland",
             "snippet": "Recruitment for marketing and sales roles."},
            {"url": "https://www.linkedin.com/company/brightpath", "title": "BrightPath Talent | LinkedIn",
             "snippet": "recruitment"},
            {"url": "https://bakery.test/", "title": "Fresh Bread Testland", "snippet": "Bakery"},
        ]
        run = discovery(searcher=searcher({"recruitment agency": hits})).run(
            DiscoveryRequest(industry="marketing", **REQ), methods=["web_search"])
        self.assertEqual(len(run.agencies), 1)
        a = run.agencies[0]
        self.assertEqual((a.name, a.domain), ("BrightPath Talent", "brightpath-talent.test"))
        self.assertEqual(a.facts_for("website")[0].source_url, "https://brightpath-talent.test/about")
        self.assertTrue(any("marketing" in q for q in methods(run)["web_search"].checked))

    def test_maps_uses_places_and_records_reviews(self):
        calls = []

        def poster(url, headers, body):
            calls.append((url, headers, body))
            return json.dumps({"places": [{
                "id": "p1", "displayName": {"text": "Orbit Staffing Partners"},
                "formattedAddress": "1 Harbour Road, Port Test", "websiteUri": "https://www.orbit-staffing.test/",
                "rating": 4.6, "userRatingCount": 120, "googleMapsUri": "https://maps.test/place/p1",
                "businessStatus": "OPERATIONAL"}]})
        d = discovery(poster=poster, maps_api_key="test-key", rules=AgencyRules(search_terms=["staffing agency"]))
        run = d.run(DiscoveryRequest(city="Port Test", **REQ), methods=["maps"])
        self.assertEqual(calls[0][1]["X-Goog-Api-Key"], "test-key")
        self.assertIn("places.websiteUri", calls[0][1]["X-Goog-FieldMask"])
        self.assertEqual(calls[0][2]["textQuery"], "staffing agency in Port Test, Testland")
        a = run.agencies[0]
        self.assertEqual(a.domain, "orbit-staffing.test")
        self.assertEqual(a.values("rating"), ["4.6"])
        self.assertEqual(a.facts_for("review_count")[0].source_url, "https://maps.test/place/p1")

    def test_maps_api_error_is_reported(self):
        d = discovery(poster=lambda u, h, b: json.dumps({"error": {"status": "PERMISSION_DENIED"}}),
                      maps_api_key="bad", rules=AgencyRules(search_terms=["staffing agency"]))
        m = methods(d.run(DiscoveryRequest(**REQ), methods=["maps"]))["maps"]
        self.assertEqual(m.status, "error")
        self.assertIn("PERMISSION_DENIED", m.detail)

    def test_openstreetmap_tagged_offices_with_city_filter(self):
        body = json.dumps({"elements": [
            {"type": "node", "id": 11, "tags": {"office": "employment_agency", "name": "Harbour Jobs Centre",
                                                "addr:city": "Port Test", "website": "https://harbour-jobs.test",
                                                "email": "hello@harbour-jobs.test"}},
            {"type": "way", "id": 12, "tags": {"office": "employment_agency", "name": "Inland Placement",
                                               "addr:city": "Hilltown"}},
        ]})
        seen = []

        def fetch(url):
            seen.append(url)
            if url.startswith(OVERPASS):
                return body
            raise OSError("unreachable")
        run = discovery(fetcher=fetch).run(DiscoveryRequest(city="Port Test", **REQ), methods=["openstreetmap"])
        self.assertIn("ISO3166-1%22%3D%22TL", seen[0])
        self.assertEqual([a.name for a in run.agencies], ["Harbour Jobs Centre"])
        a = run.agencies[0]
        self.assertEqual(a.facts_for("maps_listing")[0].source_url, "https://www.openstreetmap.org/node/11")
        lead = a.facts_for("listed_email")[0]
        self.assertIn("lead", lead.note)

    def test_openstreetmap_resolves_country_names(self):
        fetch = site({}, {OVERPASS: json.dumps({"elements": []})})
        d = discovery(fetcher=fetch, country_resolver=lambda c: "TL" if c == "Testland" else "")
        m = methods(d.run(DiscoveryRequest(country="Testland"), methods=["openstreetmap"]))["openstreetmap"]
        self.assertEqual(m.status, "empty")

    def test_directories_read_agency_links(self):
        page = ('<h1>Top recruiters</h1>'
                '<a href="https://www.cedar-search.test/">Cedar Executive Search</a>'
                '<a href="/profile/lumen">Lumen Recruitment Group</a>'
                '<a href="https://shop.test/">Buy shoes</a>'
                '<a href="https://www.facebook.com/x">Pine Staffing on Facebook</a>')
        hits = [{"url": "https://guide.test/best-recruiters", "title": "List of recruitment agencies", "snippet": ""}]
        d = discovery(searcher=searcher({"list of recruitment agencies": hits}),
                      fetcher=site({"https://guide.test/best-recruiters": page}))
        run = d.run(DiscoveryRequest(**REQ), methods=["directories"])
        names = {a.name: a for a in run.agencies}
        self.assertEqual(set(names), {"Cedar Executive Search", "Lumen Recruitment Group", "Pine Staffing on Facebook"})
        self.assertEqual(names["Cedar Executive Search"].domain, "cedar-search.test")
        self.assertEqual(names["Lumen Recruitment Group"].domain, "")
        self.assertEqual(names["Lumen Recruitment Group"].values("profile_page"), ["https://guide.test/profile/lumen"])
        self.assertEqual(names["Pine Staffing on Facebook"].domain, "")
        self.assertEqual(names["Cedar Executive Search"].facts_for("name")[0].source_url,
                         "https://guide.test/best-recruiters")

    def test_job_boards_need_configured_sites(self):
        hits = [{"url": "https://board.test/company/quill", "title": "Quill Recruitment - jobs | Board", "snippet": ""}]
        d = discovery(searcher=searcher({"site:board.test": hits}), job_board_sites=["board.test"])
        run = d.run(DiscoveryRequest(**REQ), methods=["job_boards"])
        self.assertEqual(run.agencies[0].name, "Quill Recruitment")
        self.assertEqual(run.agencies[0].values("job_board_listing"), ["https://board.test/company/quill"])

    def test_tracker_mines_agency_employers_in_the_area(self):
        jobs = [
            JobPosting(title="Marketing Lead", company="Summit Manpower Services", location="Port Test, Testland",
                       url="https://jobs.test/1", source="rss", contact_emails=["cv@summit-manpower.test"]),
            JobPosting(title="Analyst", company="Acorn Holdings", location="Testland", url="https://jobs.test/2",
                       source="rss", description="We are recruiting on behalf of our client, a retailer."),
            JobPosting(title="Chef", company="Other Staffing", location="Elsewhere", url="https://jobs.test/3"),
            JobPosting(title="Clerk", company="Plain Traders", location="Testland", url="https://jobs.test/4"),
        ]
        run = discovery().run(DiscoveryRequest(**REQ), methods=["tracker"], jobs=jobs)
        names = sorted(a.name for a in run.agencies)
        self.assertEqual(names, ["Acorn Holdings", "Summit Manpower Services"])
        summit = [a for a in run.agencies if a.name.startswith("Summit")][0]
        self.assertEqual(summit.facts_for("listed_email")[0].source_url, "https://jobs.test/1")

    def test_supplied_candidates_and_pages(self):
        supplied = [{"name": "Delta Talent Solutions", "website": "delta-talent.test",
                     "source_url": "https://registry.test/delta"},
                    {"url": "https://chamber.test/members", "text": '<a href="https://echo-hr.test">Echo HR Consultants</a>'}]
        run = discovery().run(DiscoveryRequest(**REQ), methods=["supplied"], supplied=supplied)
        self.assertEqual(sorted(a.domain for a in run.agencies), ["delta-talent.test", "echo-hr.test"])


class TestMerge(unittest.TestCase):
    def test_same_agency_from_several_methods_is_one_record(self):
        a = Agency("BrightPath Talent", country="Testland", domain="brightpath-talent.test")
        a.add_fact("name", "BrightPath Talent", "https://s.test/1", "web_search")
        b = Agency("BrightPath Talent LLC", country="Testland", domain="https://www.brightpath-talent.test/")
        b.add_fact("rating", "4.2", "https://maps.test/b", "maps")
        c = Agency("Brightpath Talent Recruitment", country="Testland")
        c.add_fact("job_listing", "Analyst", "https://jobs.test/9", "tracker")
        d = Agency("Lumen Recruitment Group", country="Testland")
        e = Agency("Lumen Recruitment", country="Testland")
        merged = merge_agencies([a, b, c, d, e])
        self.assertEqual(len(merged), 2)
        bp = merged[0]
        self.assertEqual(set(bp.found_by), {"web_search", "maps", "tracker"})
        self.assertEqual(bp.values("rating"), ["4.2"])
        self.assertEqual(bp.id, Agency("x", domain="brightpath-talent.test").id)


def _brightpath(**kw):
    a = Agency("BrightPath Talent", country="Testland", domain="brightpath-talent.test", **kw)
    a.add_fact("name", "BrightPath Talent", "https://s.test/1", "web_search")
    return a


HOME = ('<title>BrightPath Talent - Recruitment</title><a href="/contact">Contact</a>'
        '<a href="https://www.linkedin.com/company/brightpath-talent-test">LinkedIn</a>')
CONTACT = '<p>Send your CV to <a href="mailto:careers@brightpath-talent.test">careers</a></p>'


class TestValidation(unittest.TestCase):
    def test_fully_validated_agency_keeps_evidence(self):
        pages = {"https://brightpath-talent.test/": HOME, "https://brightpath-talent.test/contact": CONTACT}
        a = validator(pages, search=no_results).validate(_brightpath(), maps_ran=False)
        self.assertEqual(a.status, "validated")
        self.assertEqual(a.contact_email, "careers@brightpath-talent.test")
        self.assertEqual(a.contact_source, "https://brightpath-talent.test/contact")
        self.assertEqual(a.check("linkedin").status, "pass")
        self.assertEqual(a.values("linkedin"), ["https://www.linkedin.com/company/brightpath-talent-test"])
        self.assertEqual(a.check("maps_presence").status, "not_run")
        self.assertEqual(a.check("reviews").status, "not_run")
        self.assertEqual(a.checked_at, 1000.0)
        for f in a.facts:
            self.assertTrue(f.source_url, f)
        self.assertEqual(a.email_hunt["status"], "found")

    def test_dead_website_is_no_verified_contact(self):
        a = validator({}, search=no_results).validate(_brightpath())
        self.assertEqual(a.check("website").status, "fail")
        self.assertEqual(a.check("contact_email").status, "not_run")
        self.assertEqual(a.status, "no_verified_contact")

    def test_bot_block_is_not_a_conclusion(self):
        def fetch(url):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        v = AgencyValidator(fetcher=fetch, searcher=None, mx_resolver=lambda d: True,
                            email_finder=EmailFinder(fetcher=fetch, searcher=None, mx_resolver=lambda d: True))
        a = v.validate(_brightpath())
        self.assertEqual(a.check("website").status, "error")
        self.assertEqual(a.status, "discovered")
        self.assertIn("website", a.missing_checks())

    def test_mx_lookup_failure_leaves_it_discovered(self):
        pages = {"https://brightpath-talent.test/": HOME, "https://brightpath-talent.test/contact": CONTACT}
        a = validator(pages, mx=lambda d: None, search=no_results).validate(_brightpath())
        self.assertEqual(a.check("contact_email").status, "error")
        self.assertEqual(a.check("mx").status, "error")
        self.assertEqual(a.status, "discovered")
        self.assertIn("mx", a.summary())

    def test_every_method_ran_and_nothing_verified(self):
        pages = {"https://brightpath-talent.test/": "<title>BrightPath Talent</title> no emails here"}
        a = validator(pages, search=no_results).validate(_brightpath())
        self.assertEqual(a.check("contact_email").status, "fail")
        self.assertEqual(a.status, "no_verified_contact")

    def test_missing_search_keeps_email_check_open(self):
        pages = {"https://brightpath-talent.test/": "<title>BrightPath Talent</title>"}
        a = validator(pages, search=None).validate(_brightpath())
        self.assertEqual(a.check("contact_email").status, "error")
        self.assertIn("still to run", a.check("contact_email").detail)
        self.assertEqual(a.check("linkedin").status, "not_run")
        self.assertEqual(a.status, "discovered")

    def test_unconfirmed_domain_never_concludes(self):
        # the site does not name the agency, so the domain is not confirmed
        pages = {"https://brightpath-talent.test/": "<title>Parked domain</title>",
                 "https://brightpath-talent.test/contact": CONTACT}
        a = validator(pages, search=no_results).validate(_brightpath())
        self.assertEqual(a.check("contact_email").status, "error")
        self.assertEqual(a.status, "discovered")
        self.assertEqual(a.contact_email, "")

    def test_third_party_listed_email_stays_a_lead(self):
        pages = {"https://brightpath-talent.test/": "<title>BrightPath Talent</title>"}
        a = _brightpath()
        a.add_fact("listed_email", "hello@brightpath-talent.test", "https://www.openstreetmap.org/node/1",
                   "openstreetmap")
        a = validator(pages, search=no_results).validate(a)
        self.assertNotEqual(a.status, "validated")
        leads = [e for e in a.email_hunt["emails"] if e["address"] == "hello@brightpath-talent.test"]
        self.assertTrue(leads and not leads[0]["verified"])

    def test_website_found_by_search_for_name_only_record(self):
        hits = [{"url": "https://www.facebook.com/lumen", "title": "Lumen Recruitment Group"},
                {"url": "https://lumen-recruitment.test/", "title": "Lumen Recruitment Group - Home"}]
        pages = {"https://lumen-recruitment.test/": "<title>Lumen Recruitment Group</title>"}
        a = Agency("Lumen Recruitment Group", country="Testland")
        old_id = a.id
        a = validator(pages, mx=("lumen-recruitment.test",),
                      search=searcher({'"Lumen Recruitment Group"': hits})).validate(a)
        self.assertEqual(a.domain, "lumen-recruitment.test")
        self.assertNotEqual(a.id, old_id)
        self.assertEqual(a.facts_for("website")[0].source_url, "https://lumen-recruitment.test/")

    def test_maps_listing_and_reviews_signals(self):
        pages = {"https://brightpath-talent.test/": HOME, "https://brightpath-talent.test/contact": CONTACT}
        a = _brightpath()
        a.add_fact("maps_listing", "https://maps.test/p", "https://maps.test/p", "maps")
        a.add_fact("rating", "4.6", "https://maps.test/p", "maps")
        a.add_fact("review_count", "120", "https://maps.test/p", "maps")
        a = validator(pages, search=no_results).validate(a, maps_ran=True, maps_key=True)
        self.assertEqual(a.check("maps_presence").status, "pass")
        self.assertEqual(a.check("reviews").detail, "rating 4.6 from 120 review(s)")
        self.assertEqual(sorted(a.signals()), ["linkedin", "maps_presence", "reviews"])

    def test_contacted_is_never_downgraded(self):
        a = _brightpath(status="contacted")
        self.assertEqual(validator({}).validate(a).status, "contacted")
        self.assertEqual(decide_status(a), "contacted")


class TestTracker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tracker = Tracker(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.tracker.close()
        self.tmp.cleanup()

    def _validated(self):
        pages = {"https://brightpath-talent.test/": HOME, "https://brightpath-talent.test/contact": CONTACT}
        return validator(pages, search=no_results).validate(_brightpath())

    def test_statuses_counts_and_contacted_rules(self):
        self.tracker.upsert_agency(Agency("Lumen Recruitment Group", country="Testland"))
        a = self._validated()
        self.tracker.upsert_agency(a)
        counts = self.tracker.agency_counts()
        self.assertEqual((counts["discovered"], counts["validated"]), (1, 1))
        lumen = self.tracker.resolve_agency_id("Lumen")
        with self.assertRaises(ValueError):
            self.tracker.set_agency_contacted(lumen, "msg-1")        # nothing verified
        with self.assertRaises(ValueError):
            self.tracker.set_agency_contacted(a.id, "  ")           # no proof
        self.tracker.set_agency_contacted(a.id, "sent-message-123")
        stored = self.tracker.get_agency(a.id)
        self.assertEqual((stored.status, stored.contact_proof), ("contacted", "sent-message-123"))
        # a later discovery pass adds facts but keeps the contacted status
        again = _brightpath()
        again.add_fact("rating", "4.0", "https://maps.test/b", "maps")
        self.tracker.upsert_agency(again)
        stored = self.tracker.get_agency(a.id)
        self.assertEqual(stored.status, "contacted")
        self.assertIn("4.0", stored.values("rating"))
        self.assertEqual([x.id for x in self.tracker.list_agencies("contacted", "testland")], [a.id])

    def test_new_domain_folds_name_only_row(self):
        a = Agency("Lumen Recruitment Group", country="Testland")
        a.add_fact("name", a.name, "https://guide.test/list", "directories")
        self.tracker.upsert_agency(a)
        old = a.id
        a.domain = "lumen-recruitment.test"
        a.id = Agency("x", domain=a.domain).id
        self.tracker.upsert_agency(a, previous_id=old)
        self.assertIsNone(self.tracker.get_agency(old))
        self.assertEqual(len(self.tracker.list_agencies()), 1)


class TestCli(unittest.TestCase):
    def test_discover_validate_list_and_contact(self):
        from findmejob.cli import main
        pages = {"https://brightpath-talent.test/": HOME, "https://brightpath-talent.test/contact": CONTACT}
        hits = [{"url": "https://brightpath-talent.test/", "title": "BrightPath Talent | Recruitment agency",
                 "snippet": ""}]
        search = searcher({"recruitment agency": hits})
        fetch = site(pages)

        def fake_build(raw, no_search=False, env=None, fetcher=None):
            d = discovery(searcher=search, fetcher=fetch)
            v = validator(pages, search=no_results)
            return d, v
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                main(["--dir", tmp, "init"])
            out = io.StringIO()
            with mock.patch("findmejob.agencies.build_from_config", fake_build), redirect_stdout(out):
                code = main(["--dir", tmp, "agencies", "--country", "Testland", "--country-code", "TL",
                             "--methods", "web_search,maps"])
            text = out.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("maps           not_run", text)
            self.assertIn("validated - contact careers@brightpath-talent.test", text)
            out = io.StringIO()
            with redirect_stdout(out):
                main(["--dir", tmp, "agencies", "--list", "--evidence"])
            self.assertIn("fact contact_email: careers@brightpath-talent.test <- https://brightpath-talent.test/contact",
                          out.getvalue())
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                self.assertEqual(main(["--dir", tmp, "agencies", "--agency", "BrightPath", "--outcome", "contacted"]), 1)
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["--dir", tmp, "agencies", "--agency", "BrightPath", "--outcome", "contacted",
                                       "--proof", "sent-message-1"]), 0)
                main(["--dir", tmp, "status"])
            self.assertIn("recruitment agencies: contacted 1", out.getvalue())

    def test_build_from_config_respects_key_and_no_search(self):
        raw = {"agency_finder": {"job_board_sites": ["board.test"], "maps_api_key_env": "FMJ_TEST_KEY"}}
        d, v = build_from_config(raw, no_search=True, env={"FMJ_TEST_KEY": "k"})
        self.assertIsNone(d.search)
        self.assertEqual(d.maps_api_key, "k")
        self.assertEqual(d.job_board_sites, ["board.test"])
        d, _ = build_from_config({}, no_search=True, env={})
        self.assertEqual(d.maps_api_key, "")


if __name__ == "__main__":
    unittest.main()
