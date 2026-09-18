# Using findmejob with local models

findmejob's core needs no model at all: search, policy, scoring, tailoring,
email drafts, browser guards and the tracker are deterministic Python. The
built-in conversation brain is command-based and works offline.

If you want a local model for freeform chat and summarization:

```bash
ollama serve
ollama pull llama3.1
```

config.json:

```json
"llm": {"provider": "ollama", "model": "llama3.1"}
```

Capability note: local models vary in tool-use reliability. findmejob
therefore keeps tool execution deterministic (the CLI) instead of relying
on model-side function calling. The model adds prose; the pipeline does the
work. Check what your setup supports with `findmejob runtimes`.
