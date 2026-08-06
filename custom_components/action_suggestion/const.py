"""Constants for Action Suggestion."""

DOMAIN = "action_suggestion"
PLATFORMS = ["sensor"]

# --- Config entry data (set once at setup, changed via reconfigure) -------

# Areas to monitor - state changes on entities outside these areas are never
# looked at at all, and a context snapshot never reaches beyond the area of
# the entity that changed. See const "Nicht-Ziele": "Kein globales Sammeln
# von Kontext-Daten außerhalb der jeweiligen Area".
CONF_AREAS = "areas"

# --- Options (changed any time via the options flow, see config_flow.py) --

# How wide one time slot is. Coarser = more forgiving of "usually around
# 18:00, sometimes 18:10", but also more likely to blend genuinely distinct
# habits together.
CONF_TIME_BUCKET_MINUTES = "time_bucket_minutes"
DEFAULT_TIME_BUCKET_MINUTES = 30
TIME_BUCKET_CHOICES = [15, 30]

# Numeric context entities (temperature, illuminance, ...) are rounded to
# this step size before hashing, so e.g. 21.3°C and 21.4°C count as the same
# context instead of two contexts that each look "unreliable" on their own.
CONF_NUMERIC_BIN_SIZE = "numeric_bin_size"
DEFAULT_NUMERIC_BIN_SIZE = 2.0

# A pattern only becomes a suggestion once it has been observed at least
# this many times ...
CONF_MIN_OBSERVATIONS = "min_observations"
DEFAULT_MIN_OBSERVATIONS = 3

# ... AND the same outcome happened at least this fraction of the times this
# exact (entity, weekday, time_bucket, context) combination was observed at
# all - see pattern_engine.py `consistency`. 0.7 = 70%.
CONF_MIN_CONSISTENCY = "min_consistency"
DEFAULT_MIN_CONSISTENCY = 0.7

# Applied to a pattern's own weight every time that *exact* outcome is
# observed again: weight = weight * decay_factor + 1 (see
# pattern_engine.record_event). A value close to 1.0 barely discounts older
# hits; lower values make recent behaviour dominate faster. Only ever
# applied to the outcome that just happened - a competing outcome for the
# same context that stops recurring simply stops growing rather than being
# actively pushed down, see pattern_engine.py module docstring.
CONF_DECAY_FACTOR = "decay_factor"
DEFAULT_DECAY_FACTOR = 0.9

SERVICE_RESET = "reset"
# Tapping a suggestion in the dashboard calls this, targeting the
# suggestion sensor itself - see sensor.py module docstring for why an
# indirection service instead of a static per-suggestion service call.
SERVICE_EXECUTE_SUGGESTION = "execute_suggestion"

# Where the integration's own SQLite DB lives, relative to the HA config
# dir - deliberately NOT the Recorder DB (spec: "nicht die Recorder-DB, die
# zu kurz vorhält") and not under .storage/ either, since that directory is
# reserved for HA's own Store()-managed JSON files, not arbitrary DB files.
STORAGE_SUBDIR = DOMAIN
STORAGE_DB_FILENAME = "patterns.db"

# Below this, a decayed pattern weight is treated as noise and dropped
# during storage maintenance rather than kept around forever taking up rows
# for an outcome nobody has picked in a very long time.
PRUNE_WEIGHT_FLOOR = 0.05

# How often the coordinator re-evaluates which patterns are *currently*
# due (current weekday/time_bucket/context matches a qualifying pattern) -
# independent of how often state-change events themselves happen, since a
# pattern can start/stop being "due" purely because the clock moved into
# the next time_bucket with nobody having touched anything.
ACTIVE_SUGGESTIONS_REFRESH_INTERVAL_MINUTES = 5
