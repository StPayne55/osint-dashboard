import asyncio
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.detect import build_query
from app.scanners import all_scanners
from app.scanners.spiderfoot_scan import (
    SpiderFootScanner,
    derive_target,
    events_to_findings,
    parse_spiderfoot_stdout,
    remote_configured,
    sf_script_path,
)


@pytest.fixture(autouse=True)
def _clear_runner_env(monkeypatch):
    monkeypatch.delenv("SPIDERFOOT_URL", raising=False)
    monkeypatch.delenv("SPIDERFOOT_RUNNER_TOKEN", raising=False)

SAMPLE_JSON = """[
{"type": "Account on External Site", "data": "GitHub (Category: coding)\\n<SFURL>https://github.com/torvalds</SFURL>", "module": "sfp_accounts", "source": "torvalds"},
{"type": "SOCIAL_MEDIA", "data": "Twitter: https://twitter.com/torvalds ", "module": "sfp_social", "source": "https://twitter.com/torvalds"},
{"type": "USERNAME", "data": "torvalds", "module": "sfp_accounts", "source": "torvalds"},
{"type": "Email Address", "data": "linus@example.com", "module": "sfp_gravatar", "source": "torvalds"},
{"type": "Account on External Site", "data": "Instagram (Category: social)\\n<SFURL>https://instagram.com/</SFURL>", "module": "sfp_accounts", "source": "torvalds"},
{"type": "Hacked Email Address", "data": "linus@example.com", "module": "sfp_haveibeenpwned", "source": "linus@example.com"},
{"type": "EMAILADDR_COMPROMISED", "data": "pwned@example.com", "module": "sfp_haveibeenpwned", "source": "pwned@example.com"}
]"""


def test_spiderfoot_registered_and_abstract_phone_is_not():
    ids = [s.id for s in all_scanners()]
    assert "spiderfoot" in ids
    assert "abstract_phone" not in ids


def test_unavailable_when_binary_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SPIDERFOOT_HOME", str(tmp_path / "missing"))
    monkeypatch.setenv("SPIDERFOOT_ENABLED", "1")
    scanner = SpiderFootScanner()
    assert sf_script_path() is None
    assert scanner.available() is False
    result = asyncio.run(scanner.run(build_query("torvalds")))
    assert result.status.status == "unavailable"
    assert result.findings == []


def test_disabled_by_default_even_if_binary_present(monkeypatch, tmp_path):
    home = tmp_path / "sf"
    home.mkdir()
    (home / "sf.py").write_text("# fake\n", encoding="utf-8")
    monkeypatch.setenv("SPIDERFOOT_HOME", str(home))
    monkeypatch.delenv("SPIDERFOOT_ENABLED", raising=False)
    from app.scanners.spiderfoot_scan import spiderfoot_enabled

    assert spiderfoot_enabled() is False
    scanner = SpiderFootScanner()
    assert scanner.available() is False
    result = asyncio.run(scanner.run(build_query("torvalds")))
    assert result.status.status == "unavailable"
    assert "disabled" in (result.status.error or result.status.summary).lower()


def test_blank_env_is_disabled(monkeypatch, tmp_path):
    home = tmp_path / "sf"
    home.mkdir()
    (home / "sf.py").write_text("# fake\n", encoding="utf-8")
    monkeypatch.setenv("SPIDERFOOT_HOME", str(home))
    monkeypatch.setenv("SPIDERFOOT_ENABLED", "")
    from app.scanners.spiderfoot_scan import spiderfoot_enabled

    assert spiderfoot_enabled() is False
    assert SpiderFootScanner().available() is False


def test_disabled_even_if_binary_present(monkeypatch, tmp_path):
    home = tmp_path / "sf"
    home.mkdir()
    (home / "sf.py").write_text("# fake\n", encoding="utf-8")
    monkeypatch.setenv("SPIDERFOOT_HOME", str(home))
    monkeypatch.setenv("SPIDERFOOT_ENABLED", "0")
    scanner = SpiderFootScanner()
    assert scanner.available() is False
    result = asyncio.run(scanner.run(build_query("torvalds")))
    assert result.status.status == "unavailable"
    assert "disabled" in (result.status.error or "")


