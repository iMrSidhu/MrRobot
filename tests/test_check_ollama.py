import pathlib
import sys

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import check_ollama as co  # noqa: E402


class Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, reachable=True, models=(), pullable=(), gen_fail=()):
        self.reachable = reachable
        self.models = set(models)
        self.pullable = set(pullable)
        self.gen_fail = set(gen_fail)
        self.pulled = []
        self.probed = []

    def get(self, url):
        if not self.reachable:
            raise httpx.ConnectError("down")
        assert url == "/api/tags"
        return Resp(200, {"models": [{"name": m} for m in sorted(self.models)]})

    def post(self, url, json=None, timeout=None):
        if url == "/api/pull":
            name = json["name"]
            self.pulled.append(name)
            return Resp(200 if name in self.pullable else 500)
        if url == "/api/generate":
            name = json["model"]
            self.probed.append(name)
            if name in self.gen_fail:
                return Resp(500)
            return Resp(200, {"response": "OK"})
        raise AssertionError(f"unexpected {url}")

    def close(self):
        pass


def _wire(monkeypatch, fake):
    monkeypatch.setenv("SYNTHESIS_MODEL", "test-a:1")
    monkeypatch.setenv("SECURITY_MODEL", "test-b:1")
    monkeypatch.setattr(co, "get_client", lambda *a, **k: fake)
    monkeypatch.setattr(co.shutil, "which", lambda name: None)  # no nvidia-smi in tests


def test_server_down_exits_nonzero_with_message(monkeypatch, capsys):
    _wire(monkeypatch, FakeClient(reachable=False))
    assert co.check() == 1
    assert "cannot reach Ollama" in capsys.readouterr().out


def test_happy_path(monkeypatch, capsys):
    fake = FakeClient(models={"test-a:1", "test-b:1"})
    _wire(monkeypatch, fake)
    assert co.check() == 0
    assert fake.probed == ["test-a:1", "test-b:1"]
    assert "OK: test-a:1 replied" in capsys.readouterr().out


def test_missing_models_without_pull(monkeypatch, capsys):
    _wire(monkeypatch, FakeClient(models={"test-a:1"}))
    assert co.check() == 2
    assert "not pulled: test-b:1" in capsys.readouterr().out


def test_missing_models_pulled_with_flag(monkeypatch):
    fake = FakeClient(models={"test-a:1"}, pullable={"test-b:1"})
    _wire(monkeypatch, fake)
    assert co.check(pull=True) == 0
    assert fake.pulled == ["test-b:1"]


def test_probe_failure_exits_nonzero(monkeypatch, capsys):
    _wire(monkeypatch, FakeClient(models={"test-a:1", "test-b:1"}, gen_fail={"test-b:1"}))
    assert co.check() == 3
    assert "FAIL" in capsys.readouterr().out
