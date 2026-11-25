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
            row = conn.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
            if row and row[0] != self.identity:
                # Bit positions and interlocks have changed: never reinterpret old masks.
                conn.execute("DELETE FROM frames")
            conn.execute("INSERT OR REPLACE INTO metadata VALUES ('identity', ?)", (self.identity,))

    def write(self, frames, *, replace=False):
        verb = "REPLACE" if replace else "IGNORE"
        with closing(self.connect()) as conn, conn:
            conn.executemany(
                f"INSERT OR {verb} INTO frames VALUES (?, ?, ?, ?, ?, ?, ?)",
                [astuple(frame) for frame in frames],
            )

    def read(self):
        with closing(self.connect()) as conn:
            rows = conn.execute("""
                SELECT f.* FROM frames f WHERE NOT EXISTS
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
