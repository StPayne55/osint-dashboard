import asyncio

from app.detect import build_query
from app.scanners import all_scanners
from app.scanners.pdl_scan import (
    PDL_ENRICH_URL,
    PdlScanner,
    findings_from_person,
    public_fields,
)


def test_pdl_registered_in_catalog():
    ids = [s.id for s in all_scanners()]
    assert "pdl" in ids
    scanner = next(s for s in all_scanners() if s.id == "pdl")
    assert scanner.name == "People Data Labs"
    assert scanner.optional_key == "PDL_API_KEY"
    assert scanner.accepts[0].value == "email"


def test_available_only_when_key_set(monkeypatch):
    monkeypatch.delenv("PDL_API_KEY", raising=False)
    assert PdlScanner().available() is False
    monkeypatch.setenv("PDL_API_KEY", "  test-key  ")
    assert PdlScanner().available() is True


def test_skipped_without_key_does_not_call_http(monkeypatch):
    monkeypatch.delenv("PDL_API_KEY", raising=False)
    called = {"n": 0}

    class BoomClient:
        def __init__(self, *args, **kwargs):
            called["n"] += 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            raise AssertionError("PDL must not be called without a key")

    monkeypatch.setattr("app.scanners.pdl_scan.httpx.AsyncClient", BoomClient)
    result = asyncio.run(PdlScanner().run(build_query("ada@example.com")))
    assert result.status.status == "skipped"
    assert "PDL_API_KEY" in result.status.summary
    assert result.findings == []
    assert called["n"] == 0


def test_skipped_without_email(monkeypatch):
    monkeypatch.setenv("PDL_API_KEY", "test-key")
    query = build_query("torvalds")
    result = asyncio.run(PdlScanner().run(query))
    assert result.status.status == "skipped"
    assert result.status.summary == "No email"


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}" if payload is not None else b""
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _patch_client(monkeypatch, handler):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.headers = kwargs.get("headers") or {}
            handler["headers"] = self.headers
            handler["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            handler["url"] = url
            handler["params"] = params or {}
            return handler["response"]

    monkeypatch.setattr("app.scanners.pdl_scan.httpx.AsyncClient", FakeClient)


def test_enrichment_emits_only_present_public_fields(monkeypatch):
    monkeypatch.setenv("PDL_API_KEY", "test-key")
    handler: dict = {
        "response": _FakeResponse(
            200,
            {
                "status": 200,
                "likelihood": 8,
                "data": {
                    "full_name": "Ada Lovelace",
                    "job_title": "Analyst",
                    "job_company_name": "Analytical Engines",
                    "location_locality": "London",
                    "location_region": "England",
                    "linkedin_url": "linkedin.com/in/ada",
                    "twitter_url": "twitter.com/ada",
                    "github_url": "github.com/",
                    "emails": [{"address": "secret@example.com"}],
                    "phone_numbers": ["+15555550100"],
                    "birth_date": "1815-12-10",
                    "street_addresses": [{"street_address": "12 Secret Lane"}],
                    "profiles": [
                        {
                            "network": "linkedin",
                            "url": "linkedin.com/in/ada",
                        },
                        {
                            "network": "medium",
                            "url": "medium.com/@ada",
                        },
                    ],
                },
            },
        )
    }
    _patch_client(monkeypatch, handler)

    result = asyncio.run(PdlScanner().run(build_query("ada@example.com")))
    assert result.status.status == "success"
    assert handler["url"] == PDL_ENRICH_URL
    assert handler["params"]["email"] == "ada@example.com"
    assert handler["params"]["data_include"]
    assert "emails" not in handler["params"]["data_include"]
    assert handler["headers"]["X-Api-Key"] == "test-key"

    by_title = {f.title: f for f in result.findings}
    assert by_title["Full name"].value == "Ada Lovelace"
    assert by_title["Full name"].kind == "note"
    assert by_title["Job title"].value == "Analyst"
    assert by_title["Employer"].value == "Analytical Engines"
    assert by_title["City / region"].value == "London, England"
    assert by_title["LinkedIn"].kind == "profile"
    assert by_title["LinkedIn"].url == "https://linkedin.com/in/ada"
    assert by_title["Twitter"].url == "https://twitter.com/ada"
    assert by_title["Medium"].url == "https://medium.com/@ada"
    assert "GitHub" not in by_title  # homepage is not a profile

    values = " ".join(f.value for f in result.findings)
    assert "secret@example.com" not in values
    assert "+15555550100" not in values
    assert "1815-12-10" not in values
    assert "Secret Lane" not in values

    raw = result.raw
    assert raw["endpoint"] == PDL_ENRICH_URL
    assert raw["likelihood"] == 8
    assert "emails" not in raw
    assert "phone_numbers" not in raw["public_fields"]
    assert "birth_date" not in raw["public_fields"]


def test_missing_fields_are_not_invented():
    findings = findings_from_person(
        {
            "full_name": None,
            "job_title": "",
            "job_company_name": "   ",
            "linkedin_url": None,
        }
    )
    assert findings == []
    assert public_fields({"emails": ["x@y.com"], "full_name": None}) == {}


def test_404_is_empty_not_fabricated(monkeypatch):
    monkeypatch.setenv("PDL_API_KEY", "test-key")
    handler: dict = {
        "response": _FakeResponse(
            404,
            {"status": 404, "error": {"type": "not_found", "message": "No records were found"}},
        )
    }
    _patch_client(monkeypatch, handler)
    result = asyncio.run(PdlScanner().run(build_query("nobody@example.com")))
    assert result.status.status == "empty"
    assert result.findings == []
    assert "no person match" in result.status.summary.lower()


def test_401_is_error(monkeypatch):
    monkeypatch.setenv("PDL_API_KEY", "bad-key")
    handler: dict = {"response": _FakeResponse(401, {"status": 401})}
    _patch_client(monkeypatch, handler)
    result = asyncio.run(PdlScanner().run(build_query("ada@example.com")))
    assert result.status.status == "error"
    assert "rejected" in result.status.summary.lower()


def test_request_error_is_error(monkeypatch):
    monkeypatch.setenv("PDL_API_KEY", "test-key")

    class BoomClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            raise httpx_timeout()

    def httpx_timeout():
        import httpx

        return httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.scanners.pdl_scan.httpx.AsyncClient", BoomClient)
    result = asyncio.run(PdlScanner().run(build_query("ada@example.com")))
    assert result.status.status == "error"
    assert result.status.error


def test_email_jobs_plan_pdl():
    query = build_query("ada@example.com")
    planned = [s.id for s in all_scanners() if s.applicable(query) or s.optional_key]
    assert "pdl" in planned


def test_200_without_public_fields_is_empty(monkeypatch):
    monkeypatch.setenv("PDL_API_KEY", "test-key")
    handler: dict = {
        "response": _FakeResponse(
            200,
            {"status": 200, "likelihood": 2, "data": {"id": "abc", "full_name": None}},
        )
    }
    _patch_client(monkeypatch, handler)
    result = asyncio.run(PdlScanner().run(build_query("ada@example.com")))
    assert result.status.status == "empty"
    assert result.findings == []
    assert "no public-safe fields" in result.status.summary
