"""Action Suggestion - learns patterns from manual state changes in the
configured Areas and exposes qualifying, currently-due ones as suggestion
sensor entities (see sensor.py). Never executes anything itself: tapping a
suggestion in the dashboard is what calls the service - see sensor.py's
tap-action handling - which in turn produces a normal `context.user_id`
event that reinforces the pattern again, same as any other manual action.
"""

from __future__ import annotations

import logging
import os
from functools import partial
from pathlib import Path

import voluptuous as vol
from aiohttp import web
from homeassistant.components import frontend
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.loader import async_get_integration

from .const import (
    CONF_DECAY_FACTOR,
    DEFAULT_DECAY_FACTOR,
    DOMAIN,
    PLATFORMS,
    PRUNE_WEIGHT_FLOOR,
    SERVICE_EXECUTE_SUGGESTION,
    SERVICE_RESET,
    STORAGE_DB_FILENAME,
    STORAGE_SUBDIR,
)
from .coordinator import ActionSuggestionCoordinator
from .storage import PatternStorage

EXECUTE_SUGGESTION_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_ids})

_LOGGER = logging.getLogger(__name__)

# Separate hass.data key from DOMAIN (which maps entry_id -> coordinator, see
# async_setup_entry) - the frontend card registration is process-wide, not
# per-entry, and mixing a non-entry_id key into that dict would break
# async_unload_entry's "no entries left" check below.
_FRONTEND_DATA_KEY = f"{DOMAIN}_frontend"
_CARD_JS_URL_PATH = "/action-suggestion-card.js"


async def _serve_card_js(path: str, request: web.Request) -> web.FileResponse:
    # "no-cache" (not "no explicit header") forces revalidation on every
    # request rather than leaving it to unpredictable browser heuristics -
    # aiohttp's FileResponse still sets Last-Modified/ETag, so an unchanged
    # file gets an efficient 304 rather than a full re-download.
    #
    # Content-Type set explicitly rather than left to FileResponse's
    # mimetypes-based guess: frontend.add_extra_js_url loads this as
    # `<script type="module">`, and browsers refuse to execute a module
    # script whose response Content-Type isn't a JS MIME type - silently,
    # with no error from this integration's own code, just a "Custom
    # element not found" from Lovelace once the card is actually used. Some
    # systems' mimetypes databases don't map `.js` correctly (observed: file
    # downloads fine standalone, but the module never registers), hence
    # pinning it here instead of trusting the guess.
    return web.FileResponse(
        path,
        headers={"Cache-Control": "no-cache", "Content-Type": "text/javascript; charset=utf-8"},
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    db_dir = hass.config.path(STORAGE_SUBDIR)
    await hass.async_add_executor_job(lambda: os.makedirs(db_dir, exist_ok=True))
    db_path = hass.config.path(STORAGE_SUBDIR, STORAGE_DB_FILENAME)

    storage = PatternStorage(db_path)
    await hass.async_add_executor_job(storage.setup)
    # Maintenance, not correctness: ages and then drops pattern rows
    # nobody has confirmed in a very long time (see storage.py `prune`
    # docstring for why that needs its own pass rather than following
    # from record_event's per-hit decay alone). Once per startup/reload is
    # plenty - this isn't time-sensitive.
    decay_factor = entry.options.get(CONF_DECAY_FACTOR, DEFAULT_DECAY_FACTOR)
    await hass.async_add_executor_job(storage.prune, PRUNE_WEIGHT_FLOOR, decay_factor)

    coordinator = ActionSuggestionCoordinator(hass, entry, storage)
    coordinator.async_setup()
    # Raises ConfigEntryNotReady on failure rather than leaving the entry
    # half-set-up - standard DataUpdateCoordinator behaviour, and here the
    # first refresh is also what populates self.data before any sensor
    # entity is created below.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Registers the "Vorschlagsliste" Lovelace card's JS once per running
    # process (not once per config entry - a reload must not re-register the
    # aiohttp route or re-inject the <script> tag, both of which would raise/
    # duplicate). frontend.add_extra_js_url makes it load automatically on
    # every dashboard without the user having to add it as a Lovelace
    # resource by hand.
    if not hass.data.get(_FRONTEND_DATA_KEY):
        card_js_path = Path(__file__).parent / "action-suggestion-card.js"
        hass.http.app.router.add_route("GET", _CARD_JS_URL_PATH, partial(_serve_card_js, str(card_js_path)))
        integration = await async_get_integration(hass, DOMAIN)
        card_js_url = f"{_CARD_JS_URL_PATH}?v={integration.version}"
        frontend.add_extra_js_url(hass, card_js_url)
        hass.data[_FRONTEND_DATA_KEY] = card_js_url

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    async def _async_handle_reset(call: ServiceCall) -> None:
        await hass.async_add_executor_job(storage.reset)
        await coordinator.async_request_refresh()

    async def _async_handle_execute_suggestion(call: ServiceCall) -> None:
        """Resolves each targeted suggestion sensor back to its pattern's
        service call (via coordinator.entity_pattern_keys, populated by
        the sensor entities themselves - see sensor.py) and executes it,
        passing this call's own context straight through. That's the
        whole point of going through this service instead of the target
        service directly from Lovelace: whoever/whatever triggered this
        service call (normally a dashboard tap, so a real logged-in user)
        becomes the context of the resulting state change too, exactly
        like a normal manual action - so it reinforces the same pattern
        rather than looking like an unattributed change. A suggestion
        that's no longer active by the time this runs (context moved on
        since the card was rendered) is silently skipped rather than
        raising - a slightly stale dashboard card shouldn't produce an
        error popup.
        """
        for entity_id in call.data[ATTR_ENTITY_ID]:
            pattern_key = coordinator.entity_pattern_keys.get(entity_id)
            if pattern_key is None:
                _LOGGER.warning("Action Suggestion: %s is not a known suggestion entity", entity_id)
                continue
            resolved = coordinator.async_call_service_for(pattern_key)
            if resolved is None:
                _LOGGER.debug("Action Suggestion: suggestion %s is no longer active, skipping", entity_id)
                continue
            service_domain, service_name, service_data = resolved
            await hass.services.async_call(
                service_domain, service_name, service_data, context=call.context
            )

    # Single-instance integration (see config_flow.py) - registering once
    # here, keyed off this closure's storage/coordinator, is safe since
    # there is never more than one config entry.
    hass.services.async_register(DOMAIN, SERVICE_RESET, _async_handle_reset)
    hass.services.async_register(
        DOMAIN, SERVICE_EXECUTE_SUGGESTION, _async_handle_execute_suggestion, schema=EXECUTE_SUGGESTION_SCHEMA
    )

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # Simplest way to apply changed thresholds/bucket size: reload the
    # whole entry rather than trying to patch a running coordinator's
    # config live.
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: ActionSuggestionCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.async_unload()
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_RESET)
            hass.services.async_remove(DOMAIN, SERVICE_EXECUTE_SUGGESTION)
    return unload_ok
