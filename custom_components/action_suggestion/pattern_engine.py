"""Frequency/consistency engine - no ML, no model, just counting. Sits
between storage.py (raw persistence) and coordinator.py (event handling /
entity state): applies the "is this actually a reliable habit" thresholds
from the config entry's options to storage's raw pattern rows.

"Consistency" here means: out of every time this exact (entity, weekday,
time_bucket, context) situation has come up, what fraction of the time did
the person do *this specific* thing - as opposed to raw frequency, which
would treat "did X 20 times, but also Y 20 times and Z 20 times in the same
situation" the same as "did X 20 times and nothing else ever". Only the
former is a genuine habit worth suggesting.
"""

from __future__ import annotations

from .storage import PatternStorage, QualifyingPattern


def record_event(
    storage: PatternStorage,
    *,
    entity_id: str,
    new_state: str,
    weekday: int,
    time_bucket: int,
    context_hash: str,
    decay_factor: float,
    now_iso: str,
) -> None:
    """Thin pass-through to storage - kept here rather than called
    directly from the coordinator so all "what counts as reinforcing a
    pattern" logic has one home, in case that grows beyond a straight
    insert later (e.g. capping how many raw `events` rows are kept)."""
    storage.record_event(
        entity_id=entity_id,
        new_state=new_state,
        weekday=weekday,
        time_bucket=time_bucket,
        context_hash=context_hash,
        decay_factor=decay_factor,
        now_iso=now_iso,
    )


def best_qualifying_pattern(
    storage: PatternStorage,
    *,
    entity_id: str,
    weekday: int,
    time_bucket: int,
    context_hash: str,
    min_observations: int,
    min_consistency: float,
) -> QualifyingPattern | None:
    """The single outcome to suggest for this exact situation, if any -
    whichever recorded outcome has the highest consistency, but only
    returned at all if it clears *both* configured thresholds. A context
    with e.g. "on" at 55% and "off" at 45% consistency returns nothing
    rather than picking "on" just because it's the larger of two
    unreliable numbers."""
    candidates = storage.get_patterns_for_context(
        entity_id=entity_id,
        weekday=weekday,
        time_bucket=time_bucket,
        context_hash=context_hash,
    )
    qualifying = [
        pattern
        for pattern in candidates
        if pattern.observations >= min_observations and pattern.consistency >= min_consistency
    ]
    if not qualifying:
        return None
    return max(qualifying, key=lambda pattern: pattern.consistency)
