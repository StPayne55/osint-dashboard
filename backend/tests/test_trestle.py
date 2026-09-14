import asyncio

from app.detect import build_query
from app.jobs import _identity
from app.scanners import all_scanners
from app.scanners.trestle_scan import (
    TRESTLE_REVERSE_PHONE_URL,
    TrestleReversePhoneScanner,
    findings_from_reverse_phone,
)
from app.scanners.whitepages_scan import WhitepagesProScanner


# Official sample shape from https://docs.trestleiq.com/api-reference/reverse-phone-api
OFFICIAL_FIXTURE = {
    "id": "Phone.3dbb6fef-a2df-4b08-cfe3-bc7128b6f5b4",
    "phone_number": "2069735100",
    "is_valid": True,
    "country_calling_code": "1",
    "line_type": "NonFixedVOIP",
    "carrier": "Trestle Telco",
    "is_prepaid": False,
    "is_commercial": True,
    "owners": [
        {
            "id": "Person.fffdcf06-0929-4b5a-9921-ee49b101ca84",
            "name": "Waidong L Syrws",
            "firstname": "Waidong",
            "middlename": "L",
            "lastname": "Syrws",
            "alternate_names": ["Sryws W L"],
            "age_range": "25-29",
            "gender": None,
            "type": "Person",
            "link_to_phone_start_date": "2019-03-23",
            "industry": None,
            "current_addresses": [
                {
                    "id": "Location.d1a40ed5-a70a-46f8-80a9-bb4ac27e3a01",
                    "location_type": "Address",
                    "street_line_1": "100 Syrws St",
                    "street_line_2": "Ste 1",
                    "city": "Lynden",
                    "postal_code": "98264",
                    "zip4": "98264-9999",
                    "state_code": "WA",
                    "country_code": "US",
                }
            ],
            "emails": [{"address": "waidong@example.com"}],
        }
    ],
    "error": None,
    "warnings": [],
}


def test_trestle_registered_alongside_whitepages():
    ids = [s.id for s in all_scanners()]
    assert "trestle" in ids
    assert "whitepages" in ids
    scanner = next(s for s in all_scanners() if s.id == "trestle")
    assert scanner.name == "Trestle Reverse Phone"
    assert scanner.optional_key == "TRESTLE_API_KEY"
    assert scanner.accepts[0].value == "phone"
    whitepages = next(s for s in all_scanners() if s.id == "whitepages")
    assert whitepages.optional_key == "WHITEPAGES_API_KEY"


def test_available_only_when_key_set(monkeypatch):
    monkeypatch.delenv("TRESTLE_API_KEY", raising=False)
    assert TrestleReversePhoneScanner().available() is False
    monkeypatch.setenv("TRESTLE_API_KEY", "  test-key  ")
    assert TrestleReversePhoneScanner().available() is True


def test_skipped_without_key_does_not_call_http(monkeypatch):
    monkeypatch.delenv("TRESTLE_API_KEY", raising=False)
    called = {"n": 0}

    class BoomClient:
        def __init__(self, *args, **kwargs):
            called["n"] += 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            raise AssertionError("Trestle must not be called without a key")

    monkeypatch.setattr("app.scanners.trestle_scan.httpx.AsyncClient", BoomClient)
    result = asyncio.run(TrestleReversePhoneScanner().run(build_query("+14155552671")))
    assert result.status.status == "skipped"
    assert "TRESTLE_API_KEY" in result.status.summary
    assert result.findings == []
    assert called["n"] == 0


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

    monkeypatch.setattr("app.scanners.trestle_scan.httpx.AsyncClient", FakeClient)


def test_reverse_phone_emits_only_returned_fields(monkeypatch):
    monkeypatch.setenv("TRESTLE_API_KEY", "test-key")
    handler: dict = {"response": _FakeResponse(200, OFFICIAL_FIXTURE)}
    _patch_client(monkeypatch, handler)

    result = asyncio.run(TrestleReversePhoneScanner().run(build_query("+12069735100")))
    assert result.status.status == "success"
    assert handler["url"] == TRESTLE_REVERSE_PHONE_URL
    assert handler["params"]["phone"] == "+12069735100"
    assert handler["params"]["phone.country_hint"] == "US"
    assert handler["headers"]["x-api-key"] == "test-key"

    by_title = {f.title: f for f in result.findings}
    assert by_title["Name"].value == "Waidong L Syrws"
    assert by_title["Name"].kind == "note"
    assert by_title["Name"].extra.get("source") == "trestle"
    assert by_title["Alternate name"].value == "Sryws W L"
    assert by_title["Current address"].value == "100 Syrws St Ste 1, Lynden, WA 98264"
    assert by_title["Current address"].extra.get("city") == "Lynden"
    assert by_title["Email"].kind == "email"
    assert by_title["Email"].value == "waidong@example.com"
    assert by_title["Line type"].value == "NonFixedVOIP"
    assert by_title["Carrier"].value == "Trestle Telco"
    assert by_title["Commercial"].value == "commercial line"
    assert "Prepaid" not in by_title
    values = " ".join(f.value for f in result.findings)
    assert "25-29" not in values
    assert "2019-03-23" not in values

    ident = _identity(build_query("+12069735100"), [result])
    assert ident.caller_name is None
    assert "waidong@example.com" in ident.emails


