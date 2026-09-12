from fastapi.testclient import TestClient

from app.detect import build_query
from app.main import app
from app.scanners import all_scanners

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
        "twilio",
        "numverify",
        "spiderfoot",
    }:
        assert required in ids
    assert "abstract_phone" not in ids


def test_phone_jobs_do_not_plan_abstract_phone():
    query = build_query("+1 415 555 2671")
    planned = [s.id for s in all_scanners() if s.applicable(query) or s.optional_key]
    assert "phone" in planned
    assert "dorks" in planned
    assert "twilio" in planned
    assert "numverify" in planned
    assert "abstract_phone" not in planned

    r = client.post("/api/scans", json={"query": "+1 415 555 2671", "type": "phone"})
    assert r.status_code == 200
    assert "abstract_phone" not in r.json()["scanners"]
    assert "phone" in r.json()["scanners"]
    assert "twilio" in r.json()["scanners"]
    assert "dorks" in r.json()["scanners"]


def test_start_scan_and_poll():
    r = client.post("/api/scans", json={"query": "example@example.com", "type": "email"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    report = client.get(f"/api/scans/{job_id}")
    assert report.status_code == 200
    body = report.json()
    assert body["query"]["email"] == "example@example.com"
    assert "honesty" in body
    assert "spiderfoot" in r.json()["scanners"]
    assert "abstract_phone" not in r.json()["scanners"]
