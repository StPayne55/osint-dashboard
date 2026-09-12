from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict, deque
from typing import Any, AsyncIterator

from app.config import (
    HEAVY_SCANNER_CONCURRENCY,
    JOB_TTL_SEC,
    MAX_JOBS,
    RATE_LIMIT_SCANS,
    RATE_LIMIT_WINDOW_SEC,
)
from app.consumer_mail import HARVEST_EMAIL_CAP, email_local_part, is_consumer_mail_domain
from app.models import Finding, IdentitySummary, ModuleStatus, PHONE_HONESTY, Query, QueryType, Report, ScannerResult
from app.profile_urls import is_concrete_profile_url
from app.scanners import all_scanners
from app.scanners.base import Scanner

Event = dict[str, Any]

_heavy_sema: asyncio.Semaphore | None = None


def is_heavy_scanner(scanner: Scanner) -> bool:
    return bool(getattr(scanner, "heavy", False))


def reset_heavy_gate(concurrency: int | None = None) -> asyncio.Semaphore:
    """Replace the shared heavy-scanner semaphore (tests / config reload)."""
    global _heavy_sema
    n = max(1, concurrency if concurrency is not None else HEAVY_SCANNER_CONCURRENCY)
    _heavy_sema = asyncio.Semaphore(n)
    return _heavy_sema


def heavy_scanner_gate() -> asyncio.Semaphore:
    if _heavy_sema is None:
        return reset_heavy_gate()
    return _heavy_sema


