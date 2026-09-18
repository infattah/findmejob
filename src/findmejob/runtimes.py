"""Runtime selection: findmejob works under different agents and models.

Two ways to run findmejob:

1. Coding-agent driven (recommended): open this repo in Claude Code, Codex,
   or any tool-capable CLI agent. The agent reads AGENTS.md + agents/*.md and
   drives the CLI. Provider choice is yours - the playbooks are plain markdown
   and the CLI is plain Python, so nothing here is model-specific.

2. Standalone: the deterministic brain needs no model at all. For freeform
   chat and summarization you can point config.json at an LLM API
   (Anthropic, OpenAI-compatible, or a local Ollama model).

This module detects what is available and reports capabilities, so the main
agent can degrade gracefully: no browser support means apply tasks pause
early; no LLM means conversation stays command-based.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class RuntimeInfo:
    name: str
    kind: str  # cli-agent | api | local | builtin
    available: bool
    capabilities: dict[str, bool] = field(default_factory=dict)
    setup_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _has(binary: str) -> bool:
    return shutil.which(binary) is not None


def _playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def detect_runtimes() -> list[RuntimeInfo]:
    browser = _playwright_available()
    return [
        RuntimeInfo(
            "claude-code", "cli-agent", _has("claude"),
            {"chat": True, "tools": True, "browser": browser, "structured_output": True},
            "Install Claude Code, open this repo, say 'find me jobs'. "
            "It reads AGENTS.md and drives the findmejob CLI."),
        RuntimeInfo(
            "codex", "cli-agent", _has("codex"),
            {"chat": True, "tools": True, "browser": browser, "structured_output": True},
            "Install Codex CLI, open this repo, say 'find me jobs'. "
            "It reads AGENTS.md and drives the findmejob CLI."),
        RuntimeInfo(
            "generic-cli-agent", "cli-agent", True,
            {"chat": True, "tools": True, "browser": browser, "structured_output": False},
            "Any tool-capable coding agent works: point it at AGENTS.md and the CLI."),
        RuntimeInfo(
            "anthropic", "api", bool(os.environ.get("ANTHROPIC_API_KEY")),
            {"chat": True, "tools": False, "browser": False, "structured_output": True},
            "Set llm.provider=anthropic in config.json and ANTHROPIC_API_KEY in .env."),
        RuntimeInfo(
            "openai", "api", bool(os.environ.get("OPENAI_API_KEY")),
            {"chat": True, "tools": False, "browser": False, "structured_output": True},
            "Set llm.provider=openai in config.json and OPENAI_API_KEY in .env."),
        RuntimeInfo(
            "ollama", "local", _has("ollama"),
            {"chat": True, "tools": False, "browser": False, "structured_output": False},
            "Run `ollama serve`, set llm.provider=ollama and llm.model in config.json."),
        RuntimeInfo(
            "builtin-deterministic", "builtin", True,
            {"chat": True, "tools": True, "browser": browser, "structured_output": True},
            "No setup. Command-style conversation, full pipeline, zero keys."),
    ]


def select_runtime(cfg_llm_provider: str = "") -> RuntimeInfo:
    """Pick the best available runtime. Explicit provider config wins."""
    runtimes = {r.name: r for r in detect_runtimes()}
    explicit = (cfg_llm_provider or "").lower()
    if explicit in ("anthropic", "openai", "ollama") and runtimes.get(explicit) and runtimes[explicit].available:
        return runtimes[explicit]
    for name in ("claude-code", "codex", "anthropic", "openai", "ollama"):
        if runtimes[name].available:
            return runtimes[name]
    return runtimes["builtin-deterministic"]
