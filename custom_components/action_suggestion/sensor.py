"""One sensor entity per learned pattern.

Entities are created once, the first time a given pattern_key is ever seen
as active, and then kept for good (HA discourages dynamically removing
entities, and a habit that isn't due *right now* still deserves to exist as
"currently inactive" rather than blinking in and out of the entity
registry every few minutes). Whether it's actually due right now lives in
its state, re-derived from `coordinator.data` on every coordinator update -
see `native_value`/`extra_state_attributes` below.

Tapping the suggestion in the dashboard doesn't call the underlying service
(e.g. `light.turn_on`) directly from the Lovelace config - which service
that even is varies per suggestion and per moment, so a static card
wouldn't know it ahead of time. Instead it calls this integration's own
`execute_suggestion` service with this entity as target, which resolves
today's action from the coordinator and calls it, preserving the tap's own
context. See services.yaml and README.md for the example card.
"""

from __future__ import annotations

import hashlib

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ActionSuggestionCoordinator, SuggestionData

STATE_ACTIVE = "active"
STATE_INACTIVE = "inactive"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: ActionSuggestionCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_pattern_keys: set[str] = set()

    def _add_new_entities() -> None:
        new_keys = set(coordinator.data) - known_pattern_keys
        if not new_keys:
            return
        known_pattern_keys.update(new_keys)
        async_add_entities([ActionSuggestionSensor(coordinator, key) for key in new_keys])

    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))
    _add_new_entities()


class ActionSuggestionSensor(CoordinatorEntity[ActionSuggestionCoordinator], SensorEntity):
    """State is "active"/"inactive" rather than the target entity's
    on/off-style state itself - this sensor describes *whether a
    suggestion applies right now*, not the target entity. What it would
    do lives in the `action` / `new_state` attributes instead, exactly the
    shape the spec's example card taps into."""

    _attr_icon = "mdi:lightbulb-on-outline"

    def __init__(self, coordinator: ActionSuggestionCoordinator, pattern_key: str) -> None:
        super().__init__(coordinator)
        self._pattern_key = pattern_key
        digest = hashlib.sha1(pattern_key.encode("utf-8")).hexdigest()[:12]
        self._attr_unique_id = f"{DOMAIN}_{digest}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Lets the execute_suggestion service (see __init__.py) go from
        # "which entity was tapped" back to "which pattern was that" -
        # entity_id isn't derivable from pattern_key alone (it's
        # HA-assigned, based on `name` below, and can be user-renamed).
        self.coordinator.entity_pattern_keys[self.entity_id] = self._pattern_key

    async def async_will_remove_from_hass(self) -> None:
        self.coordinator.entity_pattern_keys.pop(self.entity_id, None)
        await super().async_will_remove_from_hass()

    @property
    def _data(self) -> SuggestionData | None:
        return self.coordinator.data.get(self._pattern_key)

    @property
    def name(self) -> str:
        data = self._data
        target_entity_id = data.target_entity_id if data else self._pattern_key.split("|", 1)[0]
        target_state = self.hass.states.get(target_entity_id) if self.hass else None
        target_name = target_state.name if target_state else target_entity_id
        return f"Vorschlag {target_name}"

    @property
    def native_value(self) -> str:
        return STATE_ACTIVE if self._data is not None else STATE_INACTIVE

    @property
    def extra_state_attributes(self) -> dict:
        data = self._data
        if data is None:
            return {}
        return {
            "target_entity_id": data.target_entity_id,
            "area_id": data.area_id,
            "action": f"{data.service_domain}.{data.service_name}",
            "new_state": data.new_state,
            "confidence": data.confidence,
            "observations": data.observations,
            "reason": data.reason,
        }