def test_missing_fields_are_not_invented():
    findings = findings_from_reverse_phone(
        {
            "is_valid": True,
            "line_type": None,
            "carrier": "",
            "owners": [
                {
                    "name": None,
                    "firstname": "",
                    "lastname": "   ",
                    "current_addresses": [{"city": None, "state_code": ""}],
                    "emails": [],
                }
            ],
        }
    )
    assert findings == []


def test_belongs_to_and_historical_address():
    findings = findings_from_reverse_phone(
        {
            "belongs_to": [
                {
                    "firstname": "Ada",
                    "lastname": "Lovelace",
                    "historical_addresses": [
                        {
                            "street_line_1": "12 St James Sq",
                            "city": "London",
                            "postal_code": "SW1",
                            "country_code": "GB",
                        }
                    ],
                }
            ]
        }
    )
    by_title = {f.title: f for f in findings}
    assert by_title["Name"].value == "Ada Lovelace"
    assert "12 St James Sq" in by_title["Historical address"].value
    assert "London" in by_title["Historical address"].value
    assert by_title["Historical address"].value.endswith("GB")


def test_404_is_empty_not_fabricated(monkeypatch):
    monkeypatch.setenv("TRESTLE_API_KEY", "test-key")
    handler: dict = {"response": _FakeResponse(404, {"error": "not found"})}
    _patch_client(monkeypatch, handler)
    result = asyncio.run(TrestleReversePhoneScanner().run(build_query("+14155552671")))
    assert result.status.status == "empty"
    assert result.findings == []
    assert "no reverse-phone match" in result.status.summary.lower()


def test_403_is_error(monkeypatch):
    monkeypatch.setenv("TRESTLE_API_KEY", "bad-key")
    handler: dict = {
        "response": _FakeResponse(
            403,
            {"errorCode": "INVALID_API_KEY", "message": "The API key provided is invalid"},
        )
    }
    _patch_client(monkeypatch, handler)
    result = asyncio.run(TrestleReversePhoneScanner().run(build_query("+14155552671")))
    assert result.status.status == "error"
    assert "rejected" in result.status.summary.lower()
    assert "invalid" in (result.status.error or "").lower()


def test_request_error_is_error(monkeypatch):
    monkeypatch.setenv("TRESTLE_API_KEY", "test-key")

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

    monkeypatch.setattr("app.scanners.trestle_scan.httpx.AsyncClient", BoomClient)
    result = asyncio.run(TrestleReversePhoneScanner().run(build_query("+14155552671")))
    assert result.status.status == "error"
    assert result.status.error


def test_phone_jobs_plan_trestle_and_whitepages():
    query = build_query("+14155552671")
    planned = [s.id for s in all_scanners() if s.applicable(query) or s.optional_key]
    assert "trestle" in planned
    assert "whitepages" in planned
    email = build_query("ada@example.com")
    assert TrestleReversePhoneScanner().applicable(email) is False
    assert WhitepagesProScanner().applicable(email) is False


def test_email_query_does_not_call_http(monkeypatch):
    monkeypatch.setenv("TRESTLE_API_KEY", "test-key")
    called = {"n": 0}

    class BoomClient:
        def __init__(self, *args, **kwargs):
            called["n"] += 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            raise AssertionError("Trestle accepts phone queries only")

    monkeypatch.setattr("app.scanners.trestle_scan.httpx.AsyncClient", BoomClient)
    result = asyncio.run(TrestleReversePhoneScanner().run(build_query("ada@example.com")))
    assert result.status.status == "skipped"
    assert called["n"] == 0


def test_200_without_fields_is_empty(monkeypatch):
    monkeypatch.setenv("TRESTLE_API_KEY", "test-key")
    handler: dict = {
        "response": _FakeResponse(
            200,
            {"is_valid": True, "owners": [], "line_type": None, "carrier": None},
        )
    }
    _patch_client(monkeypatch, handler)
    result = asyncio.run(TrestleReversePhoneScanner().run(build_query("+14155552671")))
    assert result.status.status == "empty"
    assert result.findings == []
    assert "no name" in result.status.summary.lower()


def test_e164_preferred_over_national(monkeypatch):
    monkeypatch.setenv("TRESTLE_API_KEY", "test-key")
    handler: dict = {"response": _FakeResponse(200, {"is_valid": True, "owners": []})}
    _patch_client(monkeypatch, handler)
    query = build_query("4155552671")
    assert query.phone_e164
    result = asyncio.run(TrestleReversePhoneScanner().run(query))
    assert result.status.status == "empty"
    assert handler["params"]["phone"] == query.phone_e164
    assert handler["params"]["phone"].startswith("+")
