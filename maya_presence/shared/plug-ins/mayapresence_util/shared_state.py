"""
Layer 1: shared globals + worker accessor.

Imports allowed from: settings (L0), extension_monitor (L0), common, stdlib.
This module must NOT import from higher-layer modules (render_hooks, rpc,
context, settings_menu, timer, callbacks) — those depend on this module,
so any reverse edge creates a cycle.

State sharing across module copies: Maya's plug-in loader exec's
maya_presence.py without registering it in sys.modules, so a subsequent
`import maya_presence` from anywhere creates a duplicate top-level
module. THIS package, however, goes through normal Python import
machinery — `import mayapresence_util.shared_state` finds an existing
entry in sys.modules after the first import, so every reader of
`shared_state.MP_PREFS` (or any other module-level global declared
here) gets the same instance regardless of which maya_presence copy
they're being called from.

That's why these globals don't need the builtins-stash workaround that
they would if they lived in maya_presence.py — sys.modules handles the
sharing for us at this layer.
"""
from typing import Any, Optional

from common import SessionInfo, RPCUpdateDetails

from .settings import MPSettings
from .extension_monitor import MPExtensionMonitor


MP_DISCORD_APP_ID = "1498143095852634252"
MP_EXTENSIONS = MPExtensionMonitor()

MP_PREFS: MPSettings = MPSettings()
MP_SESSION: SessionInfo = SessionInfo()
MP_UPDATE_DETAILS: RPCUpdateDetails = RPCUpdateDetails("maya")

# The running worker thread. Set by maya_presence.mp_start via _set_worker;
# read everywhere else via _get_worker. Module-level here means every
# importer of shared_state sees the same value (sys.modules caches the
# module), so this works as the canonical reference without builtins.
# Typed Optional[Any] rather than Optional[_MPRPCWorker] so this module
# stays at L1 — importing _MPRPCWorker from worker_thread (L2) would be
# an upward edge and a cycle.
MP_WORKER: Optional[Any] = None


def mp_print(msg: str):
    print(f"[MayaPresence] {msg}")


def _get_worker() -> Optional[Any]:
    return MP_WORKER


def _set_worker(worker: Optional[Any]):
    global MP_WORKER
    MP_WORKER = worker


def _clear_worker():
    """Drop the worker reference at plugin teardown."""
    global MP_WORKER
    MP_WORKER = None
