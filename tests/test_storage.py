"""Standalone tests for storage.py - no Home Assistant dependency at all
(unlike classification.py/context.py/coordinator.py, which can't be
imported without homeassistant installed), so these actually run and
verify the SQL/decay/consistency logic for real rather than relying on
manual review alone.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from _load import load_module

PatternStorage = load_module("storage").PatternStorage


def make_storage(tmp_path: Path) -> PatternStorage:
    storage = PatternStorage(str(tmp_path / "patterns.db"))
    storage.setup()
    return storage


def test_record_event_creates_pattern_and_context_total(tmp_path):
    storage = make_storage(tmp_path)
    storage.record_event(
        entity_id="light.wohnzimmer",
        new_state="on",
        weekday=0,
        time_bucket=1080,
        context_hash="abc123",
        decay_factor=0.9,
        now_iso=datetime.now().isoformat(),
    )
    patterns = storage.get_patterns_for_context(
        entity_id="light.wohnzimmer", weekday=0, time_bucket=1080, context_hash="abc123"
    )
    assert len(patterns) == 1
    assert patterns[0].new_state == "on"
    assert patterns[0].observations == 1
    assert patterns[0].consistency == 1.0
    assert patterns[0].weight == 1  # first hit: 0 * decay + 1


def test_consistency_reflects_competing_outcomes(tmp_path):
    """Same (entity, weekday, time_bucket, context) but 3x "on", 1x "off" ->
    "on" should have consistency 0.75, "off" should have 0.25 - this is the
    whole point of context_totals existing (see storage.py docstring)."""
    storage = make_storage(tmp_path)
    now_iso = datetime.now().isoformat()
    for new_state in ("on", "on", "on", "off"):
        storage.record_event(
            entity_id="light.wohnzimmer",
            new_state=new_state,
            weekday=0,
            time_bucket=1080,
            context_hash="abc123",
            decay_factor=0.9,
            now_iso=now_iso,
        )
    patterns = {
        p.new_state: p
        for p in storage.get_patterns_for_context(
            entity_id="light.wohnzimmer", weekday=0, time_bucket=1080, context_hash="abc123"
        )
    }
    assert patterns["on"].observations == 3
    assert patterns["on"].consistency == 0.75
    assert patterns["off"].observations == 1
    assert patterns["off"].consistency == 0.25


def test_decay_formula_applied_on_each_hit(tmp_path):
    storage = make_storage(tmp_path)
    now_iso = datetime.now().isoformat()
    decay_factor = 0.9
    weights = []
    for _ in range(3):
        storage.record_event(
            entity_id="light.x",
            new_state="on",
            weekday=0,
            time_bucket=0,
            context_hash="h",
            decay_factor=decay_factor,
            now_iso=now_iso,
        )
        pattern = storage.get_patterns_for_context(entity_id="light.x", weekday=0, time_bucket=0, context_hash="h")[0]
        weights.append(pattern.weight)
    # weight = weight * decay_factor + 1, starting at 0
    expected = [1.0, 1.0 * decay_factor + 1, (1.0 * decay_factor + 1) * decay_factor + 1]
    for got, want in zip(weights, expected):
        assert abs(got - want) < 1e-9


def test_unrecorded_context_returns_empty(tmp_path):
    storage = make_storage(tmp_path)
    patterns = storage.get_patterns_for_context(
        entity_id="light.never_seen", weekday=0, time_bucket=0, context_hash="nope"
    )
    assert patterns == []


def test_prune_ages_and_removes_stale_pattern(tmp_path):
    storage = make_storage(tmp_path)
    # Recorded "9 weeks ago" - directly writing an old last_seen rather
    # than waiting, to keep the test fast/deterministic.
    old_iso = (datetime.now() - timedelta(weeks=9)).isoformat()
    storage.record_event(
        entity_id="light.stale",
        new_state="on",
        weekday=0,
        time_bucket=0,
        context_hash="h",
        decay_factor=0.9,
        now_iso=old_iso,
    )
    # weight is 1 after a single hit; 0.9**9 ≈ 0.387, still above a 0.05
    # floor - a single old observation shouldn't vanish immediately...
    removed = storage.prune(weight_floor=0.05, decay_factor=0.9)
    assert removed == 0
    remaining = storage.get_patterns_for_context(entity_id="light.stale", weekday=0, time_bucket=0, context_hash="h")
    assert len(remaining) == 1

    # ...but after enough elapsed weeks, it should actually fall below the
    # floor and get removed. 0.9**60 ≈ 0.0018 < 0.05.
    very_old_iso = (datetime.now() - timedelta(weeks=60)).isoformat()
    storage.record_event(
        entity_id="light.very_stale",
        new_state="on",
        weekday=0,
        time_bucket=0,
        context_hash="h2",
        decay_factor=0.9,
        now_iso=very_old_iso,
    )
    removed = storage.prune(weight_floor=0.05, decay_factor=0.9)
    assert removed == 1
    remaining = storage.get_patterns_for_context(
        entity_id="light.very_stale", weekday=0, time_bucket=0, context_hash="h2"
    )
    assert remaining == []


def test_reset_clears_everything(tmp_path):
    storage = make_storage(tmp_path)
    storage.record_event(
        entity_id="light.x",
        new_state="on",
        weekday=0,
        time_bucket=0,
        context_hash="h",
        decay_factor=0.9,
        now_iso=datetime.now().isoformat(),
    )
    storage.reset()
    assert storage.get_patterns_for_context(entity_id="light.x", weekday=0, time_bucket=0, context_hash="h") == []
    assert storage.get_all_context_keys({"light.x"}) == set()


def test_get_all_context_keys_scoped_to_requested_entities(tmp_path):
    storage = make_storage(tmp_path)
    now_iso = datetime.now().isoformat()
    storage.record_event(
        entity_id="light.a", new_state="on", weekday=0, time_bucket=0, context_hash="h", decay_factor=0.9, now_iso=now_iso
    )
    storage.record_event(
        entity_id="light.b", new_state="on", weekday=0, time_bucket=0, context_hash="h", decay_factor=0.9, now_iso=now_iso
    )
    keys = storage.get_all_context_keys({"light.a"})
    assert {k[0] for k in keys} == {"light.a"}
