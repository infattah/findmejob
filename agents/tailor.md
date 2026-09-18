# Tailor worker playbook

Job: produce a role-specific CV and a short application email.

- `findmejob tailor --job <id>` renders output/cvs/<name>_<id>.md and
  output/emails/<id>_email.txt.
- The render uses only master-CV facts: skills and bullets reordered by
  relevance to the role. Never add employers, titles, dates, metrics or
  skills that are not in the master CV.
- check_fidelity flags tokens in the output that never appear in the master
  CV. Treat every warning as a review item, not a nit.
- Emails stay short: role interest, one line of fit, CV attached, links,
  contact details. The CV carries the detail.
