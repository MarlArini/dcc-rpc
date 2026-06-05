"""
Maya scene + plug-in lifecycle callback registration.
"""
import time
from typing import Set, Tuple

import maya.api.OpenMaya as om  # pyright: ignore[reportMissingImports, reportMissingModuleSource] pylint: disable=import-error

from .shared_state import MP_EXTENSIONS, mp_print, MP_PREFS, MP_SESSION
from .render_hooks import mp_install_render_handlers


# Registered om.MSceneMessage IDs, paired with a human-readable name for
# error reporting at removal time.
MP_CALLBACKS: Set[Tuple[str, int]] = set()


def mp_observe_plugin_load(string_array, clientData):  # pylint: disable=unused-argument,invalid-name
    """If the loaded plugin was a monitored render engine, populate its type table
    so the next presence compose can use it."""
    if not string_array:
        return
    # kAfterPluginLoad string array layout is [plugin_path, plugin_name]
    loaded_plugin_name = string_array[-1]
    for engine_name, engine in MP_EXTENSIONS.monitored_engines.items():
        if engine.plugin_name == loaded_plugin_name:
            MP_EXTENSIONS.init_engine(engine_name)
            return


def mp_observe_plugin_unload(string_array, clientData):  # pylint: disable=unused-argument,invalid-name
    """If a monitored render engine was unloaded, stop counting its types."""
    if not string_array:
        return
    # kAfterPluginUnload string array layout is [plugin_name, plugin_path]
    unloaded_plugin_name = string_array[0]
    for _name, engine in MP_EXTENSIONS.monitored_engines.items():
        if engine.plugin_name == unloaded_plugin_name:
            engine.loaded = False


def mp_on_file(*args): #pylint: disable=unused-argument
    mp_install_render_handlers()
    if MP_PREFS.resetTimer:
        MP_SESSION.start_time = time.time()


def mp_add_callbacks():
    """Register all callbacks.
      1. kAfterNew, kAfterOpen: re-run the render-hook installer so a
         scene change can't strand us with unregistered hooks. Install is
         idempotent and respects MP_PREFS.useRenderHooks.
      2. kAfterPluginLoad: detect when a monitored render engine just
         became available so we can populate its type tables.
      3. kAfterPluginUnload: detect when a monitored engine went away."""
    k_new = om.MSceneMessage.addCallback(
        om.MSceneMessage.kAfterNew, mp_on_file
    )
    k_open = om.MSceneMessage.addCallback(
        om.MSceneMessage.kAfterOpen, mp_on_file
    )
    k_load = om.MSceneMessage.addStringArrayCallback(
        om.MSceneMessage.kAfterPluginLoad, mp_observe_plugin_load
    )
    k_unload = om.MSceneMessage.addStringArrayCallback(
        om.MSceneMessage.kAfterPluginUnload, mp_observe_plugin_unload
    )
    MP_CALLBACKS.add(("kAfterNew", k_new))
    MP_CALLBACKS.add(("kAfterOpen", k_open))
    MP_CALLBACKS.add(("kAfterPluginLoad", k_load))
    MP_CALLBACKS.add(("kAfterPluginUnload", k_unload))


def mp_remove_callbacks():
    """Best-effort uninstall — failures are logged but don't abort the
    teardown sequence."""
    for cb in MP_CALLBACKS.copy():
        cb_name, cb_id = cb
        try:
            om.MMessage.removeCallback(cb_id)
        except RuntimeError as e:
            mp_print(f"failed to remove callback {cb_name}: {e}")
    MP_CALLBACKS.clear()
