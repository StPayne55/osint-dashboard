from __future__ import annotations

from app.models import Finding, Query, QueryType, ScannerResult
from app.scanners.base import Scanner


class UsernameCandidateScanner(Scanner):
    id = "usernames"
    name = "Username candidates"
    tool = "built-in"
    description = (
        "Derives likely handles from a name or email local-part "
        "(firstlast, first.last, flast, …). Used as input hints for Sherlock/socialscan."
    )
    accepts = [QueryType.email, QueryType.name, QueryType.username]
    limitations = "Guesses only. Not evidence the person uses these handles."
    timeout = 2.0

    def applicable(self, query: Query) -> bool:
        return bool(query.username or query.username_candidates)

    async def run(self, query: Query) -> ScannerResult:
        findings = [
            Finding(kind="username", title="Candidate", value=c)
            for c in query.username_candidates
        ]
        if query.username and query.username not in query.username_candidates:
            findings.insert(0, Finding(kind="username", title="Primary", value=query.username))
        summary = (
            f"{len(findings)} candidate handle(s)"
            if findings
            else "Could not derive username candidates"
        )
        return self._result("success", summary, findings=findings, raw=query.username_candidates)
