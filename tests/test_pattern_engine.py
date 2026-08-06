"""Standalone tests for pattern_engine.py - see test_storage.py docstring
for why this module (and pattern_engine.py itself) has no Home Assistant
dependency and can be tested directly."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from _load import load_module

best_qualifying_pattern = load_module("pattern_engine").best_qualifying_pattern
PatternStorage = load_module("storage").PatternStorage


def make_storage(tmp_path: Path) -> PatternStorage:
    storage = PatternStorage(str(tmp_path / "patterns.db"))
    storage.setup()
    return storage


def record(storage, new_state, n=1, decay_factor=0.9):
    now_iso = datetime.now().isoformat()
    for _ in range(n):
        storage.record_event(
            entity_id="light.x",
            new_state=new_state,
            weekday=0,
            time_bucket=1080,
            context_hash="ctx",
            decay_factor=decay_factor,
            now_iso=now_iso,
        )


def test_returns_none_below_min_observations(tmp_path):
    storage = make_storage(tmp_path)
    record(storage, "on", n=2)
    result = best_qualifying_pattern(
        storage,
        entity_id="light.x",
        weekday=0,
        time_bucket=1080,
        context_hash="ctx",
        min_observations=3,
        min_consistency=0.7,
    )
    assert result is None


def test_returns_none_below_min_consistency(tmp_path):
    storage = make_storage(tmp_path)
    # 2x "on", 2x "off" -> 50% consistency each, below a 70% threshold.
    record(storage, "on", n=2)
    record(storage, "off", n=2)
    result = best_qualifying_pattern(
        storage,
        entity_id="light.x",
        weekday=0,
        time_bucket=1080,
        context_hash="ctx",
        min_observations=1,
        min_consistency=0.7,
    )
    assert result is None


def test_returns_qualifying_pattern(tmp_path):
    storage = make_storage(tmp_path)
    record(storage, "on", n=4)
    record(storage, "off", n=1)
    result = best_qualifying_pattern(
        storage,
        entity_id="light.x",
        weekday=0,
        time_bucket=1080,
        context_hash="ctx",
        min_observations=3,
        min_consistency=0.7,
    )
    assert result is not None
    assert result.new_state == "on"
    assert result.consistency == 0.8


def test_picks_the_higher_consistency_outcome_when_both_qualify(tmp_path):
    """Only realistic if min_consistency is low enough to let both through -
    e.g. two outcomes at 60/40 with a 0.5 threshold. Picks the winner
    rather than e.g. the most recently recorded."""
    storage = make_storage(tmp_path)
    record(storage, "on", n=3)
    record(storage, "off", n=2)
    result = best_qualifying_pattern(
        storage,
        entity_id="light.x",
        weekday=0,
        time_bucket=1080,
        context_hash="ctx",
        min_observations=1,
        min_consistency=0.3,
    )
    assert result is not None
    assert result.new_state == "on"
    assert result.consistency == 0.6
