"""Typed settings loaded from environment / .env, with design defaults (DESIGN.md §4–5)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()  # does not override already-set env vars


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    github_token: str
    db_path: str
    repo_cache_dir: str
    vault_dir: str
    ollama_host: str
    synthesis_model: str
    security_model: str
    min_stars: int
    search_keywords: tuple[str, ...]
    poll_interval_sec: int
    llm_timeout_sec: int
    context_budget_tokens: int
    ast_summary: bool


def load_settings() -> Settings:
    return Settings(
        github_token=_env("GITHUB_TOKEN", ""),
        db_path=_env("DB_PATH", "sentinel.db"),
        repo_cache_dir=_env("REPO_CACHE_DIR", "/tmp/repo_cache"),
        vault_dir=_env("VAULT_DIR", "vault"),
        ollama_host=_env("OLLAMA_HOST", "http://localhost:11434"),
        synthesis_model=_env("SYNTHESIS_MODEL", "qwen2.5-coder:3b"),
        security_model=_env("SECURITY_MODEL", "phi3:mini"),
        min_stars=int(_env("MIN_STARS", "1000")),
        search_keywords=tuple(
            k.strip()
            for k in _env(
                "SEARCH_KEYWORDS", "ai agent, harness, autonomous, llm framework"
            ).split(",")
            if k.strip()
        ),
        poll_interval_sec=int(_env("POLL_INTERVAL_SEC", "300")),
        llm_timeout_sec=int(_env("LLM_TIMEOUT_SEC", "120")),
        context_budget_tokens=int(_env("CONTEXT_BUDGET_TOKENS", "6000")),
        ast_summary=bool(int(_env("AST_SUMMARY", "1"))),
    )


# shortcut: import-time snapshot for convenience; call load_settings() when env may change
settings = load_settings()
