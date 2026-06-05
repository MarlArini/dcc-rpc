"""Background thread for sending RPC updates."""
import copy
import threading
import time
from typing import Optional

from pypresence.presence import Presence
from pypresence import exceptions as pypresence_exceptions

from common import RPCUpdateDetails, rpc_update

from .shared_state import MP_PREFS, mp_print

_RPC_LOST_EXC = (
    pypresence_exceptions.InvalidID,
    pypresence_exceptions.PipeClosed,
    pypresence_exceptions.DiscordNotFound,
    pypresence_exceptions.ServerError,
    AssertionError,
)


class _MPRPCWorker(threading.Thread):
    """Daemon thread that owns the Presence client.
    During sequence renders and certain other events like file dialogs,
    the Maya application is not considered idle, and so om.MTimerMessage
    will never fire. Qt timers also do not tick during a sequence render.
    The solution is to have a background thread that pushes RPC updates,
    and to update presence details manually from the MEL callbacks for
    render start/end.
    The thread handles rate limiting updates, so callers can publish
    to it as frequently as they desire."""

    def __init__(self, app_id: str):
        super().__init__(name="MayaPresenceRPC", daemon=True)
        self._client = Presence(app_id)
        self._connected = False
        self._stop = threading.Event()
        self._stopped = False
        self._last_update_time = 0.0
        self._lock = threading.Lock()
        self._details = RPCUpdateDetails("maya")

    def stop(self, timeout: float = 2.0) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._stop.set()
        if self.is_alive() and threading.current_thread() is not self:
            try:
                self.join(timeout=timeout)
            except RuntimeError:
                pass
        try:
            if self._connected:
                self._client.clear()
        except BaseException:
            pass
        try:
            self._client.close()
        except BaseException:
            pass
        self._connected = False

    def _ensure_connected(self) -> bool:
        if self._connected:
            return True
        try:
            self._client.connect()
            self._connected = True
            return True
        except Exception as e:  # noqa: BLE001
            mp_print(f"worker connect failed: {e}")
            return False

    def _push(self) -> None:
        if not self._ensure_connected():
            return
        try:
            with self._lock:
                rpc_update(self._details, self._client, MP_PREFS.enableTime)
        except _RPC_LOST_EXC as e:
            self._connected = False
            mp_print(f"worker push failed: {e}")
        except Exception as e:  # noqa: BLE001
            mp_print(f"worker push error (non-fatal): {e}")

    def publish(self, details) -> None:
        """Called at the end of mp_update_presence. Makes a local copy of
        the details object which is used in RPC updates to avoid reading a
        half-updated details object with inconsistent fields if the thread
        ticks for an update between events in the mp_update_presence function.
        Prefs are not copied since they only update one-at-a-time via user
        interaction, while details need to be updated all at once.
        """
        with self._lock:
            self._details = copy.copy(details)

    def _clear(self) -> None:
        if not self._connected:
            return
        try:
            self._client.clear()
        except _RPC_LOST_EXC as e:
            self._connected = False
            mp_print(f"worker clear failed: {e}")
        except Exception as e:  # noqa: BLE001
            mp_print(f"worker clear error (non-fatal): {e}")

    def run(self) -> None:
        while not self._stopped:
            self._stop.wait(1)
            if not MP_PREFS.generalEnable:
                self._clear()
                continue
            if time.time() - self._last_update_time > MP_PREFS.generalUpdate:
                self._push()
                self._last_update_time = time.time()
