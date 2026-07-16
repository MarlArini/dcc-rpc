"""
Main-thread polling timer.
The tick body also handles Redshift's behavior of not creating its
render options node until its settings menu is opened.
"""
import maya.api.OpenMaya as om  # pyright: ignore[reportMissingImports, reportMissingModuleSource] pylint: disable=import-error

from .shared_state import MP_PREFS
from .rpc import mp_update_presence
from .render_hooks import (
    mp_check_render_handlers_installed,
    mp_install_render_handlers,
)


MP_TIMER_CALLBACK_ID = None


def mp_on_timer(elapsed_time, last_time, client_data):  # pylint: disable=unused-argument
    # Redshift lazy-installs its options node when the user first opens
    # the Redshift render settings panel, so check each tick if there are
    # missing render handlers
    if not mp_check_render_handlers_installed():
        mp_install_render_handlers()

    mp_update_presence()


def mp_schedule():
    global MP_TIMER_CALLBACK_ID
    if MP_TIMER_CALLBACK_ID is not None:
        return
    MP_TIMER_CALLBACK_ID = om.MTimerMessage.addTimerCallback(
        MP_PREFS.generalUpdate, mp_on_timer
    )


def mp_cancel():
    global MP_TIMER_CALLBACK_ID
    if MP_TIMER_CALLBACK_ID is not None:
        try:
            om.MMessage.removeCallback(MP_TIMER_CALLBACK_ID)
        except RuntimeError:
            pass
        MP_TIMER_CALLBACK_ID = None


def mp_refresh_timer():
    """User changed the update period — reinstall with the new interval."""
    mp_cancel()
    mp_schedule()