class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many scans from this address")
        self.retry_after = retry_after


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    def check_rate(self, client_id: str) -> None:
        now = time.time()
        bucket = self._hits[client_id]
        while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SEC:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_SCANS:
            retry = int(RATE_LIMIT_WINDOW_SEC - (now - bucket[0])) + 1
            raise RateLimited(max(retry, 1))
        bucket.append(now)

    def get(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job and time.time() - job.created_at > JOB_TTL_SEC:
            self._jobs.pop(job_id, None)
            return None
        return job

    def create(self, query: Query) -> Job:
        self._gc()
        job = Job(query)
        self._jobs[job.id] = job
        return job

    def _gc(self) -> None:
        now = time.time()
        expired = [k for k, j in self._jobs.items() if now - j.created_at > JOB_TTL_SEC]
        for k in expired:
            self._jobs.pop(k, None)
        if len(self._jobs) > MAX_JOBS:
            oldest = sorted(self._jobs.values(), key=lambda j: j.created_at)
            for job in oldest[: len(self._jobs) - MAX_JOBS]:
                self._jobs.pop(job.id, None)


class Job:
    def __init__(self, query: Query) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.created_at = time.time()
        self.query = query
        self.history: list[Event] = []
        self.subscribers: list[asyncio.Queue[Event | None]] = []
        self.results: dict[str, ScannerResult] = {}
        self.module_state: dict[str, str] = {}
        self.status = "queued"
        self.finished_at: float | None = None

    def subscribe(self) -> asyncio.Queue[Event | None]:
        q: asyncio.Queue[Event | None] = asyncio.Queue()
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event | None]) -> None:
        if q in self.subscribers:
            self.subscribers.remove(q)

    def emit(self, event: Event) -> None:
        self.history.append(event)
        for q in list(self.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def report(self) -> Report:
        findings: dict[str, list[Finding]] = {}
        modules: list[ModuleStatus] = []
        for scanner in all_scanners():
            result = self.results.get(scanner.id)
            if result:
                findings[scanner.id] = result.findings
                modules.append(result.status)
            else:
                live = self.module_state.get(scanner.id)
                if live not in {"queued", "running"}:
                    live = "queued" if self.status != "completed" else "skipped"
                modules.append(
                    ModuleStatus(
                        id=scanner.id,
                        name=scanner.name,
                        status=live,  # type: ignore[arg-type]
                    )
                )
        identity = _identity(self.query, list(self.results.values()))
        honesty = PHONE_HONESTY if self.query.type == QueryType.phone else None
        report_kwargs: dict[str, Any] = dict(
            job_id=self.id,
            status=self.status,  # type: ignore[arg-type]
            created_at=self.created_at,
            finished_at=self.finished_at,
            query=self.query,
            identity=identity,
            modules=modules,
            findings=findings,
        )
        if honesty:
            report_kwargs["honesty"] = honesty
        return Report(**report_kwargs)


def _identity(query: Query, results: list[ScannerResult]) -> IdentitySummary:
    emails: list[str] = []
    phones: list[str] = []
    usernames: list[str] = []
    notes: list[str] = []
    profiles = 0
    images = 0
    phone_carrier: str | None = None
    phone_region: str | None = None
    phone_line_type: str | None = None
    caller_name: str | None = None
    if query.email:
        emails.append(query.email)
    if query.phone_e164:
        phones.append(query.phone_e164)
    usernames.extend(query.username_candidates)
    for result in results:
        for finding in result.findings:
            if finding.kind == "email" and finding.value not in emails:
                emails.append(finding.value)
            elif finding.kind == "phone" and finding.value not in phones:
                phones.append(finding.value)
            elif finding.kind == "username" and finding.value not in usernames:
                usernames.append(finding.value)
            elif finding.kind == "profile":
                if is_concrete_profile_url(finding.url):
                    profiles += 1
            elif finding.kind == "image":
                images += 1
            elif finding.kind == "note":
                notes.append(finding.value)

            title = (finding.title or "").strip().lower()
            extra = finding.extra or {}
            if finding.kind in {"metadata", "phone", "note"}:
                if title in {"carrier", "carrier (dataset)"} and finding.value:
                    phone_carrier = phone_carrier or finding.value
                if title in {"region", "location"} and finding.value:
                    phone_region = phone_region or finding.value
                if title in {"line type"} and finding.value:
                    phone_line_type = phone_line_type or finding.value
                if title in {"caller name (cnam)", "caller name"} and finding.kind == "metadata":
                    caller_name = caller_name or finding.value
            if extra.get("carrier") and not phone_carrier:
                phone_carrier = str(extra["carrier"])
            if extra.get("region") and not phone_region:
                phone_region = str(extra["region"])
            if extra.get("line_type") and not phone_line_type:
                phone_line_type = str(extra["line_type"])

    if query.email and is_consumer_mail_domain(query.domain):
        q = query.email.lower()
        q_local = email_local_part(q)
        emails = [
            e
            for e in emails
            if e.lower() == q or email_local_part(e) == q_local
        ]

    return IdentitySummary(
        query=query,
        emails=emails[:HARVEST_EMAIL_CAP],
        phones=phones[:20],
        usernames=usernames[:20],
        profiles=profiles,
        images=images,
        notes=notes[:8],
        phone_carrier=phone_carrier,
        phone_region=phone_region,
        phone_line_type=phone_line_type,
        caller_name=caller_name,
    )


async def run_job(job: Job) -> None:
    job.status = "running"
    scanners = all_scanners()
    job.emit(
        {
            "type": "job",
            "status": "started",
            "job_id": job.id,
            "query": job.query.model_dump(),
            "scanners": [s.info().model_dump() for s in scanners],
        }
    )
    tasks = [asyncio.create_task(_run_scanner(job, scanner)) for scanner in scanners]
    await asyncio.gather(*tasks, return_exceptions=True)
    job.status = "completed"
    job.finished_at = time.time()
    report = job.report()
    job.emit(
        {
            "type": "job",
            "status": "completed",
            "job_id": job.id,
            "report": report.model_dump(),
        }
    )


async def _run_scanner(job: Job, scanner: Scanner) -> None:
    skip = scanner.skip_reason(job.query)
    if skip and not scanner.applicable(job.query):
        result = scanner._result("skipped", skip)
        job.results[scanner.id] = result
        job.emit({"type": "scanner", "id": scanner.id, "status": "skipped", "result": result.model_dump()})
        return
    if skip and not scanner.available() and scanner.optional_key is None:
        result = scanner._result("unavailable", skip, error=skip)
        job.results[scanner.id] = result
        job.emit({"type": "scanner", "id": scanner.id, "status": "unavailable", "result": result.model_dump()})
        return

    if is_heavy_scanner(scanner):
        job.module_state[scanner.id] = "queued"
        job.emit({"type": "scanner", "id": scanner.id, "name": scanner.name, "status": "queued"})
        async with heavy_scanner_gate():
            await _execute_scanner(job, scanner)
        return
    await _execute_scanner(job, scanner)


async def _execute_scanner(job: Job, scanner: Scanner) -> None:
    job.module_state[scanner.id] = "running"
    job.emit({"type": "scanner", "id": scanner.id, "name": scanner.name, "status": "running"})
    started = time.time()
    try:
        # Timeout starts after the heavy-scanner slot is acquired so queued
        # wait time does not burn the module wall clock.
        result = await asyncio.wait_for(scanner.run(job.query), timeout=scanner.timeout)
    except asyncio.TimeoutError:
        result = scanner._result(
            "timeout",
            f"Timed out after {int(scanner.timeout)}s",
            error="timeout",
            duration_ms=int(scanner.timeout * 1000),
        )
    except Exception as exc:
        result = scanner._result("error", "Scanner crashed", error=str(exc))
    result.status.duration_ms = int((time.time() - started) * 1000)
    result.status.finding_count = len(result.findings)
    job.results[scanner.id] = result
    job.module_state.pop(scanner.id, None)
    job.emit(
        {
            "type": "scanner",
            "id": scanner.id,
            "status": result.status.status,
            "result": result.model_dump(),
        }
    )


async def sse_events(job: Job) -> AsyncIterator[Event]:
    queue = job.subscribe()
    try:
        for event in list(job.history):
            yield event
            if event.get("type") == "job" and event.get("status") in {"completed", "failed"}:
                return
        while True:
            event = await queue.get()
            if event is None:
                return
            yield event
            if event.get("type") == "job" and event.get("status") in {"completed", "failed"}:
                return
    finally:
        job.unsubscribe(queue)
