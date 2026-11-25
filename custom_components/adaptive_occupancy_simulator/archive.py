"""AOS-owned compact SQLite archive. Never opens or modifies Recorder's DB."""

import json
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import astuple
from pathlib import Path

from .model import Frame


class Archive:
    """Short per-job transactions; call every method in an executor."""

    def __init__(self, path, identity):
        self.path = Path(path)
        self.identity = json.dumps(identity, sort_keys=True)

    def connect(self):
        return sqlite3.connect(self.path, timeout=20)

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn, conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS frames (
                    ts INTEGER PRIMARY KEY, mask INTEGER, minute INTEGER, weekend INTEGER,
                    elevation REAL, eligible INTEGER, reason TEXT);
                CREATE TABLE IF NOT EXISTS exclusions (
                    id INTEGER PRIMARY KEY, start INTEGER, end INTEGER, reason TEXT);
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(frames)")}
            for name, declaration in (
                ("known_mask", "INTEGER"),
                ("baseline_eligible", "INTEGER DEFAULT 0"),
                ("origin", "TEXT DEFAULT 'legacy'"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE frames ADD COLUMN {name} {declaration}")
            row = conn.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
            if row and row[0] != self.identity:
                # Bit positions and interlocks have changed: never reinterpret old masks.
                conn.execute("DELETE FROM frames")
            conn.execute("INSERT OR REPLACE INTO metadata VALUES ('identity', ?)", (self.identity,))

    def write(self, frames, *, replace=False):
        columns = "ts,mask,minute,weekend,elevation,eligible,reason,known_mask,baseline_eligible,origin"
        update = ",".join(f"{key}=excluded.{key}" for key in columns.split(",")[1:])
        # Preserve live observations and legacy complete/unsafe frames. Re-scan only
        # legacy light_unknown rows to recover partial evidence with current gates.
        guard = (
            ""
            if replace
            else " WHERE frames.origin='import' OR (frames.origin='legacy' AND frames.reason='light_unknown')"
        )
        with closing(self.connect()) as conn, conn:
            conn.executemany(
                f"INSERT INTO frames ({columns}) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ts) DO UPDATE SET {update}{guard}",
                [(*astuple(frame), "live" if replace else "import") for frame in frames],
            )

    def read(self):
        with closing(self.connect()) as conn:
            rows = conn.execute("""
                SELECT f.ts,f.mask,f.minute,f.weekend,f.elevation,f.eligible,f.reason,f.known_mask,f.baseline_eligible FROM frames f WHERE NOT EXISTS
                (SELECT 1 FROM exclusions e WHERE f.ts >= e.start AND f.ts < e.end)
                ORDER BY ts
            """).fetchall()
        return [Frame(*row) for row in rows]

    def exclude(self, start, end, reason):
        if end <= start:
            raise ValueError("Exclusion end must follow start")
        with closing(self.connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO exclusions(start,end,reason) VALUES (?, ?, ?)", (start, end, reason[:200])
            )
            return cur.lastrowid

    def close_exclusion(self, exclusion_id, end):
        with closing(self.connect()) as conn, conn:
            conn.execute("UPDATE exclusions SET end=? WHERE id=?", (end, exclusion_id))

    def close_abandoned_sessions(self, keep_id, end):
        """Recover a crash between opening an interval and persisting intent."""
        with closing(self.connect()) as conn, conn:
            conn.execute(
                "UPDATE exclusions SET end=? WHERE end=32503680000 "
                "AND reason='AOS enabled session' AND id != ?",
                (end, keep_id if keep_id is not None else -1),
            )

    def prune(self, before):
        with closing(self.connect()) as conn, conn:
            conn.execute("DELETE FROM frames WHERE ts < ?", (before,))
            conn.execute("DELETE FROM exclusions WHERE end < ?", (before,))

    def summary(self):
        with closing(self.connect()) as conn:
            counts = dict(conn.execute("SELECT reason, count(*) FROM frames GROUP BY reason"))
            bounds = conn.execute("SELECT min(ts), max(ts), count(*) FROM frames").fetchone()
            exclusions = [
                dict(zip(("id", "start", "end", "reason"), row, strict=True))
                for row in conn.execute("SELECT * FROM exclusions ORDER BY start DESC LIMIT 100")
            ]
        return {
            "counts": dict(Counter(counts)),
            "first": bounds[0],
            "last": bounds[1],
            "frames": bounds[2],
            "exclusions": exclusions,
        }
