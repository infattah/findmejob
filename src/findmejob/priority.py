"""Config-driven job priority engine.

Turns a user's own priority list into three things:

1. a ranking for tracked jobs (which role to look at / apply to first),
2. a wave-ordered search plan (title x location queries, best first),
3. a living list: new fitting titles can be added without code changes.

Everything comes from the ``priority`` section of config.json. The product
ships no opinion about roles, places or industries - the example config is a
placeholder. Knock-out rules (salary floor, sector exclusions, title
exclusions, locations) stay in ``policy`` and are applied before ranking.

Config shape (all keys optional except title_groups)::

    "priority": {
      "tiers": ["first", "high", "medium", "backup"],
      "title_groups": [
        {"name": "Data analysis", "tier": "first",
         "titles": ["data analyst", "analytics specialist"],
         "stretch_titles": ["head of analytics"]}
      ],
      "seniority": {"in_range": ["senior", "lead"], "stretch": ["director"]},
      "locations": [
        {"name": "Berlin", "match": ["berlin"]},
        {"name": "Remote (EU)", "match": ["remote - eu", "europe"], "remote": true}
      ],
      "remote_anywhere_rank": "last",
      "industries": {"prefer": ["consultancy"], "deprioritise": ["mining"]},
      "wave_order": "title_first",
      "unlisted_titles": "review"
    }
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .models import JobPosting
from .scoring import _target_phrase_in_title

DEFAULT_TIERS = ["first", "high", "medium", "backup"]
WAVE_ORDERS = {"title_first", "location_first"}
UNLISTED = {"review", "skip", "keep"}


class PriorityConfigError(ValueError):
    pass


@dataclass
class TitleGroup:
    name: str
    tier: str
    titles: list[str] = field(default_factory=list)
    stretch_titles: list[str] = field(default_factory=list)


@dataclass
class Location:
    name: str
    match: list[str] = field(default_factory=list)
    remote: bool = False


@dataclass
class TitleMatch:
    group: str
    tier: str
    tier_rank: int
    group_rank: int
    title: str
    stretch: bool


@dataclass
class JobPriority:
    job_id: str
    title: str
    company: str
    location: str
    wave: int | None
    tier: str | None
    group: str | None
    matched_title: str | None
    stretch: bool
    location_name: str | None
    location_rank: int | None
    industry: int  # +1 preferred, 0 neutral, -1 deprioritised
    seniority: str  # in_range | stretch | unspecified
    listed: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _clean_list(values: Any, where: str) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise PriorityConfigError(f"{where} must be a list of strings")
    out, seen = [], set()
    for v in values:
        v = " ".join(v.split())
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


@dataclass
class PriorityConfig:
    tiers: list[str]
    groups: list[TitleGroup]
    locations: list[Location]
    seniority_in_range: list[str]
    seniority_stretch: list[str]
    prefer: list[str]
    deprioritise: list[str]
    wave_order: str = "title_first"
    remote_anywhere_rank: str = "last"
    unlisted_titles: str = "review"

    @property
    def enabled(self) -> bool:
        return bool(self.groups)

    # ------------------------------------------------------------ loading
    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "PriorityConfig":
        raw = raw or {}
        if not isinstance(raw, dict):
            raise PriorityConfigError("priority must be an object")
        tiers = _clean_list(raw.get("tiers"), "priority.tiers") or list(DEFAULT_TIERS)
        tier_keys = [t.lower() for t in tiers]
        groups: list[TitleGroup] = []
        names = set()
        for i, g in enumerate(raw.get("title_groups") or []):
            if not isinstance(g, dict):
                raise PriorityConfigError(f"priority.title_groups[{i}] must be an object")
            name = str(g.get("name") or "").strip()
            if not name:
                raise PriorityConfigError(f"priority.title_groups[{i}] needs a name")
            if name.lower() in names:
                raise PriorityConfigError(f"duplicate title group name: {name}")
            names.add(name.lower())
            tier = str(g.get("tier") or tiers[0]).strip()
            if tier.lower() not in tier_keys:
                raise PriorityConfigError(
                    f"title group '{name}' has tier '{tier}', expected one of {tiers}")
            groups.append(TitleGroup(
                name=name, tier=tiers[tier_keys.index(tier.lower())],
                titles=_clean_list(g.get("titles"), f"{name}.titles"),
                stretch_titles=_clean_list(g.get("stretch_titles"), f"{name}.stretch_titles")))
        locations: list[Location] = []
        for i, loc in enumerate(raw.get("locations") or []):
            if isinstance(loc, str):
                loc = {"name": loc}
            if not isinstance(loc, dict) or not str(loc.get("name") or "").strip():
                raise PriorityConfigError(f"priority.locations[{i}] needs a name")
            name = str(loc["name"]).strip()
            match = _clean_list(loc.get("match"), f"location {name}.match") or [name]
            locations.append(Location(name=name, match=match, remote=bool(loc.get("remote"))))
        sen = raw.get("seniority") or {}
        ind = raw.get("industries") or {}
        wave_order = str(raw.get("wave_order") or "title_first")
        if wave_order not in WAVE_ORDERS:
            raise PriorityConfigError(f"priority.wave_order must be one of {sorted(WAVE_ORDERS)}")
        unlisted = str(raw.get("unlisted_titles") or "review")
        if unlisted not in UNLISTED:
            raise PriorityConfigError(f"priority.unlisted_titles must be one of {sorted(UNLISTED)}")
        rar = str(raw.get("remote_anywhere_rank") or "last")
        if rar not in {"last", "ignore"}:
            raise PriorityConfigError("priority.remote_anywhere_rank must be 'last' or 'ignore'")
        return cls(tiers=tiers, groups=groups, locations=locations,
                   seniority_in_range=_clean_list(sen.get("in_range"), "seniority.in_range"),
                   seniority_stretch=_clean_list(sen.get("stretch"), "seniority.stretch"),
                   prefer=_clean_list(ind.get("prefer"), "industries.prefer"),
                   deprioritise=_clean_list(ind.get("deprioritise"), "industries.deprioritise"),
                   wave_order=wave_order, remote_anywhere_rank=rar, unlisted_titles=unlisted)

    # ------------------------------------------------------------ queries
    def all_titles(self, include_stretch: bool = True) -> list[str]:
        out, seen = [], set()
        for g in self.groups:
            for t in g.titles + (g.stretch_titles if include_stretch else []):
                if t.lower() not in seen:
                    seen.add(t.lower())
                    out.append(t)
        return out

    def tier_rank(self, tier: str) -> int:
        return [t.lower() for t in self.tiers].index(tier.lower())

    def match_title(self, title: str) -> TitleMatch | None:
        """Best (highest tier, then earliest group, direct before stretch) match.

        Longer configured titles are tried first inside a group so
        "senior performance marketing manager" beats "marketing manager".
        """
        best: TitleMatch | None = None
        for gi, g in enumerate(self.groups):
            for stretch, titles in ((False, g.titles), (True, g.stretch_titles)):
                for t in sorted(titles, key=lambda s: -len(s.split())):
                    if _target_phrase_in_title(t, title):
                        cand = TitleMatch(g.name, g.tier, self.tier_rank(g.tier), gi, t, stretch)
                        if best is None or _match_key(cand) < _match_key(best):
                            best = cand
                        break
        return best

    def match_location(self, job: JobPosting) -> tuple[int | None, str | None]:
        loc = (job.location or "").lower()
        for i, l in enumerate(self.locations):
            if any(m.lower() in loc for m in l.match):
                if l.remote and not (job.remote or "remote" in loc):
                    continue
                return i, l.name
        if job.remote and self.remote_anywhere_rank == "last":
            return len(self.locations), "remote (anywhere)"
        return None, None

    def industry_score(self, job: JobPosting) -> tuple[int, str]:
        text = f"{job.company} {job.title} {job.description}".lower()
        for kw in self.prefer:
            if kw.lower() in text:
                return 1, f"preferred industry: {kw}"
        for kw in self.deprioritise:
            if kw.lower() in text:
                return -1, f"deprioritised industry: {kw}"
        return 0, ""

    def seniority(self, title: str) -> str:
        if any(_target_phrase_in_title(w, title) for w in self.seniority_stretch):
            return "stretch"
        if any(_target_phrase_in_title(w, title) for w in self.seniority_in_range):
            return "in_range"
        return "unspecified"

    def location_slots(self) -> int:
        return len(self.locations) + (1 if self.remote_anywhere_rank == "last" else 0) or 1

    def wave_number(self, tier_rank: int, loc_rank: int) -> int:
        """1-based wave. title_first: every location for tier 1, then tier 2..."""
        if self.wave_order == "title_first":
            return tier_rank * self.location_slots() + loc_rank + 1
        return loc_rank * len(self.tiers) + tier_rank + 1

    # ------------------------------------------------------------ outputs
    def prioritise(self, job: JobPosting) -> JobPriority:
        reasons: list[str] = []
        m = self.match_title(job.title)
        loc_rank, loc_name = self.match_location(job)
        ind, ind_reason = self.industry_score(job)
        sen = self.seniority(job.title)
        if m:
            reasons.append(f"{m.tier} tier - {m.group}" + (" (stretch title)" if m.stretch else "")
                           + f": matched '{m.title}'")
        else:
            reasons.append("title is not on your priority list")
        if loc_name:
            reasons.append(f"location #{loc_rank + 1}: {loc_name}")
        elif self.locations:
            reasons.append("location is not on your priority list")
        if ind_reason:
            reasons.append(ind_reason)
        if sen == "stretch":
            reasons.append("stretch seniority")
        wave = None
        if m and (loc_rank is not None or not self.locations):
            wave = self.wave_number(m.tier_rank, loc_rank or 0)
        return JobPriority(
            job_id=job.id, title=job.title, company=job.company, location=job.location,
            wave=wave, tier=m.tier if m else None, group=m.group if m else None,
            matched_title=m.title if m else None, stretch=bool(m and m.stretch),
            location_name=loc_name, location_rank=loc_rank, industry=ind, seniority=sen,
            listed=m is not None, reasons=reasons)

    def sort_key(self, p: JobPriority, fit_score: int | None = None) -> tuple:
        """Lower sorts first. Unranked jobs go last, never disappear."""
        big = 10 ** 6
        group_rank = next((i for i, g in enumerate(self.groups) if g.name == p.group), big)
        return (p.wave if p.wave is not None else big,
                1 if p.stretch or p.seniority == "stretch" else 0,
                -p.industry,
                group_rank,
                -(fit_score or 0),
                p.title.lower())

    def search_plan(self, include_stretch: bool = False) -> list[dict[str, Any]]:
        """Wave-ordered title x location queries."""
        locs: list[tuple[int, str | None]] = [(i, l.name) for i, l in enumerate(self.locations)]
        if not locs:
            locs = [(0, None)]
        elif self.remote_anywhere_rank == "last":
            locs.append((len(self.locations), "remote (anywhere)"))
        waves: dict[int, dict[str, Any]] = {}
        for g in self.groups:
            tr = self.tier_rank(g.tier)
            titles = g.titles + (g.stretch_titles if include_stretch else [])
            for li, lname in locs:
                w = self.wave_number(tr, li)
                entry = waves.setdefault(w, {"wave": w, "tier": g.tier, "location": lname,
                                             "queries": []})
                for t in titles:
                    entry["queries"].append({"title": t, "location": lname, "group": g.name})
        return [waves[k] for k in sorted(waves)]


def _match_key(m: TitleMatch) -> tuple:
    return (m.tier_rank, 1 if m.stretch else 0, m.group_rank)


# ---------------------------------------------------------------- helpers

def load_priority(cfg_raw: dict[str, Any]) -> PriorityConfig:
    return PriorityConfig.from_dict(cfg_raw.get("priority"))


def effective_role_keywords(cfg_raw: dict[str, Any]) -> list[str]:
    """role_keywords plus every direct title on the priority list (for scoring)."""
    base = list((cfg_raw.get("search") or {}).get("role_keywords") or [])
    try:
        pri = load_priority(cfg_raw)
    except PriorityConfigError:
        return base
    seen = {k.lower() for k in base}
    for t in pri.all_titles(include_stretch=True):
        if t.lower() not in seen:
            seen.add(t.lower())
            base.append(t)
    return base


def rank_jobs(pri: PriorityConfig, jobs: Iterable[tuple[JobPosting, int | None]]
              ) -> list[tuple[JobPriority, int | None]]:
    rows = [(pri.prioritise(job), score) for job, score in jobs]
    rows.sort(key=lambda r: pri.sort_key(r[0], r[1]))
    return rows


def add_title(config_path: Path, group: str, title: str, stretch: bool = False,
              tier: str | None = None) -> dict[str, Any]:
    """Living list: add a title to a group (creating the group if a tier is given).

    Returns {"added": bool, "group": name, "created_group": bool}. Writes
    config.json only when something changed. Validates the result first.
    """
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    pri_raw = dict(raw.get("priority") or {})
    groups = [dict(g) for g in pri_raw.get("title_groups") or []]
    title = " ".join(title.split())
    if not title:
        raise PriorityConfigError("title is empty")
    target = next((g for g in groups if str(g.get("name", "")).lower() == group.lower()), None)
    created = False
    if target is None:
        if not tier:
            raise PriorityConfigError(
                f"no title group named '{group}'. Pass --tier to create it.")
        target = {"name": group, "tier": tier, "titles": [], "stretch_titles": []}
        groups.append(target)
        created = True
    key = "stretch_titles" if stretch else "titles"
    existing = [t.lower() for g in groups for t in (g.get("titles") or []) + (g.get("stretch_titles") or [])]
    if title.lower() in existing:
        return {"added": False, "group": target["name"], "created_group": False,
                "reason": "already on the list"}
    target[key] = list(target.get(key) or []) + [title]
    pri_raw["title_groups"] = groups
    PriorityConfig.from_dict(pri_raw)  # validate before writing
    raw["priority"] = pri_raw
    config_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return {"added": True, "group": target["name"], "created_group": created}


def suggest_titles(pri: PriorityConfig, jobs: Iterable[tuple[JobPosting, int | None]],
                   min_score: int = 45, limit: int = 20) -> list[dict[str, Any]]:
    """Titles seen in tracked jobs that fit well but are not on the list yet.

    These are candidates only - a person decides whether to add them.
    """
    counts: dict[str, dict[str, Any]] = {}
    for job, score in jobs:
        if pri.match_title(job.title) is not None or (score or 0) < min_score:
            continue
        key = " ".join(job.title.lower().split())
        c = counts.setdefault(key, {"title": job.title, "seen": 0, "best_score": 0})
        c["seen"] += 1
        c["best_score"] = max(c["best_score"], score or 0)
    out = sorted(counts.values(), key=lambda c: (-c["best_score"], -c["seen"], c["title"].lower()))
    return out[:limit]
