# findmejob

Open-source, local-first AI job-search and application copilot.

findmejob turns one master CV and a plain preferences file into a repeatable pipeline. It works for any profession and any region: everything role-, country- or industry-specific lives in your configuration, not in the code.

> **Alpha software.** findmejob is early-stage and under active development. Try it with dummy or fictional data first - no real accounts, email credentials, or API keys - until you have reviewed the setup and the code. The local web UI has no authentication; never expose it to the internet. See [docs/safety-and-limitations.md](docs/safety-and-limitations.md).

1. **Find** roles from public job boards and feeds. Responses are cached with ETag/Last-Modified, so repeat runs only process what changed, and the same role found on several boards is merged into one record that keeps every source link. When a listing states its pay or prints a contact email in the description, both are captured on the role.
2. **Filter** them against your constraints: salary floor in your own currency, locations, industries, and anything you want excluded.
3. **Verify** the employer from its official site, LinkedIn and an independent operational signal, while discovering source-backed careers, ATS or contact routes. Re-check listings later with `findmejob refresh --verify` so expired roles drop out.
4. **Qualify** separately from discovery. Every lead is classified as strong, plausible/adjacent, insufficient-evidence, policy-review, stale, or reject. Only strong is actionable; unknown evidence never becomes a positive from keyword score. Requirement evidence remains grounded in your master CV.
5. **Tailor** your CV for each role, using only facts from your master CV. It never invents experience. Output is Markdown plus a designed, ATS-safe PDF. `findmejob cv` is the standalone CV builder: a tracked role, any pasted job ad, or one general profile CV - navy/gold designed PDF by default, optional photo.
6. **Reach a person.** A portal application is one route; a follow-up to a verified company address is the second. `findmejob emails` runs every discovery method - the listing, the official site's contact/careers pages, web search, LinkedIn, business registries, MX checks and pattern checks - and only reports "no verified address" when all of them ran and found nothing. It never guesses an address. See [docs/email-finder.md](docs/email-finder.md).
7. **Draft** a short, natural application email. The CV carries the detail.
8. **Apply** with a browser assistant that fills what it knows and stops to ask when it hits a CAPTCHA, a payment wall, an account-creation prompt, or a question your data cannot answer.
9. **Track** every role, status, decision and follow-up date in a local database, and gather everything for one application into a single pack (`findmejob pack`).

It is designed to be driven by chat through a coding agent you already use - Claude Code, Codex, or any tool-capable CLI agent - but every step is also a plain CLI command you can run yourself. No model lock-in: the core pipeline is deterministic Python, and LLM calls are optional and provider-pluggable. You do not need to be a developer: a guided setup writes your configuration from plain questions, and `findmejob doctor` tells you what is missing.

## Why it exists

Job hunting is repetitive: search ten sites, re-read your CV, rewrite the same email, fill the same forms, lose track of what you applied to. findmejob keeps the parts a machine is good at (searching, deduping, bookkeeping, formatting) and keeps you in charge of the parts that matter (what is true about you, where you want to work, and every final submit).

## Quickstart

Requires Python 3.10+. Core pipeline has zero required Python dependencies; PDF fonts are bundled.

```bash
git clone https://github.com/infattah/findmejob.git
cd findmejob
python -m pip install .      # regular, non-editable install

findmejob setup                      # guided: plain questions -> config.json
findmejob ingest --cv path/to/master_cv.md
findmejob doctor                     # checks your setup, says what is missing
findmejob search                     # pulls from your configured sources (cached)
findmejob triage                     # policy check + fit score + evidence report
findmejob tailor --job <id>          # tailored CV (Markdown + PDF) + email draft
findmejob cv --job <id>              # designed CV for a tracked role
findmejob cv --ad ad.txt             # personalized CV from any pasted job ad
findmejob cv --general               # one general profile CV, no job targeting
findmejob emails --job <id>          # verified contact email hunt (every method before "none")
findmejob emails --all               # hunt for every qualified role still missing one
findmejob pack --job <id>            # one folder with everything for that application
findmejob apply --job <id>           # browser-assisted apply (dry-run by default)
findmejob refresh --verify           # drop listings that have expired
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

- Guess or construct email addresses. Every address it uses was published on a public page, and that page is recorded.
- Invent experience, employers, numbers or qualifications. Tailoring only reorders and emphasizes facts already in your master CV, and a fidelity check flags anything that looks new.
- Bypass CAPTCHAs, paywalls, paid application portals, or account-creation flows. It pauses and asks you.
- Spend money or submit paid applications.
- Send email or click final submit without your explicit approval (configurable, off by default).
- Store secrets in the repo. API keys live in `.env`, which is gitignored.

See `docs/company-verification.md` for the evidence and route-discovery workflow, and `docs/safety-and-limitations.md` for the full list, including why universal auto-submit across every job site is not a goal.

## Repository layout

```
agents/        worker playbooks a coding agent follows (scout, analyst, tailor, applier, tracker)
docs/          architecture, runtimes, configuration, safety, per-agent usage guides
sample_data/   fictional master CV and sample jobs for the offline demo
src/findmejob/agent/     the persistent main agent + focused workers
src/findmejob/sources/   job board adapters (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, RSS, Remotive, JSON)
src/findmejob/render/    designed Unicode PDF CV renderer (stdlib-only; bundled open fonts)
src/findmejob/browser/   browser apply flow + safety guards (Playwright, optional)
src/findmejob/ui/        local web UI with chat (stdlib http.server)
tests/         offline unit tests (stdlib unittest, no network; PDF text-extraction
               tests skip when poppler-utils is not installed)
```

## License

MIT. See `LICENSE`.
