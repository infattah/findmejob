"""Deterministic, CV-grounded qualification evidence."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import JobPosting, Profile

_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_REQ_HEADER = re.compile(r"(requirements|qualifications|what you'?ll need|what we'?re looking for|who you are|about you|must[- ]haves?|you have|you bring)", re.I)
_SECTION_HEADER = re.compile(r"(responsibilities|what you'?ll do|about the role|about us|benefits|perks|nice[- ]to[- ]haves?|preferred)", re.I)
_TOKEN = re.compile(r"[a-z][a-z0-9+#.]{2,}")
_YEARS = re.compile(r"(?<!\d)(\d{1,2})\s*(?:\+|plus)?\s*years?", re.I)
_HARD = re.compile(r"\b(must|required|requires?|minimum|at least|fluent|native|proficien(?:t|cy)|\d+\s*(?:\+|plus)?\s*years?|senior|head of|director|b2b|saas)\b", re.I)
_STOP = {"the", "and", "for", "with", "you", "your", "our", "are", "will", "that", "this", "have", "has", "from", "who", "what", "ability", "strong", "experience", "experienced", "years", "year", "work", "working", "team", "skills", "skill", "knowledge", "plus", "etc", "role", "job", "must", "should", "least", "related", "field", "equivalent", "proven", "track", "record", "familiarity", "understanding", "including", "such", "like", "able"}


_YEARS_AND = re.compile(r"(\d{1,2}\s*(?:\+|plus)?\s*years?(?:\s+(?:of|in)\s+\w+)*?)\s+and\s+", re.I)
_PREFERRED = re.compile(r"\b(nice[- ]to[- ]have|good[- ]to[- ]have|preferred|a plus|bonus|advantage)\b", re.I)
_REQ_MARKER = re.compile(r"(requires?|must|years?|experience|proficien\w*|degree|bachelor|master|diploma|fluent|native|certif\w*|knowledge|familiar\w*|expert\w*|ability to|skilled|skills)\b", re.I)
_GENERIC_YEAR = {"requires", "require", "required", "minimum"}
_DOMAIN_CUE = re.compile(r"(expertise|experience|knowledge|background|track record|domain)", re.I)


def _tokens(text: str) -> set[str]:
    # Period is valid inside tokens such as framework names, but sentence-final
    # punctuation must not turn "experience." into a fake domain term.
    tokens = {clean for raw in _TOKEN.findall(text.lower())
              if (clean := raw.strip(".")) and clean not in _STOP}
    # Small lexical normalization keeps ordinary CV wording aligned without
    # turning unrelated domains into matches.
    if "marketer" in tokens or "marketers" in tokens:
        tokens.add("marketing")
    return tokens


def extract_requirements(description: str, max_items: int = 12) -> list[str]:
    if not description:
        return []
    lines = [line.strip() for line in description.splitlines() if line.strip()]
    reqs: list[str] = []
    in_req = False
    for line in lines:
        if _REQ_HEADER.search(line) and len(line) < 120:
            in_req = True
            continue
        if _SECTION_HEADER.search(line) and len(line) < 120:
            in_req = False
            continue
        text = _BULLET.sub("", line).strip() if _BULLET.match(line) else line
        looks_like = in_req or any(x in text.lower() for x in ("year", "experience", "proficien", "degree", "skill", "knowledge", "familiar", "expert", "fluent", "native", "certif", "bachelor", "master", "diploma", "ability to", "required"))
        if looks_like and 12 <= len(text) <= 300:
            reqs.append(text)
    if not reqs:
        for sent in re.split(r"(?<=[.!?])\s+", description):
            if _YEARS.search(sent) and 12 <= len(sent) <= 300:
                reqs.append(sent.strip())
    seen: set[str] = set()
    out: list[str] = []
    for req in reqs:
        key = " ".join(sorted(_tokens(req)))[:200] or req.lower()
        if key not in seen:
            seen.add(key)
            out.append(req)
        if len(out) >= max_items:
            break
    return out




def _year_head(clause: str) -> str:
    """Keep only the words that directly modify a years phrase.

    Comma lists ("Requires 2+ years, Google Ads, ...") and "N years and X"
    tails name independent clauses, not the domain of the years themselves.
    """
    head = clause.split(",", 1)[0]
    match = _YEARS_AND.search(head)
    if match:
        head = head[:match.end(1)]
    return head


def _list_atoms(sentence: str) -> list[str]:
    """Return comma/"and" list atoms after the years head of a sentence."""
    if "," in sentence:
        rest = sentence.split(",", 1)[1]
        atoms = [part.strip(" .;,") for part in rest.split(",")]
    else:
        match = _YEARS_AND.search(sentence.split(",", 1)[0])
        if not match:
            return []
        atoms = [sentence[match.end():].strip(" .;,")]
    if atoms and re.search(r"\s+and\s+", atoms[-1], re.I):
        tail = atoms.pop()
        atoms.extend(part.strip(" .;,") for part in re.split(r"\s+and\s+", tail, flags=re.I))
    return [atom for atom in atoms if _tokens(atom)]


def decompose_requirement(requirement: str) -> list[tuple[str, bool]]:
    """Split a compound requirement into independently checkable clauses.

    Returns (text, preferred) pairs. A years phrase stays bound to domain
    words in its own clause head and to an adjacent requirement sentence, but
    comma-list atoms and "years and ..." tails become standalone items so each
    is checked against its own CV evidence. Preferred ("good to have") clauses
    are kept but can never count as hard gaps.
    """
    sentences = _bounded_clauses(requirement)
    if len(sentences) <= 1 and "," not in requirement and not _PREFERRED.search(requirement):
        return [(requirement, False)]
    items: list[tuple[str, bool]] = []
    consumed: set[int] = set()
    for idx, sent in enumerate(sentences):
        if idx in consumed:
            continue
        preferred = bool(_PREFERRED.search(sent))
        if _YEARS.search(sent):
            head = _year_head(sent).strip(" .;,")
            generic = not (_tokens(_YEARS.sub("", head)) - _GENERIC_YEAR)
            if generic:
                carry_idx = next((j for j, other in enumerate(sentences)
                                  if j != idx and _DOMAIN_CUE.search(other)
                                  and not _PREFERRED.search(other)), None)
                if carry_idx is not None:
                    # A generic "N years of experience" sentence shares its
                    # domain with an adjacent experience-domain sentence
                    # ("B2B SaaS demand generation expertise required"); keep
                    # them together so the years gate stays domain-bound.
                    # Independent qualifications (degrees, languages) are not
                    # carry sources and decompose into their own clauses.
                    items.append((requirement, False))
                    consumed.update(j for j, other in enumerate(sentences)
                                    if _DOMAIN_CUE.search(other) and not _PREFERRED.search(other))
                    continue
            if generic:
                items.append((head, preferred))
                items.extend((atom, preferred) for atom in _list_atoms(sent))
            else:
                # Domain words directly modify the years: keep the whole clause bound.
                items.append((sent, preferred))
        elif _REQ_MARKER.search(sent) or preferred:
            clean = _PREFERRED.sub("", sent).strip(" .;,")
            if clean and _tokens(clean):
                items.append((clean, preferred))
    return items or [(requirement, False)]


def is_hard_requirement(requirement: str) -> bool:
    return bool(_HARD.search(requirement))


@dataclass
class RequirementMatch:
    requirement: str
    status: str
    evidence: list[str] = field(default_factory=list)
    hard: bool = False
    preferred: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"requirement": self.requirement, "status": self.status, "evidence": self.evidence, "hard": self.hard, "preferred": self.preferred}


@dataclass
class FitReport:
    job_title: str
    company: str
    items: list[RequirementMatch] = field(default_factory=list)

    @property
    def strong(self) -> int:
        return sum(i.status == "strong" for i in self.items)

    @property
    def partial(self) -> int:
        return sum(i.status == "partial" for i in self.items)

    @property
    def missing(self) -> int:
        return sum(i.status == "missing" for i in self.items)

    @property
    def hard_missing(self) -> int:
        return sum(i.hard and i.status != "strong" for i in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {"job_title": self.job_title, "company": self.company, "strong": self.strong, "partial": self.partial, "missing": self.missing, "hard_missing": self.hard_missing, "items": [i.to_dict() for i in self.items]}


def _max_years(text: str) -> int | None:
    values = [int(x) for x in _YEARS.findall(text)]
    return max(values) if values else None


def _bounded_clauses(text: str) -> list[str]:
    """Split prose where separate claims stop sharing evidence context."""
    return [part.strip() for part in re.split(r"(?<=[.!?;])\s+|[;]", text)
            if part.strip()]


def _profile_evidence_fragments(profile: Profile) -> list[str]:
    """Return sentence/clause-bounded CV facts without context donation."""
    fragments: list[str] = []
    for prose in (profile.headline, profile.summary):
        fragments.extend(_bounded_clauses(prose))
    fragments.extend(profile.skills)
    for exp in profile.experiences:
        # A role/company heading is useful domain evidence on its own, but must
        # not be prepended to every bullet: that would lend its domain tokens to
        # an unrelated numeric duration in the bullet.
        context = f"{exp.role} {exp.company}".strip()
        fragments.append(context)
        for bullet in exp.bullets:
            for clause in _bounded_clauses(bullet):
                fragments.append(clause)
                # "did X for N years" explicitly ties the duration to this
                # experience entry. A bare "N years in other-domain" does not.
                if re.search(r"\bfor\s+\d{1,2}\s*(?:\+|plus)?\s*years?\b", clause, re.I):
                    fragments.append(f"{context}: {clause}")
    # Free-form CV lines can contain several sentences. Bound those sentences too.
    for line in profile.raw_text.splitlines():
        fragments.extend(_bounded_clauses(line))
    return [fragment for fragment in fragments if fragment]


def _year_domain_tokens(requirement: str) -> set[str]:
    # Bind years to the domain words that directly modify them. Comma-list
    # atoms and "years and ..." tails are independent clauses, not modifiers.
    # If the head is generic ("5+ years of experience"), carry the domain from
    # an adjacent requirement sentence so split wording remains one
    # domain-specific gate; responsibilities or blurb sentences never carry.
    clauses = _bounded_clauses(requirement)
    year_clause = next((part for part in clauses if _YEARS.search(part)), requirement)
    year_tokens = _tokens(_YEARS.sub("", _year_head(year_clause))) - _GENERIC_YEAR
    if year_tokens:
        return year_tokens
    adjacent_tokens: set[str] = set()
    for clause in clauses:
        if clause != year_clause and _DOMAIN_CUE.search(clause) and not _PREFERRED.search(clause):
            adjacent_tokens.update(_tokens(clause))
    return adjacent_tokens - _GENERIC_YEAR


def _grounded_domain(requirement: str, fragment: str) -> bool:
    domain_terms = _year_domain_tokens(requirement)
    fragment_tokens = _tokens(fragment)
    overlap = len(domain_terms & fragment_tokens)
    if not domain_terms:
        return False
    # "X or Y" names alternatives. One complete alternative plus the shared
    # domain word is sufficient (for example "growth marketing").
    if re.search(r"\bor\b", requirement, re.I) and "marketing" in domain_terms:
        alternatives = domain_terms - {"marketing"}
        return "marketing" in fragment_tokens and bool(alternatives & fragment_tokens)
    ratio = overlap / len(domain_terms)
    # A single distinctive term can ground a one-term domain (for example SEO).
    # Longer domain phrases need at least two matching terms and half the phrase.
    return overlap >= 1 if len(domain_terms) == 1 else overlap >= 2 and ratio >= .5


def _domain_overlap(requirement: str, fragment: str) -> tuple[int, float]:
    req_tokens = _year_domain_tokens(requirement)
    if not req_tokens:
        return 0, 0.0
    overlap = len(req_tokens & _tokens(fragment))
    return overlap, overlap / len(req_tokens)


def _match_one(requirement: str, profile: Profile) -> RequirementMatch:
    hard = is_hard_requirement(requirement)
    req_years = _max_years(requirement)
    if req_years is not None:
        fragments = _profile_evidence_fragments(profile)
        domain_terms = _year_domain_tokens(requirement)
        numeric = [(years, fragment) for fragment in fragments
                   if (years := _max_years(fragment)) is not None and years >= req_years]
        if not domain_terms and numeric:
            years, fragment = max(numeric, key=lambda item: item[0])
            return RequirementMatch(requirement, "strong",
                                    [f"CV explicitly states {years}+ years: {fragment[:140]}"], hard)
        grounded_numeric = [(years, fragment) for years, fragment in numeric
                            if _grounded_domain(requirement, fragment)]
        if grounded_numeric:
            years, fragment = max(grounded_numeric, key=lambda item: item[0])
            return RequirementMatch(requirement, "strong",
                                    [f"domain-matched experience: {fragment[:160]}"], hard)
        domain_evidence = [fragment for fragment in fragments
                           if _grounded_domain(requirement, fragment)]
        if domain_evidence:
            # Preserve recall when the CV proves the domain but does not attach a
            # trustworthy duration to it. Hard requirements still go to review.
            return RequirementMatch(requirement, "partial",
                                    [f"domain evidence without grounded duration: {domain_evidence[0][:140]}"], hard)
        return RequirementMatch(requirement, "missing", [], hard)
    req_tokens = _tokens(requirement)
    if not req_tokens:
        return RequirementMatch(requirement, "missing" if hard else "partial", [], hard)
    for skill in profile.skills:
        skill_tokens = _tokens(skill)
        if skill_tokens and skill_tokens <= req_tokens:
            return RequirementMatch(requirement, "strong", [f"skill: {skill}"], hard)
    # A short decomposed clause is proven when every one of its content tokens
    # appears in a single bounded CV fragment.
    for fragment in _profile_evidence_fragments(profile):
        if req_tokens <= _tokens(fragment):
            return RequirementMatch(requirement, "strong", [f"evidence: {fragment[:160]}"], hard)
    best: tuple[int, str] = (0, "")
    for exp in profile.experiences:
        for bullet in [exp.role + " " + exp.company] + exp.bullets:
            overlap = len(req_tokens & _tokens(bullet))
            if overlap > best[0]:
                best = (overlap, bullet.strip())
    ratio = best[0] / len(req_tokens)
    if (best[0] >= 3 and ratio >= .5) or (best[0] >= 2 and ratio >= .8):
        return RequirementMatch(requirement, "strong", [f"experience: {best[1][:160]}"], hard)
    if not hard and best[0] >= 2 and ratio >= .3:
        return RequirementMatch(requirement, "partial", [f"related experience: {best[1][:160]}"], hard)
    return RequirementMatch(requirement, "missing", [], hard)


def evaluate_requirements(profile: Profile, job: JobPosting, max_items: int = 20) -> FitReport:
    report = FitReport(job.title, job.company)
    clauses: list[tuple[str, bool]] = []
    for req in extract_requirements(job.description):
        clauses.extend(decompose_requirement(req))
    seen: set[str] = set()
    for text, preferred in clauses:
        key = " ".join(sorted(_tokens(text)))[:200] or text.lower()
        if key in seen:
            continue
        seen.add(key)
        item = _match_one(text, profile)
        item.preferred = preferred
        if preferred:
            # Nice-to-have wording can never count as an unproven hard gap.
            item.hard = False
        report.items.append(item)
        if len(report.items) >= max_items:
            break
    return report


def render_report_markdown(report: FitReport, score: int | None = None, score_reasons: list[str] | None = None) -> str:
    lines = [f"# Fit report: {report.job_title} @ {report.company}", ""]
    if score is not None:
        lines.append(f"Keyword fit score: {score}/100")
    lines += [f"Requirements: {report.strong} strong, {report.partial} partial, {report.missing} missing (of {len(report.items)} found)", f"Hard requirements not proven: {report.hard_missing}", ""]
    if score_reasons:
        lines += ["Score reasons:"] + [f"- {r}" for r in score_reasons] + [""]
    if not report.items:
        lines += ["No structured requirements found; read the listing before relying on the keyword score.", ""]
        return "\n".join(lines)
    icon = {"strong": "[strong]", "partial": "[partial]", "missing": "[MISSING]"}
    for item in report.items:
        flags = (" [HARD]" if item.hard else "") + (" [preferred]" if item.preferred else "")
        lines.append(f"- {icon[item.status]}{flags} {item.requirement}")
        lines += [f"    evidence: {ev}" for ev in item.evidence]
    lines += ["", "Missing means the master CV shows no evidence for the requirement - it says nothing about the person.", ""]
    return "\n".join(lines)
