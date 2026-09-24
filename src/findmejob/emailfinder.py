"""Multi-method email discovery for an employer or recruiter.

Goal: get the application in front of a real person. A portal submission is
one route; a short follow-up to a verified company address is the second.
This module finds that address, and it is strict about what "found" means.

Rules this module enforces:

- Never construct, guess, or pattern-generate an address. Every address in a
  report was read from a public page, and the report keeps that page's URL.
- An address is ``verified`` only when (a) it was published on the job listing
  or on a page of the company's own confirmed domain, (b) its domain matches
  the confirmed official domain (or the listing published it directly), and
  (c) the address domain has a live MX record.
- ``no_verified_address`` is a conclusion, not a default. It is returned only
  when every method actually ran and none produced a verified address. If any
  method was skipped (no search provider, no domain, network error), the
  status is ``incomplete`` and the report says which methods still need to run.

Methods, in order:
  listing        emails printed in the job description itself
  official_site  homepage + contact/careers/about pages on the official domain
  web_search     search results for the company plus contact/careers/HR terms
  linkedin       LinkedIn company/people signals (search results or supplied pages)
  registry       business registries/directories (search results or supplied pages)
  mx             DNS MX check for every candidate address domain
  pattern        consistency checks on found addresses (domain, role inbox,
                 free-mail, lookalike domain). It verifies; it never generates.

Everything network-facing is injectable (fetcher, searcher, MX resolver) so
tests never touch the network.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable, Optional

USER_AGENT = "findmejob/0.2 (+https://github.com/infattah/findmejob)"

METHODS = ["listing", "official_site", "web_search", "linkedin", "registry", "mx", "pattern"]

# Paths commonly used for contact and hiring details. Only fetched on the
# confirmed official domain.
CONTACT_PATHS = [
    "/", "/contact", "/contact-us", "/contactus", "/contact.html", "/careers",
    "/career", "/careers.html", "/jobs", "/join-us", "/work-with-us", "/about",
    "/about-us",
]
_LINK_HINTS = ("contact", "career", "job", "join", "hiring", "recruit", "about", "vacanc")

FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "live.com", "icloud.com", "aol.com", "proton.me", "protonmail.com", "gmx.com",
    "mail.com", "yandex.com", "zoho.com",
}
ROLE_LOCALS = {
    "careers": "careers", "career": "careers", "jobs": "careers", "job": "careers",
    "recruitment": "recruitment", "recruiting": "recruitment", "recruit": "recruitment",
    "talent": "recruitment", "hiring": "recruitment", "hr": "hr",
    "humanresources": "hr", "people": "hr", "cv": "careers", "resume": "careers",
    "info": "general", "contact": "general", "hello": "general", "enquiries": "general",
    "enquiry": "general", "inquiries": "general", "office": "general", "admin": "general",
}
# Addresses that should never be used for an application.
_REJECT_LOCALS = {"noreply", "no-reply", "donotreply", "do-not-reply", "abuse",
                  "postmaster", "webmaster", "privacy", "unsubscribe", "billing",
                  "support-noreply", "mailer-daemon"}
_REJECT_DOMAINS = {"example.com", "example.org", "example.net", "domain.com",
                   "email.com", "sentry.io", "wixpress.com", "sentry-next.wixpress.com"}
_ASSET_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "ico"}

_EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24})(?![\w-])")
# Only bracketed forms. Bare "at"/"dot" words are ordinary prose ("apply at
# acme.com") and rewriting them would invent addresses.
_OBFUSCATED = [
    (re.compile(r"\s*[\[\(\{<]\s*at\s*[\]\)\}>]\s*", re.I), "@"),
    (re.compile(r"\s*[\[\(\{<]\s*dot\s*[\]\)\}>]\s*", re.I), "."),
]
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)

Fetcher = Callable[[str], str]                         # url -> page text/html
Searcher = Callable[[str], list[dict[str, str]]]       # query -> [{url,title,snippet}]
MXResolver = Callable[[str], Optional[bool]]           # domain -> True/False/None(unknown)


# ---------------------------------------------------------------- extraction

def _clean(address: str) -> str:
    return address.strip().strip(".,;:()[]<>\"'").lower()


def _acceptable(address: str) -> bool:
    if "@" not in address:
        return False
    local, domain = address.rsplit("@", 1)
    if local in _REJECT_LOCALS or domain in _REJECT_DOMAINS:
        return False
    if domain.rsplit(".", 1)[-1] in _ASSET_TLDS:   # logo@2x.png etc.
        return False
    if re.fullmatch(r"[0-9a-f]{16,}", local):        # tracking hashes
        return False
    return True


def extract_emails(text: str) -> list[str]:
    """Return addresses literally present in text (incl. mailto and simple
    [at]/[dot] obfuscation), de-duplicated in first-seen order.

    This reads what the page published. It does not invent anything."""
    if not text:
        return []
    raw = html.unescape(text)
    raw = urllib.parse.unquote(raw) if "%40" in raw else raw
    candidates: list[str] = []
    for match in re.finditer(r"mailto:([^\"'?>\s]+)", raw, re.I):
        candidates.append(match.group(1))
    plain = re.sub(r"<[^>]+>", " ", raw)
    for pattern, repl in _OBFUSCATED:
        plain = pattern.sub(repl, plain)
    candidates.extend(m.group(1) for m in _EMAIL_RE.finditer(plain))
    seen: list[str] = []
    for cand in candidates:
        for piece in cand.split(","):
            addr = _clean(piece)
            if _EMAIL_RE.fullmatch(addr) and _acceptable(addr) and addr not in seen:
                seen.append(addr)
    return seen


def host_of(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def same_domain(a: str, b: str) -> bool:
    a, b = a.lower().removeprefix("www."), b.lower().removeprefix("www.")
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def _looks_like_lookalike(domain: str, official: str) -> bool:
    """e.g. acme-careers.com or acmehr.net next to official acme.com."""
    if not official or same_domain(domain, official):
        return False
    stem = official.split(".")[0]
    return len(stem) >= 4 and stem in domain.split(".")[0]


def role_of(address: str) -> str:
    local = address.split("@", 1)[0].replace(".", "").replace("-", "").replace("_", "")
    for key, role in ROLE_LOCALS.items():
        if local == key or local.startswith(key):
            return role
    return "person"


# ---------------------------------------------------------------- data

@dataclass
class FoundEmail:
    address: str
    source_url: str
    method: str
    role: str = "person"          # careers | recruitment | hr | general | person
    mx_ok: Optional[bool] = None  # None = not checked / unknown
    verified: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class MethodResult:
    name: str
    status: str = "skipped"       # found | empty | skipped | error
    detail: str = ""
    checked: list[str] = field(default_factory=list)


@dataclass
class EmailHunt:
    company: str
    official_domain: str = ""
    domain_confirmed: bool = False
    status: str = "incomplete"    # found | no_verified_address | incomplete
    emails: list[FoundEmail] = field(default_factory=list)
    methods: list[MethodResult] = field(default_factory=list)

    def verified(self) -> list[FoundEmail]:
        return [e for e in self.emails if e.verified]

    def best(self) -> Optional[FoundEmail]:
        """Preferred verified address: hiring inboxes first, then people who
        were published as a hiring contact, then general inboxes."""
        order = {"careers": 0, "recruitment": 0, "hr": 1, "person": 2, "general": 3}
        ranked = sorted(self.verified(), key=lambda e: (order.get(e.role, 9), METHODS.index(e.method)))
        return ranked[0] if ranked else None

    def missing_methods(self) -> list[str]:
        return [m.name for m in self.methods if m.status in ("skipped", "error")]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmailHunt":
        return cls(
            company=str(data.get("company", "")),
            official_domain=str(data.get("official_domain", "")),
            domain_confirmed=bool(data.get("domain_confirmed", False)),
            status=str(data.get("status", "incomplete")),
            emails=[FoundEmail(**e) for e in data.get("emails", [])],
            methods=[MethodResult(**m) for m in data.get("methods", [])],
        )

    def to_routes(self) -> list[dict[str, Any]]:
        """Verified addresses as ApplicationRoute dicts (see verification.py)."""
        return [{"kind": "email", "value": e.address, "source_url": e.source_url,
                 "label": f"{e.role} ({e.method})", "verified": True}
                for e in self.verified() if e.source_url.startswith("https://")]

    def summary(self) -> str:
        if self.status == "found":
            best = self.best()
            return f"verified: {best.address} (source {best.source_url})" if best else "found"
        if self.status == "no_verified_address":
            return "no verified address - every method ran"
        return "incomplete - still to run: " + ", ".join(self.missing_methods())


# ---------------------------------------------------------------- default network adapters

def default_fetcher(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        if ctype and not any(t in ctype for t in ("html", "text", "json", "xml")):
            return ""
        return resp.read(2_000_000).decode("utf-8", errors="replace")


def doh_mx_resolver(domain: str, fetch: Optional[Fetcher] = None) -> Optional[bool]:
    """MX lookup over DNS-over-HTTPS (stdlib has no resolver).

    True = at least one MX record; False = NXDOMAIN or no MX; None = lookup
    failed, which is reported as unknown rather than as a negative."""
    url = "https://cloudflare-dns.com/dns-query?" + urllib.parse.urlencode({"name": domain, "type": "MX"})
    try:
        if fetch is None:
            req = urllib.request.Request(url, headers={"accept": "application/dns-json",
                                                       "User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
        else:
            body = fetch(url)
        data = json.loads(body)
    except Exception:
        return None
    if data.get("Status") == 3:
        return False
    answers = [a for a in data.get("Answer", []) or [] if a.get("type") == 15]
    return bool(answers)


class SearchUnavailable(RuntimeError):
    """The provider answered with a block/challenge page instead of results.
    Reported as an error so the hunt stays incomplete; never read as "no hits"."""


def duckduckgo_searcher(fetch: Optional[Fetcher] = None, limit: int = 8) -> Searcher:
    """Minimal HTML search adapter. Swap in any provider with the same shape."""
    fetch = fetch or default_fetcher

    def search(query: str) -> list[dict[str, str]]:
        page = fetch("https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query}))
        if "result__a" not in page:
            if re.search(r"no-results|No results\.", page):
                return []
            raise SearchUnavailable("search provider returned no result markup (likely a bot check)")
        results: list[dict[str, str]] = []
        for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=class="result__a"|$)',
                             page, re.S):
            href = html.unescape(m.group(1))
            if "uddg=" in href:
                href = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0])
            snippet = re.sub(r"<[^>]+>", " ", m.group(3))
            results.append({"url": href, "title": re.sub(r"<[^>]+>", "", m.group(2)),
                            "snippet": html.unescape(snippet)[:500]})
            if len(results) >= limit:
                break
        return results

    return search


def searxng_searcher(base_url: str, fetch: Optional[Fetcher] = None, limit: int = 8) -> Searcher:
    """SearXNG JSON API (self-hosted or a trusted instance with format=json on)."""
    fetch = fetch or default_fetcher

    def search(query: str) -> list[dict[str, str]]:
        body = fetch(base_url.rstrip("/") + "/search?" + urllib.parse.urlencode({"q": query, "format": "json"}))
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise SearchUnavailable("SearXNG did not return JSON") from exc
        return [{"url": r.get("url", ""), "title": r.get("title", ""), "snippet": r.get("content", "")}
                for r in data.get("results", [])[:limit]]

    return search


# ---------------------------------------------------------------- the finder

@dataclass
class FinderInput:
    company: str
    official_domain: str = ""        # bare domain, e.g. "example.com"
    domain_confirmed: bool = False   # True when checked against the official site/LinkedIn
    listing_text: str = ""
    listing_url: str = ""
    # Pages a person or agent already opened (LinkedIn, registry, directory):
    # [{"method": "linkedin"|"registry"|"official_site"|"web_search", "url": ..., "text": ...}]
    supplied_pages: list[dict[str, str]] = field(default_factory=list)


class EmailFinder:
    def __init__(self, fetcher: Optional[Fetcher] = None, searcher: Optional[Searcher] = None,
                 mx_resolver: Optional[MXResolver] = None, max_pages: int = 14,
                 max_search_pages: int = 4,
                 registry_sites: Iterable[str] = ("opencorporates.com",)):
        self.fetch = fetcher or default_fetcher
        self.search = searcher                   # None -> search-based methods are "skipped"
        self.mx = mx_resolver or doh_mx_resolver
        self.max_pages = max_pages
        self.max_search_pages = max_search_pages
        self.registry_sites = list(registry_sites)

    # -- helpers
    def _add(self, hunt: EmailHunt, address: str, url: str, method: str) -> bool:
        if any(e.address == address for e in hunt.emails):
            return False
        hunt.emails.append(FoundEmail(address=address, source_url=url, method=method,
                                      role=role_of(address)))
        return True

    def _safe_fetch(self, url: str) -> tuple[str, str]:
        try:
            return self.fetch(url) or "", ""
        except Exception as exc:  # network errors are recorded, never fatal
            return "", f"{type(exc).__name__}"

    def _harvest(self, hunt: EmailHunt, result: MethodResult, url: str, text: str,
                 method: str, domain_filter: Optional[str] = None) -> int:
        result.checked.append(url)
        added = 0
        for addr in extract_emails(text):
            if domain_filter and not same_domain(addr.rsplit("@", 1)[1], domain_filter) \
                    and not same_domain(host_of(url), domain_filter):
                continue
            added += self._add(hunt, addr, url, method)
        return added

    def _search_method(self, hunt: EmailHunt, name: str, queries: list[str],
                       site_filter: Optional[Callable[[str], bool]] = None) -> MethodResult:
        result = MethodResult(name)
        if self.search is None:
            result.detail = "no search provider configured"
            return result
        found = fetched = 0
        errors: list[str] = []
        for q in queries:
            try:
                hits = self.search(q)
            except Exception as exc:
                errors.append(f"search failed: {type(exc).__name__}")
                continue
            result.checked.append(f"search: {q}")
            for hit in hits:
                url = hit.get("url", "")
                if site_filter and not site_filter(url):
                    continue
                # snippets count as evidence only with the page URL they came from
                found += self._harvest(hunt, result, url, hit.get("title", "") + " " + hit.get("snippet", ""),
                                       name, hunt.official_domain or None)
                if fetched < self.max_search_pages and url.startswith("http"):
                    text, err = self._safe_fetch(url)
                    fetched += 1
                    if text:
                        found += self._harvest(hunt, result, url, text, name, hunt.official_domain or None)
        if errors and not result.checked:
            result.status, result.detail = "error", "; ".join(errors)
        else:
            result.status = "found" if found else "empty"
            result.detail = f"{found} new address(es)" + (f"; {len(errors)} query error(s)" if errors else "")
        return result

    # -- methods
    def _m_listing(self, hunt: EmailHunt, inp: FinderInput) -> MethodResult:
        result = MethodResult("listing")
        if not inp.listing_text:
            result.status, result.detail = "empty", "no listing text"
            return result
        n = self._harvest(hunt, result, inp.listing_url or "listing", inp.listing_text, "listing")
        result.status = "found" if n else "empty"
        result.detail = f"{n} address(es) printed in the listing"
        return result

    def _m_official_site(self, hunt: EmailHunt, inp: FinderInput) -> MethodResult:
        result = MethodResult("official_site")
        domain = hunt.official_domain
        if not domain:
            result.detail = "official domain unknown - confirm it (company verification) and re-run"
            return result
        base = f"https://{domain}"
        queue = [base + p for p in CONTACT_PATHS]
        seen: set[str] = set()
        found = errors = 0
        while queue and len(seen) < self.max_pages:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            text, err = self._safe_fetch(url)
            if err:
                errors += 1
                continue
            found += self._harvest(hunt, result, url, text, "official_site")
            # follow same-domain links that look like contact/careers pages
            for href in _HREF_RE.findall(text):
                nxt = urllib.parse.urljoin(url, href.split("#")[0])
                if nxt.startswith("https://") and same_domain(host_of(nxt), domain) \
                        and any(h in nxt.lower() for h in _LINK_HINTS) and nxt not in seen:
                    queue.append(nxt)
        for page in inp.supplied_pages:
            if page.get("method") == "official_site" and same_domain(host_of(page.get("url", "")), domain):
                found += self._harvest(hunt, result, page["url"], page.get("text", ""), "official_site")
        if not result.checked:
            result.status, result.detail = "error", f"site unreachable ({errors} fetch errors)"
        else:
            result.status = "found" if found else "empty"
            result.detail = f"{len(result.checked)} page(s) read, {found} address(es)"
        return result

    def _m_web_search(self, hunt: EmailHunt, inp: FinderInput) -> MethodResult:
        c = inp.company
        queries = [f'"{c}" careers email', f'"{c}" HR recruitment email contact']
        if hunt.official_domain:
            queries.append(f'"@{hunt.official_domain}"')
        return self._search_method(hunt, "web_search", queries)

    def _supplied(self, hunt: EmailHunt, result: MethodResult, inp: FinderInput, name: str) -> int:
        n = 0
        for page in inp.supplied_pages:
            if page.get("method") == name and page.get("url"):
                n += self._harvest(hunt, result, page["url"], page.get("text", ""), name,
                                   hunt.official_domain or None)
        return n

    def _merge_supplied(self, hunt: EmailHunt, result: MethodResult, inp: FinderInput) -> MethodResult:
        n = self._supplied(hunt, result, inp, result.name)
        if n or (result.status == "skipped" and result.checked):
            result.status = "found" if n or result.status == "found" else "empty"
            result.detail = (result.detail + "; " if result.detail else "") + f"{n} from supplied pages"
        return result

    def _m_linkedin(self, hunt: EmailHunt, inp: FinderInput) -> MethodResult:
        c = inp.company
        result = self._search_method(
            hunt, "linkedin",
            [f'site:linkedin.com/company "{c}"', f'site:linkedin.com "{c}" recruiter OR "talent acquisition" email'],
            site_filter=lambda u: "linkedin.com" in host_of(u))
        return self._merge_supplied(hunt, result, inp)

    def _m_registry(self, hunt: EmailHunt, inp: FinderInput) -> MethodResult:
        c = inp.company
        queries = [f'site:{s} "{c}"' for s in self.registry_sites] + [f'"{c}" company registry email']
        result = self._search_method(hunt, "registry", queries)
        return self._merge_supplied(hunt, result, inp)

    def _m_mx(self, hunt: EmailHunt) -> MethodResult:
        result = MethodResult("mx")
        domains = sorted({e.address.rsplit("@", 1)[1] for e in hunt.emails})
        if not domains:
            result.status, result.detail = "empty", "no candidate addresses to check"
            return result
        cache: dict[str, Optional[bool]] = {}
        for d in domains:
            try:
                cache[d] = self.mx(d)
            except Exception:
                cache[d] = None
            result.checked.append(d)
        for e in hunt.emails:
            e.mx_ok = cache.get(e.address.rsplit("@", 1)[1])
        unknown = [d for d, v in cache.items() if v is None]
        live = [d for d, v in cache.items() if v]
        if unknown and not live:
            result.status, result.detail = "error", "MX lookup failed for: " + ", ".join(unknown)
        else:
            result.status = "found" if live else "empty"
            result.detail = f"live MX: {', '.join(live) or 'none'}" + (f"; unknown: {', '.join(unknown)}" if unknown else "")
        return result

    def _m_pattern(self, hunt: EmailHunt, inp: FinderInput) -> MethodResult:
        """Verify found addresses. Never generates new ones."""
        result = MethodResult("pattern")
        official = hunt.official_domain
        listing_host = host_of(inp.listing_url)
        for e in hunt.emails:
            domain = e.address.rsplit("@", 1)[1]
            on_official_page = bool(official) and same_domain(host_of(e.source_url), official)
            from_listing = e.method == "listing"
            domain_matches = bool(official) and same_domain(domain, official)
            if domain in FREE_MAIL:
                e.notes.append("free-mail address - only usable if the company itself publishes it; needs review")
            if official and _looks_like_lookalike(domain, official):
                e.notes.append(f"lookalike of {official} - possible impersonation; needs review")
            if e.mx_ok is False:
                e.notes.append("no MX record - address cannot receive mail")
            elif e.mx_ok is None:
                e.notes.append("MX not confirmed")
            ok_source = from_listing or (on_official_page and hunt.domain_confirmed)
            ok_domain = (domain_matches and hunt.domain_confirmed) or (from_listing and domain not in FREE_MAIL)
            e.verified = bool(ok_source and ok_domain and e.mx_ok is True
                              and not (official and _looks_like_lookalike(domain, official)))
            if not e.verified and not e.notes:
                if not hunt.domain_confirmed:
                    e.notes.append("official domain not confirmed")
                elif not ok_source:
                    e.notes.append("not published on the listing or the official site")
                elif not ok_domain:
                    e.notes.append("domain differs from the official domain")
        result.checked = [e.address for e in hunt.emails]
        n = len(hunt.verified())
        result.status = "found" if n else "empty"
        result.detail = f"{n} of {len(hunt.emails)} address(es) passed"
        return result

    # -- run
    def run(self, inp: FinderInput) -> EmailHunt:
        domain = inp.official_domain.lower().strip().removeprefix("www.").strip("/")
        hunt = EmailHunt(company=inp.company, official_domain=domain,
                         domain_confirmed=bool(domain) and inp.domain_confirmed)
        hunt.methods.append(self._m_listing(hunt, inp))
        hunt.methods.append(self._m_official_site(hunt, inp))
        hunt.methods.append(self._m_web_search(hunt, inp))
        hunt.methods.append(self._m_linkedin(hunt, inp))
        hunt.methods.append(self._m_registry(hunt, inp))
        hunt.methods.append(self._m_mx(hunt))
        hunt.methods.append(self._m_pattern(hunt, inp))
        if hunt.verified():
            hunt.status = "found"
        elif hunt.missing_methods():
            hunt.status = "incomplete"
        else:
            hunt.status = "no_verified_address"
        return hunt


def finder_from_config(email_finder_cfg: dict[str, Any] | None = None,
                       fetcher: Optional[Fetcher] = None) -> EmailFinder:
    cfg = email_finder_cfg or {}
    provider = str(cfg.get("search_provider", "duckduckgo")).lower()
    searcher: Optional[Searcher] = None
    if provider == "duckduckgo":
        searcher = duckduckgo_searcher(fetcher)
    elif provider == "searxng" and cfg.get("searxng_url"):
        searcher = searxng_searcher(str(cfg["searxng_url"]), fetcher)
    return EmailFinder(fetcher=fetcher, searcher=searcher,
                       max_pages=int(cfg.get("max_site_pages", 14)),
                       max_search_pages=int(cfg.get("max_search_pages", 4)),
                       registry_sites=cfg.get("registry_sites", ["opencorporates.com"]))
