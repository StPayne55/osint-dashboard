import asyncio
from types import SimpleNamespace

from app.detect import build_query
from app.scanners import all_scanners
from app.scanners.maigret_scan import (
    MaigretScanner,
    derive_username,
    findings_from_results,
)


def _claimed(url: str, tags: list[str] | None = None, ids: dict | None = None):
    return {
        "status": SimpleNamespace(
            is_found=lambda: True,
            site_url_user=url,
            ids_data=ids or {},
            tags=tags or ["social"],
        ),
        "url_user": url,
        "found": True,
        "is_similar": False,
        "ids_data": ids or {},
        "tags": tags or ["social"],
    }


SAMPLE = {
    "GitHub": _claimed(
        "https://github.com/torvalds",
        ids={"name": "Linus Torvalds", "image": "https://avatars.githubusercontent.com/u/1024025"},
    ),
    "Twitter": _claimed("https://twitter.com/torvalds"),
    "Instagram": _claimed("https://instagram.com/"),
    "Ghost": {
        "status": SimpleNamespace(is_found=lambda: False, site_url_user="https://ghost.example/u/x"),
        "url_user": "https://ghost.example/u/x",
        "found": False,
    },
    "Lookalike": {
        **_claimed("https://example.com/not-torvalds"),
        "is_similar": True,
    },
}


def test_maigret_registered_with_spiderfoot():
    ids = [s.id for s in all_scanners()]
    assert "maigret" in ids
    assert "spiderfoot" in ids
    assert "abstract_phone" not in ids


def test_unavailable_when_import_fails(monkeypatch):
    monkeypatch.setattr("app.scanners.maigret_scan._load_maigret", lambda: None)
    scanner = MaigretScanner()
    assert scanner.available() is False
    result = asyncio.run(scanner.run(build_query("torvalds")))
    assert result.status.status == "unavailable"
    assert result.findings == []


def test_findings_keep_concrete_profiles_only():
    findings = findings_from_results(SAMPLE, "torvalds")
    profiles = [f for f in findings if f.kind == "profile"]
    urls = {f.url for f in profiles}
    assert urls == {"https://github.com/torvalds", "https://twitter.com/torvalds"}
    assert "https://instagram.com/" not in urls
    assert all(f.title for f in profiles)
    github = next(f for f in profiles if f.title == "GitHub")
    assert github.extra.get("display_name") == "Linus Torvalds"
    photos = [f for f in findings if f.kind == "image"]
    assert photos and photos[0].url.startswith("https://avatars.githubusercontent.com/")
    assert not any("not-torvalds" in (f.url or "") for f in findings)


def test_derive_username_matches_sherlock_style():
    assert derive_username(build_query("torvalds")) == "torvalds"
    assert derive_username(build_query("ada@example.com")) == "ada"
    name = build_query("Ada Lovelace")
    assert derive_username(name)
    assert derive_username(build_query("+1 415 555 2671")) is None


def test_run_maps_mocked_search(monkeypatch):
    scanner = MaigretScanner()
    monkeypatch.setattr(scanner, "available", lambda: True)
    monkeypatch.setattr(
        "app.scanners.maigret_scan._load_maigret",
        lambda: (object(), object()),
    )

    async def fake_search(username: str, loaded):
        assert username == "torvalds"
        return {"results": SAMPLE, "subset": True, "top": 200, "checked": 4}

    monkeypatch.setattr(scanner, "_search", fake_search)
    result = asyncio.run(scanner.run(build_query("torvalds")))
    assert result.status.status == "success"
    assert {f.url for f in result.findings if f.kind == "profile"} == {
        "https://github.com/torvalds",
        "https://twitter.com/torvalds",
    }
    assert "top 200" in result.status.summary


def test_timeout_status(monkeypatch):
    scanner = MaigretScanner()
    monkeypatch.setattr("app.scanners.maigret_scan._load_maigret", lambda: (object(), object()))
    monkeypatch.setenv("MAIGRET_TIMEOUT", "0.2")

    async def hang(username: str, loaded):
        await asyncio.sleep(30)
        return {"results": {}}

    monkeypatch.setattr(scanner, "_search", hang)
    result = asyncio.run(scanner.run(build_query("torvalds")))
    assert result.status.status == "timeout"
    assert result.status.error == "timeout"


def test_username_jobs_plan_maigret_phone_does_not():
    user = build_query("torvalds")
    planned = [s.id for s in all_scanners() if s.applicable(user) or s.optional_key]
    assert "maigret" in planned
    phone = build_query("+1 415 555 2671")
    planned_phone = [s.id for s in all_scanners() if s.applicable(phone) or s.optional_key]
    assert "maigret" not in planned_phone
