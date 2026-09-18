# Architecture

findmejob is agent-powered, not a conventional app with a chat wrapper.
One persistent main agent owns the conversation and the plan; focused workers
do the task work; the CLI and the web UI are two clients of the same runtime.

```
                 +-------------------+-------------------+
                 |    CLI (chat)     |   local web UI    |
                 +---------+---------+---------+---------+
                           |                   |
                           v                   v
                    +-----------------------------+
                    |         Main agent          |  conversation, preferences,
                    |  src/findmejob/agent/       |  planning, pending batching,
                    |  main_agent.py              |  follow-through
                    +--------------+--------------+
                                   | enqueues AgentTasks
                    +--------------+--------------+
                    |   Worker queue (SQLite)     |  durable, retryable
                    +--+------+------+------+-----+
                       |      |      |      |
                  source  verify  tailor  apply  evidence
                       |      |      |      |
                    +--v------v------v------v--+
                    |  pipeline + sources +    |
                    |  policy/scoring/tailor + |
                    |  browser guards          |
                    +--------------+-----------+
                                   |
                    +--------------v-----------+
                    |  SQLite: jobs, events,   |
                    |  pending, prefs, tasks,  |
                    |  messages                |
                    +--------------------------+
```

## Agent contracts

- **AgentTask** (kind, payload, durable id). Kinds: source, verify, tailor,
  apply, evidence. See src/findmejob/agent/contracts.py.
- **AgentResult** (ok, summary, data, needs_user). needs_user questions go to
  the pending list; the main agent batches them for the user.
- Workers never talk to the user and never widen their own scope. The main
  agent relays decisions.

## Durable state

All state lives in data/findmejob.db: jobs, events, pending questions,
learned preferences, the worker task queue and the conversation log. Kill
the process mid-run and nothing is lost: queued tasks resume on the next
`findmejob tick`.

## Concurrency and retries

Task claiming is atomic (BEGIN IMMEDIATE + status transition), so two pumps
cannot double-run a task. A failed task retries up to 3 attempts, then is
marked failed with the error recorded. The web UI server is threaded; the
CLI pump is sequential.

## Runtimes and models

The core is deterministic Python: no model required. Model access is an
optional adapter (src/findmejob/llm.py: Anthropic, OpenAI-compatible,
Ollama). Coding agents (Claude Code, Codex, others) drive the same CLI via
AGENTS.md; nothing in the domain logic is provider-specific.
src/findmejob/runtimes.py detects what is available and reports
capabilities so the agent degrades gracefully: no browser support means
apply tasks pause early; no LLM means conversation stays command-based.

## Safety boundaries

The browser apply flow is dry-run by default. Guards stop the run at
CAPTCHAs, payment requests, account-creation walls and unknown required
fields. Final submit needs explicit approval per application and
autonomy.auto_apply=true. Tailoring can only reuse master-CV facts, and the
fidelity check flags anything that looks new.
