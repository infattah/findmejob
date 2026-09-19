# Safety and limitations

## Hard boundaries

- **No invented facts.** Tailoring reuses only master-CV facts.
  check_fidelity flags output tokens absent from the master CV. It is a
  heuristic: review warnings, and review the CV before sending.
- **No CAPTCHA bypass.** Human checks pause the run. You solve them in the
  opened browser window, then resume.
- **No payments.** Any payment request pauses the run. findmejob never pays
  to apply (autonomy.never_pay).
- **No silent account creation.** Sites that demand a new account pause the
  run (autonomy.never_create_accounts) and the question joins your pending
  list.
- **No guessed employers or contacts.** Company verification preserves unknowns. Every usable application route must cite the public source where it was found.
- **No guessing on forms.** Visa, salary expectations, notice period,
  relocation, required cover letters: unknown required fields pause the run.
- **No surprise submits.** The apply flow is dry-run by default and stops
  before final submit unless you approve that application and enable
  autonomy.auto_apply.
- **Secrets stay local.** .env is gitignored; config.json holds no keys.

## Practical limitations

- **Universal auto-submit is not a goal.** Job sites change markup weekly
  and many sit behind logins or CAPTCHAs. findmejob optimizes for: discover
  broadly, prepare everything, pre-fill what is known, and hand you a
  review-ready form. Direct, reliable submission works on simpler hosted
  boards; elsewhere the pause-and-hand-off path is the intended flow.
- **ATS PDF/DOCX rendering is out of scope.** Tailored CVs are markdown;
  convert with your editor or pandoc.
- **Source coverage is adapter-based.** If a board has no public endpoint,
  use a jsonfile source for manual finds or extend an adapter.
- **The local UI has no auth.** It binds to 127.0.0.1 for single-user
  localhost use. Do not expose it on a network interface.
- **Salary parsing is best-effort** across currencies and periods; the floor
  check errs toward flagging for review rather than silently dropping roles.
