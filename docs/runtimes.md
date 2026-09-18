# Runtimes: choosing your agent or model

Run `findmejob runtimes` to see what your machine supports right now.

| runtime | kind | setup |
|---------|------|-------|
| claude-code | coding agent drives the CLI | install Claude Code, open repo |
| codex | coding agent drives the CLI | install Codex CLI, open repo |
| generic-cli-agent | any tool-capable coding agent | point it at AGENTS.md |
| anthropic | LLM API for chat/summaries | ANTHROPIC_API_KEY in .env, llm.provider=anthropic |
| openai | LLM API for chat/summaries | OPENAI_API_KEY in .env, llm.provider=openai |
| ollama | local model | ollama serve, llm.provider=ollama |
| builtin-deterministic | zero-setup command brain | nothing |

Selection:
- config: `"llm": {"provider": "anthropic"}` (or openai / ollama / none)
- CLI: `findmejob runtimes` to inspect; coding agents are chosen by which
  agent you open the repo with
- chat/UI: say "use runtime anthropic" or "use runtime ollama"

Graceful degradation: if the selected runtime lacks browser automation,
apply tasks pause with instructions instead of failing; if no LLM is
configured, conversation falls back to the deterministic command brain and
the full pipeline still works.
