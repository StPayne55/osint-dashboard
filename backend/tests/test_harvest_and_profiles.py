import asyncio

from app.consumer_mail import (
    HARVEST_EMAIL_CAP,
    is_consumer_mail_domain,
    keep_harvested_email,
)
from app.detect import build_query
from app.dorks import build_dorks
from app.jobs import _identity
from app.models import Finding, ModuleStatus, ScannerResult
from app.profile_urls import is_concrete_profile_url
from app.scanners.harvester_scan import HarvesterScanner
from app.scanners.phone_scan import PhoneScanner
from app.scanners.twilio_scan import EMPTY_CNAM_NOTE, _findings_from_lookup


def test_consumer_mail_denylist():
    for domain in (
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.co.uk",
        "outlook.com",
        "hotmail.com",
        "hotmail.fr",
        "live.com",
        "icloud.com",
        "me.com",
        "aol.com",
        "protonmail.com",
        "proton.me",
        "gmx.de",
        "mail.com",
        "yandex.ru",
        "zoho.com",
        "qq.com",
    ):
        assert is_consumer_mail_domain(domain), domain
    assert not is_consumer_mail_domain("example.com")
    assert not is_consumer_mail_domain("stripe.com")


def test_keep_harvested_email_company_domain():
    assert keep_harvested_email("ada@acme.com", "ada@acme.com", "acme.com")
    assert keep_harvested_email("ada@mail.acme.com", "other@acme.com", "acme.com")
    assert keep_harvested_email("ada@elsewhere.org", "ada@acme.com", "acme.com")
    assert not keep_harvested_email("unrelated@gmail.com", "ada@acme.com", "acme.com")
    assert HARVEST_EMAIL_CAP == 25


def test_harvester_skips_gmail_without_network():
    q = build_query("stpayne55@gmail.com")
    result = asyncio.run(HarvesterScanner().run(q))
    assert result.status.status == "skipped"
    emails = [f.value for f in result.findings if f.kind == "email"]
    assert emails == ["stpayne55@gmail.com"]
    assert any("consumer" in (f.value or "").lower() for f in result.findings if f.kind == "note")
    assert not any(f.kind == "email" and f.value.endswith("@gmail.com") and f.value != q.email for f in result.findings)


def test_identity_drops_gmail_crtsh_noise():
    q = build_query("stpayne55@gmail.com")
    result = ScannerResult(
        scanner_id="harvester",
        name="harvester",
        status=ModuleStatus(id="harvester", name="harvester", status="success"),
        findings=[
            Finding(kind="email", title="Public email", value="noise1@gmail.com"),
            Finding(kind="email", title="Public email", value="noise2@gmail.com"),
            Finding(kind="email", title="Public email", value="stpayne55@gmail.com"),
            Finding(kind="email", title="Public email", value="other@yahoo.com"),
        ],
    )
    ident = _identity(q, [result])
    assert ident.emails == ["stpayne55@gmail.com"]


def test_profile_url_rejects_site_homepage():
    assert not is_concrete_profile_url(None)
    assert not is_concrete_profile_url("https://instagram.com")
    assert not is_concrete_profile_url("https://instagram.com/")
    assert not is_concrete_profile_url("https://www.instagram.com/")
    assert is_concrete_profile_url("https://instagram.com/someuser")
    assert is_concrete_profile_url("https://github.com/torvalds")
    assert is_concrete_profile_url("https://x.com/torvalds")


def test_ignorant_instagram_is_note_not_profile(monkeypatch):
    scanner = PhoneScanner()
    monkeypatch.setattr(
        scanner,
        "_ignorant",
        lambda *_a, **_k: {
            "checked": 1,
            "exists": [{"name": "instagram", "domain": "instagram.com", "exists": True}],
        },
    )
    q = build_query("+14155552671")
    result = asyncio.run(scanner.run(q))
    profiles = [f for f in result.findings if f.kind == "profile"]
    notes = [f for f in result.findings if f.kind == "note"]
    assert profiles == []
    assert any("instagram" in (f.title + f.value).lower() for f in notes)
    assert all(not (f.url or "").rstrip("/").endswith("instagram.com") for f in result.findings)
    assert result.findings[0].extra.get("carrier") or any(
        f.title == "Carrier (dataset)" or f.title == "Line type" for f in result.findings
    )


def test_phone_dorks_include_reverse_lookup_links():
    q = build_query("+14155552671")
    links = build_dorks(q)
    urls = " ".join(f.url or "" for f in links)
    titles = " ".join(f.title for f in links)
    for needle in (
        "whitepages.com",
        "thatsthem.com",
        "fastpeoplesearch.com",
        "truepeoplesearch.com",
        "spokeo.com",
        "411.com",
    ):
        assert needle in urls, needle
    assert "Manual reverse lookup" in titles
    assert "OpenCNAM" in titles


def test_twilio_empty_cnam_is_honest():
    findings, name = _findings_from_lookup(
        {"phone_number": "+14155552671", "caller_name": {"caller_name": None, "caller_type": None}}
    )
    assert name is None
    cnam_notes = [f for f in findings if f.title.startswith("Caller name")]
    assert cnam_notes
    assert cnam_notes[0].kind == "note"
    assert cnam_notes[0].value == EMPTY_CNAM_NOTE
    assert "no caller name on file" in cnam_notes[0].value.lower()
    assert "error" not in cnam_notes[0].value.lower()
    missing_field, missing_name = _findings_from_lookup({"phone_number": "+14155552671"})
    assert missing_name is None
    assert any(f.value == EMPTY_CNAM_NOTE for f in missing_field)
    named, got = _findings_from_lookup(
        {"caller_name": {"caller_name": "MODERN ATMOSPHERE LLC", "caller_type": "UNDETERMINED"}}
    )
    assert got == "MODERN ATMOSPHERE LLC"
    assert any(f.kind == "metadata" and f.title.startswith("Caller name") for f in named)


def test_twilio_cnam_quota_error_stays_error():
    findings, name = _findings_from_lookup(
        {"caller_name": {"caller_name": None, "error_code": 60627}}
    )
    assert name is None
    note = next(f for f in findings if f.title.startswith("Caller name"))
    assert "error" in note.value.lower()
    assert "60627" in note.value
    assert note.value != EMPTY_CNAM_NOTE
