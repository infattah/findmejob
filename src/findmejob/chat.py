"""Backward-compatible alias: the chat engine is the persistent main agent."""
from __future__ import annotations

from .agent.main_agent import MainAgent

ChatEngine = MainAgent
