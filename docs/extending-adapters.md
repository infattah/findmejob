# Extending findmejob

## Add a job source

1. Create src/findmejob/sources/mysite.py with a class that takes the spec
   dict and implements fetch() -> list[JobPosting]. Use
   sources/base.py helpers (http_json, http_text, strip_html).
2. Register it in sources/__init__.py build_source().
3. Add an offline fixture test in tests/ (mock the HTTP helper; tests never
   touch the network).

Only use public endpoints. No login scraping, no robots/CAPTCHA bypass.

## Add a worker

1. Write a function (payload, cfg, tracker) -> AgentResult in
   src/findmejob/agent/workers.py and register it in _WORKERS.
2. Enqueue it from the main agent or the CLI with tracker.enqueue_task.
3. Return needs_user questions for anything a human must decide; never ask
   the user directly from a worker.

## Add an LLM provider

Implement a generate(prompt) -> str closure in src/findmejob/llm.py
get_generate(). Keys come from environment variables only. The core
pipeline must keep working when the provider is absent or down.
