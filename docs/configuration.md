# Configuration (config.json)

`findmejob init` creates config.json from config.example.json. JSON only;
secrets never go here (they live in .env).

## profile

- `master_cv` - path to your structured markdown master CV.
- `full_name`, `email`, `phone`, `links` - used to pre-fill forms and draft
  emails. Values in the CV win if both exist.

## search

- `role_keywords` - titles you want, e.g. ["growth marketing", "performance
  marketing"]. Used for scoring.
- `sources` - list of source specs. See docs/sources.md for every type.

## policy

- `salary_floor` - yearly number in `currency`. Roles with a stated salary
  below the floor go to review; roles with no salary are flagged, not
  blocked.
- `locations_include` / `locations_exclude` - substring matches on the
  posting's location. Remote roles always pass location.
- `sector_exclusions` - your own list of keywords to avoid. Empty by
  default; the product ships no judgments.
- `title_exclude` - e.g. ["intern"].
- `min_fit_score` - 0-100; roles below it are parked, not shortlisted.

## autonomy

- `auto_apply` (default false) - allow final submit after approval.
- `require_confirmation` (default true) - always stop before submit.
- `max_applications_per_run` - cap for a single apply batch.
- `never_pay` (default true) - pause at any payment request.
- `never_create_accounts` (default true) - pause at account-creation walls.

## llm

- `provider`: none | anthropic | openai | ollama. Keys come from .env.
- `model` - optional override.

## paths

- `db`, `output`, `browser_profile` - where state, artifacts and the
  persistent browser profile live. All are gitignored.
