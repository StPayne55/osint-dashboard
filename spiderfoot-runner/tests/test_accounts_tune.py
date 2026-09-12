import json
from pathlib import Path

import accounts_tune
import patch_spiderfoot


def _sites(n: int = 716, *, include_github: bool = True) -> list[dict]:
    sites = []
    if include_github:
        sites.append(
            {
                "name": "GitHub (User)",
                "uri_check": "https://api.github.com/users/{account}",
                "uri_pretty": "https://github.com/{account}",
                "e_code": "200",
                "e_string": "login",
                "cat": "coding",
                "valid": True,
            }
        )
    for i in range(n - len(sites)):
        sites.append(
            {
                "name": f"Filler{i}",
                "uri_check": f"https://filler{i}.example/{{account}}",
                "e_code": "200",
                "e_string": "ok",
                "cat": "misc",
                "valid": True,
            }
        )
    return sites


def test_should_skip_distrust_defaults_on(monkeypatch):
    monkeypatch.delenv("SPIDERFOOT_SKIP_DISTRUST", raising=False)
    assert accounts_tune.should_skip_distrust() is True
    monkeypatch.setenv("SPIDERFOOT_SKIP_DISTRUST", "1")
    assert accounts_tune.should_skip_distrust() is True
    monkeypatch.setenv("SPIDERFOOT_SKIP_DISTRUST", "0")
    assert accounts_tune.should_skip_distrust() is False
    monkeypatch.setenv("SPIDERFOOT_SKIP_DISTRUST", "false")
    assert accounts_tune.should_skip_distrust() is False


def test_accounts_max_sites_and_cap(monkeypatch):
    monkeypatch.delenv("SPIDERFOOT_ACCOUNTS_MAX_SITES", raising=False)
    assert accounts_tune.accounts_max_sites() == 120
    monkeypatch.setenv("SPIDERFOOT_ACCOUNTS_MAX_SITES", "80")
    assert accounts_tune.accounts_max_sites() == 80
    monkeypatch.setenv("SPIDERFOOT_ACCOUNTS_MAX_SITES", "nope")
    assert accounts_tune.accounts_max_sites() == 120

    sites = _sites(716)
    capped = accounts_tune.cap_sites(sites, max_sites=120)
    assert len(capped) == 120
    assert capped[0]["name"] == "GitHub (User)"
    assert all(s["name"] != "xx NSFW" for s in capped)

    unlimited = accounts_tune.cap_sites(sites, max_sites=0)
    assert len(unlimited) == 716


def test_cap_skips_nsfw_unless_enabled():
    sites = _sites(5) + [
        {
            "name": "NSFW Place",
            "uri_check": "https://nsfw.example/{account}",
            "cat": "xx NSFW xx",
            "valid": True,
        }
    ]
    capped = accounts_tune.cap_sites(sites, max_sites=0, allow_nsfw=False)
    assert all(s["name"] != "NSFW Place" for s in capped)
    with_nsfw = accounts_tune.cap_sites(sites, max_sites=0, allow_nsfw=True)
    assert any(s["name"] == "NSFW Place" for s in with_nsfw)


def test_load_sites_from_priority_json():
    path = Path(__file__).resolve().parents[2] / "docker" / "wmn-priority.json"
    sites = accounts_tune.load_sites(path.read_text(encoding="utf-8"), max_sites=40)
    names = {s["name"] for s in sites}
    assert "GitHub (User)" in names
    assert "X" in names
    assert len(sites) == 40


def test_simulate_username_lookup_skips_distrust_burn(monkeypatch):
    """Account Finder path emits ACCOUNT hits without a 716-site distrust call."""
    monkeypatch.setenv("SPIDERFOOT_SKIP_DISTRUST", "1")
    monkeypatch.setenv("SPIDERFOOT_ACCOUNTS_MAX_SITES", "5")
    sites = accounts_tune.cap_sites(_sites(716), max_sites=5)
    seen: list[tuple[str, int]] = []

    def check(user: str, site_list: list[dict]) -> list[str]:
        seen.append((user, len(site_list)))
        url = f"https://github.com/{user}"
        return [f"GitHub (User) (Category: coding)\n<SFURL>{url}</SFURL>"]

    calls, hits = accounts_tune.simulate_username_lookup(
        "stpayne55",
        sites,
        check_sites=check,
    )
    assert calls == ["stpayne55"]
    assert seen == [("stpayne55", 5)]
    assert hits
    assert "https://github.com/stpayne55" in hits[0]
    assert all(len(user) != 10 or user == "stpayne55" for user, _ in seen)


