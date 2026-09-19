"""Agent contracts.

Every unit of work is an AgentTask: kind, payload, durable id. Workers return
an AgentResult. The main agent owns conversation and planning; workers never
talk to the user directly - they report results and needed decisions back to
the main agent, which batches them into the pending list.

Worker kinds:
  source    - pull roles from configured sources into the tracker
  verify    - re-check the role page and record evidence-backed company/route research
  tailor    - produce a tailored CV + short email draft
  apply     - browser-assisted application (dry-run unless approved)
  evidence  - collect screenshots/files for a job into the evidence folder
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentTask:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: int | None = None


@dataclass
class AgentResult:
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    needs_user: list[str] = field(default_factory=list)  # questions for the pending list
