import json

from fastapi.testclient import TestClient

from cli import DEFAULT_MODULES, parse_spiderfoot_stdout, sanitize_modules, stdout_excerpt
from main import app

SAMPLE_JSON = """[
{"type": "Account on External Site", "data": "GitHub (Category: coding)", "module": "sfp_accounts"},
{"type": "USERNAME", "data": "torvalds", "module": "sfp_accounts"}
]"""

client = TestClient(app)


def test_health_reports_missing_binary(monkeypatch):
    monkeypatch.setattr("main.sf_script_path", lambda: None)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json() == {"ok": False, "spiderfoot": False}


def test_health_ok_when_sf_present(monkeypatch, tmp_path):
    script = tmp_path / "sf.py"
    script.write_text("# fake\n", encoding="utf-8")
    monkeypatch.setattr("main.sf_script_path", lambda: script)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "spiderfoot": True}


def test_scan_rejects_missing_auth(monkeypatch):
    monkeypatch.setenv("SPIDERFOOT_RUNNER_TOKEN", "super-secret-token")
    r = client.post("/v1/scan", json={"target": "torvalds"})
    assert r.status_code == 401
    assert "bearer" in r.json()["detail"].lower()


def test_scan_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("SPIDERFOOT_RUNNER_TOKEN", "super-secret-token")
    r = client.post(
        "/v1/scan",
        json={"target": "torvalds"},
        headers={"Authorization": "Bearer nope"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid token"


def test_scan_rejects_when_token_unset(monkeypatch):
    monkeypatch.delenv("SPIDERFOOT_RUNNER_TOKEN", raising=False)
    r = client.post(
        "/v1/scan",
        json={"target": "torvalds"},
        headers={"Authorization": "Bearer anything"},
    )
    assert r.status_code == 503


def test_scan_runs_cli_off_thread_when_authorized(monkeypatch):
    monkeypatch.setenv("SPIDERFOOT_RUNNER_TOKEN", "super-secret-token")
    seen: dict = {}

    def fake_run(target, modules, timeout):
        seen["target"] = target
        seen["modules"] = modules
        seen["timeout"] = timeout
        return {
            "status": "ok",
            "target": target,
            "events": [{"type": "USERNAME", "data": target}],
            "stdout_excerpt": "[]",
            "error": None,
        }

    monkeypatch.setattr("main.run_spiderfoot", fake_run)
    r = client.post(
        "/v1/scan",
        json={"target": "torvalds", "modules": ["sfp_accounts"], "timeout": 90},
        headers={"Authorization": "Bearer super-secret-token"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["target"] == "torvalds"
    assert seen["timeout"] == 90
    assert seen["modules"] == ["sfp_accounts"]


def test_sanitize_modules_drops_breach_and_unknown():
    cleaned = sanitize_modules(["sfp_accounts", "sfp_haveibeenpwned", "not-a-module", ""])
    assert cleaned == ["sfp_accounts"]
    assert sanitize_modules(None) == list(DEFAULT_MODULES)
    assert sanitize_modules([]) == list(DEFAULT_MODULES)


def test_parse_spiderfoot_stdout_and_excerpt():
    events = parse_spiderfoot_stdout(SAMPLE_JSON)
    assert len(events) == 2
    assert events[0]["module"] == "sfp_accounts"
    truncated = SAMPLE_JSON.rsplit("},", 1)[0] + "}"
    assert parse_spiderfoot_stdout(truncated)
    assert stdout_excerpt("abc", limit=10) == "abc"
    assert stdout_excerpt("abcdefghijk", limit=4) == "abcd…"


def test_parse_ignores_non_json():
    assert parse_spiderfoot_stdout("") == []
    assert parse_spiderfoot_stdout("SpiderFoot starting…") == []
    blob = json.dumps({"type": "USERNAME", "data": "x"})
    assert parse_spiderfoot_stdout(blob) == [{"type": "USERNAME", "data": "x"}]
