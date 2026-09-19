"""Configuration loading. JSON only (stdlib), .env for secrets."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_NAME = "config.json"


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)
    root: Path = field(default_factory=Path.cwd)

    @property
    def profile(self) -> dict[str, Any]:
        return self.raw.get("profile", {})

    @property
    def search(self) -> dict[str, Any]:
        return self.raw.get("search", {})

    @property
    def policy(self) -> dict[str, Any]:
        return self.raw.get("policy", {})

    @property
    def autonomy(self) -> dict[str, Any]:
        a = {"auto_apply": False, "require_confirmation": True,
             "max_applications_per_run": 5, "never_pay": True,
             "never_create_accounts": True}
        a.update(self.raw.get("autonomy", {}))
        return a

    @property
    def llm(self) -> dict[str, Any]:
        return self.raw.get("llm", {"provider": "none"})

    @property
    def email(self) -> dict[str, Any]:
        return self.raw.get("email", {})

    @property
    def paths(self) -> dict[str, Any]:
        p = {"db": "data/findmejob.db", "output": "output",
             "browser_profile": "data/browser-profile"}
        p.update(self.raw.get("paths", {}))
        return p

    def resolve(self, rel: str) -> Path:
        path = Path(rel)
        return path if path.is_absolute() else self.root / path

    @property
    def db_path(self) -> Path:
        return self.resolve(self.paths["db"])

    @property
    def output_dir(self) -> Path:
        return self.resolve(self.paths["output"])


def load_env_file(root: Path) -> None:
    """Load KEY=VALUE lines from .env into os.environ (without overriding)."""
    env_path = root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def load_config(root: Path | None = None) -> Config:
    root = root or Path.cwd()
    load_env_file(root)
    cfg_path = root / DEFAULT_CONFIG_NAME
    if not cfg_path.exists():
        example = root / "config.example.json"
        if example.exists():
            cfg_path = example
        else:
            raise FileNotFoundError(
                f"No {DEFAULT_CONFIG_NAME} found in {root}. Run `findmejob init` first."
            )
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    return Config(raw=raw, root=root)


def scaffold(root: Path) -> list[str]:
    """Create config.json and directory scaffold. Returns created paths."""
    root.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    example = root / "config.example.json"
    target = root / DEFAULT_CONFIG_NAME
    if not target.exists():
        if example.exists():
            target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            target.write_text("{\n  \"profile\": {},\n  \"search\": {\"sources\": []},\n  \"policy\": {},\n  \"autonomy\": {},\n  \"llm\": {\"provider\": \"none\"}\n}\n", encoding="utf-8")
        created.append(str(target))
    for rel in ("data", "data/profile", "output", "output/cvs", "output/emails", "output/screenshots"):
        d = root / rel
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))
    env = root / ".env"
    if not env.exists():
        example_env = root / ".env.example"
        env.write_text(example_env.read_text(encoding="utf-8") if example_env.exists() else "", encoding="utf-8")
        created.append(str(env))
    return created
