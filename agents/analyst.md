# Analyst worker playbook

Job: verify and judge roles before effort is spent.

- `findmejob` verify task re-fetches the role URL. Dead pages (404/410) are
  marked skipped; aggregator ghosts are common.
- Fit is scored deterministically from the master CV: skills, title
  keywords, context overlap, location/remote. See src/findmejob/scoring.py.
- Verify the employer and discover official application routes using the evidence rule in
  `docs/company-verification.md`. Preserve incomplete research as `unknown`; never guess
  contacts or reconstruct ATS links.
- Company research (what they do, size, funding) belongs in notes; use
  public pages only.
- Requirement gaps (years, domain, credentials) are facts to report, not
  reasons to inflate the CV. If the gap is a judgment call, it becomes a
  pending question for the user.
