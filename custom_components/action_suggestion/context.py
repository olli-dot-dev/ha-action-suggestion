"""Area resolution and context-snapshot building.

A "context snapshot" is: every other entity's current state in the same
Area as the entity that just changed, binned to reduce noise, plus the
weekday and time bucket the change happened in. Together these get hashed
into a single `context_hash` that patterns are grouped by (see storage.py /
pattern_engine.py) - two manual changes end up in the "same" context if
their snapshots are equal after binning, even if e.g. a temperature sensor
reads 21.3° in one and 21.4° in the other.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er


def async_resolve_area_id(hass: HomeAssistant, entity_id: str) -> str | None:
    """The Area an entity belongs to - directly assigned on the entity
    itself, or inherited from its device. Mirrors how Area Manager resolves
    area membership (entity override takes precedence over the device's
    area, else there is none)."""
    entity_entry = er.async_get(hass).async_get(entity_id)
    if entity_entry is None:
        return None
    if entity_entry.area_id:
        return entity_entry.area_id
    if entity_entry.device_id:
        device_entry = dr.async_get(hass).async_get(entity_entry.device_id)
        if device_entry is not None:
            return device_entry.area_id
    return None


def async_entity_ids_in_area(hass: HomeAssistant, area_id: str) -> set[str]:
    """Every entity_id whose Area (directly or via its device) is
    `area_id`. Used to build a context snapshot scoped to exactly one Area,
    and to decide which entities to attach state-change listeners to in the
    first place - see coordinator.py."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    result: set[str] = set()
    for entity_entry in entity_registry.entities.values():
        entity_area_id = entity_entry.area_id
        if entity_area_id is None and entity_entry.device_id:
            device_entry = device_registry.async_get(entity_entry.device_id)
            entity_area_id = device_entry.area_id if device_entry else None
        if entity_area_id == area_id:
            result.add(entity_entry.entity_id)
    return result


def async_configured_area_ids(hass: HomeAssistant, area_ids: list[str]) -> list[str]:
    """Filters out Area IDs that no longer exist (e.g. renamed/deleted in
    HA after this integration was configured) - silently, rather than
    failing setup over a stale config entry option."""
    area_registry = ar.async_get(hass)
    return [area_id for area_id in area_ids if area_registry.async_get_area(area_id) is not None]


def time_bucket(dt: datetime, bucket_minutes: int) -> int:
    """Minutes since midnight, rounded down to `bucket_minutes` - e.g. with
    a 30-minute bucket, 18:07 and 18:24 both become 1080 (18:00)."""
    minutes_since_midnight = dt.hour * 60 + dt.minute
    return (minutes_since_midnight // bucket_minutes) * bucket_minutes


def bin_state_value(raw_state: str, numeric_bin_size: float) -> str:
    """Rounds a numeric state to the configured step size so nearby values
    count as identical context; non-numeric states (on/off, an enum like
    hvac_mode, ...) pass through unchanged - binning only makes sense for
    continuous values."""
    try:
        value = float(raw_state)
    except (TypeError, ValueError):
        return raw_state
    if numeric_bin_size <= 0:
        return raw_state
    binned = round(value / numeric_bin_size) * numeric_bin_size
    # Avoid "21.0" vs "21" style false mismatches from float formatting.
    return f"{binned:g}"


def build_context_snapshot(
    hass: HomeAssistant,
    area_id: str,
    changed_entity_id: str,
    numeric_bin_size: float,
) -> dict[str, str]:
    """entity_id -> binned state, for every *other* entity in `area_id`
    that currently has a real state (skips `unknown`/`unavailable` - those
    say nothing about context and would otherwise make two genuinely
    identical situations hash differently just because one sensor happened
    to be briefly unavailable)."""
    snapshot: dict[str, str] = {}
    for entity_id in async_entity_ids_in_area(hass, area_id):
        if entity_id == changed_entity_id:
            continue
        state: State | None = hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            continue
        snapshot[entity_id] = bin_state_value(state.state, numeric_bin_size)
    return snapshot


def context_hash(snapshot: dict[str, str]) -> str:
    """Stable, order-independent hash over a context snapshot. Short and
    opaque on purpose - it's a grouping key for storage/pattern_engine, not
    something meant to be read directly (the human-readable "reason" shown
    to the user is built separately, see coordinator.py)."""
    normalized = ",".join(f"{entity_id}={value}" for entity_id, value in sorted(snapshot.items()))
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
