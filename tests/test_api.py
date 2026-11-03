"""Dashboard API + SSE tests - the FastAPI app is exercised offline via
TestClient (design Phase 5.2), with a live event write proving the stream
picks new events up within a second."""
import json
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from dashboard.api import create_app
from shared import db


def _db(tmp_path):
    conn = db.connect(tmp_path / "api.db")
    db.init_db(conn)
    return conn


def _client(tmp_path):
    path = tmp_path / "api.db"
    return TestClient(create_app(str(path))), path


def test_health_and_repos_list(tmp_path):
    conn = _db(tmp_path)
    db.add_repo_if_new(conn, 1, "acme/rover", "u", 1500)
    conn.close()
    client, _ = _client(tmp_path)
    assert client.get("/health").json()["status"] == "ok"
    rows = client.get("/repos").json()
    assert [r["name"] for r in rows] == ["acme/rover"]
    assert client.get("/repos/999").status_code == 404


def test_repo_detail_returns_synthesis_and_security_json(tmp_path):
    conn = _db(tmp_path)
    db.add_repo_if_new(conn, 1, "acme/rover", "u", 1500)
    synth = tmp_path / "acme_rover.synthesis.json"
    synth.write_text(json.dumps({"architecture": "cli tool", "capability_tags": ["ocr"]}), encoding="utf-8")
    # the DB stores the security JSON path explicitly (repositories.security_json_path)
    (tmp_path / "acme_rover.security.json").write_text(
        json.dumps({"findings": [{"severity": "HIGH", "file": "main.py", "line": 2,
                                  "description": "secret", "mitigation": "rotate"}]}),
        encoding="utf-8",
    )
    db.set_status(conn, 1, "DONE", synthesis_path=str(synth),
                  security_json_path=str(tmp_path / "acme_rover.security.json"),
                  security_report_path=str(tmp_path / "vault.md"))
    conn.close()

    body = _client(tmp_path)[0].get("/repos/1").json()
    assert body["repo"]["name"] == "acme/rover"
    assert body["synthesis"]["capability_tags"] == ["ocr"]
    assert body["security"]["findings"][0]["severity"] == "HIGH"


def test_repo_detail_missing_artifacts_are_null(tmp_path):
    conn = _db(tmp_path)
    db.add_repo_if_new(conn, 1, "acme/rover", "u", 1500)
    conn.close()
    body = _client(tmp_path)[0].get("/repos/1").json()
    assert body["synthesis"] is None and body["security"] is None


def _read_sse_ids(response, count):
    ids = []
    for line in response.iter_lines():
        if line.startswith("id: "):
            ids.append(int(line[4:]))
            if len(ids) == count:
                return ids
    return ids


def test_sse_streams_backlog(tmp_path):
    conn = _db(tmp_path)
    db.add_repo_if_new(conn, 1, "acme/rover", "u", 1500)
    for i in range(3):
        db.add_event(conn, 1, "DISCOVERED", f"event {i}")
    conn.close()
    with _client(tmp_path)[0].stream("GET", "/events/stream") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert _read_sse_ids(resp, 3) == [1, 2, 3]


def test_sse_resumes_from_last_event_id(tmp_path):
    conn = _db(tmp_path)
    db.add_repo_if_new(conn, 1, "acme/rover", "u", 1500)
    for i in range(3):
        db.add_event(conn, 1, "DISCOVERED", f"event {i}")
    conn.close()
    client, _ = _client(tmp_path)
    with client.stream("GET", "/events/stream", headers={"Last-Event-ID": "2"}) as resp:
        ids = _read_sse_ids(resp, 1)
    assert ids == [3]  # everything up to id 2 was already seen


def test_sse_delivers_new_event_within_one_second(tmp_path):
    conn = _db(tmp_path)
    db.add_repo_if_new(conn, 1, "acme/rover", "u", 1500)
    db.add_event(conn, 1, "DISCOVERED", "seed")
    conn.close()
    client, path = _client(tmp_path)

    def late_writer():
        time.sleep(0.3)
        writer = db.connect(path)
        db.add_event(writer, 1, "ANALYSIS_START", "arrives live")
        writer.close()

    threading.Thread(target=late_writer, daemon=True).start()
    start = time.monotonic()
    with client.stream("GET", "/events/stream") as resp:
        ids = _read_sse_ids(resp, 2)  # seed event + the live one
    assert ids == [1, 2]
    assert time.monotonic() - start < 1.0, "event took over a second to reach the stream"


def _report_client(tmp_path, report_path=None):
    """Client whose vault guard is scoped to tmp_path/vault."""
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    conn = _db(tmp_path)
    db.add_repo_if_new(conn, 1, "acme/rover", "u", 1500)
    if report_path is not None:
        db.set_status(conn, 1, "DONE", security_report_path=str(report_path))
    conn.close()
    return TestClient(create_app(str(tmp_path / "api.db"), str(vault)))


def test_report_endpoint_serves_vault_markdown(tmp_path):
    (tmp_path / "vault").mkdir()
    md = tmp_path / "vault" / "acme_rover.md"
    md.write_text("# acme/rover\n\n## Action items\n\n- [ ] rotate keys\n",
                  encoding="utf-8")
    body = _report_client(tmp_path, md).get("/repos/1/report").json()
    assert body["markdown"].startswith("# acme/rover")
    assert "rotate keys" in body["markdown"]
    assert body["path"].endswith("acme_rover.md")


def test_report_endpoint_blocks_traversal(tmp_path):
    secret = tmp_path / "secret.md"
    secret.write_text("TOP SECRET", encoding="utf-8")
    sneaky = tmp_path / "vault" / ".." / "secret.md"
    resp = _report_client(tmp_path, sneaky).get("/repos/1/report")
    assert resp.status_code == 400
    assert "TOP SECRET" not in resp.text


def test_report_endpoint_404_without_report(tmp_path):
    client = _report_client(tmp_path, None)
    assert client.get("/repos/1/report").status_code == 404
    assert client.get("/repos/999/report").status_code == 404
    # report path recorded but file already deleted -> 404, not 500
    gone = tmp_path / "vault" / "deleted.md"
    client2 = _report_client(tmp_path, gone)
    assert client2.get("/repos/1/report").status_code == 404
