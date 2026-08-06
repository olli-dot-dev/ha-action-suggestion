"""Config flow for Action Suggestion.

Single-instance (one config entry covers every configured Area - see
CONF_AREAS). Setup only asks which Areas to learn from; everything else
(time bucket size, numeric binning, decay, the consistency/observation
thresholds) lives in the options flow so it can be tuned later without
reconfiguring from scratch.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
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
    TIME_BUCKET_CHOICES,
)


class ActionSuggestionConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the (single) config flow for Action Suggestion."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            areas = user_input.get(CONF_AREAS) or []
            if not areas:
                errors["base"] = "no_areas"
            else:
                return self.async_create_entry(title="Action Suggestion", data={CONF_AREAS: areas})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_AREAS): selector.selector({"area": {"multiple": True}})}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ActionSuggestionOptionsFlow:
        return ActionSuggestionOptionsFlow()


class ActionSuggestionOptionsFlow(config_entries.OptionsFlow):
    """Every tunable threshold from the spec's "Frequenz-Engine" and
    "Kontext-Snapshot" sections, all in one step - there's no natural
    sub-grouping the way ha-automation-monitor's options are split by
    "what they configure", these all feed the same single pattern
    engine."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            # The time-bucket select's options are strings (selector
            # values are always strings) - everything downstream
            # (context.time_bucket, storage's integer columns) expects an
            # int, so convert right here rather than at every call site.
            user_input[CONF_TIME_BUCKET_MINUTES] = int(user_input[CONF_TIME_BUCKET_MINUTES])
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TIME_BUCKET_MINUTES,
                    default=str(options.get(CONF_TIME_BUCKET_MINUTES, DEFAULT_TIME_BUCKET_MINUTES)),
                ): selector.selector(
                    {
                        "select": {
                            "options": [str(choice) for choice in TIME_BUCKET_CHOICES],
                            "mode": "dropdown",
                        }
                    }
                ),
                vol.Required(
                    CONF_NUMERIC_BIN_SIZE,
                    default=options.get(CONF_NUMERIC_BIN_SIZE, DEFAULT_NUMERIC_BIN_SIZE),
                ): selector.selector({"number": {"min": 0.1, "max": 50, "step": 0.1, "mode": "box"}}),
                vol.Required(
                    CONF_MIN_OBSERVATIONS,
                    default=options.get(CONF_MIN_OBSERVATIONS, DEFAULT_MIN_OBSERVATIONS),
                ): selector.selector({"number": {"min": 1, "max": 100, "step": 1, "mode": "box"}}),
                vol.Required(
                    CONF_MIN_CONSISTENCY,
                    default=options.get(CONF_MIN_CONSISTENCY, DEFAULT_MIN_CONSISTENCY),
                ): selector.selector({"number": {"min": 0.1, "max": 1.0, "step": 0.05, "mode": "slider"}}),
                vol.Required(
                    CONF_DECAY_FACTOR,
                    default=options.get(CONF_DECAY_FACTOR, DEFAULT_DECAY_FACTOR),
                ): selector.selector({"number": {"min": 0.5, "max": 0.99, "step": 0.01, "mode": "slider"}}),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
