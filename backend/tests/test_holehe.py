import asyncio

from app.detect import build_query
from app.scanners.holehe_scan import HoleheScanner


def test_holehe_timeout_keeps_partial_findings(monkeypatch):
    scanner = HoleheScanner()
    monkeypatch.setattr("app.scanners.holehe_scan._load_holehe", lambda: (object(), (object(), object())))
    monkeypatch.setattr("app.scanners.holehe_scan._collect_functions", lambda *_a, **_k: [object()])

    async def fake_to_thread(fn, *args, **kwargs):
        return (
            [
                {
                    "exists": True,
                    "rateLimit": False,
                    "name": "GitHub",
                    "domain": "github.com",
                    "url": "https://github.com/octocat",
                }
            ],
            True,
        )

    monkeypatch.setattr("app.scanners.holehe_scan.asyncio.to_thread", fake_to_thread)
    result = asyncio.run(scanner.run(build_query("ada@example.com")))
    assert result.status.status == "timeout"
    assert result.status.error == "timeout"
    assert any(f.url == "https://github.com/octocat" for f in result.findings)
    assert result.raw.get("partial") is True
    assert "partial" in result.status.summary


def test_holehe_success_without_timeout(monkeypatch):
    scanner = HoleheScanner()
    monkeypatch.setattr("app.scanners.holehe_scan._load_holehe", lambda: (object(), (object(), object())))
    monkeypatch.setattr("app.scanners.holehe_scan._collect_functions", lambda *_a, **_k: [object()])

    async def fake_to_thread(fn, *args, **kwargs):
        return (
            [
                {
                    "exists": True,
                    "rateLimit": False,
                    "name": "Twitter",
                    "domain": "twitter.com",
                    "url": "https://twitter.com/ada",
                }
            ],
            False,
        )

    monkeypatch.setattr("app.scanners.holehe_scan.asyncio.to_thread", fake_to_thread)
    result = asyncio.run(scanner.run(build_query("ada@example.com")))
    assert result.status.status == "success"
    assert result.raw.get("partial") is False
    assert any(f.url == "https://twitter.com/ada" for f in result.findings)
