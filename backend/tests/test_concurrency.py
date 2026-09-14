import asyncio
import time

from app.detect import build_query
from app.jobs import (
    Job,
    _run_scanner,
    heavy_scanner_gate,
    is_heavy_scanner,
    reset_heavy_gate,
)
from app.models import Finding, Query, QueryType, ScannerResult
from app.scanners import all_scanners
from app.scanners.base import Scanner


class FakeScanner(Scanner):
    tool = "fake"
    description = "test double"
    accepts = [QueryType.email, QueryType.username, QueryType.name]
    timeout = 5.0

    def __init__(
        self,
        sid: str,
        *,
        heavy: bool = False,
        delay: float = 0.08,
        hold: asyncio.Event | None = None,
    ) -> None:
        self.id = sid
        self.name = sid
        self.heavy = heavy
        self.delay = delay
        self.hold = hold

    async def run(self, query: Query) -> ScannerResult:
        if self.hold is not None:
            await self.hold.wait()
        else:
            await asyncio.sleep(self.delay)
        return self._result(
            "success",
            "ok",
            findings=[Finding(kind="note", title=self.id, value="ok")],
        )


def _scanner_statuses(job: Job, scanner_id: str) -> list[str]:
    return [
        str(event["status"])
        for event in job.history
        if event.get("type") == "scanner" and event.get("id") == scanner_id
    ]


def test_registered_heavy_scanners():
    heavy = {s.id for s in all_scanners() if is_heavy_scanner(s)}
    assert heavy == {"holehe", "socialscan", "sherlock", "maigret", "spiderfoot"}
    light = {s.id for s in all_scanners() if not is_heavy_scanner(s)}
    for sid in ("usernames", "email_intel", "gravatar", "dorks", "twilio", "hibp", "whitepages", "trestle"):
        assert sid in light


def test_heavy_scanners_do_not_run_concurrently_when_limit_is_one():
    reset_heavy_gate(1)
    current = 0
    peak = 0
    light_ran_during_heavy = False
    heavy_entered = asyncio.Event()

    class Tracked(FakeScanner):
        async def run(self, query: Query) -> ScannerResult:
            nonlocal current, peak, light_ran_during_heavy
            if self.heavy:
                current += 1
                peak = max(peak, current)
                heavy_entered.set()
            else:
                await heavy_entered.wait()
                light_ran_during_heavy = current > 0
            try:
                await asyncio.sleep(self.delay)
            finally:
                if self.heavy:
                    current -= 1
            return self._result("success", "ok")

    async def go() -> None:
        job = Job(build_query("ada@example.com"))
        scanners = [
            Tracked("h1", heavy=True, delay=0.12),
            Tracked("h2", heavy=True, delay=0.12),
            Tracked("h3", heavy=True, delay=0.12),
            Tracked("gravatar", heavy=False, delay=0.04),
        ]
        await asyncio.gather(*[_run_scanner(job, s) for s in scanners])
        assert {s.id for s in scanners} <= set(job.results)

    asyncio.run(go())
    assert peak == 1
    assert light_ran_during_heavy is True


def test_heavy_emits_queued_until_slot_then_running():
    reset_heavy_gate(1)
    release = asyncio.Event()

    async def go() -> None:
        job = Job(build_query("ada@example.com"))
        first = FakeScanner("holehe", heavy=True, hold=release)
        second = FakeScanner("maigret", heavy=True, delay=0.01)
        t1 = asyncio.create_task(_run_scanner(job, first))
        for _ in range(50):
            if "running" in _scanner_statuses(job, "holehe"):
                break
            await asyncio.sleep(0.01)
        assert "running" in _scanner_statuses(job, "holehe")
        t2 = asyncio.create_task(_run_scanner(job, second))
        for _ in range(50):
            if "queued" in _scanner_statuses(job, "maigret"):
                break
            await asyncio.sleep(0.01)
        assert _scanner_statuses(job, "holehe")[0] == "queued"
        assert "running" in _scanner_statuses(job, "holehe")
        assert _scanner_statuses(job, "maigret")[0] == "queued"
        assert "running" not in _scanner_statuses(job, "maigret")
        live = {m.id: m.status for m in job.report().modules}
        assert live["holehe"] == "running"
        assert live["maigret"] == "queued"
        release.set()
        await asyncio.gather(t1, t2)
        assert "running" in _scanner_statuses(job, "maigret")
        assert job.results["maigret"].status.status == "success"
        assert job.results["holehe"].status.status == "success"

    asyncio.run(go())


def test_light_scanners_start_while_heavy_holds_slot():
    reset_heavy_gate(1)
    release = asyncio.Event()

    async def go() -> None:
        job = Job(build_query("ada@example.com"))
        heavy = FakeScanner("sherlock", heavy=True, hold=release)
        light = FakeScanner("gravatar", heavy=False, delay=0.01)
        t_heavy = asyncio.create_task(_run_scanner(job, heavy))
        t_light = asyncio.create_task(_run_scanner(job, light))
        await t_light
        assert _scanner_statuses(job, "gravatar")[0] == "running"
        assert job.results["gravatar"].status.status == "success"
        assert "sherlock" not in job.results
        release.set()
        await t_heavy

    asyncio.run(go())


def test_skipped_heavy_does_not_hold_slot():
    reset_heavy_gate(1)

    class SkipHeavy(FakeScanner):
        def applicable(self, query: Query) -> bool:
            return False

        def skip_reason(self, query: Query) -> str | None:
            return "Does not accept this query"

    async def go() -> None:
        job = Job(build_query("ada@example.com"))
        skip = SkipHeavy("holehe", heavy=True, delay=2.0)
        other = FakeScanner("maigret", heavy=True, delay=0.01)
        started = time.monotonic()
        await asyncio.gather(_run_scanner(job, skip), _run_scanner(job, other))
        assert time.monotonic() - started < 1.0
        assert job.results["holehe"].status.status == "skipped"
        assert job.results["maigret"].status.status == "success"
        assert heavy_scanner_gate()._value == 1

    asyncio.run(go())


def test_concurrency_two_allows_two_heavy():
    reset_heavy_gate(2)
    current = 0
    peak = 0

    class Tracked(FakeScanner):
        async def run(self, query: Query) -> ScannerResult:
            nonlocal current, peak
            current += 1
            peak = max(peak, current)
            try:
                await asyncio.sleep(0.12)
            finally:
                current -= 1
            return self._result("success", "ok")

    async def go() -> None:
        job = Job(build_query("ada@example.com"))
        await asyncio.gather(
            *[_run_scanner(job, Tracked(f"h{i}", heavy=True)) for i in range(3)]
        )

    asyncio.run(go())
    assert peak == 2