def test_available_when_sf_py_present(monkeypatch, tmp_path):
    home = tmp_path / "sf"
    home.mkdir()
    (home / "sf.py").write_text("# fake\n", encoding="utf-8")
    monkeypatch.setenv("SPIDERFOOT_HOME", str(home))
    monkeypatch.setenv("SPIDERFOOT_ENABLED", "1")
    assert SpiderFootScanner().available() is True


def test_parse_sample_json_yields_concrete_profiles_only():
    events = parse_spiderfoot_stdout(SAMPLE_JSON)
    assert len(events) == 7
    findings = events_to_findings(events)
    profiles = [f for f in findings if f.kind == "profile"]
    urls = {f.url for f in profiles}
    assert "https://github.com/torvalds" in urls
    assert "https://twitter.com/torvalds" in urls
    assert "https://instagram.com/" not in urls
    assert all(f.title for f in profiles)
    assert any(f.kind == "username" and f.value == "torvalds" for f in findings)
    assert any(f.kind == "email" and f.value == "linus@example.com" for f in findings)
    assert not any(f.kind == "breach" for f in findings)
    assert not any("pwned" in f.value for f in findings)


def test_truncated_json_still_parses():
    truncated = SAMPLE_JSON.rsplit("},", 1)[0] + "}"
    events = parse_spiderfoot_stdout(truncated)
    assert events
    assert any("github.com/torvalds" in str(e.get("data")) for e in events)


def test_derive_target_username_email_name_phone():
    assert derive_target(build_query("torvalds")) == "torvalds"
    email = build_query("ada@example.com")
    assert derive_target(email) == "ada@example.com"
    name = build_query("Ada Lovelace")
    assert derive_target(name) == "Ada Lovelace"
    phone = build_query("+1 415 555 2671")
    assert derive_target(phone) == "+14155552671"


def test_run_parses_cli_stdout(monkeypatch, tmp_path):
    home = tmp_path / "sf"
    home.mkdir()
    (home / "sf.py").write_text("# fake\n", encoding="utf-8")
    monkeypatch.setenv("SPIDERFOOT_HOME", str(home))
    monkeypatch.setenv("SPIDERFOOT_ENABLED", "1")
    scanner = SpiderFootScanner()

    def fake_cli(target: str, script: Path):
        assert target == "torvalds"
        assert script == home / "sf.py"
        return SAMPLE_JSON, "ok", None

    monkeypatch.setattr(scanner, "_run_cli", fake_cli)
    result = asyncio.run(scanner.run(build_query("torvalds")))
    assert result.status.status == "success"
    profiles = [f for f in result.findings if f.kind == "profile"]
    assert {f.url for f in profiles} == {
        "https://github.com/torvalds",
        "https://twitter.com/torvalds",
    }


