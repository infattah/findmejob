# Using findmejob with Codex CLI

1. Install and open the repo:

```bash
git clone https://github.com/infattah/findmejob.git
cd findmejob
codex
```

2. Say what you want: "set up findmejob with my CV and find roles".

Codex reads AGENTS.md (it also reads AGENTS.md-compatible instructions) and
drives the findmejob CLI: ingest, search, triage, tailor, apply, status.
The playbooks in agents/ define how each workflow runs and where it must
stop and ask.

Notes:
- The CLI is provider-agnostic: same commands, same state, same safety
  gates, whichever agent drives them.
- Browser apply needs the optional dependency:
  `pip install -e .[browser] && playwright install chromium`.
