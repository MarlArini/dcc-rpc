"""
MayaPresence is a Discord Rich Presence client plugin for Autodesk Maya, based on
https://github.com/abrasic/blendpresence. MayaPresence has been tested on Maya 2026
and Maya 2027. For more info, see https://github.com/MarlArini/dcc-rpc
"""

import atexit
import time

# pylint: disable=import-error, no-name-in-module, line-too-long, unused-import
import maya.cmds as cmds  # pyright: ignore[reportMissingImports, reportMissingModuleSource]
import maya.api.OpenMaya as om  # pyright: ignore[reportMissingImports, reportMissingModuleSource]

# Re-export the entire package surface. The plug-in's own lifecycle code
# below only needs a handful of names, but external callers (tests, MEL
# python() fragments, anything that scripts against the loaded plug-in)
# expect to find symbols at maya_presence.<name>. Listing the names
# explicitly rather than star-importing means private names (_get_worker
# etc.) come along intentionally instead of by accident.
from mayapresence_util import (  # noqa: F401  pylint: disable=unused-import
    # L0
    MPSettings,
    extension_types,
    # L1
    MP_DISCORD_APP_ID,
    MP_PREFS,
    MP_SESSION,
    MP_UPDATE_DETAILS,
    MP_WORKER,
    _clear_worker,
    _get_worker,
    _set_worker,
    mp_print,
    # L2
    MPContext,
    _MPRPCWorker,
    # L3
    MP_DISPLAY_TYPES,
    mp_update_large_icon,
    mp_update_presence,
    mp_update_presence_details,
    mp_update_presence_state,
    mp_update_small_icon,
    mp_update_small_icon_rendering,
    mp_update_small_icon_tool,
    # L4
    MP_HOOK_END,
    MP_HOOK_START,
    mp_check_render_handlers_installed,
    mp_install_render_handlers,
    mp_on_frame_render_end,
    mp_on_render_end,
    mp_on_render_start,
    mp_uninstall_render_handlers,
    mp_wrap_mel,
    # L5
    MP_CALLBACKS,
    mp_add_callbacks,
    mp_cancel,
    mp_observe_plugin_load,
    mp_observe_plugin_unload,
    mp_on_timer,
    mp_refresh_timer,
    mp_remove_callbacks,
    mp_schedule,
    # L6
    MayaPresenceSettings,
    mp_install_settings_menu,
    mp_on_setting_change,
    mp_show_settings_dialog,
    mp_uninstall_settings_menu,
)


###################
# Plugin Lifetime #
###################
# pylint: disable=invalid-name,unused-argument


def maya_useNewAPI():
    pass


# The canonical MP_WORKER reference lives in mayapresence_util.shared_state
# (re-exported above). All reads go through _get_worker(); writes go
# through _set_worker(). We don't keep a local module-level shadow here
# because that would diverge from shared_state's value the moment we
# rebind it.


def mp_start():
    if cmds.about(batch=True):
        return
    MP_SESSION.start_time = time.time()
    if _get_worker() is None:
        worker = _MPRPCWorker(MP_DISCORD_APP_ID)
        worker.start()
        _set_worker(worker)
    # Seed the extension-type cache from whatever plug-ins are already
    # loaded at this point. mp_add_callbacks below registers the
    # kAfterPluginLoad/Unload handlers that keep it refreshed.
    extension_types.rebuild()
    mp_update_presence()
    if MP_PREFS.useRenderHooks:
        mp_install_render_handlers()
    mp_install_settings_menu()
    mp_add_callbacks()
    mp_schedule()


def mp_stop():
    if cmds.about(batch=True):
        return
    worker = _get_worker()
    cleanup_steps = [
        ("cancel timer", mp_cancel),
        ("stop RPC worker", worker.stop if worker is not None else None),
        ("remove callbacks", mp_remove_callbacks),
        ("uninstall render handlers", mp_uninstall_render_handlers),
        ("uninstall settings menu", mp_uninstall_settings_menu),
    ]
    for description, step in cleanup_steps:
        if step is None:
            continue
        try:
            step()
        except Exception as e:  # noqa: BLE001
            mp_print(f"failed to {description}: {e}")
    _clear_worker()


def initializePlugin(mobject):
    # pylint: disable=unused-variable
    fn = om.MFnPlugin(mobject, "MarlArini", "1.0", "Any")  # noqa: F841
    mp_start()


def uninitializePlugin(plugin):
    mp_stop()


def _mp_atexit():
    """Insurance against process exit without uninitializePlugin (e.g.
    Maya killed). stop() drains clear+close from inside the worker."""
    worker = _get_worker()
    if worker is not None:
        try:
            worker.stop(timeout=1.0)
        except BaseException:
            pass


atexit.register(_mp_atexit)
