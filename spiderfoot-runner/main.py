"""Tiny FastAPI wrapper that runs SpiderFoot OSS v4.0 CLI off the event loop."""

from __future__ import annotations

import asyncio
import hmac
import os

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cli import run_spiderfoot, sanitize_modules, sf_script_path

app = FastAPI(title="OSINT Desk SpiderFoot runner", docs_url=None, redoc_url=None)
_scan_lock = asyncio.Lock()


class ScanRequest(BaseModel):
    target: str = Field(min_length=1, max_length=256)
    modules: list[str] | None = None
    timeout: int = Field(default=180, ge=10, le=600)


def _expected_token() -> str:
    return os.getenv("SPIDERFOOT_RUNNER_TOKEN", "").strip()


def require_bearer(authorization: str | None) -> None:
    expected = _expected_token()
    if not expected:
        raise HTTPException(status_code=503, detail="SPIDERFOOT_RUNNER_TOKEN is not set")
    if not authorization:
        raise HTTPException(status_code=401, detail="missing bearer token")
    scheme, _, token = authorization.partition(" ")
    provided = token.strip()
    if scheme.lower() != "bearer" or not provided:
        raise HTTPException(status_code=401, detail="missing bearer token")
    want = expected.encode("utf-8")
    got = provided.encode("utf-8")
    if len(got) != len(want) or not hmac.compare_digest(got, want):
        raise HTTPException(status_code=401, detail="invalid token")


@app.get("/health")
async def health() -> JSONResponse:
    present = sf_script_path() is not None
    payload = {"ok": present, "spiderfoot": present}
    return JSONResponse(payload, status_code=200 if present else 503)


@app.post("/v1/scan")
async def scan(
    body: ScanRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    require_bearer(authorization)
    modules = sanitize_modules(body.modules)
    async with _scan_lock:
        return await asyncio.to_thread(
            run_spiderfoot,
            body.target.strip(),
            modules,
            body.timeout,
        )
