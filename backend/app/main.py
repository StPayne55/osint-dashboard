from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.config import APP_NAME, APP_VERSION
from app.detect import build_query, detect_type
from app.jobs import JobStore, RateLimited, run_job, sse_events
from app.models import QueryType, ScanAccepted, ScanRequest
from app.scanners import all_scanners

STORE = JobStore()

app = FastAPI(title=APP_NAME, version=APP_VERSION, docs_url="/api/docs", redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "name": APP_NAME, "version": APP_VERSION}


@app.get("/api/catalog")
async def catalog() -> dict:
    scanners = [s.info().model_dump() for s in all_scanners()]
    return {
        "app": APP_NAME,
        "honesty": (
            "Every module uses public or open-source checks. Nothing here queries "
            "credential dumps, paid people-search scrapers, or private accounts."
        ),
        "scanners": scanners,
    }


@app.get("/api/detect")
async def detect(q: str, type: QueryType = QueryType.auto) -> dict:
    query = build_query(q, type)
    guessed = detect_type(q)
    return {"guessed": guessed.value, "query": query.model_dump()}


@app.post("/api/scans", response_model=ScanAccepted)
async def start_scan(body: ScanRequest, request: Request) -> ScanAccepted:
    client = request.client.host if request.client else "local"
    try:
        STORE.check_rate(client)
    except RateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit: wait {exc.retry_after}s",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    try:
        query = build_query(body.query, body.type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = STORE.create(query)
    import asyncio

    asyncio.create_task(run_job(job))
    planned = [s.id for s in all_scanners() if s.applicable(query) or s.optional_key]
    return ScanAccepted(job_id=job.id, query=query, scanners=planned)


@app.get("/api/scans/{job_id}")
async def get_scan(job_id: str) -> dict:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown or expired scan")
    return job.report().model_dump()


@app.get("/api/scans/{job_id}/export.json")
async def export_scan(job_id: str) -> JSONResponse:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown or expired scan")
    payload = job.report().model_dump()
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": f'attachment; filename="osint-desk-{job_id}.json"'
        },
    )


@app.get("/api/scans/{job_id}/events")
async def scan_events(job_id: str) -> StreamingResponse:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown or expired scan")

    async def stream():
        async for event in sse_events(job):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@app.get("/{path:path}")
async def spa(path: str):
    if path.startswith("api"):
        raise HTTPException(status_code=404, detail="Not found")
    if not DIST.is_dir():
        raise HTTPException(status_code=404, detail="UI not built")
    candidate = DIST / path
    if path and candidate.is_file():
        return FileResponse(candidate)
    index = DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="UI not built")
