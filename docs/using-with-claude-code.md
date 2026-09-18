# Using findmejob with Claude Code

1. Install and open the repo:

```bash
git clone https://github.com/infattah/findmejob.git
cd findmejob
claude
```

2. Say what you want in plain language: "set this up for me, here is my CV"
   or "find me growth marketing roles in Dubai".

Claude Code reads AGENTS.md and the playbooks in agents/, then runs the
findmejob CLI for you: ingest, search, triage, tailor, apply, status. You
approve submissions and answer application questions in chat; everything
else runs.

Tips:
- Give preferences once (salary floor, locations, exclusions); they are
  written to config.json and persist across sessions.
- If the browser apply pauses (CAPTCHA, account wall, unknown question),
  finish that step yourself, then say "continue".
- All state is in data/findmejob.db, so closing and reopening the session
  loses nothing.
