"""Coordinator: has two independent jobs that deliberately don't share a
code path -

- Learning (event-driven, `_handle_state_change`): fires on every tracked
  entity's state_changed event, discards anything that isn't a genuinely
  manual action (see classification.py), and records the rest into
  storage via pattern_engine.record_event. Runs immediately, not on the
  polling interval below.
- Suggesting (polling, `_async_update_data`, HA's own DataUpdateCoordinator
  machinery): every ACTIVE_SUGGESTIONS_REFRESH_INTERVAL_MINUTES, re-derives
  which learned patterns are due *right now* - current weekday, current
  time bucket, and a freshly-built context snapshot that hashes to the
  same context_hash the pattern was learned under. A pattern can start or
  stop being "due" purely because the clock or the context moved, with
  nobody touching any entity, which is why this needs its own timer
  instead of only recomputing inside `_handle_state_change`.

`self.data` (the coordinator's standard `dict` contract) maps a stable
`pattern_key` (see `_pattern_key`) to a `SuggestionData` for every
currently-due pattern - sensor.py listens for this to know which
suggestion entities exist and what they show right now.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import context as ctx
from .classification import EventOrigin, classify_origin
from .const import (
    ACTIVE_SUGGESTIONS_REFRESH_INTERVAL_MINUTES,
    CONF_AREAS,
    CONF_DECAY_FACTOR,
    CONF_MIN_CONSISTENCY,
    CONF_MIN_OBSERVATIONS,
    CONF_NUMERIC_BIN_SIZE,
    CONF_TIME_BUCKET_MINUTES,
    DEFAULT_DECAY_FACTOR,
    DEFAULT_MIN_CONSISTENCY,
    DEFAULT_MIN_OBSERVATIONS,
    DEFAULT_NUMERIC_BIN_SIZE,
    DEFAULT_TIME_BUCKET_MINUTES,
    DOMAIN,
)
from .pattern_engine import best_qualifying_pattern, record_event
from .storage import PatternStorage

_LOGGER = logging.getLogger(__name__)

WEEKDAY_NAMES_DE = ["Montags", "Dienstags", "Mittwochs", "Donnerstags", "Freitags", "Samstags", "Sonntags"]

# Domains where a plain on/off state maps to the obvious turn_on/turn_off
# service - covers the toggle-like entities the spec's own example
# (light.turn_on) is about. Anything else (climate modes, cover positions,
# media players, ...) needs a more specific service+payload than "the
# state string became X" can express safely, so v1 doesn't suggest those -
# see `resolve_service_call`.
_TURN_ON_OFF_DOMAINS = {"light", "switch", "fan", "input_boolean", "humidifier"}


@dataclass
class SuggestionData:
    """Everything one active suggestion entity (see sensor.py) needs to
    display itself and act on a tap."""

    pattern_key: str
    target_entity_id: str
    area_id: str
    service_domain: str
    service_name: str
    service_data: dict
    new_state: str
    confidence: float
    observations: int
    reason: str


def resolve_service_call(entity_id: str, new_state: str) -> tuple[str, str, dict] | None:
    """The service call that would reproduce `new_state` on `entity_id`,
    or None if this integration doesn't know how to express that state as
    a safe service call (see module docstring) - such a pattern is still
    learned and stored, just never turned into a suggestion entity."""
    domain = entity_id.split(".", 1)[0]
    if domain in _TURN_ON_OFF_DOMAINS and new_state in ("on", "off"):
        return domain, f"turn_{new_state}", {"entity_id": entity_id}
    if domain == "cover" and new_state in ("open", "closed"):
        return domain, ("open_cover" if new_state == "open" else "close_cover"), {"entity_id": entity_id}
    if domain == "lock" and new_state in ("locked", "unlocked"):
        return domain, ("lock" if new_state == "locked" else "unlock"), {"entity_id": entity_id}
    return None


def _pattern_key(entity_id: str, weekday: int, time_bucket: int, context_hash: str) -> str:
    """Stable identifier for one recurring habit, independent of *when* it
    happens to be evaluated - used as both the dict key in `self.data` and
    (prefixed) as a suggestion entity's unique_id, so the same habit keeps
    the same entity (and its history/customisations) across restarts."""
    return f"{entity_id}|{weekday}|{time_bucket}|{context_hash}"


class ActionSuggestionCoordinator(DataUpdateCoordinator[dict[str, SuggestionData]]):
    """See module docstring."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, storage: PatternStorage) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=ACTIVE_SUGGESTIONS_REFRESH_INTERVAL_MINUTES),
        )
        self.data = {}
        self._entry = entry
        self._storage = storage
        self._remove_listener = None
        self.tracked_entity_ids: set[str] = set()
        # entity_id -> pattern_key, populated by each ActionSuggestionSensor
        # in async_added_to_hass (see sensor.py) - lets the
        # execute_suggestion service (__init__.py) resolve "which entity
        # was tapped" back to "which pattern is that", since entity_id
        # itself isn't derivable from pattern_key (it's HA-assigned and
        # user-renamable).
        self.entity_pattern_keys: dict[str, str] = {}

    def _opt(self, key: str, default):
        return self._entry.options.get(key, default)

    def async_setup(self) -> None:
        area_ids = ctx.async_configured_area_ids(self.hass, self._entry.data.get(CONF_AREAS, []))
        self.tracked_entity_ids = set()
        for area_id in area_ids:
            self.tracked_entity_ids |= ctx.async_entity_ids_in_area(self.hass, area_id)

        if self.tracked_entity_ids:
            self._remove_listener = async_track_state_change_event(
                self.hass, list(self.tracked_entity_ids), self._handle_state_change
            )
        else:
            _LOGGER.warning(
                "Action Suggestion: no entities found in the configured areas (%s) - nothing to learn from",
                area_ids,
            )

    def async_unload(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    # --- Learning ------------------------------------------------------

    @callback
    def _handle_state_change(self, event: Event) -> None:
        # event.data is {"entity_id": str, "old_state": State | None, "new_state":
        # State | None} - kept as a plain Event/dict access rather than importing
        # the newer EventStateChangedData TypedDict for the type hint, since that
        # type isn't available on every HA version this integration's manifest
        # otherwise allows (2024.1.0+).
        new_state = event.data["new_state"]
        old_state = event.data["old_state"]
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return
        if old_state is not None and old_state.state == new_state.state:
            # An attribute-only update (e.g. a light's brightness changing
            # while it was already "on") isn't a new decision to learn from.
            return

        origin = classify_origin(event.context)
        if origin is not EventOrigin.MANUAL:
            _LOGGER.debug(
                "Action Suggestion: ignoring %s -> %s on %s (origin=%s)",
                old_state.state if old_state else None,
                new_state.state,
                new_state.entity_id,
                origin.value,
            )
            return

        entity_id = new_state.entity_id
        area_id = ctx.async_resolve_area_id(self.hass, entity_id)
        if area_id is None:
            return

        now = datetime.now()
        numeric_bin_size = self._opt(CONF_NUMERIC_BIN_SIZE, DEFAULT_NUMERIC_BIN_SIZE)
        snapshot = ctx.build_context_snapshot(self.hass, area_id, entity_id, numeric_bin_size)

        # Fire-and-forget from this @callback, but as a tracked task with its
        # own error handling - a bare async_add_executor_job() call here
        # would be a Future nothing ever awaits, so a failure would only
        # ever surface as an unhandled-exception warning at garbage-collection
        # time instead of a real log entry pointing at what broke.
        self.hass.async_create_task(
            self._async_record_event(
                entity_id=entity_id,
                new_state=new_state.state,
                weekday=now.weekday(),
                time_bucket=ctx.time_bucket(now, self._opt(CONF_TIME_BUCKET_MINUTES, DEFAULT_TIME_BUCKET_MINUTES)),
                context_hash=ctx.context_hash(snapshot),
                decay_factor=self._opt(CONF_DECAY_FACTOR, DEFAULT_DECAY_FACTOR),
                now_iso=now.isoformat(),
            )
        )

    async def _async_record_event(
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
        try:
            await self.hass.async_add_executor_job(
                lambda: record_event(
                    self._storage,
                    entity_id=entity_id,
                    new_state=new_state,
                    weekday=weekday,
                    time_bucket=time_bucket,
                    context_hash=context_hash,
                    decay_factor=decay_factor,
                    now_iso=now_iso,
                )
            )
        except Exception:  # noqa: BLE001 - must never crash the event listener
            _LOGGER.exception("Action Suggestion: failed to record event for %s", entity_id)

    # --- Suggesting ------------------------------------------------------

    async def _async_update_data(self) -> dict[str, SuggestionData]:
        if not self.tracked_entity_ids:
            return {}

        known_entity_ids = await self.hass.async_add_executor_job(
            lambda: {key[0] for key in self._storage.get_all_context_keys(self.tracked_entity_ids)}
        )

        min_observations = self._opt(CONF_MIN_OBSERVATIONS, DEFAULT_MIN_OBSERVATIONS)
        min_consistency = self._opt(CONF_MIN_CONSISTENCY, DEFAULT_MIN_CONSISTENCY)
        bucket_minutes = self._opt(CONF_TIME_BUCKET_MINUTES, DEFAULT_TIME_BUCKET_MINUTES)
        numeric_bin_size = self._opt(CONF_NUMERIC_BIN_SIZE, DEFAULT_NUMERIC_BIN_SIZE)

        now = datetime.now()
        weekday = now.weekday()
        bucket = ctx.time_bucket(now, bucket_minutes)

        active: dict[str, SuggestionData] = {}
        for entity_id in known_entity_ids:
            area_id = ctx.async_resolve_area_id(self.hass, entity_id)
            if area_id is None:
                continue
            snapshot = ctx.build_context_snapshot(self.hass, area_id, entity_id, numeric_bin_size)
            snapshot_hash = ctx.context_hash(snapshot)

            pattern = await self.hass.async_add_executor_job(
                lambda eid=entity_id, h=snapshot_hash: best_qualifying_pattern(
                    self._storage,
                    entity_id=eid,
                    weekday=weekday,
                    time_bucket=bucket,
                    context_hash=h,
                    min_observations=min_observations,
                    min_consistency=min_consistency,
                )
            )
            if pattern is None:
                continue

            # Already in this state - nothing to suggest.
            current = self.hass.states.get(entity_id)
            if current is not None and current.state == pattern.new_state:
                continue

            service_call = resolve_service_call(entity_id, pattern.new_state)
            if service_call is None:
                continue
            service_domain, service_name, service_data = service_call

            key = _pattern_key(entity_id, weekday, bucket, snapshot_hash)
            active[key] = SuggestionData(
                pattern_key=key,
                target_entity_id=entity_id,
                area_id=area_id,
                service_domain=service_domain,
                service_name=service_name,
                service_data=service_data,
                new_state=pattern.new_state,
                confidence=round(pattern.consistency, 2),
                observations=pattern.observations,
                reason=self._build_reason(weekday, bucket, snapshot),
            )

        return active

    def _build_reason(self, weekday: int, bucket_minutes_since_midnight: int, snapshot: dict[str, str]) -> str:
        """Human-readable summary, e.g. "Montags gegen 18:00 Uhr, ähnlich
        wie sonst" - deliberately doesn't try to enumerate every entity in
        the context snapshot (could be a long, unreadable list); the exact
        snapshot is available via storage for debugging if needed, this is
        just an at-a-glance hint show on the suggestion entity itself."""
        hours, minutes = divmod(bucket_minutes_since_midnight, 60)
        day_name = WEEKDAY_NAMES_DE[weekday]
        base = f"{day_name} gegen {hours:02d}:{minutes:02d} Uhr"
        if not snapshot:
            return base
        return f"{base}, wie sonst in dieser Situation"

    def async_call_service_for(self, pattern_key: str) -> tuple[str, str, dict] | None:
        """Looks up the service call for a still-active suggestion by its
        pattern_key - used by sensor.py's button-tap handling. Returns
        None if the suggestion is no longer active (context moved on
        between the card rendering and the tap)."""
        suggestion = self.data.get(pattern_key)
        if suggestion is None:
            return None
        return suggestion.service_domain, suggestion.service_name, suggestion.service_data
