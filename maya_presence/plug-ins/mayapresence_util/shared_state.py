"""
Layer 1: shared globals + worker accessor.

Imports allowed from: settings (L0), common, stdlib.

State sharing across module copies: Maya's plug-in loader execs
maya_presence.py without registering it in sys.modules, however,
submodules go through normal Python import machinery, so
`import mayapresence_util.shared_state` finds an existing
entry
"""

from typing import Any, Optional

from common import SessionInfo, RPCUpdateDetails

from .settings import MPSettings


MP_DISCORD_APP_ID = "1498143095852634252"

MP_PREFS: MPSettings = MPSettings()
MP_SESSION: SessionInfo = SessionInfo()
MP_UPDATE_DETAILS: RPCUpdateDetails = RPCUpdateDetails("maya")

# The running worker thread. Set by maya_presence.mp_start via _set_worker;
# read everywhere else via _get_worker. Module-level here means every
# importer of shared_state sees the same value (sys.modules caches the
# module), so this works as the canonical reference without builtins.
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