def test_timeout_returns_timeout_status(monkeypatch, tmp_path):
    home = tmp_path / "sf"
    home.mkdir()
    (home / "sf.py").write_text("# fake\n", encoding="utf-8")
    monkeypatch.setenv("SPIDERFOOT_HOME", str(home))
    monkeypatch.setenv("SPIDERFOOT_ENABLED", "1")
    monkeypatch.setenv("SPIDERFOOT_TIMEOUT", "12")
    scanner = SpiderFootScanner()

    def fake_popen(*_a, **_k):
        class Proc:
            pid = 4242
            returncode = None
            calls = 0

            def communicate(self, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    raise subprocess.TimeoutExpired(cmd="sf.py", timeout=timeout)
                return "", ""

            def poll(self):
                return None

            def kill(self):
                return None

        return Proc()

    monkeypatch.setattr("app.scanners.spiderfoot_scan.subprocess.Popen", fake_popen)
    monkeypatch.setattr("app.scanners.spiderfoot_scan._kill_group", lambda proc: None)
    result = asyncio.run(scanner.run(build_query("torvalds")))
    assert result.status.status == "timeout"
    assert result.status.error
    assert "Timed out" in result.status.summary


def test_timeout_keeps_partial_profiles(monkeypatch, tmp_path):
    home = tmp_path / "sf"
    home.mkdir()
    (home / "sf.py").write_text("# fake\n", encoding="utf-8")
    monkeypatch.setenv("SPIDERFOOT_HOME", str(home))
    monkeypatch.setenv("SPIDERFOOT_ENABLED", "1")
    scanner = SpiderFootScanner()

    def fake_cli(target: str, script: Path):
        return SAMPLE_JSON, "timeout", "timeout after 10s"

    monkeypatch.setattr(scanner, "_run_cli", fake_cli)
    result = asyncio.run(scanner.run(build_query("torvalds")))
    assert result.status.status == "timeout"
    assert any(f.kind == "profile" for f in result.findings)


def test_username_and_email_jobs_plan_spiderfoot():
    for raw, expected in (
        ("torvalds", True),
        ("ada@example.com", True),
        ("Ada Lovelace", True),
        ("+1 415 555 2671", True),
    ):
        query = build_query(raw)
        planned = [s.id for s in all_scanners() if s.applicable(query) or s.optional_key]
        assert "spiderfoot" in planned, raw
        assert expected


def _install_fake_sf(monkeypatch, tmp_path) -> Path:
    home = tmp_path / "sf"
    home.mkdir()
    (home / "sf.py").write_text("# fake\n", encoding="utf-8")
    monkeypatch.setenv("SPIDERFOOT_HOME", str(home))
    monkeypatch.setenv("SPIDERFOOT_ENABLED", "1")
    return home


def test_run_dispatches_cli_via_to_thread(monkeypatch, tmp_path):
    home = _install_fake_sf(monkeypatch, tmp_path)
    scanner = SpiderFootScanner()
    seen: dict = {}

    async def fake_to_thread(fn, *args, **kwargs):
        seen["fn"] = fn
        seen["args"] = args
        return SAMPLE_JSON, "ok", None

    monkeypatch.setattr("app.scanners.spiderfoot_scan.asyncio.to_thread", fake_to_thread)
    result = asyncio.run(scanner.run(build_query("torvalds")))
    assert seen["fn"] == scanner._run_cli
    assert seen["args"] == ("torvalds", home / "sf.py")
    assert result.status.status == "success"
    assert any(f.url == "https://github.com/torvalds" for f in result.findings)


def test_communicate_does_not_run_on_event_loop(monkeypatch, tmp_path):
    _install_fake_sf(monkeypatch, tmp_path)
    scanner = SpiderFootScanner()
    communicate_threads: list[int] = []
    loop_thread = {"id": 0}

    class Proc:
        pid = 4242
        returncode = 0

        def communicate(self, timeout=None):
            communicate_threads.append(threading.get_ident())
            return SAMPLE_JSON, ""

        def poll(self):
            return 0

    monkeypatch.setattr(
        "app.scanners.spiderfoot_scan.subprocess.Popen",
        lambda *_a, **_k: Proc(),
    )

    async def go():
        loop_thread["id"] = threading.get_ident()
        return await scanner.run(build_query("torvalds"))

    result = asyncio.run(go())
    assert result.status.status == "success"
    assert communicate_threads
    assert all(tid != loop_thread["id"] for tid in communicate_threads)


def test_event_loop_stays_responsive_while_cli_blocks(monkeypatch, tmp_path):
    _install_fake_sf(monkeypatch, tmp_path)
    scanner = SpiderFootScanner()
    started = threading.Event()

    def fake_cli(target: str, script: Path):
        started.set()
        time.sleep(0.25)
        return SAMPLE_JSON, "ok", None

    monkeypatch.setattr(scanner, "_run_cli", fake_cli)

    async def probe():
        task = asyncio.create_task(scanner.run(build_query("torvalds")))
        for _ in range(50):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set()
        ticks = 0
        deadline = time.monotonic() + 0.15
        while time.monotonic() < deadline:
            await asyncio.sleep(0.01)
            ticks += 1
        result = await task
        return result, ticks

    result, ticks = asyncio.run(probe())
    assert ticks >= 5
    assert result.status.status == "success"


def test_get_scan_returns_while_spiderfoot_cli_blocks(monkeypatch, tmp_path):
    """Regression: GET /api/scans/{id} must not wait on Popen.communicate()."""
    from app.jobs import reset_heavy_gate

    # This test is about the event loop, not the heavy-scanner gate. Other
    # social crawlers must not hold the single default slot.
    reset_heavy_gate(16)
    _install_fake_sf(monkeypatch, tmp_path)
    started = threading.Event()
    release = threading.Event()

    def fake_cli(self, target: str, script: Path):
        started.set()
        release.wait(timeout=5)
        return SAMPLE_JSON, "ok", None

    monkeypatch.setattr(SpiderFootScanner, "_run_cli", fake_cli)
    from app.main import app

    client = TestClient(app)
    posted = client.post("/api/scans", json={"query": "torvalds", "type": "username"})
    assert posted.status_code == 200
    job_id = posted.json()["job_id"]
    assert started.wait(timeout=2)

    t0 = time.monotonic()
    health = client.get("/api/health")
    report = client.get(f"/api/scans/{job_id}")
    elapsed = time.monotonic() - t0
    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert report.status_code == 200
    body = report.json()
    assert body["status"] in {"queued", "running"}
    spider = next(m for m in body["modules"] if m["id"] == "spiderfoot")
    assert spider["status"] in {"queued", "running"}
    assert elapsed < 1.0

    release.set()


def _remote_payload(status: str = "ok", events=None, error=None):
    return {
        "status": status,
        "target": "torvalds",
        "events": events
        if events is not None
        else [
            {
                "type": "Account on External Site",
                "data": "GitHub (Category: coding)\n<SFURL>https://github.com/torvalds</SFURL>",
                "module": "sfp_accounts",
            }
        ],
        "stdout_excerpt": "[]",
        "error": error,
    }


def _fake_async_client(handler):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            return await handler(url, json, headers, self.kwargs)

    return FakeClient


def test_available_when_remote_url_and_token(monkeypatch, tmp_path):
    monkeypatch.setenv("SPIDERFOOT_HOME", str(tmp_path / "missing"))
    monkeypatch.setenv("SPIDERFOOT_ENABLED", "0")
    monkeypatch.setenv("SPIDERFOOT_URL", "http://spiderfoot-runner:10000")
    monkeypatch.setenv("SPIDERFOOT_RUNNER_TOKEN", "shared-secret")
    assert remote_configured() is True
    assert SpiderFootScanner().available() is True


def test_unavailable_when_remote_url_without_token(monkeypatch, tmp_path):
    monkeypatch.setenv("SPIDERFOOT_HOME", str(tmp_path / "missing"))
    monkeypatch.setenv("SPIDERFOOT_URL", "http://spiderfoot-runner:10000")
    assert remote_configured() is False
    assert SpiderFootScanner().available() is False


def test_remote_run_uses_httpx(monkeypatch):
    monkeypatch.setenv("SPIDERFOOT_URL", "spiderfoot-runner:10000")
    monkeypatch.setenv("SPIDERFOOT_RUNNER_TOKEN", "shared-secret")
    monkeypatch.setenv("SPIDERFOOT_ENABLED", "0")
    seen: dict = {}

    class Resp:
        status_code = 200

        def json(self):
            return _remote_payload()

    async def handler(url, json, headers, kwargs):
        seen["url"] = url
        seen["json"] = json
        seen["headers"] = headers or kwargs.get("headers")
        return Resp()

    monkeypatch.setattr(
        "app.scanners.spiderfoot_scan.httpx.AsyncClient",
        _fake_async_client(handler),
    )
    scanner = SpiderFootScanner()
    called = {"cli": False}

    def boom(*_a, **_k):
        called["cli"] = True
        raise AssertionError("local CLI must not run when remote URL is set")

    monkeypatch.setattr(scanner, "_run_cli", boom)
    result = asyncio.run(scanner.run(build_query("torvalds")))
    assert called["cli"] is False
    assert result.status.status == "success"
    assert seen["url"] == "http://spiderfoot-runner:10000/v1/scan"
    assert seen["headers"]["Authorization"] == "Bearer shared-secret"
    assert seen["json"]["target"] == "torvalds"
    assert "sfp_accounts" in seen["json"]["modules"]
    assert any(f.url == "https://github.com/torvalds" for f in result.findings)
    assert result.raw["mode"] == "remote"


def test_remote_timeout_and_error(monkeypatch):
    monkeypatch.setenv("SPIDERFOOT_URL", "http://sf.internal:10000")
    monkeypatch.setenv("SPIDERFOOT_RUNNER_TOKEN", "shared-secret")

    class TimeoutResp:
        status_code = 200

        def json(self):
            payload = _remote_payload(status="timeout", error="timeout after 180s")
            payload["stderr_excerpt"] = "scan still running after wall clock"
            payload["salvaged"] = True
            payload["scan_id"] = "SCAN1"
            return payload

    async def timeout_handler(*_a):
        return TimeoutResp()

    monkeypatch.setattr(
        "app.scanners.spiderfoot_scan.httpx.AsyncClient",
        _fake_async_client(timeout_handler),
    )
    result = asyncio.run(SpiderFootScanner().run(build_query("torvalds")))
    assert result.status.status == "timeout"
    assert any(f.kind == "profile" for f in result.findings)
    assert result.raw["salvaged"] is True
    assert result.raw["scan_id"] == "SCAN1"
    assert "wall clock" in result.raw["stderr_excerpt"]

    class ErrResp:
        status_code = 200

        def json(self):
            return _remote_payload(status="error", events=[], error="sf.py crashed")

    async def error_handler(*_a):
        return ErrResp()

    monkeypatch.setattr(
        "app.scanners.spiderfoot_scan.httpx.AsyncClient",
        _fake_async_client(error_handler),
    )
    result = asyncio.run(SpiderFootScanner().run(build_query("torvalds")))
    assert result.status.status == "error"
    assert "crashed" in (result.status.error or "")


def test_remote_401_and_connect_error(monkeypatch):
    monkeypatch.setenv("SPIDERFOOT_URL", "http://sf.internal:10000")
    monkeypatch.setenv("SPIDERFOOT_RUNNER_TOKEN", "shared-secret")

    class Unauthorized:
        status_code = 401
        text = "nope"

        def json(self):
            return {"detail": "invalid token"}

    async def handler(*_a):
        return Unauthorized()

    monkeypatch.setattr(
        "app.scanners.spiderfoot_scan.httpx.AsyncClient",
        _fake_async_client(handler),
    )
    result = asyncio.run(SpiderFootScanner().run(build_query("torvalds")))
    assert result.status.status == "error"
    assert "401" in (result.status.error or "")

    async def boom(*_a, **_k):
        raise ConnectionError("connection refused")

    class BoomClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        post = boom

    monkeypatch.setattr("app.scanners.spiderfoot_scan.httpx.AsyncClient", BoomClient)
    result = asyncio.run(SpiderFootScanner().run(build_query("torvalds")))
    assert result.status.status == "error"
    assert "unreachable" in result.status.summary.lower()
