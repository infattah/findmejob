# Priority list

Your priority list tells findmejob which jobs matter most to you, so search,
review and applying all start with the best bets. It lives in the `priority`
section of `config.json`. Nothing about roles, places or industries is built
in - the example config uses placeholders you replace with your own.

It has three parts that you can mix freely:

1. **Title groups** - job titles bundled by theme, each with a tier
   (`first`, `high`, `medium`, `backup` by default, or your own tier names).
2. **Locations** - an ordered list of where you want to work.
3. **Tie-breakers** - industries you prefer or want ranked lower, and
   seniority words that mark a title as in range or a stretch.

Knock-out rules are separate and run first: salary floor, sector exclusions,
title exclusions and allowed locations stay in `policy`
(see docs/configuration.md). A job that fails a knock-out is skipped; the
priority list only orders what is left.

## Example

```json
"priority": {
  "tiers": ["first", "high", "medium", "backup"],
  "title_groups": [
    {"name": "Core role", "tier": "first",
     "titles": ["data analyst", "analytics specialist"],
     "stretch_titles": ["head of analytics"]},
    {"name": "Adjacent role", "tier": "high", "titles": ["data engineer"]}
  ],
  "seniority": {"in_range": ["senior", "lead"], "stretch": ["director"]},
  "locations": [
    {"name": "Your city", "match": ["your-city"]},
    {"name": "Remote in your region", "match": ["your-region"], "remote": true}
  ],
  "remote_anywhere_rank": "last",
  "industries": {"prefer": ["industry-you-prefer"],
                 "deprioritise": ["industry-you-rank-lower"]},
  "wave_order": "title_first",
  "unlisted_titles": "review"
}
```

## Fields

- `tiers` - ordered tier names, best first.
- `title_groups` - `name`, `tier`, `titles`, optional `stretch_titles`.
  Titles match in order, allowing a short word in between, so
  "marketing manager" matches "Marketing and Brand Manager"-style titles
  but "automation" alone never matches. Stretch titles are still worth
  applying to but rank after direct titles in the same wave.
- `seniority.in_range` / `seniority.stretch` - words that mark the level.
  A stretch-level title ranks after in-range titles in the same wave.
- `locations` - ordered. `match` is a list of substrings checked against
  the job's location (defaults to the name). `remote: true` means the entry
  only counts for remote jobs.
- `remote_anywhere_rank` - `last` (default) ranks remote jobs outside your
  list after all listed locations; `ignore` leaves them unranked.
- `industries.prefer` / `industries.deprioritise` - substrings checked
  against company, title and description. Used only to break ties.
- `wave_order` - `title_first` (default): the first tier across every
  location, then the next tier. `location_first`: every tier in your first
  location, then the next location.
- `unlisted_titles` - what happens to a job whose title is not on the list:
  `review` (default, kept and ranked last), `keep` (same, no flag) or
  `skip` (marked skipped at search time).

## Waves

Each tier x location pair is a wave. With `title_first` and two locations
plus remote, wave 1 is first-tier titles in location 1, wave 2 is
first-tier titles in location 2, wave 3 is first-tier remote, wave 4 is
second-tier titles in location 1, and so on. Inside a wave: direct titles
before stretches, preferred industries before neutral before deprioritised,
then group order, then fit score.

## Commands

```
findmejob priority plan [--stretch] [--json]   # wave-ordered search queries
findmejob priority rank [--limit N] [--listed-only] [--status S] [--json]
findmejob priority add --group "Core role" --title "BI analyst" [--stretch]
findmejob priority add --group "New group" --tier high --title "Some title"
findmejob priority suggest                     # fitting titles not on your list
findmejob doctor                               # checks the list is valid
```

## Driving search from the list

Any source that takes a search term (for example `remotive`) can run once
per list title, best wave first:

```json
{"type": "remotive", "search": "{priority}"}
```

`search.max_priority_queries` (default 20) caps how many queries one such
source may run.

## A living list

The list is meant to grow. `findmejob priority suggest` looks at tracked
jobs whose titles are not on your list but whose descriptions overlap
strongly with your CV, and shows them as candidates. You decide; nothing is
added on its own. `findmejob priority add` writes the title into
config.json after checking the result is valid.

Every title on the list also counts as a target role for fit scoring and
qualification, on top of `search.role_keywords`.
