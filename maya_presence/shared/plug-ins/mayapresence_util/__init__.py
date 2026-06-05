"""
mayapresence_util — internal submodules for the Maya plug-in.

Re-exports are listed in the same bottom-up order as the layering so
the read order matches the dependency order:

    L0  settings, extension_monitor
    L1  shared_state
    L2  context, worker_thread
    L3  rpc
    L4  render_hooks
    L5  callbacks, timer
    L6  settings_menu

Anything that crosses a layer downward is a bug; anything that crosses
upward should go through this package's import surface, not via a
direct `from .submodule import X` from outside the package.
"""
# L0
from .settings import MPSettings
from .extension_monitor import MPExtensionMonitor

# L1
from .shared_state import (
    MP_DISCORD_APP_ID,
    MP_EXTENSIONS,
    MP_PREFS,
    MP_SESSION,
    MP_UPDATE_DETAILS,
    MP_WORKER,
    _clear_worker,
    _get_worker,
    _set_worker,
    mp_print,
)

# L2
from .context import MPContext
from .worker_thread import _MPRPCWorker

# L3
from .rpc import (
    MP_DISPLAY_TYPES,
    mp_update_large_icon,
    mp_update_presence,
    mp_update_presence_details,
    mp_update_presence_state,
    mp_update_small_icon,
    mp_update_small_icon_rendering,
    mp_update_small_icon_tool,
)

# L4
from .render_hooks import (
    MP_HOOK_END,
    MP_HOOK_START,
    mp_check_render_handlers_installed,
    mp_install_render_handlers,
    mp_on_frame_render_end,
    mp_on_render_end,
    mp_on_render_start,
    mp_uninstall_render_handlers,
    mp_wrap_mel,
)

# L5
from .callbacks import (
    MP_CALLBACKS,
    mp_add_callbacks,
    mp_observe_plugin_load,
    mp_observe_plugin_unload,
    mp_remove_callbacks,
)
from .timer import mp_cancel, mp_on_timer, mp_refresh_timer, mp_schedule

# L6
from .settings_menu import (
    MayaPresenceSettings,
    mp_install_settings_menu,
    mp_on_setting_change,
    mp_show_settings_dialog,
    mp_uninstall_settings_menu,
)
