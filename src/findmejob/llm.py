"""Optional, provider-pluggable LLM access.

The core pipeline never requires an LLM. When one is configured it is used
for nicer summaries and freeform CV structuring only. Providers are called
over plain HTTPS with urllib, so there are no hard SDK dependencies.
Keys come from environment variables (see .env.example), never from the repo.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Callable

Generate = Callable[[str], str]


def get_generate(llm_cfg: dict[str, Any]) -> Generate | None:
    provider = (llm_cfg.get("provider") or "none").lower()
    model = llm_cfg.get("model") or ""
    if provider in ("", "none"):
        return None
    if provider == "ollama":
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        model = model or "llama3.1"

        def gen(prompt: str) -> str:
            req = urllib.request.Request(
                f"{host}/api/generate",
                data=json.dumps({"model": model, "prompt": prompt, "stream": False}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())["response"]

        return gen
    if provider == "anthropic":
        key = os.environ.get(llm_cfg.get("api_key_env", "ANTHROPIC_API_KEY"), "")
        if not key:
            return None
        model = model or "claude-sonnet-4-5"

        def gen(prompt: str) -> str:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps({
                    "model": model, "max_tokens": 2048,
                    "messages": [{"role": "user", "content": prompt}],
                }).encode(),
                headers={"Content-Type": "application/json",
                         "x-api-key": key, "anthropic-version": "2023-06-01"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            return "".join(b.get("text", "") for b in data.get("content", []))

        return gen
    if provider == "openai":
        key = os.environ.get(llm_cfg.get("api_key_env", "OPENAI_API_KEY"), "")
        if not key:
            return None
        model = model or "gpt-4o-mini"

        def gen(prompt: str) -> str:
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                }).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]

        return gen
    raise ValueError(f"unknown llm provider: {provider}")
