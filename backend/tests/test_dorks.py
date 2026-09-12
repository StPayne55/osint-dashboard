from app.detect import build_query
from app.dorks import build_dorks


def _linkedin_findings(links):
    return [f for f in links if f.title.lower().startswith("linkedin")]


def test_name_dorks_lead_with_linkedin():
    q = build_query("Grace Hopper")
    links = build_dorks(q)
    linkedin = _linkedin_findings(links)
    assert linkedin, "name lookups must surface a LinkedIn-titled finding"
    assert links[0].title.lower().startswith("linkedin")
    assert any("site:linkedin.com" in (f.value or "") for f in linkedin)
    assert any("linkedin.com/in" in (f.value or "") for f in linkedin)
    assert any("linkedin.com/search/results/people" in (f.url or "") for f in linkedin)
    assert any("profile search" in f.title.lower() for f in linkedin)
    assert any("people search" in f.title.lower() for f in linkedin)
    assert "grace hopper" in links[0].value.lower()


def test_email_dorks_include_linkedin_profile_search():
    q = build_query("ada@example.com")
    links = build_dorks(q)
    linkedin = _linkedin_findings(links)
    assert linkedin, "email lookups must surface a LinkedIn-titled finding"
    assert any(i < 3 for i, f in enumerate(links) if f.title.lower().startswith("linkedin"))
    hit = next(f for f in linkedin if "profile search" in f.title.lower())
    assert "site:linkedin.com" in hit.value
    assert "linkedin.com/in" in hit.value
    assert "ada@example.com" in hit.value
    assert "ada" in hit.value.lower()


def test_username_dorks_include_linkedin_profile_search():
    q = build_query("torvalds")
    links = build_dorks(q)
    linkedin = _linkedin_findings(links)
    assert linkedin, "username lookups must surface a LinkedIn-titled finding"
    assert links[0].title.lower().startswith("linkedin")
    hit = next(f for f in linkedin if "profile search" in f.title.lower())
    assert "site:linkedin.com" in hit.value
    assert "linkedin.com/in" in hit.value
    assert "torvalds" in hit.value
    assert "google.com/search" in (hit.url or "")


def test_email_linkedin_dork_keeps_site_scoped():
    """OR terms must stay inside site:linkedin.com/in, not leak to the open web."""
    q = build_query("lisa.m.fraleigh@gmail.com")
    links = build_dorks(q)
    hit = next(f for f in _linkedin_findings(links) if "profile search" in f.title.lower())
    assert "site:linkedin.com/in (" in hit.value
    assert "lisa.m.fraleigh@gmail.com" in hit.value
    assert "lisamfraleigh" in hit.value.lower() or "lisa.m.fraleigh" in hit.value
