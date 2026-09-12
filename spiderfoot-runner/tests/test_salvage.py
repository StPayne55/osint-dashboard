import sqlite3
import subprocess
from pathlib import Path

import cli
from salvage import (
    abort_scan,
    find_scan_db,
    merge_events,
    salvage_scan_events,
)


ACCOUNT_DATA = (
    "GitHub (Category: coding)\n<SFURL>https://github.com/torvalds</SFURL>"
)
SOCIAL_DATA = "Twitter: https://twitter.com/torvalds"


def write_fake_db(
    path: Path,
    scan_id: str = "SCAN1",
    *,
    target: str = "torvalds",
    status: str = "RUNNING",
    extra_rows: list[tuple] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE tbl_scan_instance (
            guid VARCHAR NOT NULL PRIMARY KEY,
            name VARCHAR NOT NULL,
            seed_target VARCHAR NOT NULL,
            created INT DEFAULT 0,
            started INT DEFAULT 0,
            ended INT DEFAULT 0,
            status VARCHAR NOT NULL
        );
        CREATE TABLE tbl_scan_results (
            scan_instance_id VARCHAR NOT NULL,
            hash VARCHAR NOT NULL,
            type VARCHAR NOT NULL,
            generated INT NOT NULL,
            confidence INT NOT NULL DEFAULT 100,
            visibility INT NOT NULL DEFAULT 100,
            risk INT NOT NULL DEFAULT 0,
            module VARCHAR NOT NULL,
            data VARCHAR,
            false_positive INT NOT NULL DEFAULT 0,
            source_event_hash VARCHAR DEFAULT 'ROOT'
        );
        """
    )
    conn.execute(
        "INSERT INTO tbl_scan_instance VALUES (?,?,?,?,?,?,?)",
        (scan_id, target, target, 1_000, 1_000, 0, status),
    )
    conn.execute(
        "INSERT INTO tbl_scan_results VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (scan_id, "ROOTHASH", "ROOT", 1, 100, 100, 0, "", target, 0, "ROOT"),
    )
    conn.execute(
        "INSERT INTO tbl_scan_results VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            scan_id,
            "h1",
            "ACCOUNT_EXTERNAL_OWNED",
            2,
            100,
            100,
            0,
            "sfp_accounts",
            ACCOUNT_DATA,
            0,
            "ROOTHASH",
        ),
    )
    conn.execute(
        "INSERT INTO tbl_scan_results VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            scan_id,
            "h2",
            "SOCIAL_MEDIA",
            3,
            100,
            100,
            0,
            "sfp_social",
            SOCIAL_DATA,
            0,
            "ROOTHASH",
        ),
    )
    conn.execute(
        "INSERT INTO tbl_scan_results VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            scan_id,
            "h3",
            "EMAILADDR_COMPROMISED",
            4,
            100,
            100,
            0,
            "sfp_haveibeenpwned",
            "pwned@example.com",
            0,
            "ROOTHASH",
        ),
    )
    for row in extra_rows or []:
        conn.execute(
            "INSERT INTO tbl_scan_results VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )
    conn.commit()
    conn.close()
    return path


def test_find_scan_db_under_home_and_data_dir(tmp_path):
    home = tmp_path / "run"
    db = home / ".spiderfoot" / "spiderfoot.db"
    write_fake_db(db)
    assert find_scan_db(home) == db
    assert find_scan_db(home / ".spiderfoot") == db
    assert find_scan_db(tmp_path / "missing") is None


def test_salvage_returns_account_social_and_aborts(tmp_path, caplog):
    import logging

    db = write_fake_db(tmp_path / "spiderfoot.db")
    with caplog.at_level(logging.INFO, logger="spiderfoot-runner"):
        events, scan_id = salvage_scan_events(tmp_path, target="torvalds")
    assert scan_id == "SCAN1"
    types = {e["type"] for e in events}
    assert types == {"ACCOUNT_EXTERNAL_OWNED", "SOCIAL_MEDIA"}
    assert any("github.com/torvalds" in e["data"] for e in events)
    assert any("twitter.com/torvalds" in e["data"] for e in events)
    assert not any("pwned" in e["data"] for e in events)
    conn = sqlite3.connect(str(db))
    status = conn.execute("SELECT status FROM tbl_scan_instance").fetchone()[0]
    conn.close()
    assert status == "ABORTED"
    assert "ACCOUNT_EXTERNAL_OWNED=1" in caplog.text
    assert "SOCIAL_MEDIA=1" in caplog.text


def test_abort_scan_and_latest_scan_fallback(tmp_path):
    write_fake_db(tmp_path / "spiderfoot.db", scan_id="OTHER", target="someone")
    assert abort_scan(tmp_path / "spiderfoot.db", "OTHER") is True
    events, scan_id = salvage_scan_events(tmp_path, abort=False)
    assert scan_id == "OTHER"
    assert events


def test_merge_events_dedups():
    a = {"type": "USERNAME", "data": "x", "module": "sfp_accounts"}
    assert merge_events([a], [a, {"type": "USERNAME", "data": "y", "module": "sfp"}]) == [
        a,
        {"type": "USERNAME", "data": "y", "module": "sfp"},
    ]


def test_build_command_default_threads_is_8(monkeypatch, tmp_path):
    monkeypatch.delenv("SPIDERFOOT_MAX_THREADS", raising=False)
    cmd = cli.build_command("torvalds", tmp_path / "sf.py", ["sfp_accounts"])
    assert cmd[cmd.index("-max-threads") + 1] == "8"
    monkeypatch.setenv("SPIDERFOOT_MAX_THREADS", "3")
    cmd = cli.build_command("torvalds", tmp_path / "sf.py", ["sfp_accounts"])
    assert cmd[cmd.index("-max-threads") + 1] == "3"


def test_timeout_salvages_partial_events_from_sqlite(monkeypatch, tmp_path):
    home = tmp_path / "sf"
    home.mkdir()
    (home / "sf.py").write_text("# fake\n", encoding="utf-8")
    monkeypatch.setenv("SPIDERFOOT_HOME", str(home))
    monkeypatch.setenv("SPIDERFOOT_ABORT_GRACE", "1")
    monkeypatch.setattr(cli.os, "killpg", lambda *_a, **_k: None)

    class Proc:
        pid = 4242
        returncode = None
        calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(cmd="sf.py", timeout=timeout)
            return "[", "scan still running after wall clock\n"

        def poll(self):
            return -9 if self.calls > 1 else None

        def send_signal(self, _sig):
            return None

        def kill(self):
            self.returncode = -9

    def fake_popen(_cmd, **kwargs):
        env = kwargs.get("env") or {}
        data = Path(env["SPIDERFOOT_DATA"])
        write_fake_db(data / "spiderfoot.db")
        return Proc()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    result = cli.run_spiderfoot("torvalds", modules=["sfp_accounts"], timeout=10)
    assert result["status"] == "timeout"
    assert result["error"] == "timeout after 10s"
    assert result["salvaged"] is True
    assert result["scan_id"] == "SCAN1"
    assert any("github.com/torvalds" in e["data"] for e in result["events"])
    assert any(e["type"] == "SOCIAL_MEDIA" for e in result["events"])
    assert "wall clock" in result["stderr_excerpt"]
    assert result["stdout_excerpt"] == "["


def test_event_type_counts_format_salvaged_types():
    events = [
        {"type": "ACCOUNT_EXTERNAL_OWNED", "data": ACCOUNT_DATA, "module": "sfp_accounts"},
        {"type": "SOCIAL_MEDIA", "data": SOCIAL_DATA, "module": "sfp_social"},
        {"type": "USERNAME", "data": "torvalds", "module": "sfp_accounts"},
        {"type": "USERNAME", "data": "other", "module": "sfp_accounts"},
    ]
    counts = cli.event_type_counts(events)
    assert counts == {
        "ACCOUNT_EXTERNAL_OWNED": 1,
        "SOCIAL_MEDIA": 1,
        "USERNAME": 2,
    }
    assert cli.format_event_type_counts(counts) == (
        "ACCOUNT_EXTERNAL_OWNED=1, SOCIAL_MEDIA=1, USERNAME=2"
    )
    assert cli.format_event_type_counts({}) == "none"
