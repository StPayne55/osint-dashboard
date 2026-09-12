from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class QueryType(str, Enum):
    auto = "auto"
    email = "email"
    phone = "phone"
    username = "username"
    name = "name"


class Query(BaseModel):
    raw: str
    type: QueryType
    email: str | None = None
    phone_e164: str | None = None
    phone_national: str | None = None
    phone_country_code: str | None = None
    username: str | None = None
    name: str | None = None
    domain: str | None = None
    username_candidates: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    kind: Literal[
        "email",
        "phone",
        "profile",
        "image",
        "link",
        "note",
        "metadata",
        "username",
        "breach",
    ]
    title: str
    value: str
    url: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ScannerInfo(BaseModel):
    id: str
    name: str
    tool: str
    description: str
    accepts: list[QueryType]
    optional_key: str | None = None
    limitations: str
    available: bool = True


class ModuleStatus(BaseModel):
    id: str
    name: str
    status: Literal[
        "queued",
        "running",
        "success",
        "empty",
        "error",
        "timeout",
        "skipped",
        "unavailable",
    ] = "queued"
    summary: str = ""
    error: str | None = None
    duration_ms: int = 0
    finding_count: int = 0


class ScannerResult(BaseModel):
    scanner_id: str
    name: str
    status: ModuleStatus
    findings: list[Finding] = Field(default_factory=list)
    raw: Any = None


class ScanRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    type: QueryType = QueryType.auto


class IdentitySummary(BaseModel):
    query: Query
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    usernames: list[str] = Field(default_factory=list)
    profiles: int = 0
    images: int = 0
    notes: list[str] = Field(default_factory=list)
    phone_carrier: str | None = None
    phone_region: str | None = None
    phone_line_type: str | None = None
    caller_name: str | None = None


class Report(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    created_at: float
    finished_at: float | None = None
    query: Query
    identity: IdentitySummary | None = None
    modules: list[ModuleStatus] = Field(default_factory=list)
    findings: dict[str, list[Finding]] = Field(default_factory=dict)
    honesty: str = (
        "This report is assembled from public, open-source checks only. "
        "It is not a government or commercial people-search dossier. "
        "Empty modules mean no public hit — not that the person has no accounts."
    )


PHONE_HONESTY = (
    "Free phone scanners report carrier, region, line type, and whether a "
    "number appears registered on a few public sites. They cannot name the "
    "subscriber. A caller name (CNAM) only appears if you set Twilio Lookup "
    "keys — empty CNAM is left empty, never invented. Use the labeled reverse-lookup "
    "search links (Whitepages, Thatsthem, FastPeopleSearch, TruePeopleSearch, "
    "Spokeo, 411) for manual follow-up."
)


class ScanAccepted(BaseModel):
    job_id: str
    query: Query
    scanners: list[str]
