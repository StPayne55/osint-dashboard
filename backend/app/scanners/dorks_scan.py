from __future__ import annotations

from app.dorks import build_dorks
from app.models import Query, QueryType, ScannerResult
from app.scanners.base import Scanner


class DorkScanner(Scanner):
    id = "dorks"
    name = "Search links / dorks"
    tool = "built-in"
    description = (
        "Generates Google, DuckDuckGo, Bing, LinkedIn, Facebook, and public-records "
        "style queries. Opens in the user's browser — this module never scrapes those engines."
    )
    accepts = [QueryType.email, QueryType.phone, QueryType.username, QueryType.name]
    limitations = (
        "Links only — this module never scrapes those engines. Phone reports include "
        "labeled reverse-lookup search links (Whitepages, Thatsthem, FastPeopleSearch, "
        "TruePeopleSearch, Spokeo, 411). Commercial people-search sites are not queried "
        "via API. Name/address hits must be reviewed manually."
    )
    timeout = 2.0

    def applicable(self, query: Query) -> bool:
        return True

    async def run(self, query: Query) -> ScannerResult:
        findings = build_dorks(query)
        return self._result(
            "success",
            f"{len(findings)} search / dork links",
            findings=findings,
        )
