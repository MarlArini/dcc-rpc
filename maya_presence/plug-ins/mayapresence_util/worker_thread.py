"""Background thread for sending RPC updates."""

import copy
import threading
import time

from pypresence.presence import Presence
from pypresence import exceptions as pypresence_exceptions

from common import RPCUpdateDetails, SessionInfo, push_rpc_update

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
    the Maya application is not considered idle, so om.MTimerMessage
    will never fire. Qt timers also do not tick during a sequence render.
    The solution is to have a background thread that pushes RPC updates,
    and to update presence details manually from the MEL callbacks for
    render start/end.
    The thread handles rate limiting updates, so callers can publish
    to it as frequently as they desire."""

    def __init__(self, app_id: str):
        super().__init__(name="MayaPresenceRPC", daemon=True)
        self._client = Presence(app_id)
        self._session = SessionInfo()
        self._stop = threading.Event()
        self._stopped = False
        self._last_attempt = 0.0
        self._lock = threading.Lock()
        # Serializes access to self._client so the main thread can still
        # publish while the worker is mid-write.
        self._io_lock = threading.Lock()
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
        # If the join timed out the worker may still be inside a client call.
        acquired = self._io_lock.acquire(timeout=timeout)
        try:
            try:
                if self._session.connected:
                    self._client.clear()
            except BaseException:
                pass
            try:
                self._client.close()
            except BaseException:
                pass
        finally:
            if acquired:
                self._io_lock.release()
        self._session.connected = False

    def _ensure_connected(self) -> bool:
        if self._session.connected:
            return True
        try:
            self._client.connect()
            self._session.connected = True
            return True
        except Exception as e:  # noqa: BLE001
            mp_print(f"worker connect failed: {e}")
            return False

    def _push(self) -> None:
        # publish() rebinds self._details rather than mutating it, so grabbing
        # the reference under the lock is enough; the network write happens
        # under _io_lock instead so publish() never blocks behind a slow socket.
        with self._lock:
            details = self._details
        with self._io_lock:
            if not self._ensure_connected():
                return
            try:
                push_rpc_update(
                    self._session,
                    details,
                    MP_PREFS,
                    self._client,
                    "maya",
                    mp_print,
                )
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
        if not self._session.connected or self._session.cleared:
            return
        with self._io_lock:
            try:
                self._client.clear()
                self._session.cleared = True
            except _RPC_LOST_EXC as e:
                self._session.connected = False
                mp_print(f"Worker clear failed: {e}")
            except Exception as e:  # noqa: BLE001
                mp_print(f"Worker clear error (non-fatal): {e}")

    def run(self) -> None:
        while not self._stopped:
            self._stop.wait(1)
            # stop() sets the flag before waking us; re-check here so a
            # teardown never slips one more client call past the check above.
            if self._stopped:
                return
            if not MP_PREFS.generalEnable:
                self._clear()
                continue
            # Throttle on attempt time, not session.last_update (which only
            # advances on success) — otherwise a closed Discord client would
            # trigger a reconnect attempt and log line every second.
            if time.time() - self._last_attempt > MP_PREFS.generalUpdate:
                self._last_attempt = time.time()
                self._push()
