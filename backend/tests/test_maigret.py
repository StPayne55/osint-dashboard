import asyncio
import threading
from types import SimpleNamespace

from app.detect import build_query
from app.scanners import all_scanners
from app.scanners.maigret_scan import (
    MaigretScanner,
    _site_limits,
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


def test_default_top_sites_is_small_for_render():
    from app.config import MAIGRET_TOP_SITES

    assert MAIGRET_TOP_SITES == 50
    top, subset, excluded = _site_limits()
    assert subset is True
    assert top == 50
    assert "porn" in excluded


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
    assert photos[0].extra.get("source") == "maigret"
    assert not any("not-torvalds" in (f.url or "") for f in findings)


def test_findings_accept_nested_and_protocol_relative_photos():
    results = {
        "GitHub": _claimed(
            "https://github.com/ada",
            ids={"image": {"url": "//avatars.githubusercontent.com/u/99"}},
        ),
        "GitLab": _claimed(
            "https://gitlab.com/ada",
            ids={"photos": [{"value": "https://cdn.example.com/ada.png"}]},
        ),
    }
    findings = findings_from_results(results, "ada")
    photo_urls = {f.url for f in findings if f.kind == "image"}
    assert "https://avatars.githubusercontent.com/u/99" in photo_urls
    assert "https://cdn.example.com/ada.png" in photo_urls


def test_derive_username_matches_sherlock_style():
    assert derive_username(build_query("torvalds")) == "torvalds"
    assert derive_username(build_query("ada@example.com")) == "ada"
    name = build_query("Ada Lovelace")
    assert derive_username(name)
    assert derive_username(build_query("+1 415 555 2671")) is None
    assert derive_username(build_query("Lisa.m.fraleigh@gmail.com")).lower() == "lisamfraleigh"


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


def test_dotted_email_tries_undotted_handle_first(monkeypatch):
    scanner = MaigretScanner()
    monkeypatch.setattr("app.scanners.maigret_scan._load_maigret", lambda: (object(), object()))
    seen: list[str] = []

    async def fake_search(username: str, loaded):
        seen.append(username)
        if username.lower() == "lisamfraleigh":
            return {
                "results": {
                    "GitHub": _claimed("https://github.com/lisamfraleigh"),
                },
                "subset": True,
                "top": 50,
                "checked": 1,
                "found": [{"site": "GitHub", "url": "https://github.com/lisamfraleigh", "found": True}],
            }
        return {
            "results": {
                "GitHub": _claimed("https://github.com/lisamfraleigh"),
                "Twitter": _claimed("https://twitter.com/lisa.m.fraleigh"),
            },
            "subset": True,
            "top": 50,
            "checked": 2,
            "found": [],
        }

    monkeypatch.setattr(scanner, "_search", fake_search)
    result = asyncio.run(scanner.run(build_query("Lisa.m.fraleigh@gmail.com")))
    assert result.status.status == "success"
    assert seen[0].lower() == "lisamfraleigh"
    assert "lisamfraleigh" in seen[0].lower()
    assert any("lisa.m.fraleigh" in u.lower() for u in seen)
    urls = {f.url for f in result.findings if f.kind == "profile"}
    assert urls == {
        "https://github.com/lisamfraleigh",
        "https://twitter.com/lisa.m.fraleigh",
    }
    assert "lisamfraleigh" in result.status.summary
    assert "lisa.m.fraleigh" in result.status.summary


def test_search_loads_database_off_loop_and_awaits_maigret(monkeypatch):
    """Maigret search() is a real coroutine; only sync DB load is off-loop."""
    scanner = MaigretScanner()
    db_thread: list[int] = []
    loop_thread = {"id": 0}

    class FakeDB:
        def ranked_sites_dict(self, **_k):
            return {"GitHub": _claimed("https://github.com/torvalds")}

    def fake_db(_cls):
        db_thread.append(threading.get_ident())
        return FakeDB()

    async def fake_search(**_k):
        assert threading.get_ident() == loop_thread["id"]
        return {
            "GitHub": _claimed("https://github.com/torvalds"),
        }

    monkeypatch.setattr("app.scanners.maigret_scan._database", fake_db)

    async def go():
        loop_thread["id"] = threading.get_ident()
        return await scanner._search("torvalds", (fake_search, object()))

    raw = asyncio.run(go())
    assert raw["username"] == "torvalds"
    assert raw["checked"] == 1
    assert db_thread and all(tid != loop_thread["id"] for tid in db_thread)
