import asyncio

from app.detect import build_query
from app.jobs import _identity
from app.scanners import all_scanners
from app.scanners.whitepages_scan import (
    WHITEPAGES_PERSON_URL,
    WhitepagesProScanner,
    findings_from_people,
)


OFFICIAL_ARRAY_FIXTURE = [
    {
        "id": "P1234567890",
        "name": "John Smith",
        "aliases": ["Johnny Smith"],
        "is_dead": False,
        "age": 40,
        "date_of_birth": "1985-03-00",
        "linkedin_url": "https://linkedin.com/in/johnsmith",
        "company_name": "Acme Corp",
        "job_title": "Software Engineer",
        "match_score": 95,
        "matched_by": ["phone"],
        "phones": [
            {"number": "(212) 555-0198", "type": "mobile", "score": 95},
            {"number": "(212) 555-0199", "type": "landline", "score": 72},
        ],
        "current_addresses": [
            {
                "address_id": "A9876543210",
                "full_address": "123 Main St, New York, NY 10001",
                "line1": "123 Main St",
                "city": "New York",
                "state": "NY",
                "zip": "10001",
            }
        ],
        "historic_addresses": [
            {"id": "A1234567890", "address": "456 Oak Ave, Brooklyn, NY 11201"}
        ],
        "owned_properties": [],
        "emails": [{"email": "john.smith@example.com", "score": 88}],
        "relatives": [{"id": "P0987654321", "name": "Jane Smith"}],
    }
]


def test_whitepages_registered_in_catalog():
    ids = [s.id for s in all_scanners()]
    assert "whitepages" in ids
    assert "trestle" in ids
    scanner = next(s for s in all_scanners() if s.id == "whitepages")
    assert scanner.name == "Whitepages Pro"
    assert scanner.optional_key == "WHITEPAGES_API_KEY"
    assert scanner.accepts[0].value == "phone"


def test_available_only_when_key_set(monkeypatch):
    monkeypatch.delenv("WHITEPAGES_API_KEY", raising=False)
    assert WhitepagesProScanner().available() is False
    monkeypatch.setenv("WHITEPAGES_API_KEY", "  test-key  ")
    assert WhitepagesProScanner().available() is True


def test_skipped_without_key_does_not_call_http(monkeypatch):
    monkeypatch.delenv("WHITEPAGES_API_KEY", raising=False)
    called = {"n": 0}

    class BoomClient:
        def __init__(self, *args, **kwargs):
            called["n"] += 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            raise AssertionError("Whitepages must not be called without a key")

    monkeypatch.setattr("app.scanners.whitepages_scan.httpx.AsyncClient", BoomClient)
    result = asyncio.run(WhitepagesProScanner().run(build_query("+14155552671")))
    assert result.status.status == "skipped"
    assert "WHITEPAGES_API_KEY" in result.status.summary
    assert result.findings == []
    assert called["n"] == 0


class _FakeResponse:
    def __init__(self, status_code: int, payload, text: str = ""):
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

    monkeypatch.setattr("app.scanners.whitepages_scan.httpx.AsyncClient", FakeClient)


def test_person_search_emits_only_returned_fields(monkeypatch):
    monkeypatch.setenv("WHITEPAGES_API_KEY", "test-key")
    handler: dict = {"response": _FakeResponse(200, OFFICIAL_ARRAY_FIXTURE)}
    _patch_client(monkeypatch, handler)

    result = asyncio.run(WhitepagesProScanner().run(build_query("+12125550198")))
    assert result.status.status == "success"
    assert handler["url"] == WHITEPAGES_PERSON_URL
    assert handler["params"]["phone"] == "+12125550198"
    assert handler["headers"]["X-Api-Key"] == "test-key"

    by_title = {f.title: f for f in result.findings}
    assert by_title["Name"].value == "John Smith"
    assert by_title["Name"].kind == "note"
    assert by_title["Name"].extra.get("source") == "whitepages"
    assert by_title["Alternate name"].value == "Johnny Smith"
    assert by_title["Current address"].value == "123 Main St, New York, NY 10001"
    assert by_title["Historical address"].value == "456 Oak Ave, Brooklyn, NY 11201"
    assert by_title["Email"].kind == "email"
    assert by_title["Email"].value == "john.smith@example.com"
    assert by_title["Line type"].value == "mobile"
    assert by_title["Job title"].value == "Software Engineer"
    assert by_title["Employer"].value == "Acme Corp"
    assert by_title["LinkedIn"].kind == "profile"
    assert by_title["Relative"].value == "Jane Smith"

    values = " ".join(f.value for f in result.findings)
    assert "1985-03-00" not in values
    assert "40" not in values.split()

    ident = _identity(build_query("+12125550198"), [result])
    assert ident.caller_name is None
    assert "john.smith@example.com" in ident.emails


