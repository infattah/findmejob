# findmejob

Open-source, local-first AI job-search and application copilot.

findmejob turns one master CV and a plain preferences file into a repeatable pipeline:

1. **Find** roles from public job boards and feeds.
2. **Filter** them against your constraints: salary floor, locations, industries, and anything you want excluded.
3. **Score** fit against your real experience.
4. **Tailor** your CV for each role, using only facts from your master CV. It never invents experience.
5. **Draft** a short, natural application email. The CV carries the detail.
6. **Apply** with a browser assistant that fills what it knows and stops to ask when it hits a CAPTCHA, a payment wall, an account-creation prompt, or a question your data cannot answer.
7. **Track** every role, status, decision and follow-up date in a local database.

It is designed to be driven by chat through a coding agent you already use - Claude Code, Codex, or any tool-capable CLI agent - but every step is also a plain CLI command you can run yourself. No model lock-in: the core pipeline is deterministic Python, and LLM calls are optional and provider-pluggable.

## Why it exists

Job hunting is repetitive: search ten sites, re-read your CV, rewrite the same email, fill the same forms, lose track of what you applied to. findmejob keeps the parts a machine is good at (searching, deduping, bookkeeping, formatting) and keeps you in charge of the parts that matter (what is true about you, where you want to work, and every final submit).

## Quickstart

Requires Python 3.10+. Core pipeline has zero required dependencies.

```bash
git clone https://github.com/infattah/findmejob.git
cd findmejob
pip install -e .            # or just run: python -m findmejob ...

findmejob init                       # creates config.json and data/ scaffold
# edit config.json with your preferences
findmejob ingest --cv path/to/master_cv.md
findmejob search                     # pulls from your configured sources
findmejob triage                     # policy check + fit score
findmejob tailor --job <id>          # tailored CV + email draft in output/
findmejob apply --job <id>           # browser-assisted apply (dry-run by default)
findmejob status                     # tracker overview
```

Try the offline demo with fictional sample data:

```bash
scripts/demo.sh
```

## Two clients, one agent

findmejob is agent-powered. A persistent main agent owns your conversation,
preferences, plan, tracker and follow-through, and dispatches focused workers
for sourcing, verification, CV tailoring, browser applications and evidence
collection. You can talk to that same agent two ways, with shared state:

```bash
findmejob chat     # terminal chat
findmejob ui       # local web UI at http://127.0.0.1:8787 with chat, tracker,
                   # pending decisions, CV/evidence downloads and activity
```

Or let a coding agent drive it: open the repo in Claude Code, Codex, or any
tool-capable CLI agent and say "find me jobs". The agent reads `AGENTS.md`
and the playbooks in `agents/`, then runs the same CLI on your behalf. You
pick the runtime - Claude, OpenAI-compatible, a local model, or no model at
all (the core pipeline is deterministic Python). See `docs/runtimes.md` and
`docs/using-with-claude-code.md` / `docs/using-with-codex.md`.

## What it will not do

- Invent experience, employers, numbers or qualifications. Tailoring only reorders and emphasizes facts already in your master CV, and a fidelity check flags anything that looks new.
- Bypass CAPTCHAs, paywalls, paid application portals, or account-creation flows. It pauses and asks you.
- Spend money or submit paid applications.
- Send email or click final submit without your explicit approval (configurable, off by default).
- Store secrets in the repo. API keys live in `.env`, which is gitignored.

See `docs/safety-and-limitations.md` for the full list, including why universal auto-submit across every job site is not a goal.

## Repository layout

```
agents/        worker playbooks a coding agent follows (scout, analyst, tailor, applier, tracker)
docs/          architecture, runtimes, configuration, safety, per-agent usage guides
sample_data/   fictional master CV and sample jobs for the offline demo
src/findmejob/agent/     the persistent main agent + focused workers
src/findmejob/sources/   job board adapters (Greenhouse, Lever, Workable, RSS, Remotive, JSON)
src/findmejob/browser/   browser apply flow + safety guards (Playwright, optional)
src/findmejob/ui/        local web UI with chat (stdlib http.server)
tests/         offline unit tests (stdlib unittest, no network)
```

## License

MIT. See `LICENSE`.
