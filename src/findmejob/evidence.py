"""Deterministic, CV-grounded qualification evidence."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import JobPosting, Profile

_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_REQ_HEADER = re.compile(r"(requirements|qualifications|what you'?ll need|what we'?re looking for|who you are|about you|must[- ]haves?|you have|you bring)", re.I)
_SECTION_HEADER = re.compile(r"(responsibilities|what you'?ll do|about the role|about us|about (?:the )?company|company overview|benefits|perks)", re.I)
_PREFERRED_HEADER = re.compile(r"(nice[- ]to[- ]haves?|preferred|desirable|bonus|what would amaze us|good to have)", re.I)
_TOKEN = re.compile(r"[a-z][a-z0-9+#.]{2,}")
_YEARS = re.compile(r"(?<!\d)(\d{1,2})\s*(?:\+|plus)?\s*years?", re.I)
_HARD = re.compile(r"\b(must|required|requires?|minimum|at least|fluent|native|proficien(?:t|cy)|\d+\s*(?:\+|plus)?\s*years?|senior|head of|director|b2b|saas)\b", re.I)
_STOP = {"the", "and", "for", "with", "you", "your", "our", "are", "will", "that", "this", "have", "has", "from", "who", "what", "ability", "strong", "experience", "experienced", "years", "year", "work", "working", "team", "skills", "skill", "knowledge", "plus", "etc", "role", "job", "must", "should", "least", "related", "field", "equivalent", "proven", "track", "record", "familiarity", "understanding", "including", "such", "like", "able"}


_YEARS_AND = re.compile(r"(\d{1,2}\s*(?:\+|plus)?\s*years?(?:\s+(?:of|in)\s+\w+)*?)\s+and\s+", re.I)
_PREFERRED = re.compile(r"\b(nice[- ]to[- ]have|good[- ]to[- ]have|preferred|desirable|a plus|bonus|advantage)\b", re.I)
_REQ_MARKER = re.compile(r"(requires?|must|years?|experience|proficien\w*|degree|bachelor|master|diploma|fluent|native|certif\w*|knowledge|familiar\w*|expert\w*|ability to|skilled|skills)\b", re.I)
_GENERIC_YEAR = {"requires", "require", "required", "minimum"}
_DOMAIN_CUE = re.compile(r"(expertise|experience|knowledge|background|track record|domain)", re.I)
_COMPANY_HISTORY_YEARS = re.compile(
    r"(?ix)(?:"
    r"^\s*(?:for|over|more\s+than)\s+\d{1,3}\s*(?:\+|plus)?\s*years?\s*,"
    r"|\b(?:founded|established)\s+\d{1,3}\s*(?:\+|plus)?\s*years?\s+ago\b"
    # Company-history subjects are explicit organizations, never generic people
    # or candidate pronouns. This keeps natural JD requirements intact.
    r"|\b(?:we|the\s+(?:company|business|group|brand|platform|employer|organization)|"
    r"our\s+(?:company|business|group|brand|platform|organization)|"
    r"(?-i:[A-Z][\w&.-]+\s+[A-Z][\w&.-]+(?:\s+[A-Z][\w&.-]+){0,2})\b)"
    r".{0,45}\b(?:has|have|been|is|are|delivering|operating|serving|building|founded)\b"
    r".{0,30}\b(?:for|over|more\s+than)\s+\d{1,3}\s*(?:\+|plus)?\s*years?\b"
    r"|\b(?:we|the\s+(?:company|business|group|brand|platform|employer|organization)|"
    r"our\s+(?:company|business|group|brand|platform|organization)|"
    r"(?-i:[A-Z][\w&.-]+\s+[A-Z][\w&.-]+(?:\s+[A-Z][\w&.-]+){0,2})\b)"
    r".{0,20}\b(?:has|have|brings?|boasts?)\s+\d{1,3}\s*(?:\+|plus)?\s*years?"
    r"\s+of\s+experience\b"
    # A single-token proper company name is common (Acme, Google). Limit this
    # form to company-history predicates and explicitly reject human/candidate
    # subjects, rather than treating every capitalized word as an organization.
    r"|\b(?-i:(?!(?:Candidate|You|Person|Applicant|He|She|They)\b)[A-Z][\w&.-]+)"
    r"\s+(?:has|have)\s+(?:"
    r"\d{1,3}\s*(?:\+|plus)?\s*years?\s+of\s+experience\b"
    r"|(?:operated|served|delivered|built|traded)\b.{0,40}?\b(?:for\s+)?"
    r"(?:over|more\s+than)?\s*\d{1,3}\s*(?:\+|plus)?\s*years?\b)"
    r")"
)

_GENERIC_CAREER_YEARS = re.compile(
    r"(?i)\b\d{1,2}\s*(?:\+|plus)?\s*years?\s+(?:of\s+)?(?:professional |career |work )?experience\b"
)

_SUBDOMAIN_PATTERNS = {
    "growth_marketing": re.compile(r"(?i)\b(?:growth|performance) marketing\b|\bpaid (?:acquisition|media)\b|\b(?:cac|ltv|roas|cpl)\b"),
    "brand_campaign": re.compile(r"(?i)\bbrand (?:building|marketing|campaigns?)\b|\bintegrated (?:brand )?campaigns?\b|\bcampaign project management\b"),
}



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
    """Extract candidate requirements and retain preferred-section modality."""
    if not description: return []
    lines=[line.strip() for line in description.splitlines() if line.strip()]
    reqs=[]; mode="other"
    for line in lines:
        is_bullet=bool(_BULLET.match(line))
        # Headers must be actual short labels, not prose that happens to contain
        # words such as "experience" or "preferred".
        if not is_bullet and len(line) < 80 and _PREFERRED_HEADER.fullmatch(line.rstrip(": ")):
            mode="preferred"; continue
        if not is_bullet and len(line) < 80 and _REQ_HEADER.fullmatch(line.rstrip(": ")):
            mode="required"; continue
        if not is_bullet and len(line) < 80 and _SECTION_HEADER.fullmatch(line.rstrip(": ")):
            mode="excluded"; continue
        text=_BULLET.sub("",line).strip() if is_bullet else line
        looks_like=any(x in text.lower() for x in ("year","experience","proficien","degree","skill","knowledge","familiar","expert","fluent","native","certif","bachelor","master","diploma","ability to","required"))
        if mode in {"required","preferred"} and 12 <= len(text) <= 300 and not _COMPANY_HISTORY_YEARS.search(text):
            reqs.append(("preferred: " if mode=="preferred" else "")+text)
        elif mode == "other" and looks_like and 12 <= len(text) <= 300 and not _COMPANY_HISTORY_YEARS.search(text) and _REQ_MARKER.search(text):
            # Preserve legacy unheaded explicit requirements, but reject company
            # blurbs: they must contain an actual candidate requirement marker.
            reqs.append(text)
    if not reqs:
        for sent in re.split(r"(?<=[.!?])\s+",description):
            if _YEARS.search(sent) and 12 <= len(sent) <= 300 and not _COMPANY_HISTORY_YEARS.search(sent) and re.search(r"(?i)\b(?:you|candidate|applicant|required|qualification|experience)\b",sent): reqs.append(sent.strip())
    seen=set(); out=[]
    for req in reqs:
        key=_dedupe_key(req)
        if key not in seen: seen.add(key); out.append(req)
        if len(out)>=max_items: break
    return out




def _dedupe_key(text: str) -> str:
    # Include numeric thresholds so different seniority gates ("Requires 2+
    # years" vs "Requires 5+ years") stay distinct; a token-only key collapses
    # them because digits are not tokens.
    parts = sorted(_tokens(text)) + sorted(_YEARS.findall(text))
    return " ".join(parts)[:200] or text.lower()

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


def _preferred_clause(text: str) -> tuple[str, bool]:
    """Return (clean text, preferred) for a single clause or list atom.

    "good to have" wording belongs to the clause or atom that carries it,
    never to the whole comma sentence: a tail like "MBA good to have" must
    not soften a hard years or skill clause sharing the same sentence.
    """
    preferred = bool(_PREFERRED.search(text))
    return _PREFERRED.sub("", text).strip(" .;,:-"), preferred


def decompose_requirement(requirement: str) -> list[tuple[str, bool]]:
    """Split a compound requirement into independently checkable clauses.

    Returns (text, preferred) pairs. A years phrase stays bound to domain
    words in its own clause head and to an adjacent requirement sentence, but
    comma-list atoms and "years and ..." tails become standalone items so each
    is checked against its own CV evidence. Preferred status is decided per
    clause or atom, never per sentence, so a "good to have" tail can neither
    become a hard gap nor soften a hard clause beside it.
    """
    sentences = _bounded_clauses(requirement)
    # Protect numeric ranges from the generic hyphen separator.
    range_requirement = re.sub(
        r"(?<!\d)(\d{1,2})\s*[-–—]\s*(?=\d{1,2}\s*(?:\+|plus)?\s*years?)",
        r"\1__RANGE__",
        requirement,
    )
    # Every numeric tenure phrase owns its attached domain. Split at the join
    # before each later years phrase so one duration can never be borrowed by
    # another domain. If multiple phrases cannot be separated safely, the
    # matcher below fails the unresolved compound closed.
    # A range such as 3-5 years is one tenure phrase, not two atoms.
    structural_requirement = range_requirement.replace("__RANGE__", "-")
    year_occurrences = list(_YEARS.finditer(structural_requirement))
    if len(year_occurrences) > 1:
        atoms = [part.strip(" .;,:—-") for part in re.split(
            r"(?i)\s*(?:,|;|[—-]|\b(?:with|and|alongside|together\s+with|combined\s+with|plus|as\s+well\s+as)\b)\s*(?=\d{1,2}\s*(?:\+|plus)?\s*years?)",
            structural_requirement,
        ) if part.strip(" .;,:—-")]
        if len(atoms) == len(year_occurrences) and all(len(_YEARS.findall(atom)) == 1 for atom in atoms):
            return [(atom, False) for atom in atoms]
    # Language and non-language hard gates must remain independent across the
    # conjunctions commonly used in listings. Split only when each side keeps
    # a recognizable hard marker. Unrecognized joins remain a single compound,
    # which the language matcher refuses to early-return as strong.
    atoms = [part.strip(" .;,:—-") for part in re.split(
        r"(?i)\s*(?:[&/:;,]|[—-]|\b(?:and|with|alongside|together\s+with|combined\s+with|plus|as\s+well\s+as)\b)\s*",
        range_requirement,
    ) if part.strip(" .;,:—-")]
    atoms = [atom.replace("__RANGE__", "-") for atom in atoms]
    if len(atoms) > 1 and all(_HARD.search(atom) for atom in atoms):
        return [(atom, False) for atom in atoms]
    if len(sentences) <= 1 and "," not in requirement and not _PREFERRED.search(requirement):
        return [(requirement.strip(" .;,"), False)]
    items: list[tuple[str, bool]] = []
    consumed: set[int] = set()
    for idx, sent in enumerate(sentences):
        if idx in consumed:
            continue
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
            # Emit the years clause (its head keeps the domain words that
            # directly modify the years) and each independent tail atom, each
            # with its own preferred status.
            head_clean, head_preferred = _preferred_clause(head)
            items.append((head_clean, head_preferred))
            for atom in _list_atoms(sent):
                clean, atom_preferred = _preferred_clause(atom)
                if clean and _tokens(clean):
                    items.append((clean, atom_preferred))
        else:
            if _PREFERRED.search(sent) and "," in sent:
                # A preferred tail sharing a comma sentence with a hard clause
                # ("B2B SaaS experience required, MBA good to have") must not
                # soften the hard clause: split and judge each atom on its own.
                atoms = [part.strip(" .;,") for part in sent.split(",")]
            else:
                atoms = [sent]
            for atom in atoms:
                clean, preferred = _preferred_clause(atom)
                if not (_REQ_MARKER.search(clean) or preferred):
                    continue
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


def _required_years(text: str) -> int | None:
    range_match = re.search(r"(?<!\d)(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*(?:\+|plus)?\s*years?", text, re.I)
    if range_match:
        return int(range_match.group(1))
    return _max_years(text)


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
    # Marketing subdomains require coherent phrases, even when their individual
    # tokens overlap. This prevents "growth mindset and marketing" or unrelated
    # brand/campaign/project mentions from passing as domain evidence.
    frag_low = fragment.lower()
    if ("growth" in domain_terms or "performance" in domain_terms) and "marketing" in domain_terms:
        extras = domain_terms - {"growth", "performance", "marketing"}
        return bool(_SUBDOMAIN_PATTERNS["growth_marketing"].search(frag_low)) and extras <= fragment_tokens
    if "brand" in domain_terms and "marketing" in domain_terms:
        extras = domain_terms - {"brand", "marketing", "campaign", "campaigns", "project", "management"}
        return bool(_SUBDOMAIN_PATTERNS["brand_campaign"].search(frag_low)) and extras <= fragment_tokens
    ratio = overlap / len(domain_terms)
    return bool(overlap >= 1 if len(domain_terms) == 1 else overlap >= 2 and ratio >= .5)


def _domain_overlap(requirement: str, fragment: str) -> tuple[int, float]:
    req_tokens = _year_domain_tokens(requirement)
    if not req_tokens:
        return 0, 0.0
    overlap = len(req_tokens & _tokens(fragment))
    return overlap, overlap / len(req_tokens)


_LANG_LEVEL = r"fluent|professional working proficiency|working proficiency|professional proficiency|native|bilingual"
_LANG_MODS = r"(?:(?:both\s+)?(?:written|spoken)(?:\s+and\s+(?:written|spoken))?\s+)"
_LANG_PATTERNS = (
    # "spoken fluent English", "fluent in written English"
    re.compile(rf"(?i)\b(?P<mods1>{_LANG_MODS})?(?P<level>{_LANG_LEVEL})\s+(?:in\s+)?(?P<mods2>{_LANG_MODS})?(?P<language>[a-z]+)\b"),
    # "English written and spoken fluent", "English: fluent"
    re.compile(rf"(?i)\b(?P<language>[a-z]+)\s*[-:]?\s*(?P<mods1>{_LANG_MODS})?(?P<level>{_LANG_LEVEL})\b"),
)


def _language_phrases(text: str) -> list[tuple[str, str, set[str], tuple[int, int]]]:
    """Parse language, level, and modality from one locally bound phrase."""
    found: list[tuple[str, str, set[str], tuple[int, int]]] = []
    occupied: list[tuple[int, int]] = []
    for pattern in _LANG_PATTERNS:
        for match in pattern.finditer(text):
            span = match.span()
            if match.group("language").lower() in {"professional", "working", "written", "spoken", "both", "in"}:
                continue
            if any(span[0] < end and start < span[1] for start, end in occupied):
                continue
            mods = {value.lower() for value in re.findall(
                r"(?i)\b(written|spoken)\b",
                (match.groupdict().get("mods1") or "") + " "
                + (match.groupdict().get("mods2") or ""),
            )}
            found.append((
                match.group("language").lower(),
                match.group("level").lower(),
                mods,
                span,
            ))
            occupied.append(span)
    return sorted(found, key=lambda item: item[3][0])


def _match_language(requirement: str, profile: Profile, hard: bool) -> RequirementMatch | None:
    targets = _language_phrases(requirement)
    if not targets:
        return None
    # Never let one recognized language phrase hide another hard constraint.
    # Decomposition handles known conjunctions; any remaining text must be only
    # harmless requirement wording/punctuation or the compound stays unresolved.
    residual = requirement
    for _, _, _, (start, end) in reversed(targets):
        residual = residual[:start] + " " + residual[end:]
    residual = re.sub(r"(?i)\b(?:must|required|requirement|language|proficiency|in)\b", " ", residual)
    residual = re.sub(r"[\s:().,;/-]+", "", residual)
    if residual or len(targets) != 1:
        return None
    language, level, required_mods, _ = targets[0]
    candidates: list[tuple[str, str, set[str]]] = []
    for fragment in _profile_evidence_fragments(profile):
        for ev_language, ev_level, evidence_mods, _ in _language_phrases(fragment):
            if ev_language != language:
                continue
            if evidence_mods:
                expected = required_mods or {"written", "spoken"}
                if not expected <= evidence_mods:
                    continue
            if level in {"native", "bilingual"} and ev_level not in {"native", "bilingual"}:
                continue
            candidates.append((fragment, ev_level, evidence_mods))
    if not candidates:
        return RequirementMatch(requirement, "missing", [], hard)
    evidence = candidates[0][0]
    return RequirementMatch(
        requirement,
        "strong",
        [f"explicit language evidence: {evidence[:140]}"],
        hard,
    )


def _profession_anchor(tokens: set[str]) -> str | None:
    # Profession-level anchors can donate overall tenure only when the CV and
    # requirement share the same anchor. Subdomain evidence is still required.
    for anchor in ("marketing", "engineering", "sales", "design", "finance", "operations"):
        if anchor in tokens:
            return anchor
    return None



_PROFICIENCY_CUE = re.compile(r"(?i)\b(hands-on proficiency|proficiency|proficient|expertise)\b")
_NUMBER_WORD = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)"
_TENURE_PHRASE = re.compile(
    rf"(?i)(?:\b\d{{1,2}}\s*(?:\+|plus|or\s+more)?|\b{_NUMBER_WORD}\s*(?:plus|or\s+more)?)\s+years?\b"
)
_EXPLICIT_STRONG = re.compile(
    r"(?i)\b(?:certified|administrators?|admin|power\s+user|"
    r"daily\s+hands[- ]on\s+use|hands[- ]on\s+(?:use|experience)|"
    r"advanced\s+proficien(?:cy|t)|expert(?:ise)?)\b"
)
_WEAK_LEVEL = re.compile(
    r"(?i)\b(?:basic|limited|minimal|light|novic(?:e|es)|beginner(?:s)?|"
    r"introductor(?:y|ily)|high[- ]level|working\s+knowledge|"
    r"famili(?:ar|arity)|aware(?:ness)?|some|vague)\b"
)
_WEAK_FREQUENCY = re.compile(r"(?i)\b(?:occasional(?:ly)?|sometimes?|rarely|seldom)\b")
_WEAK_EXPOSURE = re.compile(
    r"(?i)\b(?:expos(?:ure|ed)|learn(?:ed|t|ing)?|stud(?:y|ied|ies|ying)|"
    r"courses?|coursework|train(?:ed|ing|ings)|attend(?:ed|ing|s)?|"
    r"explor(?:e|ed|es|ing|ation)|play(?:ed|ing|s)?|dabbl(?:e|ed|es|ing)|"
    r"shadow(?:ed|ing|s)?|interested)\b"
)
_NEGATION = re.compile(
    r"(?i)\b(?:no|none|lack(?:s|ed|ing)?|never|not|without|do not|does not|did not|"
    r"have not|has not|had not)\b"
)


def _normalized_evidence(text: str) -> str:
    normalized = text.lower().replace("’", "'")
    contractions = {
        "doesn't": "does not", "don't": "do not", "didn't": "did not",
        "haven't": "have not", "hasn't": "has not", "hadn't": "had not",
        "isn't": "is not", "wasn't": "was not", "weren't": "were not",
    }
    for source, target in contractions.items():
        normalized = normalized.replace(source, target)
    return re.sub(r"[^a-z0-9+#.]+", " ", normalized).strip()


def _local_claim_windows(normalized: str, component: str | None) -> list[str]:
    """Return bounded phrase windows around the claimed skill.

    Evidence strength belongs to the target claim, not the whole CV line. This
    keeps an unrelated negative/weak claim from suppressing a separate strong
    one while supporting order and punctuation variants around the target.
    """
    if not component:
        return [normalized]
    anchors = _tokens(component) - {"tools", "tool", "product", "experience"}
    words = normalized.split()
    windows: list[str] = []
    for idx, word in enumerate(words):
        if word in anchors:
            windows.append(" ".join(words[max(0, idx - 6):idx + 7]))
    return windows or [normalized]


_SHORTHAND_META = {
    "occasional", "occasionally", "sometimes", "rarely", "seldom",
    "used", "uses", "using", "worked", "works", "working", "with", "on",
    "touched", "touches", "touching", "administered", "administers",
    "administering", "administration", "operated", "operates", "operating",
    "handled", "handles", "handling", "experience", "none", "never", "not",
    "no", "without", "limited", "minimal", "light", "basic", "knowledge",
    "exposure", "trained", "training", "studied", "course", "coursework",
}
_CONTRAST = re.compile(r"(?i)\s*[,;:]?\s*\b(?:but|though|although|however|yet)\b\s*[,;:]?\s*")


def _has_different_target(clause: str, anchors: set[str]) -> bool:
    """Reject shorthand inheritance when the clause names another target."""
    content = _tokens(clause) - anchors - _SHORTHAND_META
    return bool(content)


def _claim_strength(claim: str) -> str:
    """Classify one target-bound claim; callers combine claims independently."""
    if _NEGATION.search(claim):
        return "negated"
    if (_WEAK_LEVEL.search(claim) or _WEAK_EXPOSURE.search(claim)
            or _WEAK_FREQUENCY.search(claim)):
        return "weak"
    return "strong"


def _evidence_strength(fragment: str, component: str | None = None) -> str:
    """Classify target claims independently and discard weak/negated claims."""
    # Contrast coordinators start a new claim even inside one sentence.
    # Leading subordinate contrast ("Although X, Y") ends at its comma.
    separated = re.sub(r"(?i)^\s*(?:although|though)\s+([^,]+),\s*", r"\1;", fragment)
    separated = _CONTRAST.sub(";", separated)
    raw_clauses = [part for part in re.split(r"[;.!?\n]+", separated) if part.strip()]
    # Question/answer shorthand belongs to the preceding claim.
    joined: list[str] = []
    for part in raw_clauses:
        if _normalized_evidence(part) == "none" and joined:
            joined[-1] += " none"
        else:
            joined.append(part)
    clauses = [_normalized_evidence(part) for part in joined]
    anchors = _tokens(component or "") - {"tools", "tool", "product", "experience"}
    claims: list[str] = []
    for idx, clause in enumerate(clauses):
        if anchors and not (anchors & _tokens(clause)):
            continue
        # Natural shorthand carries a named target into the immediately
        # following anchorless modifier/activity clause. Treat the pair as one
        # claim, so "HubSpot; occasionally administered" is weak rather than a
        # bare strong claim plus an orphaned modifier.
        if idx + 1 < len(clauses):
            following = clauses[idx + 1]
            following_has_anchor = bool(anchors & _tokens(following)) if anchors else False
            if (not following_has_anchor
                    and not _has_different_target(following, anchors)
                    and (_WEAK_FREQUENCY.search(following)
                         or _WEAK_LEVEL.search(following)
                         or _WEAK_EXPOSURE.search(following)
                         or _NEGATION.search(following))):
                clause = f"{clause} {following}"
        claims.extend(_local_claim_windows(clause, component))
    if not claims:
        claims = [_normalized_evidence(fragment)]
    strengths = [_claim_strength(claim) for claim in claims]
    # A separate strong target claim wins after weak/negated target claims are
    # discarded. Weak fragments never combine into a strong claim.
    if "strong" in strengths:
        return "strong"
    if "negated" in strengths:
        return "negated"
    return "weak"

def _compound_components(requirement: str) -> list[str]:
    """Return mandatory AND components for explicit proficiency compounds."""
    if _TENURE_PHRASE.search(requirement):
        return []
    if not _PROFICIENCY_CUE.search(requirement) or not re.search(r"(?i)(?:\band\b|[&/])", requirement):
        return []
    if re.search(r"(?i)\b(?:or|preferred|optional|nice[- ]to[- ]have|bonus)\b", requirement):
        return []
    body = _PROFICIENCY_CUE.sub("", requirement, count=1)
    body = re.sub(r"(?i)^\s*(?:with|in)\s+", "", body).strip(" .;,:-")
    parts = [part.strip(" .;,:-") for part in re.split(r"(?i)\s*(?:\band\b|[&/])\s*", body)]
    if any(_TENURE_PHRASE.search(part) for part in parts):
        return []
    return parts if len(parts) > 1 and all(_tokens(part) for part in parts) else []


def _component_explicitly_grounded(component: str, fragment: str) -> bool:
    want = _tokens(component) - {"tools", "tool", "product"}
    got = _tokens(fragment)
    if not want or _evidence_strength(fragment, component) != "strong":
        return False
    # Product analytics needs an explicit analytics/tool context, not unrelated
    # financial analytics or generic claims of tool use.
    if "analytics" in _tokens(component):
        if "analytics" not in got or not ({"product", "posthog", "ga4", "amplitude", "mixpanel"} & got):
            return False
    return want <= got or (want == {"analytics"} and "analytics" in got)


def _match_compound(requirement: str, profile: Profile, hard: bool) -> RequirementMatch | None:
    components = _compound_components(requirement)
    if not components:
        return None
    fragments = _profile_evidence_fragments(profile)
    evidence: list[str] = []
    for component in components:
        match = next((f for f in fragments if _component_explicitly_grounded(component, f)), None)
        if not match:
            return RequirementMatch(requirement, "missing", [], hard)
        evidence.append(f"{component}: {match[:120]}")
    return RequirementMatch(requirement, "strong", evidence, hard)

def _match_one(requirement: str, profile: Profile) -> RequirementMatch:
    hard = is_hard_requirement(requirement)
    language = _match_language(requirement, profile, hard)
    if language is not None:
        return language
    compound = _match_compound(requirement, profile, hard)
    if compound is not None:
        return compound
    req_years = _required_years(requirement)
    if req_years is not None:
        # Multiple tenure gates must have been atomized by decomposition. An
        # unresolved compound is never eligible for a strong years match.
        structural_requirement = re.sub(r"(?<!\d)\d{1,2}\s*[-–—]\s*(?=\d{1,2}\s*(?:\+|plus)?\s*years?)", "", requirement)
        if len(_YEARS.findall(structural_requirement)) != 1:
            return RequirementMatch(requirement, "missing", [], hard)
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
        # A CV may state total professional tenure once, then list the matching
        # domain and tools separately. Combine only an explicitly generic career
        # duration with independently bounded domain evidence. A duration tied to
        # consumer retail or another domain is never transferable.
        broad_profession = _year_domain_tokens(requirement)
        anchor = _profession_anchor(broad_profession)
        generic_numeric = [(years, fragment) for years, fragment in numeric
                           if _GENERIC_CAREER_YEARS.search(fragment)
                           or (anchor and anchor in _tokens(fragment))]
        if generic_numeric and domain_evidence:
            years, duration = max(generic_numeric, key=lambda item: item[0])
            return RequirementMatch(
                requirement, "strong",
                [f"CV states {years}+ years overall and matching domain evidence: "
                 f"{domain_evidence[0][:120]}"], hard)
        if domain_evidence:
            # Preserve recall when the CV proves the domain but does not attach a
            # trustworthy duration to it. Hard requirements still go to review.
            return RequirementMatch(requirement, "partial",
                                    [f"domain evidence without grounded duration: {domain_evidence[0][:140]}"], hard)
        return RequirementMatch(requirement, "missing", [], hard)
    # Spelled-out tenure belongs to the tenure matcher, not generic token
    # overlap. Until that matcher supports it, fail closed rather than borrowing
    # words such as "five" from an unrelated team-size statement.
    if _TENURE_PHRASE.search(requirement):
        return RequirementMatch(requirement, "missing", [], hard)
    req_tokens = _tokens(requirement)
    if not req_tokens:
        return RequirementMatch(requirement, "missing" if hard else "partial", [], hard)
    for skill in profile.skills:
        if _evidence_strength(skill, requirement) != "strong":
            continue
        skill_tokens = _tokens(skill)
        if skill_tokens and skill_tokens <= req_tokens:
            return RequirementMatch(requirement, "strong", [f"skill: {skill}"], hard)
    # A short decomposed clause is proven when every one of its content tokens
    # appears in a single bounded CV fragment.
    for fragment in _profile_evidence_fragments(profile):
        if _evidence_strength(fragment, requirement) != "strong":
            continue
        if req_tokens <= _tokens(fragment):
            return RequirementMatch(requirement, "strong", [f"evidence: {fragment[:160]}"], hard)
    best: tuple[int, str] = (0, "")
    for exp in profile.experiences:
        for bullet in [exp.role + " " + exp.company] + exp.bullets:
            if _evidence_strength(bullet, requirement) != "strong":
                continue
            overlap = len(req_tokens & _tokens(bullet))
            if overlap > best[0]:
                best = (overlap, bullet.strip())
    ratio = best[0] / len(req_tokens)
    if (best[0] >= 3 and ratio >= .5) or (best[0] >= 2 and ratio >= .8):
        return RequirementMatch(requirement, "strong", [f"experience: {best[1][:160]}"], hard)
    if not hard and best[0] >= 2 and ratio >= .3:
        return RequirementMatch(requirement, "partial", [f"related experience: {best[1][:160]}"], hard)
    return RequirementMatch(requirement, "missing", [], hard)


def evaluate_requirements(profile: Profile, job: JobPosting, max_items: int = 40) -> FitReport:
    """Evaluate every extracted requirement against bounded CV evidence.

    max_items bounds reported soft detail only: it can never hide a hard
    requirement or leave an extracted requirement without a single evaluated
    item. Pathological input is bounded upstream by extract_requirements: at
    most 12 distinct source requirements of at most 300 characters each are
    accepted. Within that finite set every hard decomposed clause is evaluated;
    there is no first-come global item truncation.
    """
    report = FitReport(job.title, job.company)
    seen: set[str] = set()
    for req in extract_requirements(job.description):
        represented = False
        for text, preferred in decompose_requirement(req):
            key = _dedupe_key(text)
            if key in seen:
                continue
            item = _match_one(text, profile)
            item.preferred = preferred
            if preferred:
                # Nice-to-have wording can never count as an unproven hard gap.
                item.hard = False
            if represented and not item.hard and len(report.items) >= max_items:
                # Surplus soft detail beyond the reporting bound may be
                # dropped; hard gaps and a requirement's first item may not.
                continue
            seen.add(key)
            report.items.append(item)
            represented = True
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
