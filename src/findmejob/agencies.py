"""Recruitment-agency discovery and validation, for any country and industry.

Agencies are a second road to a hiring manager: they place candidates with
employers who never post publicly. This module finds agencies with generic,
reusable methods, checks each one is a real business that can receive an
application, and keeps evidence for every fact.

Nothing here is tied to a country, an industry, or a list of known agencies.
Country, city, industry, search terms, directory sites and job boards are all
inputs or configuration.

Honesty contract (the same one the email finder follows):

- Every discovery method reports one of ``found``, ``empty``, ``not_run`` or
  ``error``. A method that could not run (no search provider, no API key,
  provider blocked the query, skipped by the user) is ``not_run`` or
  ``error`` with the reason. It is never reported as "no agencies".
- Every fact on an agency (name, website, address, rating, listed email...)
  keeps the URL or record it was read from and the method that read it.
- An agency is ``validated`` only when its website resolves, its domain has a
  live MX record, and the email finder produced a verified contact address.
  ``no_verified_contact`` is a conclusion: it is set only when the checks
  that decide it actually ran. Anything else stays ``discovered`` and lists
  the checks still missing.
- Nothing is guessed: no invented domains, no pattern-generated addresses.

Discovery methods (any can be skipped or plugged in):

  web_search     search-provider results for agency terms + industry + place
  maps           Google Places Text Search (needs an API key you supply)
  openstreetmap  OpenStreetMap objects tagged office=employment_agency
  directories    directory / "list of agencies" pages found by search or
                 configured directory sites; agency links are read off them
  job_boards     employer listings on configured job-board sites (via search)
  tracker        employers in roles you already track that are agencies
  supplied       pages or candidates you or your agent opened (--pages)

Validation checks per agency:

  website        official site resolves and names the agency
  mx             the domain has a live MX record
  contact_email  the email finder (emailfinder.py) finds a verified address
  linkedin       LinkedIn company presence (site link or search result)
  maps_presence  listed on Google Maps or OpenStreetMap
  reviews        public rating and review count, where accessible

Everything network-facing (fetcher, searcher, poster, MX resolver, email
finder) is injectable, so tests never touch the network.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable, Optional

from .emailfinder import (USER_AGENT, EmailFinder, Fetcher, FinderInput, MXResolver, Searcher,
                          SearchUnavailable, default_fetcher, doh_mx_resolver, duckduckgo_searcher,
                          host_of, same_domain, searxng_searcher)

DISCOVERY_METHODS = ["web_search", "maps", "openstreetmap", "directories", "job_boards",
                     "tracker", "supplied"]
VALIDATION_CHECKS = ["website", "mx", "contact_email", "linkedin", "maps_presence", "reviews"]
SIGNAL_CHECKS = ["linkedin", "maps_presence", "reviews"]
STATUSES = ["discovered", "validated", "contacted", "no_verified_contact"]

# Words that mark a business as a recruitment agency. Extend per language in
# config (agency_finder.agency_keywords).
DEFAULT_AGENCY_KEYWORDS = [
    "recruit", "staffing", "manpower", "employment agency", "employment services",
    "headhunt", "executive search", "placement", "talent acquisition", "talent solutions",
    "hr consult", "hr solutions", "human resource", "workforce solutions",
]
DEFAULT_SEARCH_TERMS = [
    "recruitment agency", "recruitment consultancy", "staffing agency",
    "employment agency", "executive search firm",
]
# Hosts that list many businesses. A result on one of these is never taken as
# an agency's own website. Extend in config (agency_finder.aggregator_hosts).
DEFAULT_AGGREGATOR_HOSTS = [
    "linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com",
    "tiktok.com", "google.com", "goo.gl", "maps.app.goo.gl", "bing.com", "duckduckgo.com",
    "wikipedia.org", "yelp.com", "indeed.com", "glassdoor.com", "reddit.com", "quora.com",
    "openstreetmap.org", "trustpilot.com", "crunchbase.com", "medium.com", "wordpress.com",
    "blogspot.com", "opencorporates.com", "github.com",
]
_NAME_NOISE = {"llc", "l.l.c", "ltd", "limited", "inc", "co", "company", "fz", "fze", "fzco",
               "fzc", "fz-llc", "dmcc", "wll", "w.l.l", "spc", "plc", "gmbh", "pvt", "private",
               "the", "and", "&", "group", "services", "service", "agency", "consultancy",
               "consultants", "consulting", "recruitment", "recruiting", "staffing", "hr",
               "solutions", "international", "global", "employment", "manpower", "llp", "sarl"}
_TITLE_NOISE = {"home", "homepage", "welcome", "to", "in", "near", "for", "of", "best", "top", "jobs",
                "job", "careers", "vacancies", "official", "site", "website", "page", "contact", "us",
                "about", "list", "directory"}
_SEPARATORS = re.compile(r"\s+[|\-\u2013\u2014:\u00b7\u2022]\s+")
_ANCHOR_RE = re.compile(r"<a\b[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_CLIENT_RE = re.compile(r"\b(on behalf of (our|a) client|our client(,)? (is|a)|recruitment partner|"
                        r"we are recruiting for)\b", re.I)

Poster = Callable[[str, dict, dict], str]   # (url, headers, json body) -> response text


# ---------------------------------------------------------------- data

@dataclass
class Fact:
    """One observed fact and where it came from."""
    field: str            # name | website | address | phone | listed_email | rating | ...
    value: str
    source_url: str       # page or record the value was read from
    method: str           # discovery method or validation check that read it
    note: str = ""


@dataclass
class MethodRun:
    """Outcome of one discovery method or validation check."""
    name: str
    status: str = "not_run"     # found|empty|not_run|error (discovery); pass|fail|not_run|error (checks)
    detail: str = ""
    checked: list[str] = field(default_factory=list)


@dataclass
class Agency:
    name: str
    country: str = ""
    city: str = ""
    domain: str = ""
    id: str = ""
    status: str = "discovered"
    found_by: list[str] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    checks: list[MethodRun] = field(default_factory=list)
    email_hunt: dict[str, Any] = field(default_factory=dict)
    contact_email: str = ""
    contact_source: str = ""
    contact_proof: str = ""
    checked_at: float = 0.0

    def __post_init__(self) -> None:
        self.domain = normalize_domain(self.domain)
        if not self.id:
            self.id = agency_id(self.name, self.domain, self.country)

    # -- facts
    def add_fact(self, fact_field: str, value: Any, source_url: str, method: str, note: str = "") -> bool:
        value = str(value).strip()
        if not value:
            return False
        for f in self.facts:
            if f.field == fact_field and f.value.lower() == value.lower() and f.source_url == source_url:
                return False
        self.facts.append(Fact(fact_field, value, source_url, method, note))
        if method not in self.found_by and method in DISCOVERY_METHODS:
            self.found_by.append(method)
        return True

    def values(self, fact_field: str) -> list[str]:
        out: list[str] = []
        for f in self.facts:
            if f.field == fact_field and f.value not in out:
                out.append(f.value)
        return out

    def facts_for(self, fact_field: str) -> list[Fact]:
        return [f for f in self.facts if f.field == fact_field]

    def check(self, name: str) -> Optional[MethodRun]:
        for c in self.checks:
            if c.name == name:
                return c
        return None

    def missing_checks(self) -> list[str]:
        done = {c.name for c in self.checks if c.status in ("pass", "fail")}
        return [c for c in VALIDATION_CHECKS if c not in done]

    def signals(self) -> list[str]:
        return [c.name for c in self.checks if c.name in SIGNAL_CHECKS and c.status == "pass"]

    def merge(self, other: "Agency") -> None:
        if not self.domain and other.domain:
            self.domain = other.domain
        if not self.city and other.city:
            self.city = other.city
        for f in other.facts:
            self.add_fact(f.field, f.value, f.source_url, f.method, f.note)
        for m in other.found_by:
            if m not in self.found_by:
                self.found_by.append(m)

    def summary(self) -> str:
        if self.status == "validated":
            return f"validated - contact {self.contact_email} (source {self.contact_source})"
        if self.status == "contacted":
            return f"contacted - {self.contact_email} (proof {self.contact_proof})"
        if self.status == "no_verified_contact":
            failed = [f"{c.name}: {c.detail}" for c in self.checks if c.status == "fail"]
            return "no verified contact - " + "; ".join(failed)
        missing = self.missing_checks()
        return "discovered" + (" - still to check: " + ", ".join(missing) if missing else "")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Agency":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        kw = {k: v for k, v in data.items() if k in known and k not in ("facts", "checks")}
        agency = cls(**kw)
        agency.facts = [Fact(**f) for f in data.get("facts", [])]
        agency.checks = [MethodRun(**c) for c in data.get("checks", [])]
        return agency


@dataclass
class DiscoveryRequest:
    country: str
    city: str = ""
    industry: str = ""
    country_code: str = ""          # ISO 3166-1 alpha-2, resolved when empty
    limit: int = 50


@dataclass
class DiscoveryRun:
    request: DiscoveryRequest
    methods: list[MethodRun] = field(default_factory=list)
    agencies: list[Agency] = field(default_factory=list)

    def not_run(self) -> list[MethodRun]:
        return [m for m in self.methods if m.status in ("not_run", "error")]

    def summary(self) -> str:
        ran = [m.name for m in self.methods if m.status in ("found", "empty")]
        text = f"{len(self.agencies)} agenc{'y' if len(self.agencies) == 1 else 'ies'} from {len(ran)} method(s) that ran"
        skipped = self.not_run()
        if skipped:
            text += "; not run: " + ", ".join(f"{m.name} ({m.detail})" for m in skipped)
        return text


# ---------------------------------------------------------------- helpers

def normalize_domain(value: str) -> str:
    value = (value or "").strip().lower()
    if "://" in value:
        value = host_of(value)
    return value.removeprefix("www.").strip("/").split("/")[0]


def normalize_name(name: str) -> str:
    words = re.findall(r"[a-z0-9\u0600-\u06ff]+", (name or "").lower())
    return " ".join(words)


def name_tokens(name: str) -> list[str]:
    """Distinctive words of a business name (legal suffixes and generic
    agency words removed)."""
    return [w for w in normalize_name(name).split() if w not in _NAME_NOISE and len(w) > 1]


def agency_id(name: str, domain: str = "", country: str = "") -> str:
    key = normalize_domain(domain) or f"{normalize_name(name)}|{normalize_name(country)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or ""))).strip()


class AgencyRules:
    """Keyword, term and host rules. All replaceable via config."""

    def __init__(self, agency_keywords: Iterable[str] = (), search_terms: Iterable[str] = (),
                 aggregator_hosts: Iterable[str] = ()):
        self.keywords = [k.lower() for k in (list(agency_keywords) or DEFAULT_AGENCY_KEYWORDS)]
        self.terms = list(search_terms) or list(DEFAULT_SEARCH_TERMS)
        self.aggregators = [h.lower() for h in DEFAULT_AGGREGATOR_HOSTS + list(aggregator_hosts)]

    def is_agency_text(self, text: str) -> bool:
        low = (text or "").lower()
        return any(k in low for k in self.keywords)

    def is_aggregator(self, host: str) -> bool:
        host = normalize_domain(host)
        return any(same_domain(host, a) and host.endswith(a) for a in self.aggregators)

    def name_from_title(self, title: str, ignore: Iterable[str] = ()) -> str:
        """Pick the part of a page title that names the agency: prefer a part
        with distinctive words and an agency keyword, then any part with
        distinctive words. Place names in ``ignore`` are not distinctive."""
        title = _strip_tags(title)
        parts = [p.strip() for p in _SEPARATORS.split(title) if p.strip()]
        if not parts:
            return ""
        skip = set(_TITLE_NOISE)
        for place in ignore:
            skip.update(normalize_name(place).split())

        def distinctive(part: str) -> list[str]:
            return [t for t in name_tokens(part) if t not in skip]
        for p in parts:
            if distinctive(p) and self.is_agency_text(p) and len(p) <= 80:
                return p
        for p in parts:
            if distinctive(p):
                return p[:80]
        return parts[0][:80]


def _place_text(req: DiscoveryRequest) -> str:
    return ", ".join(p for p in (req.city, req.country) if p)


# ---------------------------------------------------------------- default network adapters

def default_poster(url: str, headers: dict, body: dict, timeout: int = 20) -> str:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"User-Agent": USER_AGENT, "Content-Type": "application/json",
                                          **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def nominatim_country_code(country: str, fetch: Optional[Fetcher] = None) -> str:
    """Resolve a country name or alias to ISO 3166-1 alpha-2 via OpenStreetMap
    Nominatim. Returns "" when it cannot be resolved."""
    country = (country or "").strip()
    if re.fullmatch(r"[A-Za-z]{2}", country):
        return country.upper()
    fetch = fetch or default_fetcher
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": country, "format": "jsonv2", "addressdetails": 1, "limit": 1, "featureType": "country"})
    try:
        data = json.loads(fetch(url))
    except Exception:
        return ""
    if data and isinstance(data, list):
        return str((data[0].get("address") or {}).get("country_code", "")).upper()
    return ""


# ---------------------------------------------------------------- discovery

GOOGLE_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PLACES_FIELDS = ("places.id,places.displayName,places.formattedAddress,places.websiteUri,"
                        "places.rating,places.userRatingCount,places.googleMapsUri,places.businessStatus,"
                        "places.internationalPhoneNumber")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


class AgencyDiscovery:
    def __init__(self, fetcher: Optional[Fetcher] = None, searcher: Optional[Searcher] = None,
                 poster: Optional[Poster] = None, maps_api_key: str = "",
                 rules: Optional[AgencyRules] = None, directory_sites: Iterable[str] = (),
                 job_board_sites: Iterable[str] = (), max_directory_pages: int = 6,
                 overpass_url: str = OVERPASS_URL,
                 country_resolver: Optional[Callable[[str], str]] = None):
        self.fetch = fetcher or default_fetcher
        self.search = searcher                  # None -> search-based methods are not_run
        self.post = poster or default_poster
        self.maps_api_key = maps_api_key        # empty -> maps is not_run
        self.rules = rules or AgencyRules()
        self.directory_sites = [s for s in directory_sites if s]
        self.job_board_sites = [s for s in job_board_sites if s]
        self.max_directory_pages = max_directory_pages
        self.overpass_url = overpass_url
        self.resolve_country = country_resolver or (lambda c: nominatim_country_code(c, self.fetch))

    # -- helpers
    def _candidate(self, req: DiscoveryRequest, name: str, website: str, source_url: str,
                   method: str) -> Optional[Agency]:
        name = _strip_tags(name)[:120]
        if not name:
            return None
        domain = normalize_domain(website)
        if domain and self.rules.is_aggregator(domain):
            domain = ""
        agency = Agency(name=name, country=req.country, city=req.city, domain=domain)
        agency.add_fact("name", name, source_url, method)
        if domain:
            agency.add_fact("website", f"https://{domain}/", source_url, method)
        return agency

    def _queries(self, req: DiscoveryRequest, extra: str = "") -> list[str]:
        place = " ".join(p for p in (req.city, req.country) if p)
        out = []
        for term in self.rules.terms:
            q = " ".join(p for p in (extra, term, req.industry, place) if p)
            out.append(q)
        return out

    def _run_search(self, run: MethodRun, queries: list[str]) -> list[dict[str, str]]:
        hits: list[dict[str, str]] = []
        errors: list[str] = []
        for q in queries:
            try:
                results = self.search(q) if self.search else []
            except SearchUnavailable as exc:
                errors.append(f"blocked: {exc}")
                continue
            except Exception as exc:
                errors.append(f"search failed: {type(exc).__name__}")
                continue
            run.checked.append(f"search: {q}")
            hits.extend(results)
        if errors and not run.checked:
            run.status, run.detail = "error", errors[0] + (f" (+{len(errors) - 1} more)" if len(errors) > 1 else "")
        elif errors:
            run.detail = f"{len(errors)} query error(s)"
        return hits

    @staticmethod
    def _finish(run: MethodRun, found: list[Agency], extra: str = "") -> list[Agency]:
        if run.status == "error":
            return found
        run.status = "found" if found else "empty"
        parts = [f"{len(found)} candidate(s)"] + ([run.detail] if run.detail else []) + ([extra] if extra else [])
        run.detail = "; ".join(parts)
        return found

    # -- methods
    def m_web_search(self, req: DiscoveryRequest) -> tuple[MethodRun, list[Agency]]:
        run = MethodRun("web_search")
        if self.search is None:
            run.detail = "no search provider configured"
            return run, []
        found: list[Agency] = []
        for hit in self._run_search(run, self._queries(req)):
            url, title, snippet = hit.get("url", ""), hit.get("title", ""), hit.get("snippet", "")
            host = host_of(url)
            if not url.startswith("http") or not host or self.rules.is_aggregator(host):
                continue          # directories/social are read by other methods
            if not self.rules.is_agency_text(title + " " + snippet):
                continue
            agency = self._candidate(req, self.rules.name_from_title(title, (req.country, req.city)), url, url, "web_search")
            if agency:
                found.append(agency)
        return run, self._finish(run, found)

    def m_maps(self, req: DiscoveryRequest) -> tuple[MethodRun, list[Agency]]:
        run = MethodRun("maps")
        if not self.maps_api_key:
            run.detail = "no Google Maps API key (set the key named in agency_finder.maps_api_key_env)"
            return run, []
        found: list[Agency] = []
        errors: list[str] = []
        headers = {"X-Goog-Api-Key": self.maps_api_key, "X-Goog-FieldMask": GOOGLE_PLACES_FIELDS}
        for term in self.rules.terms:
            query = " ".join(p for p in (term, req.industry) if p) + f" in {_place_text(req)}"
            try:
                data = json.loads(self.post(GOOGLE_PLACES_URL, headers, {"textQuery": query}))
            except Exception as exc:
                errors.append(type(exc).__name__)
                continue
            if "error" in data:
                errors.append(str(data["error"].get("status") or data["error"].get("message", "error")))
                continue
            run.checked.append(f"places: {query}")
            for place in data.get("places", []) or []:
                name = (place.get("displayName") or {}).get("text", "")
                source = place.get("googleMapsUri") or f"google-places:{place.get('id', '')}"
                agency = self._candidate(req, name, place.get("websiteUri", ""), source, "maps")
                if not agency:
                    continue
                agency.add_fact("address", place.get("formattedAddress", ""), source, "maps")
                agency.add_fact("phone", place.get("internationalPhoneNumber", ""), source, "maps")
                agency.add_fact("maps_listing", source, source, "maps")
                agency.add_fact("business_status", place.get("businessStatus", ""), source, "maps")
                if place.get("rating") is not None:
                    agency.add_fact("rating", place["rating"], source, "maps")
                    agency.add_fact("review_count", place.get("userRatingCount", 0), source, "maps")
                found.append(agency)
        if errors and not run.checked:
            run.status, run.detail = "error", "Places API: " + ", ".join(sorted(set(errors)))
            return run, []
        if errors:
            run.detail = f"{len(errors)} request error(s)"
        return run, self._finish(run, found)

    def m_openstreetmap(self, req: DiscoveryRequest) -> tuple[MethodRun, list[Agency]]:
        run = MethodRun("openstreetmap")
        code = (req.country_code or self.resolve_country(req.country) or "").upper()
        if not re.fullmatch(r"[A-Z]{2}", code):
            run.detail = f"could not resolve '{req.country}' to an ISO country code; pass one (e.g. --country-code XX)"
            return run, []
        query = (f'[out:json][timeout:60];area["ISO3166-1"="{code}"][admin_level=2]->.a;'
                 f'nwr["office"="employment_agency"](area.a);out tags center 500;')
        url = self.overpass_url + "?" + urllib.parse.urlencode({"data": query})
        try:
            data = json.loads(self.fetch(url))
        except Exception as exc:
            code_txt = f" HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else ""
            run.status = "error"
            run.detail = (f"Overpass API unavailable ({type(exc).__name__}{code_txt}); public servers are often "
                          "busy - retry later or set agency_finder.overpass_url to another instance")
            return run, []
        run.checked.append(f"overpass: office=employment_agency in {code}")
        found: list[Agency] = []
        city = req.city.lower()
        for el in data.get("elements", []) or []:
            tags = el.get("tags") or {}
            name = tags.get("name:en") or tags.get("name") or ""
            if city and city not in " ".join(str(tags.get(k, "")) for k in
                                             ("addr:city", "addr:suburb", "addr:state", "is_in")).lower():
                continue
            source = f"https://www.openstreetmap.org/{el.get('type', 'node')}/{el.get('id', '')}"
            website = tags.get("website") or tags.get("contact:website") or ""
            agency = self._candidate(req, name, website, source, "openstreetmap")
            if not agency:
                continue
            agency.add_fact("maps_listing", source, source, "openstreetmap")
            addr = ", ".join(tags[k] for k in ("addr:street", "addr:city") if tags.get(k))
            agency.add_fact("address", addr, source, "openstreetmap")
            agency.add_fact("phone", tags.get("phone") or tags.get("contact:phone", ""), source, "openstreetmap")
            agency.add_fact("listed_email", tags.get("email") or tags.get("contact:email", ""), source,
                            "openstreetmap", "third-party listing; a lead until the email finder verifies it")
            found.append(agency)
        extra = "city filtered on OSM address tags" if city else ""
        return run, self._finish(run, found, extra)

    def agencies_from_page(self, req: DiscoveryRequest, url: str, text: str, method: str) -> list[Agency]:
        """Read agency links off a directory or list page."""
        found: list[Agency] = []
        page_host = host_of(url)
        for href, anchor in _ANCHOR_RE.findall(text or ""):
            label = _strip_tags(anchor)
            if not label or len(label) > 100 or not self.rules.is_agency_text(label):
                continue
            target = urllib.parse.urljoin(url, href)
            target_host = host_of(target)
            external = target_host and not same_domain(target_host, page_host)
            website = target if external and not self.rules.is_aggregator(target_host) else ""
            agency = self._candidate(req, label, website, url, method)
            if agency:
                if not external:
                    agency.add_fact("profile_page", target, url, method)
                found.append(agency)
        return found

    def m_directories(self, req: DiscoveryRequest) -> tuple[MethodRun, list[Agency]]:
        run = MethodRun("directories")
        if self.search is None:
            run.detail = "no search provider configured"
            return run, []
        place = _place_text(req)
        queries = [f"list of recruitment agencies in {place}", f"recruitment agencies directory {place}"]
        if req.industry:
            queries.append(f"{req.industry} recruitment agencies in {place}")
        queries += [f"site:{s} recruitment agency {place}" for s in self.directory_sites]
        found: list[Agency] = []
        fetched = 0
        for hit in self._run_search(run, queries):
            url = hit.get("url", "")
            if not url.startswith("http") or fetched >= self.max_directory_pages:
                continue
            try:
                text = self.fetch(url) or ""
            except Exception:
                continue
            fetched += 1
            run.checked.append(url)
            found.extend(self.agencies_from_page(req, url, text, "directories"))
        return run, self._finish(run, found, f"{fetched} page(s) read")

    def m_job_boards(self, req: DiscoveryRequest) -> tuple[MethodRun, list[Agency]]:
        run = MethodRun("job_boards")
        if not self.job_board_sites:
            run.detail = "no job boards configured (agency_finder.job_board_sites)"
            return run, []
        if self.search is None:
            run.detail = "no search provider configured"
            return run, []
        queries = []
        for site in self.job_board_sites:
            queries += self._queries(req, extra=f"site:{site}")[:2]
        found: list[Agency] = []
        for hit in self._run_search(run, queries):
            title, snippet, url = hit.get("title", ""), hit.get("snippet", ""), hit.get("url", "")
            if not self.rules.is_agency_text(title + " " + snippet):
                continue
            agency = self._candidate(req, self.rules.name_from_title(title, (req.country, req.city)), "", url, "job_boards")
            if agency:
                agency.add_fact("job_board_listing", url, url, "job_boards")
                found.append(agency)
        return run, self._finish(run, found)

    def m_tracker(self, req: DiscoveryRequest, jobs: Optional[list] = None) -> tuple[MethodRun, list[Agency]]:
        run = MethodRun("tracker")
        if jobs is None:
            run.detail = "no tracker available"
            return run, []
        place = [p.lower() for p in (req.country, req.city, req.country_code) if p]
        found: list[Agency] = []
        for job in jobs:
            loc = (job.location or "").lower()
            if place and not any(p in loc for p in place):
                continue
            run.checked.append(job.url or job.id)
            is_agency = self.rules.is_agency_text(job.company)
            posts_for_client = bool(_CLIENT_RE.search(job.description or ""))
            if not (is_agency or posts_for_client):
                continue
            source = job.url or f"tracker:{job.id}"
            agency = self._candidate(req, job.company, "", source, "tracker")
            if not agency:
                continue
            agency.add_fact("job_listing", f"{job.title} ({job.source})", source, "tracker",
                            "posts for a client" if posts_for_client else "")
            for email in job.contact_emails or []:
                agency.add_fact("listed_email", email, source, "tracker", "printed on a job listing")
            found.append(agency)
        return run, self._finish(run, found, f"{len(run.checked)} tracked role(s) in the area")

    def m_supplied(self, req: DiscoveryRequest, supplied: Optional[list] = None) -> tuple[MethodRun, list[Agency]]:
        """Pages ({url, text}) or candidates ({name, website?, source_url})."""
        run = MethodRun("supplied")
        if not supplied:
            run.detail = "no pages supplied (--pages)"
            return run, []
        found: list[Agency] = []
        for item in supplied:
            url = item.get("source_url") or item.get("url") or ""
            if not url:
                continue
            run.checked.append(url)
            if item.get("name"):
                agency = self._candidate(req, item["name"], item.get("website", ""), url, "supplied")
                if agency:
                    found.append(agency)
            if item.get("text"):
                found.extend(self.agencies_from_page(req, url, item["text"], "supplied"))
        return run, self._finish(run, found)

    # -- run
    def run(self, req: DiscoveryRequest, methods: Optional[Iterable[str]] = None,
            skip: Iterable[str] = (), jobs: Optional[list] = None,
            supplied: Optional[list] = None) -> DiscoveryRun:
        wanted = list(methods) if methods else list(DISCOVERY_METHODS)
        skip = set(skip)
        unknown = [m for m in wanted + list(skip) if m not in DISCOVERY_METHODS]
        if unknown:
            raise ValueError(f"unknown method(s): {', '.join(unknown)}; choose from {', '.join(DISCOVERY_METHODS)}")
        if not req.country_code and re.fullmatch(r"[A-Za-z]{2}", req.country or ""):
            req.country_code = req.country.upper()
        result = DiscoveryRun(request=req)
        collected: list[Agency] = []
        for name in DISCOVERY_METHODS:
            if name not in wanted or name in skip:
                result.methods.append(MethodRun(name, "not_run",
                                                "skipped by --skip" if name in skip else "not selected (--methods)"))
                continue
            if name == "tracker":
                run, found = self.m_tracker(req, jobs)
            elif name == "supplied":
                run, found = self.m_supplied(req, supplied)
            else:
                run, found = getattr(self, f"m_{name}")(req)
            result.methods.append(run)
            collected.extend(found)
        agencies = merge_agencies(collected)
        result.agencies = agencies[: max(req.limit, 0) or len(agencies)]
        return result


def _name_key(agency: Agency) -> str:
    return " ".join(name_tokens(agency.name)) or normalize_name(agency.name)


def merge_agencies(found: list[Agency]) -> list[Agency]:
    """Merge the same agency seen by several methods: first by domain, then a
    name-only record folds into the domain record with the same distinctive
    name, then remaining name-only records merge by name. Order is kept."""
    by_domain: dict[str, Agency] = {}
    order: list[Agency] = []
    for a in found:
        if a.domain:
            if a.domain in by_domain:
                by_domain[a.domain].merge(a)
            else:
                by_domain[a.domain] = a
                order.append(a)
    name_to_domain: dict[str, Agency] = {}
    for a in by_domain.values():
        name_to_domain.setdefault(_name_key(a), a)
    by_name: dict[str, Agency] = {}
    for a in found:
        if a.domain:
            continue
        key = _name_key(a)
        if key in name_to_domain:
            name_to_domain[key].merge(a)
        elif key in by_name:
            by_name[key].merge(a)
        else:
            by_name[key] = a
            order.append(a)
    for a in order:
        a.id = agency_id(a.name, a.domain, a.country)
    return order


# ---------------------------------------------------------------- validation

class AgencyValidator:
    def __init__(self, fetcher: Optional[Fetcher] = None, searcher: Optional[Searcher] = None,
                 mx_resolver: Optional[MXResolver] = None, email_finder: Optional[EmailFinder] = None,
                 rules: Optional[AgencyRules] = None, clock: Callable[[], float] = time.time):
        self.fetch = fetcher or default_fetcher
        self.search = searcher
        self.mx = mx_resolver or doh_mx_resolver
        self.finder = email_finder or EmailFinder(fetcher=self.fetch, searcher=searcher, mx_resolver=self.mx)
        self.rules = rules or AgencyRules()
        self.clock = clock

    def _find_website(self, agency: Agency, run: MethodRun) -> None:
        """Look for the agency's own site via search. Only accepted when the
        result host carries the agency's distinctive name words."""
        if self.search is None:
            return
        tokens = name_tokens(agency.name)
        if not tokens:
            return
        query = f'"{agency.name}" {agency.city or ""} {agency.country}'.replace("  ", " ").strip()
        try:
            hits = self.search(query)
        except Exception:
            return
        run.checked.append(f"search: {query}")
        for hit in hits:
            url = hit.get("url", "")
            host = host_of(url)
            if not host or self.rules.is_aggregator(host):
                continue
            stem = host.split(".")[0].replace("-", "")
            if all(t in stem or t in normalize_name(hit.get("title", "")) for t in tokens) and \
                    any(t in stem for t in tokens):
                agency.domain = normalize_domain(host)
                agency.add_fact("website", f"https://{agency.domain}/", url, "website",
                                "found by search; host carries the agency name")
                return

    def c_website(self, agency: Agency) -> tuple[MethodRun, str, bool]:
        run = MethodRun("website")
        if not agency.domain:
            self._find_website(agency, run)
        if not agency.domain:
            run.detail = "no website known" + ("" if self.search else " and no search provider to find one")
            return run, "", False
        url = f"https://{agency.domain}/"
        run.checked.append(url)
        try:
            text = self.fetch(url) or ""
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 429, 503):
                run.status, run.detail = "error", f"site answered HTTP {exc.code} (may block automated checks)"
            else:
                run.status, run.detail = "fail", f"HTTP {exc.code}"
            return run, "", False
        except (socket.timeout, TimeoutError) as exc:
            run.status, run.detail = "error", f"timed out ({type(exc).__name__})"
            return run, "", False
        except Exception as exc:
            run.status, run.detail = "fail", f"did not resolve ({type(exc).__name__})"
            return run, "", False
        if not text.strip():
            run.status, run.detail = "fail", "empty response"
            return run, "", False
        page = normalize_name(_strip_tags(text))
        tokens = name_tokens(agency.name)
        words = page.split()
        named = bool(tokens) and (all(t in words for t in tokens)
                                  or "".join(tokens) in page.replace(" ", ""))
        run.status = "pass"
        run.detail = "resolves" + ("; names the agency" if named else "; agency name not found on homepage")
        agency.add_fact("website_ok", url, url, "website")
        return run, text, named

    def c_mx(self, agency: Agency) -> MethodRun:
        run = MethodRun("mx")
        if not agency.domain:
            run.detail = "no domain"
            return run
        run.checked.append(agency.domain)
        try:
            ok = self.mx(agency.domain)
        except Exception:
            ok = None
        if ok is None:
            run.status, run.detail = "error", "MX lookup failed"
        elif ok:
            run.status, run.detail = "pass", "live MX record"
            agency.add_fact("mx", "live", f"dns:MX {agency.domain}", "mx")
        else:
            run.status, run.detail = "fail", "no MX record - domain cannot receive mail"
        return run

    def c_contact_email(self, agency: Agency, confirmed: bool) -> MethodRun:
        run = MethodRun("contact_email")
        if not agency.domain:
            run.detail = "no domain"
            return run
        leads = [{"method": "registry", "url": f.source_url, "text": f.value}
                 for f in agency.facts_for("listed_email") if f.source_url.startswith("http")]
        hunt = self.finder.run(FinderInput(company=agency.name, official_domain=agency.domain,
                                           domain_confirmed=confirmed, supplied_pages=leads))
        agency.email_hunt = hunt.to_dict()
        run.checked = [f"{m.name}:{m.status}" for m in hunt.methods]
        best = hunt.best()
        if hunt.status == "found" and best:
            run.status, run.detail = "pass", f"{best.address} ({best.method})"
            agency.contact_email, agency.contact_source = best.address, best.source_url
            agency.add_fact("contact_email", best.address, best.source_url, "contact_email",
                            f"verified by the email finder ({best.method})")
        elif hunt.status == "no_verified_address" and confirmed:
            run.status, run.detail = "fail", "no verified address - every email-finder method ran"
        elif not confirmed:
            # Without a confirmed official domain nothing can be verified, so
            # an empty hunt is not evidence that no contact exists.
            run.status = "error"
            run.detail = "official domain not confirmed (site does not name the agency); leads kept, none verified"
        else:
            reason = "" if confirmed else "official domain not confirmed; "
            run.status, run.detail = "error", reason + "email finder incomplete - still to run: " + \
                ", ".join(hunt.missing_methods())
        return run

    def c_linkedin(self, agency: Agency, homepage: str) -> MethodRun:
        run = MethodRun("linkedin")
        for href in re.findall(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[^\"'\s<>?#]+", homepage or "", re.I):
            run.status, run.detail = "pass", "official site links a LinkedIn company page"
            agency.add_fact("linkedin", href, f"https://{agency.domain}/", "linkedin")
            return run
        if self.search is None:
            run.detail = "no search provider configured and the site links no LinkedIn page"
            return run
        query = f'site:linkedin.com/company "{agency.name}"'
        try:
            hits = self.search(query)
        except Exception as exc:
            run.status, run.detail = "error", f"search failed ({type(exc).__name__})"
            return run
        run.checked.append(f"search: {query}")
        tokens = name_tokens(agency.name) or normalize_name(agency.name).split()
        for hit in hits:
            url = hit.get("url", "")
            if "linkedin.com/company/" in url and all(t in normalize_name(hit.get("title", "")) for t in tokens):
                run.status, run.detail = "pass", "LinkedIn company page found by search"
                agency.add_fact("linkedin", url, url, "linkedin")
                return run
        run.status, run.detail = "fail", "no LinkedIn company page matching the name"
        return run

    @staticmethod
    def c_maps_presence(agency: Agency, maps_ran: bool) -> MethodRun:
        run = MethodRun("maps_presence")
        listings = agency.facts_for("maps_listing")
        if listings:
            run.status = "pass"
            run.detail = "listed on " + ", ".join(sorted({f.method for f in listings}))
            run.checked = [f.source_url for f in listings]
        elif maps_ran:
            run.status, run.detail = "fail", "not in the map results that ran"
        else:
            run.detail = "no map method ran (maps key missing and openstreetmap skipped/failed)"
        return run

    @staticmethod
    def c_reviews(agency: Agency, maps_key: bool) -> MethodRun:
        run = MethodRun("reviews")
        ratings = agency.facts_for("rating")
        if ratings:
            count = agency.values("review_count")
            run.status = "pass"
            run.detail = f"rating {ratings[0].value}" + (f" from {count[0]} review(s)" if count else "")
            run.checked = [ratings[0].source_url]
        elif maps_key and agency.facts_for("maps_listing"):
            run.status, run.detail = "fail", "map listing has no public rating"
        else:
            run.detail = "reviews not accessible (needs a Google Maps API key, or supply review pages)"
        return run

    def validate(self, agency: Agency, maps_ran: bool = False, maps_key: bool = False) -> Agency:
        if agency.status == "contacted":
            return agency
        checks: list[MethodRun] = []
        website, homepage, named = self.c_website(agency)
        checks.append(website)
        checks.append(self.c_mx(agency))
        confirmed = website.status == "pass" and named
        if website.status == "fail":
            checks.append(MethodRun("contact_email", "not_run", "website does not resolve"))
        else:
            checks.append(self.c_contact_email(agency, confirmed))
        checks.append(self.c_linkedin(agency, homepage))
        checks.append(self.c_maps_presence(agency, maps_ran))
        checks.append(self.c_reviews(agency, maps_key))
        agency.checks = checks
        agency.id = agency_id(agency.name, agency.domain, agency.country)
        agency.checked_at = self.clock()
        agency.status = decide_status(agency)
        return agency


def decide_status(agency: Agency) -> str:
    if agency.status == "contacted":
        return "contacted"
    st = {c.name: c.status for c in agency.checks}
    if st.get("website") == "pass" and st.get("mx") == "pass" and st.get("contact_email") == "pass":
        return "validated"
    if st.get("website") == "fail" or st.get("mx") == "fail" or st.get("contact_email") == "fail":
        return "no_verified_contact"
    return "discovered"


# ---------------------------------------------------------------- config

def searcher_from_config(cfg: dict[str, Any], fetcher: Optional[Fetcher] = None) -> Optional[Searcher]:
    provider = str(cfg.get("search_provider", "duckduckgo")).lower()
    if provider == "duckduckgo":
        return duckduckgo_searcher(fetcher)
    if provider == "searxng" and cfg.get("searxng_url"):
        return searxng_searcher(str(cfg["searxng_url"]), fetcher)
    return None


def build_from_config(raw: dict[str, Any], no_search: bool = False, env: Optional[dict] = None,
                      fetcher: Optional[Fetcher] = None) -> tuple[AgencyDiscovery, AgencyValidator]:
    """Wire discovery + validation from config.json (agency_finder section,
    falling back to email_finder for the search provider)."""
    env = os.environ if env is None else env
    af = dict(raw.get("agency_finder", {}))
    ef = dict(raw.get("email_finder", {}))
    search_cfg = {"search_provider": af.get("search_provider", ef.get("search_provider", "duckduckgo")),
                  "searxng_url": af.get("searxng_url") or ef.get("searxng_url", "")}
    searcher = None if no_search else searcher_from_config(search_cfg, fetcher)
    rules = AgencyRules(af.get("agency_keywords", []), af.get("search_terms", []), af.get("aggregator_hosts", []))
    key = str(env.get(str(af.get("maps_api_key_env", "GOOGLE_MAPS_API_KEY")), "") or "")
    discovery = AgencyDiscovery(fetcher=fetcher, searcher=searcher, maps_api_key=key, rules=rules,
                                directory_sites=af.get("directory_sites", []),
                                job_board_sites=af.get("job_board_sites", []),
                                max_directory_pages=int(af.get("max_directory_pages", 6)),
                                overpass_url=str(af.get("overpass_url", OVERPASS_URL)))
    finder = EmailFinder(fetcher=fetcher, searcher=searcher,
                         max_pages=int(ef.get("max_site_pages", 14)),
                         max_search_pages=int(ef.get("max_search_pages", 4)),
                         registry_sites=ef.get("registry_sites", ["opencorporates.com"]))
    validator = AgencyValidator(fetcher=fetcher, searcher=searcher, email_finder=finder, rules=rules)
    return discovery, validator
