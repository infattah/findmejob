# Configuration (config.json)

`findmejob setup` writes config.json by asking plain questions - no JSON
editing required. `findmejob init` instead copies config.example.json if
you prefer to edit by hand. JSON only; secrets never go here (they live in
.env). `findmejob doctor` checks the result and says what is missing.

## profile

- `master_cv` - path to your structured markdown master CV.
- `full_name`, `email`, `phone`, `links` - used to pre-fill forms and draft
  emails. Values in the CV win if both exist.

## search

- `role_keywords` - titles you want, e.g. ["growth marketing", "performance
  marketing"]. Used for scoring.
- `sources` - list of source specs. See docs/sources.md for every type.
- `cache_ttl_seconds` (default 3600) - how long a fetched source response is
  reused before revalidation. 0 disables caching. See docs/sources.md.

## policy

- `salary_floor` - yearly number in `currency`. Roles with a stated salary
  below the floor go to review; roles with no salary are flagged, not
  blocked.
- `currency` - the base currency for salary comparisons (e.g. "USD", "EUR",
  "AED"). Any code works; nothing is region-specific.
- `exchange_rates` - optional map of currency code to its value in the base
  currency, e.g. {"AED": 0.27} when the base is USD. Only rates you supply
  are used. Comparison is strict: a salary whose currency is unknown ("$"
  alone is ambiguous, never assumed USD), whose pay period is unstated, or
  which has no configured rate goes to review with the reason - raw
  magnitudes are never compared across currencies or periods.
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

- `db`, `output`, `browser_profile`, `cache` - where state, artifacts, the
  persistent browser profile and the HTTP cache live. All are gitignored.