def test_simulate_username_lookup_runs_distrust_when_enabled(monkeypatch):
    monkeypatch.setenv("SPIDERFOOT_SKIP_DISTRUST", "0")
    sites = _sites(50)
    seen: list[str] = []

    def check(user: str, site_list: list[dict]) -> list[str]:
        seen.append(user)
        if user == "stpayne55":
            return ["GitHub (User) (Category: coding)\n<SFURL>https://github.com/stpayne55</SFURL>"]
        return []

    calls, hits = accounts_tune.simulate_username_lookup(
        "stpayne55",
        sites,
        skip_distrust=False,
        check_sites=check,
    )
    assert calls[0] != "stpayne55"
    assert len(calls[0]) == 10
    assert calls[-1] == "stpayne55"
    assert hits and "stpayne55" in hits[0]


def test_bake_cache_writes_distrust_none(tmp_path):
    wmn = json.dumps({"sites": _sites(3)})
    written = accounts_tune.bake_spiderfoot_cache(tmp_path, wmn_content=wmn)
    names = {p.name for p in written}
    assert accounts_tune.cache_filename(accounts_tune.DISTRUST_CACHE_LABEL) in names
    state = tmp_path / accounts_tune.cache_filename(accounts_tune.DISTRUST_CACHE_LABEL)
    assert state.read_text(encoding="utf-8") == "None"
    sites_path = tmp_path / accounts_tune.cache_filename(accounts_tune.SITES_CACHE_LABEL)
    assert json.loads(sites_path.read_text(encoding="utf-8"))["sites"]


def test_bundled_priority_json_is_used(monkeypatch):
    monkeypatch.delenv("SPIDERFOOT_WMN_JSON", raising=False)
    monkeypatch.setenv("SPIDERFOOT_HOME", str(Path("/no/such/sf-home")))
    content = accounts_tune.bundled_wmn_content()
    assert content
    data = json.loads(content)
    assert any(s.get("name") == "GitHub (User)" for s in data["sites"])


def test_live_stpayne55_priority_sites_find_github():
    """Network smoke: skip+cap path would see at least GitHub for stpayne55."""
    import urllib.error
    import urllib.request

    path = Path(__file__).resolve().parents[2] / "docker" / "wmn-priority.json"
    sites = accounts_tune.load_sites(path.read_text(encoding="utf-8"), max_sites=8)
    github = next(s for s in sites if s["name"] == "GitHub (User)")
    url = github["uri_check"].format(account="stpayne55")
    req = urllib.request.Request(url, headers={"User-Agent": "OSINT-Desk-test/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            code = str(resp.status)
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        code = str(exc.code)
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
    except OSError as exc:
        import pytest

        pytest.skip(f"network unavailable: {exc}")
    exist_code = str(github.get("e_code") or "200")
    exist_string = github.get("e_string") or ""
    assert code == exist_code
    assert not exist_string or exist_string in body


def test_patch_inserts_skip_and_cap_markers(tmp_path):
    home = tmp_path / "sf"
    modules = home / "modules"
    modules.mkdir(parents=True)
    (home / "sf.py").write_text("# placeholder\n", encoding="utf-8")
    upstream = (
        Path(__file__).resolve().parents[2] / "docker" / "testdata" / "sfp_accounts_v4.py"
    )
    (modules / "sfp_accounts.py").write_text(
        upstream.read_text(encoding="utf-8"), encoding="utf-8"
    )
    patch_spiderfoot.patch_accounts(home)
    patched = (modules / "sfp_accounts.py").read_text(encoding="utf-8")
    assert "should_skip_distrust" in patched
    assert "load_sites" in patched
    assert "bundled_wmn_content" in patched
    assert "checkSites(randuser)" in patched
    assert "web_accounts_list.json" not in patched
    assert "wmn-data.json" in patched
    assert "SPIDERFOOT_SKIP_DISTRUST" in patched
