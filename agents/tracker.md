# Tracker worker playbook

Job: keep the record true.

- Every status change, application, pause and artifact is an event in
  data/findmejob.db.
- Statuses: new, shortlisted, blocked, needs_input, tailored, ready,
  applied, skipped, rejected.
- Pending questions are the user's batched decision list. One list, exact
  questions, oldest first.
- Learned preferences (salary floor, exclusions, target roles, runtime
  choice) are written to config.json and prefs, not kept in chat memory.
