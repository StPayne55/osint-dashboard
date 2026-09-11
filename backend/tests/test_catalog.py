from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_catalog_lists_core_scanners():
    r = client.get("/api/catalog")
    assert r.status_code == 200
    ids = {s["id"] for s in r.json()["scanners"]}
    for required in {
        "holehe",
        "sherlock",
        "phone",
        "gravatar",
        "dorks",
        "email_intel",
        "socialscan",
        "harvester",
        "hibp",
    }:
        assert required in ids


def test_start_scan_and_poll():
    r = client.post("/api/scans", json={"query": "example@example.com", "type": "email"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    report = client.get(f"/api/scans/{job_id}")
    assert report.status_code == 200
    body = report.json()
    assert body["query"]["email"] == "example@example.com"
    assert "honesty" in body
