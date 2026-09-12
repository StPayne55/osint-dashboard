from app.config import SOCIAL_USERNAME_CANDIDATES, SPIDERFOOT_ENABLED
from app.detect import (
    build_query,
    detect_type,
    derive_username,
    merge_findings_by_url,
    social_username_candidates,
)
from app.dorks import build_dorks
from app.models import Finding, QueryType


def test_detect_email():
    assert detect_type("Ada@Example.COM") == QueryType.email
    q = build_query("Ada@Example.COM")
    assert q.email == "ada@example.com"
    assert q.domain == "example.com"
    assert "Ada" in q.username_candidates or "ada" in [c.lower() for c in q.username_candidates]


def test_detect_phone():
    q = build_query("+1 415 555 2671")
    assert q.type == QueryType.phone
    assert q.phone_e164 == "+14155552671"


def test_detect_name():
    q = build_query("Grace Hopper")
    assert q.type == QueryType.name
    assert "gracehopper" in [c.lower() for c in q.username_candidates]


def test_detect_username():
    q = build_query("torvalds")
    assert q.type == QueryType.username
    assert q.username == "torvalds"


def test_social_and_spiderfoot_config_defaults():
    assert SOCIAL_USERNAME_CANDIDATES == 2
    assert SPIDERFOOT_ENABLED is False


def test_email_local_does_not_strip_trailing_digits():
    q = build_query("stpayne55@gmail.com")
    lowered = [c.lower() for c in q.username_candidates]
    assert "stpayne55" in lowered
    assert "stpayne" not in lowered
    social = social_username_candidates(q)
    assert "stpayne55" in [c.lower() for c in social]
    assert "stpayne" not in [c.lower() for c in social]
    assert derive_username(q).lower() == "stpayne55"


def test_dotted_email_local_includes_nodot_variant_first():
    q = build_query("Lisa.m.fraleigh@gmail.com")
    lowered = [c.lower() for c in q.username_candidates]
    assert "lisamfraleigh" in lowered
    assert "lisa.m.fraleigh" in lowered
    assert lowered.index("lisamfraleigh") < lowered.index("lisa.m.fraleigh")
    assert q.username == "lisa.m.fraleigh"
    social = social_username_candidates(q)
    assert social[0].lower() == "lisamfraleigh"
    assert "lisa.m.fraleigh" in [c.lower() for c in social]
    assert derive_username(q) == social[0]
    assert len(social) <= 3


def test_plus_tagged_email_prefers_alphanumeric_handle(monkeypatch):
    q = build_query("Ada.Lovelace+tag@gmail.com")
    lowered = [c.lower() for c in q.username_candidates]
    assert "adalovelacetag" in lowered
    assert lowered[0] == "adalovelacetag"
    assert "ada.lovelace" in lowered or "adalovelace" in lowered
    monkeypatch.setenv("SOCIAL_USERNAME_CANDIDATES", "2")
    social = social_username_candidates(q)
    assert social[0].lower() == "adalovelacetag"
    assert len(social) == 2
    assert all("+" not in c for c in social)


def test_social_candidate_cap(monkeypatch):
    q = build_query("first.last.third@example.com")
    monkeypatch.setenv("SOCIAL_USERNAME_CANDIDATES", "1")
    assert social_username_candidates(q) == [social_username_candidates(q, limit=1)[0]]
    monkeypatch.setenv("SOCIAL_USERNAME_CANDIDATES", "3")
    assert 1 <= len(social_username_candidates(q)) <= 3
    monkeypatch.setenv("SOCIAL_USERNAME_CANDIDATES", "99")
    assert len(social_username_candidates(q)) <= 3


def test_merge_findings_by_url_dedupes_profiles():
    findings = [
        Finding(kind="profile", title="GitHub", value="https://github.com/a", url="https://github.com/a"),
        Finding(
            kind="profile",
            title="GitHub",
            value="https://github.com/a/",
            url="https://github.com/a/",
            extra={"username": "other"},
        ),
        Finding(kind="profile", title="Twitter", value="https://twitter.com/a", url="https://twitter.com/a"),
        Finding(kind="note", title="GitHub", value="taken"),
        Finding(kind="note", title="GitHub", value="taken"),
    ]
    merged = merge_findings_by_url(findings)
    urls = [f.url for f in merged if f.url]
    assert urls == ["https://github.com/a", "https://twitter.com/a"]
    assert sum(1 for f in merged if f.kind == "note") == 1


def test_dorks_not_empty():
    q = build_query("example@example.com")
    links = build_dorks(q)
    assert len(links) >= 6
    assert any("google.com" in (f.url or "") for f in links)


def test_phone_dorks_not_empty():
    q = build_query("+1 415 555 2671")
    links = build_dorks(q)
    assert len(links) >= 10
    assert any("whitepages.com" in (f.url or "") for f in links)
