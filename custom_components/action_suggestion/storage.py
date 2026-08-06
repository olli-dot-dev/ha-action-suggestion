"""Own SQLite storage - deliberately not the Recorder DB (spec: "nicht die
Recorder-DB, die zu kurz vorhält") and not a `homeassistant.helpers.storage`
Store() either (those are whole-file JSON, awkward for the
insert-one-row-at-a-time / aggregate-by-key access pattern here). Every
method in this module is a plain blocking sqlite3 call - always run via
`hass.async_add_executor_job(...)` from the coordinator, never awaited
directly.

Three tables:
- `events`: one row per learned (manual) state change - the raw log,
  mainly for future re-aggregation/debugging rather than being queried on
  the suggestion hot path.
- `context_totals`: entity_id+weekday+time_bucket+context_hash -> how many
  times this exact situation has been observed at all, *any* outcome. Not
  in the spec's own table sketch, but required to compute "consistency" -
  without a denominator, `patterns.weight` alone can't tell "always does A"
  apart from "does A, B, C about equally often".
- `patterns`: one row per entity_id+new_state+weekday+time_bucket+
  context_hash - the decayed weight and raw observation count for one
  specific outcome in one specific situation. A single context can have
  several rows (e.g. "on" and "off" both observed at 18:00 on Mondays);
  consistency = observations / context_totals.total_observations picks out
  whichever outcome actually dominates.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime


@dataclass
class QualifyingPattern:
    entity_id: str
    new_state: str
    weekday: int
    time_bucket: int
    context_hash: str
    weight: float
    observations: int
    last_seen: str
    consistency: float


class PatternStorage:
    """Not thread-safe by itself - each method opens and closes its own
    connection, so it's safe to call from whichever executor thread HA
    happens to schedule the job on, at the cost of a little overhead per
    call. Fine at this scale (a handful of writes per manual action, a
    lookup every few minutes - see const.ACTIVE_SUGGESTIONS_REFRESH_INTERVAL_MINUTES)."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def setup(self) -> None:
        """Creates the schema if it doesn't exist yet. Safe to call every
        startup."""
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    new_state TEXT NOT NULL,
                    weekday INTEGER NOT NULL,
                    time_bucket INTEGER NOT NULL,
                    context_hash TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_lookup
                    ON events(entity_id, weekday, time_bucket, context_hash);

                CREATE TABLE IF NOT EXISTS context_totals (
                    entity_id TEXT NOT NULL,
                    weekday INTEGER NOT NULL,
                    time_bucket INTEGER NOT NULL,
                    context_hash TEXT NOT NULL,
                    total_observations INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (entity_id, weekday, time_bucket, context_hash)
                );

                CREATE TABLE IF NOT EXISTS patterns (
                    entity_id TEXT NOT NULL,
                    new_state TEXT NOT NULL,
                    weekday INTEGER NOT NULL,
                    time_bucket INTEGER NOT NULL,
                    context_hash TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 0,
                    observations INTEGER NOT NULL DEFAULT 0,
                    last_seen TEXT NOT NULL,
                    PRIMARY KEY (entity_id, new_state, weekday, time_bucket, context_hash)
                );
                """
            )
            conn.commit()

    def record_event(
        self,
        *,
        entity_id: str,
        new_state: str,
        weekday: int,
        time_bucket: int,
        context_hash: str,
        decay_factor: float,
        now_iso: str,
    ) -> None:
        """Logs the raw event, bumps the context's total-observations
        counter, and applies decay+1 to the (entity, new_state, weekday,
        time_bucket, context_hash) pattern row that just happened - see
        module docstring for why only that one row, not its siblings for
        the same context."""
        with closing(self._connect()) as conn:
            conn.execute(
                """INSERT INTO events (entity_id, new_state, weekday, time_bucket, context_hash, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (entity_id, new_state, weekday, time_bucket, context_hash, now_iso),
            )
            conn.execute(
                """INSERT INTO context_totals (entity_id, weekday, time_bucket, context_hash, total_observations)
                   VALUES (?, ?, ?, ?, 1)
                   ON CONFLICT(entity_id, weekday, time_bucket, context_hash)
                   DO UPDATE SET total_observations = total_observations + 1""",
                (entity_id, weekday, time_bucket, context_hash),
            )
            conn.execute(
                """INSERT INTO patterns
                       (entity_id, new_state, weekday, time_bucket, context_hash, weight, observations, last_seen)
                   VALUES (?, ?, ?, ?, ?, 1, 1, ?)
                   ON CONFLICT(entity_id, new_state, weekday, time_bucket, context_hash)
                   DO UPDATE SET
                       weight = weight * ? + 1,
                       observations = observations + 1,
                       last_seen = ?""",
                (entity_id, new_state, weekday, time_bucket, context_hash, now_iso, decay_factor, now_iso),
            )
            conn.commit()

    def get_patterns_for_context(
        self, *, entity_id: str, weekday: int, time_bucket: int, context_hash: str
    ) -> list[QualifyingPattern]:
        """All observed outcomes for one exact (entity, weekday,
        time_bucket, context) combination, with consistency already
        computed against that context's total. Used by the coordinator to
        check "is there a pattern due right now" - see coordinator.py."""
        with closing(self._connect()) as conn:
            total_row = conn.execute(
                """SELECT total_observations FROM context_totals
                   WHERE entity_id = ? AND weekday = ? AND time_bucket = ? AND context_hash = ?""",
                (entity_id, weekday, time_bucket, context_hash),
            ).fetchone()
            if total_row is None or total_row["total_observations"] == 0:
                return []
            total = total_row["total_observations"]

            rows = conn.execute(
                """SELECT * FROM patterns
                   WHERE entity_id = ? AND weekday = ? AND time_bucket = ? AND context_hash = ?""",
                (entity_id, weekday, time_bucket, context_hash),
            ).fetchall()
            return [
                QualifyingPattern(
                    entity_id=row["entity_id"],
                    new_state=row["new_state"],
                    weekday=row["weekday"],
                    time_bucket=row["time_bucket"],
                    context_hash=row["context_hash"],
                    weight=row["weight"],
                    observations=row["observations"],
                    last_seen=row["last_seen"],
                    consistency=row["observations"] / total,
                )
                for row in rows
            ]

    def get_all_context_keys(self, entity_ids: set[str]) -> set[tuple[str, int, int, str]]:
        """Every distinct (entity_id, weekday, time_bucket, context_hash)
        combination that has ever been recorded for the given entities -
        the coordinator walks this set each refresh to find out which ones
        are due *right now* (see coordinator.py `_async_refresh_active`),
        rather than re-deriving it from `events` on every single check."""
        if not entity_ids:
            return set()
        with closing(self._connect()) as conn:
            placeholders = ",".join("?" for _ in entity_ids)
            rows = conn.execute(
                f"""SELECT DISTINCT entity_id, weekday, time_bucket, context_hash
                    FROM context_totals WHERE entity_id IN ({placeholders})""",
                tuple(entity_ids),
            ).fetchall()
            return {(row["entity_id"], row["weekday"], row["time_bucket"], row["context_hash"]) for row in rows}

    def prune(self, weight_floor: float, decay_factor: float) -> int:
        """Ages every pattern by calendar time since it was last observed,
        then deletes whatever falls below `weight_floor`.

        `record_event`'s decay only fires when a pattern's *own* outcome
        recurs (see module docstring) - weight is monotonically
        non-decreasing there, it can shrink only *relative* to a
        competing outcome that keeps getting reinforced while this one
        doesn't. That's enough for "the currently dominant outcome wins",
        but not for "a habit nobody has done in eight months should stop
        being suggested even if nothing else ever competed with it" -
        which needs weight to fade with real elapsed time, not just on a
        hit. So here, once per call (see __init__.py - once per
        startup/reload, not continuously): multiply each row's weight by
        `decay_factor` for every whole week since `last_seen`, i.e. the
        same per-hit decay formula's factor, just applied against the
        calendar instead of against new observations. A pattern that's
        still being reinforced regularly never accumulates enough elapsed
        weeks to matter; one that's gone quiet keeps fading until it
        crosses `weight_floor` and gets removed. Returns the number of
        rows removed."""
        with closing(self._connect()) as conn:
            now = datetime.now()
            rows = conn.execute("SELECT rowid, weight, last_seen FROM patterns").fetchall()
            for row in rows:
                weeks_elapsed = max(0.0, (now - datetime.fromisoformat(row["last_seen"])).days / 7)
                if weeks_elapsed < 1:
                    continue
                aged_weight = row["weight"] * (decay_factor**weeks_elapsed)
                conn.execute("UPDATE patterns SET weight = ? WHERE rowid = ?", (aged_weight, row["rowid"]))

            cursor = conn.execute("DELETE FROM patterns WHERE weight < ?", (weight_floor,))
            conn.commit()
            return cursor.rowcount

    def reset(self) -> None:
        """Wipes all learned data - used by the `reset` service (see
        __init__.py) mainly for testing/troubleshooting, not something a
        normal user needs day to day."""
        with closing(self._connect()) as conn:
            conn.executescript("DELETE FROM events; DELETE FROM context_totals; DELETE FROM patterns;")
            conn.commit()
