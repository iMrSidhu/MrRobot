import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from shared.config import load_settings  # noqa: E402

KEYS = [
    "GITHUB_TOKEN", "DB_PATH", "REPO_CACHE_DIR", "VAULT_DIR", "OLLAMA_HOST",
    "SYNTHESIS_MODEL", "SECURITY_MODEL", "MIN_STARS", "SEARCH_KEYWORDS",
    "POLL_INTERVAL_SEC", "LLM_TIMEOUT_SEC", "CONTEXT_BUDGET_TOKENS",
]


def _clean_env(monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults(monkeypatch):
    _clean_env(monkeypatch)
    s = load_settings()
    assert s.github_token == ""
    assert s.db_path == "sentinel.db"
    assert s.repo_cache_dir == "/tmp/repo_cache"
    assert s.vault_dir == "vault"
    assert s.ollama_host == "http://localhost:11434"
    assert s.synthesis_model == "qwen2.5-coder:3b"
    assert s.security_model == "phi3:mini"
    assert s.min_stars == 1000
    assert s.search_keywords == ("ai agent", "harness", "autonomous", "llm framework")
    assert s.poll_interval_sec == 300
    assert s.llm_timeout_sec == 120
    assert s.context_budget_tokens == 6000


def test_env_overrides(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("MIN_STARS", "5000")
    monkeypatch.setenv("SECURITY_MODEL", "qwen2.5-coder:1.5b")
    monkeypatch.setenv("SEARCH_KEYWORDS", "agent, harness")
    monkeypatch.setenv("DB_PATH", "custom.db")
    s = load_settings()
    assert s.min_stars == 5000
    assert s.security_model == "qwen2.5-coder:1.5b"
    assert s.search_keywords == ("agent", "harness")
    assert s.db_path == "custom.db"
