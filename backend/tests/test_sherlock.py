import asyncio

from app.detect import build_query
from app.scanners.sherlock_scan import SherlockScanner
from app.scanners.socialscan_scan import social_queries


def test_sherlock_dotted_email_merges_handles(monkeypatch):
    scanner = SherlockScanner()
    monkeypatch.setattr(scanner, "available", lambda: True)
    seen: list[str] = []

    def fake_sherlock(username: str):
        seen.append(username)
        if username.lower() == "lisamfraleigh":
            return {
                "username": username,
                "checked": 2,
                "subset": True,
                "found": [
                    {"site": "GitHub", "url": "https://github.com/lisamfraleigh", "status": "CLAIMED"},
                ],
            }
        return {
            "username": username,
            "checked": 2,
            "subset": True,
            "found": [
                {"site": "GitHub", "url": "https://github.com/lisamfraleigh", "status": "CLAIMED"},
                {"site": "Twitter", "url": "https://twitter.com/lisa.m.fraleigh", "status": "CLAIMED"},
            ],
        }

    monkeypatch.setattr(scanner, "_sherlock", fake_sherlock)
    result = asyncio.run(scanner.run(build_query("Lisa.m.fraleigh@gmail.com")))
    assert result.status.status == "success"
    assert seen[0].lower() == "lisamfraleigh"
    assert any("lisa.m.fraleigh" in u.lower() for u in seen)
    assert {f.url for f in result.findings if f.kind == "profile"} == {
        "https://github.com/lisamfraleigh",
        "https://twitter.com/lisa.m.fraleigh",
    }
    assert "lisamfraleigh" in result.status.summary
    assert "lisa.m.fraleigh" in result.status.summary
    assert result.raw.get("usernames")


def test_socialscan_queries_include_undotted_handle():
    queries = social_queries(build_query("Lisa.m.fraleigh@gmail.com"))
    assert queries[0] == "lisa.m.fraleigh@gmail.com"
    handles = [q.lower() for q in queries[1:]]
    assert handles[0] == "lisamfraleigh"
    assert "lisa.m.fraleigh" in handles
