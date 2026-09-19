"""Evidence-based company legitimacy and application-route verification.

The verifier stores findings; it does not pretend that a missing signal is a
negative one. Every positive claim and every usable route must cite a public
source URL. This keeps uncertain research as ``unknown`` and prevents guessed
email addresses or reconstructed ATS links from entering an application flow.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

ALLOWED_SIGNALS = {
    "official_website", "linkedin", "maps", "registry", "ats",
    "app_store", "review", "other",
}
ALLOWED_ROUTE_KINDS = {"careers", "ats", "recruiter", "email", "job_page"}


def _https_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme == "https" and bool(parsed.netloc)
    except ValueError:
        return False


def _email_domain(value: str) -> str:
    return value.rsplit("@", 1)[-1].lower() if "@" in value else ""


def _host(value: str) -> str:
    try:
        return (urlparse(value).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def _same_domain(left: str, right: str) -> bool:
    return left == right or left.endswith("." + right) or right.endswith("." + left)


@dataclass
class Evidence:
    kind: str
    url: str
    note: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        return cls(kind=str(data.get("kind", "")), url=str(data.get("url", "")),
                   note=str(data.get("note", "")))


@dataclass
class ApplicationRoute:
    kind: str
    value: str
    source_url: str
    label: str = ""
    verified: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApplicationRoute":
        return cls(kind=str(data.get("kind", "")), value=str(data.get("value", "")),
                   source_url=str(data.get("source_url", "")),
                   label=str(data.get("label", "")), verified=bool(data.get("verified", False)))


@dataclass
class CompanyVerification:
    company: str
    status: str = "unknown"  # unknown | verified | review
    official_domain: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    routes: list[ApplicationRoute] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompanyVerification":
        return cls(
            company=str(data.get("company", "")), status=str(data.get("status", "unknown")),
            official_domain=str(data.get("official_domain", "")),
            evidence=[Evidence.from_dict(x) for x in data.get("evidence", [])],
            routes=[ApplicationRoute.from_dict(x) for x in data.get("routes", [])],
            risks=[str(x) for x in data.get("risks", [])], notes=str(data.get("notes", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.status not in {"unknown", "verified", "review"}:
            errors.append("status must be unknown, verified, or review")
        if self.official_domain and any(c in self.official_domain for c in "/@ "):
            errors.append("official_domain must be a bare domain")
        for item in self.evidence:
            if item.kind not in ALLOWED_SIGNALS:
                errors.append(f"unsupported evidence kind: {item.kind}")
            if not _https_url(item.url):
                errors.append(f"evidence needs an HTTPS source URL: {item.url}")
        for route in self.routes:
            if route.kind not in ALLOWED_ROUTE_KINDS:
                errors.append(f"unsupported route kind: {route.kind}")
            if not _https_url(route.source_url):
                errors.append(f"route needs an HTTPS source URL: {route.value}")
            if route.kind == "email":
                if "@" not in route.value or not _email_domain(route.value):
                    errors.append(f"invalid email route: {route.value}")
                if route.verified and self.official_domain and not _same_domain(
                        _email_domain(route.value), self.official_domain.lower().removeprefix("www.")):
                    errors.append(f"email domain is inconsistent with official domain: {route.value}")
            elif not _https_url(route.value):
                errors.append(f"application route needs an HTTPS URL: {route.value}")
        if self.status == "verified":
            kinds = {item.kind for item in self.evidence}
            if "official_website" not in kinds:
                errors.append("verified status requires official_website evidence")
            if "linkedin" not in kinds:
                errors.append("verified status requires LinkedIn evidence")
            if not kinds.intersection({"registry", "ats", "app_store", "maps"}):
                errors.append("verified status requires registry, ATS, app-store, or Maps corroboration")
            if self.risks:
                errors.append("unresolved risks require review status")
        return errors

    def best_route(self) -> ApplicationRoute | None:
        """Return a source-backed route, preferring direct official paths."""
        usable = [route for route in self.routes if route.verified and not self._route_error(route)]
        order = {"job_page": 0, "ats": 1, "careers": 2, "recruiter": 3, "email": 4}
        return min(usable, key=lambda route: order[route.kind]) if usable else None

    def _route_error(self, route: ApplicationRoute) -> bool:
        probe = CompanyVerification(company=self.company, official_domain=self.official_domain,
                                    routes=[route])
        return bool(probe.validate())


def verification_from_json(data: dict[str, Any]) -> CompanyVerification:
    result = CompanyVerification.from_dict(data)
    errors = result.validate()
    if errors:
        raise ValueError("; ".join(errors))
    return result
