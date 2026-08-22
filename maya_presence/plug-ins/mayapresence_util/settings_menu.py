"""Settings menu installation."""
import maya.cmds as cmds  # pyright: ignore[reportMissingImports] pylint: disable=import-error
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin  # pyright: ignore[reportMissingImports] pylint: disable=import-error

from common import QtSettingsGUIMenu
from .shared_state import MP_PREFS
from .render_hooks import (
    mp_check_render_handlers_installed,
    mp_install_render_handlers,
    mp_uninstall_render_handlers,
    mp_wrap_mel,
)
from .rpc import mp_update_presence
from .timer import mp_refresh_timer


# Module-scoped settings-window singleton. Was previously declared in
# shared_state.py, but the `global MP_SETTINGS_WINDOW` in
# mp_show_settings_dialog only rebinds the *local* module's name —
# cross-module `global` doesn't work — so the singleton was effectively
# orphaned across modules. Keeping it here, where the only writer is,
# fixes that quietly.
MP_SETTINGS_WINDOW = None


class MayaPresenceSettings(MayaQWidgetDockableMixin, QtSettingsGUIMenu):
    pass


def mp_on_setting_change():
    if not MP_PREFS.useRenderHooks and mp_check_render_handlers_installed():
        mp_uninstall_render_handlers()
    elif MP_PREFS.useRenderHooks and not mp_check_render_handlers_installed():
        mp_install_render_handlers()
    mp_update_presence()
    mp_refresh_timer()


def mp_show_settings_dialog():
    global MP_SETTINGS_WINDOW
    if MP_SETTINGS_WINDOW is not None:
        try:
            MP_SETTINGS_WINDOW.close()
            MP_SETTINGS_WINDOW.deleteLater()
        except Exception:  # noqa: BLE001
            pass
    MP_SETTINGS_WINDOW = MayaPresenceSettings(
        prefs=MP_PREFS, refresh_func=mp_on_setting_change, app_name="Maya"
    )
    MP_SETTINGS_WINDOW.show()
    MP_SETTINGS_WINDOW.raise_()
    MP_SETTINGS_WINDOW.activateWindow()
    return MP_SETTINGS_WINDOW


def _mp_add_settings_menu_item():
    """Add the settings menuItem under mainWindowMenu. Called from the PMC
    the first time the user opens the Window menu, or directly by tests."""
    if cmds.menuItem("mayaPresenceSettingsMenuItem", exists=True):
        return
    cmds.menuItem(
        "mayaPresenceSettingsMenuItem",
        label="Maya Presence Settings…",
        parent="mainWindowMenu",
        command=lambda *_: mp_show_settings_dialog(),
    )


MP_MENU_PMC = mp_wrap_mel(_mp_add_settings_menu_item, True, False)


def mp_install_settings_menu():
    """Append a post-menu callback to mainWindowMenu instead of inserting the
    menuItem now."""
    try:
        existing_pmc = (
            cmds.menu("mainWindowMenu", query=True, postMenuCommand=True) or ""
        )
    except RuntimeError:
        return
    if MP_MENU_PMC in existing_pmc:
        return  # already hooked
    cmds.menu(
        "mainWindowMenu", edit=True, postMenuCommand=existing_pmc + ";;" + MP_MENU_PMC
    )


def mp_uninstall_settings_menu():
    """Remove our menuItem AND strip our PMC fragment, so the Window menu's
    post-menu callback doesn't try to recreate the item on the next open."""
    if cmds.menuItem("mayaPresenceSettingsMenuItem", exists=True):
        cmds.deleteUI("mayaPresenceSettingsMenuItem", menuItem=True)
    try:
        existing_pmc = (
            cmds.menu("mainWindowMenu", query=True, postMenuCommand=True) or ""
        )
    except RuntimeError:
        return
    new_pmc = existing_pmc.replace(";;" + MP_MENU_PMC, "")
    if new_pmc != existing_pmc:
        try:
            cmds.menu("mainWindowMenu", edit=True, postMenuCommand=new_pmc)
        except RuntimeError:
            pass