def test_results_wrapper_and_structured_address():
    findings = findings_from_people(
        {
            "results": [
                {
                    "name": "Ada Lovelace",
                    "current_addresses": [
                        {
                            "line1": "12 St James Sq",
                            "city": "London",
                            "state": "England",
                            "zip": "SW1",
                        }
                    ],
                }
            ],
            "metadata": {"result_count": 1},
        }
    )
    by_title = {f.title: f for f in findings}
    assert by_title["Name"].value == "Ada Lovelace"
    assert by_title["Current address"].value == "12 St James Sq, London, England SW1"


def test_missing_fields_are_not_invented():
    findings = findings_from_people(
        {
            "results": [
                {
                    "name": None,
                    "aliases": ["  "],
                    "current_addresses": [{"city": None, "state": ""}],
                    "emails": [],
                    "phones": [{"type": None}],
                }
            ]
        }
    )
    assert findings == []


def test_404_is_empty_not_fabricated(monkeypatch):
    monkeypatch.setenv("WHITEPAGES_API_KEY", "test-key")
    handler: dict = {"response": _FakeResponse(404, {"message": "not found"})}
    _patch_client(monkeypatch, handler)
    result = asyncio.run(WhitepagesProScanner().run(build_query("+14155552671")))
    assert result.status.status == "empty"
    assert result.findings == []
    assert "no reverse-phone match" in result.status.summary.lower()


def test_403_is_error(monkeypatch):
    monkeypatch.setenv("WHITEPAGES_API_KEY", "bad-key")
    handler: dict = {"response": _FakeResponse(403, {"message": "Forbidden"})}
    _patch_client(monkeypatch, handler)
    result = asyncio.run(WhitepagesProScanner().run(build_query("+14155552671")))
    assert result.status.status == "error"
    assert "rejected" in result.status.summary.lower()
    assert "forbidden" in (result.status.error or "").lower()


def test_request_error_is_error(monkeypatch):
    monkeypatch.setenv("WHITEPAGES_API_KEY", "test-key")

    class BoomClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            import httpx

            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.scanners.whitepages_scan.httpx.AsyncClient", BoomClient)
    result = asyncio.run(WhitepagesProScanner().run(build_query("+14155552671")))
    assert result.status.status == "error"
    assert result.status.error


def test_phone_jobs_plan_whitepages():
    query = build_query("+14155552671")
    planned = [s.id for s in all_scanners() if s.applicable(query) or s.optional_key]
    assert "whitepages" in planned
    assert "trestle" in planned
    email = build_query("ada@example.com")
    assert WhitepagesProScanner().applicable(email) is False


def test_email_query_does_not_call_http(monkeypatch):
    monkeypatch.setenv("WHITEPAGES_API_KEY", "test-key")
    called = {"n": 0}

    class BoomClient:
        def __init__(self, *args, **kwargs):
            called["n"] += 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            raise AssertionError("Whitepages accepts phone queries only")

    monkeypatch.setattr("app.scanners.whitepages_scan.httpx.AsyncClient", BoomClient)
    result = asyncio.run(WhitepagesProScanner().run(build_query("ada@example.com")))
    assert result.status.status == "skipped"
    assert called["n"] == 0


def test_200_without_fields_is_empty(monkeypatch):
    monkeypatch.setenv("WHITEPAGES_API_KEY", "test-key")
    handler: dict = {"response": _FakeResponse(200, {"results": [], "metadata": {"result_count": 0}})}
    _patch_client(monkeypatch, handler)
    result = asyncio.run(WhitepagesProScanner().run(build_query("+14155552671")))
    assert result.status.status == "empty"
    assert result.findings == []
    assert "no name" in result.status.summary.lower()
