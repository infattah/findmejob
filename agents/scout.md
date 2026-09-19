# Sourcing worker playbook

Job: find roles worth the user's time.

- Run the configured sources: `findmejob search`.
- A source that errors is reported, not fatal; the run continues.
- Policy runs inline: excluded titles, sectors, locations and sub-floor
  salaries are skipped automatically. Borderline cases go to needs_input
  with the exact reason.
- Responses are cached (ETag/Last-Modified + TTL); reruns only process
  changed sources. Duplicates across boards merge into one record that
  keeps every alternate source link - check the duplicate events.
- Run `findmejob refresh --verify` before big apply batches so expired
  listings drop out; ambiguous pages are left untouched.
- Before handing a role to apply, route it through the company-verification workflow. A
  verified official careers page or ATS can replace a dead aggregator listing; an unknown
  company stays unknown rather than being guessed safe or unsafe.

Adding sources: any public Greenhouse, Lever, Ashby, SmartRecruiters or
Workable board, RSS feed, Remotive search, or a local JSON list. See
docs/sources.md. When you have an official MCP connection (e.g. Indeed),
search through it and hand results to the jsonfile source. Optional
scrapers such as JobSpy stay outside the product: export to jsonfile,
never run them through the user's logged-in sessions, and verify every
lead before applying. Never scrape behind logins or bypass robots/CAPTCHA
to get listings.
