# Configuration (config.json)

`findmejob setup` writes config.json by asking plain questions - no JSON
editing required. `findmejob init` instead copies config.example.json if
you prefer to edit by hand. JSON only; secrets never go here (they live in
.env). `findmejob doctor` checks the result and says what is missing.

## profile

- `master_cv` - path to your structured markdown master CV.
- `full_name`, `email`, `phone`, `links` - used to pre-fill forms and draft
  emails. Values in the CV win if both exist.
- `photo` - optional path to a JPEG photo, used by `findmejob cv` in the
  designed style (a `--photo` flag overrides it).

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
- `sector_exclusions` - your own list of business categories to avoid. Categories stay separate: for example `forex trading`, `money transfer`, `payment processing`, `payroll services`, `corporate payments`, and `card services` are not silent aliases of one another. Empty by
  default; the product ships no judgments.
- `title_exclude` - e.g. ["intern"].
- Fit scores are diagnostic ranking aids only. Actionability comes from the evidence-gated six-outcome qualification decision; there is no numeric score threshold that can make a role actionable. Legacy `min_fit_score` values are ignored and can be removed.

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

## Discovery input

Keep discovery broad: start with simple target role names or keywords, then add the
preferred location; work mode is optional. Do not copy detailed experience, salary,
legitimacy, language or restriction rules into source queries. Those checks run after
discovery so a narrow query does not hide otherwise suitable roles.

## Qualification and policy ordering

Remote is a work mode, not a location override. If `locations_include` names real
geographies, remote listings still require a matching hiring location; an unknown
or out-of-preference location is sent to review.

The evidence report marks explicit requirements such as years of experience,
required language, seniority and named domain experience as hard. A hard
requirement without direct CV evidence constrains qualification and sends the role
to review even when keyword overlap is high. Generic summary/education overlap is
not accepted as proof of a hard requirement.

Years-of-experience checks keep the number tied to its CV context. For a requirement
such as `5+ years of B2B SaaS demand generation`, an unrelated `9+ years in retail`
does not pass. A strong match needs a sufficient duration and matching domain terms
in the same CV fact. The matcher uses a conservative equivalence only for established
performance-marketing wording such as paid media and paid acquisition. It does not treat
generic digital marketing as equivalent to performance marketing without additional
matching evidence. If the CV clearly shows the domain but does not state a duration
there, the evidence is `partial` rather than discarded; hard requirements then pause
for user review. Generic years-only requirements can still use an explicit overall
years statement.

Fit score is always stored before policy questions are applied. Salary uncertainty
can change a row to `needs_input`, but it cannot erase ranking metadata.
