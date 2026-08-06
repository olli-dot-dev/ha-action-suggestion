"""Classifies a state_changed event's origin, so only genuinely manual
actions ever reach the pattern engine.

Per spec:
- `context.user_id` set -> a real person did this through the UI or a
  companion app. The only case we learn from.
- `context.user_id` unset but `context.parent_id` set -> something else
  (almost always an automation or script) caused this as a side effect of
  its own run. Discarded - it's not a habit, it's the integration's own
  previous suggestion being accepted (which itself carries a fresh
  `user_id`, see sensor.py) or an unrelated automation.
- Both unset -> most likely a physical switch/remote reporting its state
  directly to the device integration, with no HA-side context to attribute
  it to a person at all. v1 explicitly discards these too (spec "Spätere
  Erweiterungen") rather than guessing.

Both non-MANUAL cases are discarded identically by the coordinator - the
AUTOMATION/UNKNOWN split below exists only so logs/diagnostics can say
*why* an event was skipped, not because the two are handled differently.
Resolving `parent_id` to a specific originating automation/script would
need walking HA's context chain and matching it against automation traces
(see the trace-polling approach in ha-automation-monitor for how involved
that is) - deliberately not attempted here since the outcome (discard)
would be the same either way; "AUTOMATION" below is therefore a best-effort
label, not a verified match against a specific automation entity.
"""

from __future__ import annotations

from enum import Enum

from homeassistant.core import Context


class EventOrigin(Enum):
    """Where a state_changed event most likely came from."""

    MANUAL = "manual"
    AUTOMATION = "automation"
    UNKNOWN = "unknown"


def classify_origin(context: Context) -> EventOrigin:
    """Classify a state_changed event's context. See module docstring."""
    if context.user_id is not None:
        return EventOrigin.MANUAL
    if context.parent_id is not None:
        return EventOrigin.AUTOMATION
    return EventOrigin.UNKNOWN


def is_learnable(context: Context) -> bool:
    """Shortcut for the only decision that actually matters to the
    coordinator: was this a direct user action, yes or no."""
    return classify_origin(context) is EventOrigin.MANUAL
