from app.detect import build_query, detect_type
from app.dorks import build_dorks
from app.models import QueryType


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
