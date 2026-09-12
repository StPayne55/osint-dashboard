"""Salvage SpiderFoot scan events from the per-run SQLite DB.

sf.py -o json prints ``[`` immediately and ``]`` only when the scan finishes.
Killing the process group therefore often yields empty/truncated stdout even
when ``sfp__stor_db`` already committed ACCOUNT/SOCIAL rows. On timeout we
mark the scan ABORTED (same as sf.py's SIGINT handler) and read those rows.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger("spiderfoot-runner")

# Keep in sync with cli.OUTPUT_TYPE_CODES
DEFAULT_TYPE_CODES = (
    "ACCOUNT_EXTERNAL_OWNED",
    "SIMILAR_ACCOUNT_EXTERNAL",
    "SOCIAL_MEDIA",
    "USERNAME",
    "EMAILADDR",
    "HUMAN_NAME",
    "PHONE_NUMBER",
)


def find_scan_db(*homes: Path | str | None) -> Path | None:
    """Locate spiderfoot.db under HOME / SPIDERFOOT_DATA / SPIDERFOOT_HOME."""
    seen: set[Path] = set()
    candidates: list[Path] = []
    for home in homes:
        if not home:
            continue
        root = Path(home)
        candidates.extend(
            (
                root / "spiderfoot.db",
                root / ".spiderfoot" / "spiderfoot.db",
            )
        )
        if root.is_dir():
            try:
                for found in root.rglob("spiderfoot.db"):
                    candidates.append(found)
            except OSError:
                pass
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.is_file():
            return path
    return None


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=8)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=4000")
    except sqlite3.Error:
        pass
    return conn


def _latest_scan_id(conn: sqlite3.Connection, target: str | None) -> str | None:
    if target:
        quoted = f'"{target}"'
        row = conn.execute(
            """
            SELECT guid FROM tbl_scan_instance
            WHERE seed_target IN (?, ?) OR name IN (?, ?)
            ORDER BY created DESC LIMIT 1
            """,
            (target, quoted, target, quoted),
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    row = conn.execute(
        "SELECT guid FROM tbl_scan_instance ORDER BY created DESC LIMIT 1"
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def abort_scan(db_path: Path, scan_id: str) -> bool:
    """Set scan status ABORTED, matching sf.py handle_abort."""
    try:
        with _connect(db_path) as conn:
            conn.execute(
                """
                UPDATE tbl_scan_instance
                SET status = ?, ended = ?
                WHERE guid = ?
                """,
                ("ABORTED", int(time.time() * 1000), scan_id),
            )
            conn.commit()
            return True
    except sqlite3.Error as exc:
        log.warning("Could not mark scan %s ABORTED: %s", scan_id, exc)
        return False


def _rows_to_events(
    rows: Iterable[sqlite3.Row],
    type_codes: tuple[str, ...],
) -> list[dict[str, Any]]:
    allowed = set(type_codes)
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        type_code = str(row["type"] or "")
        if type_code == "ROOT":
            continue
        if allowed and type_code not in allowed:
            continue
        data = row["data"]
        if data is None:
            continue
        data_text = data if isinstance(data, str) else str(data)
        module = str(row["module"] or "")
        source = row["source"] if "source" in row.keys() else ""
        source_text = "" if source is None else str(source)
        key = (type_code, data_text, module)
        if key in seen:
            continue
        seen.add(key)
        events.append(
            {
                "type": type_code,
                "data": data_text,
                "module": module,
                "source": source_text,
            }
        )
    return events


def query_scan_events(
    db_path: Path,
    scan_id: str,
    type_codes: tuple[str, ...] = DEFAULT_TYPE_CODES,
) -> list[dict[str, Any]]:
    sql = """
        SELECT r.type AS type, r.data AS data, r.module AS module,
               COALESCE(s.data, '') AS source
        FROM tbl_scan_results r
        LEFT JOIN tbl_scan_results s
          ON s.hash = r.source_event_hash
         AND s.scan_instance_id = r.scan_instance_id
        WHERE r.scan_instance_id = ?
          AND r.type <> 'ROOT'
        ORDER BY r.generated ASC
    """
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with _connect(db_path) as conn:
                rows = conn.execute(sql, (scan_id,)).fetchall()
            return _rows_to_events(rows, type_codes)
        except sqlite3.Error as exc:
            last_error = exc
            time.sleep(0.25 * (attempt + 1))
    log.warning("Could not query events for scan %s: %s", scan_id, last_error)
    return []


def salvage_scan_events(
    *homes: Path | str | None,
    target: str | None = None,
    scan_id: str | None = None,
    abort: bool = True,
    type_codes: tuple[str, ...] = DEFAULT_TYPE_CODES,
) -> tuple[list[dict[str, Any]], str | None]:
    """Find the temp scan DB, optionally abort, and return (events, scan_id)."""
    db_path = find_scan_db(*homes)
    if db_path is None:
        return [], None
    try:
        with _connect(db_path) as conn:
            resolved_id = scan_id or _latest_scan_id(conn, target)
    except sqlite3.Error as exc:
        log.warning("Could not open SpiderFoot DB %s: %s", db_path, exc)
        return [], None
    if not resolved_id:
        return [], None
    if abort:
        abort_scan(db_path, resolved_id)
    events = query_scan_events(db_path, resolved_id, type_codes=type_codes)
    type_counts: dict[str, int] = {}
    for event in events:
        key = str(event.get("type") or "?") or "?"
        type_counts[key] = type_counts.get(key, 0) + 1
    type_text = ", ".join(f"{k}={v}" for k, v in sorted(type_counts.items())) or "none"
    log.info(
        "Salvaged %s event(s) from %s scan %s types: %s",
        len(events),
        db_path,
        resolved_id,
        type_text,
    )
    return events, resolved_id


def merge_events(
    primary: list[dict[str, Any]],
    extra: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for event in primary + extra:
        key = (
            str(event.get("type") or ""),
            str(event.get("data") or ""),
            str(event.get("module") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(event)
    return out
