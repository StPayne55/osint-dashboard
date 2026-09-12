from app.detect import build_query
from app.jobs import Job, _identity
from app.models import Finding, ModuleStatus, ScannerResult
from app.photos import (
    collect_photo_findings,
    normalize_photo_url,
    photo_dedupe_key,
    photos_from_extra,
    promote_extra_photos,
)
from app.scanners.gravatar_scan import findings_from_profile_entry, gravatar_avatar_url


def _image(url: str, title: str = "Photo", extra: dict | None = None) -> Finding:
    return Finding(kind="image", title=title, value=url, url=url, extra=extra or {})


def test_normalize_rejects_unsafe_and_upgrades_http():
    assert normalize_photo_url("javascript:alert(1)") is None
    assert normalize_photo_url("data:image/png;base64,aaa") is None
    assert normalize_photo_url("http://127.0.0.1/secret.png") is None
    assert normalize_photo_url("https://localhost/x.png") is None
    assert normalize_photo_url("//avatars.githubusercontent.com/u/1") == (
        "https://avatars.githubusercontent.com/u/1"
    )
    assert normalize_photo_url("http://cdn.example.com/a.jpg") == "https://cdn.example.com/a.jpg"
    assert normalize_photo_url("not-a-url") is None


def test_gravatar_urls_dedupe_across_hosts_and_query():
    a = "https://www.gravatar.com/avatar/abc123?s=256&d=404"
    b = "https://secure.gravatar.com/avatar/abc123"
    assert photo_dedupe_key(a) == photo_dedupe_key(b) == "gravatar:abc123"


def test_photos_from_extra_walks_ids_and_known_keys():
    urls = photos_from_extra(
        {
            "username": "torvalds",
            "ids": {
                "name": "Linus Torvalds",
                "image": {"url": "https://avatars.githubusercontent.com/u/1024025"},
            },
            "avatar": "https://cdn.example.com/other.png",
        }
    )
    assert "https://avatars.githubusercontent.com/u/1024025" in urls
    assert "https://cdn.example.com/other.png" in urls


def test_collect_photo_findings_merges_kind_image_and_extra():
    findings = [
        _image(
            "https://www.gravatar.com/avatar/abc?s=256&d=404",
            "Gravatar avatar",
            {"source": "gravatar"},
        ),
        Finding(
            kind="profile",
            title="GitHub",
            value="https://github.com/torvalds",
            url="https://github.com/torvalds",
            extra={
                "source": "maigret",
                "ids": {"image": "https://avatars.githubusercontent.com/u/1024025?v=4"},
            },
        ),
        Finding(
            kind="profile",
            title="GitHub",
            value="https://github.com/torvalds",
            url="https://github.com/torvalds",
            extra={"ids": {"photo": "https://avatars.githubusercontent.com/u/1024025"}},
        ),
    ]
    photos = collect_photo_findings(findings)
    urls = {f.url for f in photos}
    assert "https://www.gravatar.com/avatar/abc?s=256&d=404" in urls
    assert any(u and "avatars.githubusercontent.com/u/1024025" in u for u in urls)
    assert len(photos) == 2


def test_promote_extra_photos_appends_missing_image_findings():
    findings = [
        Finding(
            kind="profile",
            title="GitLab",
            value="https://gitlab.com/ada",
            url="https://gitlab.com/ada",
            extra={"ids": {"avatar": "https://cdn.example.com/ada.png"}},
        )
    ]
    promoted = promote_extra_photos(findings)
    images = [f for f in promoted if f.kind == "image"]
    assert len(images) == 1
    assert images[0].url == "https://cdn.example.com/ada.png"
    assert images[0].title == "GitLab photo"


def test_identity_counts_harvested_extra_photos():
    q = build_query("torvalds")
    result = ScannerResult(
        scanner_id="maigret",
        name="Maigret",
        status=ModuleStatus(id="maigret", name="Maigret", status="success"),
        findings=[
            Finding(
                kind="profile",
                title="GitHub",
                value="https://github.com/torvalds",
                url="https://github.com/torvalds",
                extra={"ids": {"image": "https://avatars.githubusercontent.com/u/1024025"}},
            )
        ],
    )
    ident = _identity(q, [result])
    assert ident.images == 1
    assert ident.profiles == 1


def test_report_promotes_extra_photos_into_findings():
    job = Job(build_query("torvalds"))
    job.results["maigret"] = ScannerResult(
        scanner_id="maigret",
        name="Maigret",
        status=ModuleStatus(id="maigret", name="Maigret", status="success"),
        findings=[
            Finding(
                kind="profile",
                title="GitHub",
                value="https://github.com/torvalds",
                url="https://github.com/torvalds",
                extra={"ids": {"image": "https://avatars.githubusercontent.com/u/1024025"}},
            )
        ],
    )
    report = job.report()
    images = [f for f in report.findings.get("maigret", []) if f.kind == "image"]
    assert images and images[0].url.startswith("https://avatars.githubusercontent.com/")
    assert report.identity and report.identity.images == 1


def test_gravatar_profile_entry_emits_deduped_photos():
    digest = "abc123def"
    entry = {
        "displayName": "Ada",
        "thumbnailUrl": f"https://secure.gravatar.com/avatar/{digest}",
        "photos": [
            {"value": f"https://www.gravatar.com/avatar/{digest}?s=80", "type": "thumbnail"},
            {"value": "https://cdn.example.com/ada-extra.jpg"},
        ],
        "accounts": [{"shortname": "github", "url": "https://github.com/ada", "display": "ada"}],
    }
    findings = findings_from_profile_entry(entry, digest)
    promoted = promote_extra_photos(
        [
            Finding(
                kind="image",
                title="Gravatar avatar",
                value=gravatar_avatar_url(digest),
                url=gravatar_avatar_url(digest),
                extra={"hash": digest, "source": "gravatar"},
            ),
            *findings,
        ]
    )
    images = [f for f in promoted if f.kind == "image"]
    urls = {f.url for f in images}
    assert any("gravatar.com/avatar" in (u or "") for u in urls)
    assert "https://cdn.example.com/ada-extra.jpg" in urls
    assert len(images) == 2
    assert any(f.kind == "profile" and f.url == "https://github.com/ada" for f in findings)
