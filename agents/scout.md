# Sourcing worker playbook

Job: find roles worth the user's time.

- Run the configured sources: `findmejob search`.
- A source that errors is reported, not fatal; the run continues.
- Policy runs inline: excluded titles, sectors, locations and sub-floor
  salaries are skipped automatically. Borderline cases go to needs_input
  with the exact reason.
- Dedupe is by URL/title+company hash; reruns are cheap and safe.

Adding sources: any public Greenhouse board, Lever board, Workable board,
RSS feed, Remotive search, or a local JSON list. See docs/sources.md.
Never scrape behind logins or bypass robots/CAPTCHA to get listings.
