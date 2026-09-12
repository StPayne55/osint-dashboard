from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.models import Finding, ModuleStatus, Query, QueryType, ScannerInfo, ScannerResult


class Scanner(ABC):
    id: str
    name: str
    tool: str
    description: str
    accepts: list[QueryType]
    optional_key: str | None = None
    limitations: str = ""
    timeout: float = 45.0
    # Network-heavy social crawlers share HEAVY_SCANNER_CONCURRENCY slots.
    heavy: bool = False

    def applicable(self, query: Query) -> bool:
        return query.type in self.accepts

    def available(self) -> bool:
        return True

    def skip_reason(self, query: Query) -> str | None:
        if not self.applicable(query):
            return f"Does not accept {query.type.value} queries"
        if not self.available():
            return "Scanner unavailable in this environment"
        return None

    def info(self) -> ScannerInfo:
        return ScannerInfo(
            id=self.id,
            name=self.name,
            tool=self.tool,
            description=self.description,
            accepts=self.accepts,
            optional_key=self.optional_key,
            limitations=self.limitations,
            available=self.available(),
        )

    def _result(
        self,
        status: str,
        summary: str,
        findings: list[Finding] | None = None,
        raw: Any = None,
        error: str | None = None,
        duration_ms: int = 0,
    ) -> ScannerResult:
        if status == "success" and not findings:
            status = "empty"
            summary = summary or "No public hits"
        return ScannerResult(
            scanner_id=self.id,
            name=self.name,
            status=ModuleStatus(
                id=self.id,
                name=self.name,
                status=status,  # type: ignore[arg-type]
                summary=summary,
                error=error,
                duration_ms=duration_ms,
                finding_count=len(findings or []),
            ),
            findings=findings or [],
            raw=raw,
        )

    @abstractmethod
    async def run(self, query: Query) -> ScannerResult:
        raise NotImplementedError
