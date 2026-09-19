# Tailor worker playbook

Job: produce a role-specific CV and a short application email.

- `findmejob tailor --job <id>` renders output/cvs/<name>_<id>.md plus a
  designed, ATS-safe PDF (<name>_<id>.pdf) and output/emails/<id>_email.txt.
  Attach the PDF when applying; keep the Markdown as the editable source.
- For a complete application folder (CV, PDF, fit report, email, verified
  route, checklist), use `findmejob pack --job <id>`.
- The render uses only master-CV facts: skills and bullets reordered by
  relevance to the role. Never add employers, titles, dates, metrics or
  skills that are not in the master CV.
- check_fidelity flags tokens in the output that never appear in the master
  CV. Treat every warning as a review item, not a nit.
- Emails stay short: role interest, one line of fit, CV attached, links,
  contact details. The CV carries the detail.
