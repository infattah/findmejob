# Tailor worker playbook

Job: produce a role-specific CV and a short application email.

- `findmejob tailor --job <id>` renders output/cvs/<name>_<id>.md plus a
  designed, ATS-safe PDF (<name>_<id>.pdf) and output/emails/<id>_email.txt.
  Attach the PDF when applying; keep the Markdown as the editable source.
- For a complete application folder (CV, PDF, fit report, email, verified
  route, checklist), use `findmejob pack --job <id>`.
- `findmejob cv` is the standalone CV builder for one personalized CV on
  demand: `--job <id>` for a tracked role, `--ad <file|->` for a pasted job
  ad (add `--title`/`--company` so the filename reads well), or `--general`
  for an untargeted profile CV. It renders the designed navy/gold PDF by
  default (`--style classic` for the plain layout, `--photo me.jpg` or
  profile.photo in config.json to add a photo). Markdown is always written
  alongside as the editable source.
- The render uses only master-CV facts: skills and bullets reordered by
  relevance to the role. Never add employers, titles, dates, metrics or
  skills that are not in the master CV.
- check_fidelity flags tokens in the output that never appear in the master
  CV. Treat every warning as a review item, not a nit.
- Emails stay short: role interest, one line of fit, CV attached, links,
  contact details. The CV carries the detail.
