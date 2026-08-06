"""Loads action_suggestion submodules directly from source, without going
through `custom_components/action_suggestion/__init__.py` (which imports
`homeassistant.*` at module level and therefore can't be imported at all
without the full homeassistant package installed - not available in this
project's dev environment, see README "Bekannte Grenzen").

Only usable for the handful of submodules that have zero homeassistant
dependency of their own (currently: storage.py, pattern_engine.py) -
anything importing `homeassistant.core`/`homeassistant.helpers.*` directly
(classification.py, context.py, coordinator.py, config_flow.py, sensor.py)
still can't be loaded this way and has no automated test coverage; see
those modules' own review for correctness instead.

A plain `sys.path.insert(...); import pattern_engine` doesn't work: that
module does `from .storage import ...`, a *relative* import, which only
resolves inside a real package - so a lightweight stand-in "action_suggestion"
package is registered in sys.modules first (just enough bookkeeping for
Python's import system, without ever executing the real __init__.py), then
each needed submodule is loaded into it individually.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_INTEGRATION_DIR = Path(__file__).parent.parent / "custom_components" / "action_suggestion"


def load_module(name: str):
    """`name` e.g. "storage" or "pattern_engine" - returns the loaded module."""
    if "action_suggestion" not in sys.modules:
        stub_package = types.ModuleType("action_suggestion")
        stub_package.__path__ = [str(_INTEGRATION_DIR)]
        sys.modules["action_suggestion"] = stub_package

    full_name = f"action_suggestion.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]

    spec = importlib.util.spec_from_file_location(full_name, _INTEGRATION_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module
