# Applier worker playbook

Job: drive the browser through an application, safely.

- `findmejob apply --job <id>` is a dry-run by default: navigate, guard
  checks, fill known fields, screenshot, stop before submit.
- Guards (src/findmejob/browser/guards.py) pause the run at: CAPTCHAs and
  human checks, anything that asks for payment, account-creation walls, and
  required fields the profile cannot answer (visa, salary, notice period,
  relocation, cover letter requirements).
- A pause records a pending question with the exact blocker. Do not retry
  in a loop; report and move to the next role.
- Final submit requires the user's approval for that application and
  autonomy.auto_apply=true in config. Otherwise leave the filled form open
  in the persistent browser profile for the user to review and submit.
- Evidence (screenshots) lands in output/screenshots and is attached to the
  job's event log.
