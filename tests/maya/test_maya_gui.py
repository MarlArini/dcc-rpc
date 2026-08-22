"""
Headless-Qt integration tests for the Maya settings dialog and the
menu-item install/uninstall flow.

Maya doesn't use a Qt menubar for plugin install — `mp_install_settings_menu`
calls `cmds.menuItem(...)` to register an entry under Maya's mainWindowMenu.
The fake `cmds.menuItem` records that into `cmds._state.menu_items` and
`cmds.deleteUI` removes it, so the install path is testable end-to-end
without a real Maya UI.

`mp_show_settings_dialog` constructs `MayaPresenceSettings`
(MayaQWidgetDockableMixin + QtSettingsGUIMenu) and calls `.show()`. The mixin
is an inert stand-in in the fake, so the dialog behaves like a plain
QtSettingsGUIMenu; .show() flashes a window, hence the `gui` marker.

What we cover:
  - install_settings_menu adds a menuItem with id 'mayaPresenceSettingsMenuItem'
    parented to mainWindowMenu, with the expected label and a command
  - install removes any previous menu item with the same id first
  - uninstall_settings_menu deletes the menu item; no-op when it wasn't
    installed
  - mp_show_settings_dialog constructs a MayaPresenceSettings, stores it in
    settings_menu.MP_SETTINGS_WINDOW, and replaces a previously-open dialog
  - field-to-widget construction over MPSettings, which adds the RenderSettings
    Detail-group fields, a countExtensions toggle in General, and a 'Rendering'
    group for the Maya-only render options
  - controller-driven sensitivity reaches the Maya-specific Details fields and
    stops at the Rendering group
  - reset-to-defaults restores fields including the _INITIAL_DEFAULTS
    overrides and countExtensions
"""
from __future__ import annotations
from dataclasses import fields

import pytest
from PySide6 import QtWidgets

from common import QtSettingsGUIMenu
import maya_presence as mp


# mp_show_settings_dialog calls QDialog.show() which briefly flashes a window.
# Mark the whole file `gui` so the default `pytest` run (-m 'not gui') skips it.
pytestmark = pytest.mark.gui


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings_window():
    """Yield the module that owns MP_SETTINGS_WINDOW, with the singleton reset.

    mp_show_settings_dialog rebinds MP_SETTINGS_WINDOW via `global`, so it has
    to be read and written on mayapresence_util.settings_menu — a copy imported
    onto maya_presence would go stale the moment a dialog opens, which is why
    maya_presence.py doesn't re-export it (same reasoning as MP_WORKER).

    Any dialog a test opened is closed on the way out so `pytest -m gui`
    doesn't leave windows on screen."""
    from mayapresence_util import settings_menu  # noqa: PLC0415

    snap = settings_menu.MP_SETTINGS_WINDOW
    settings_menu.MP_SETTINGS_WINDOW = None
    yield settings_menu
    opened = settings_menu.MP_SETTINGS_WINDOW
    if opened is not None and opened is not snap:
        try:
            opened.close()
            opened.deleteLater()
        except RuntimeError:
            pass
    settings_menu.MP_SETTINGS_WINDOW = snap


@pytest.fixture
def prefs_snapshot():
    """Snapshot every public field on MP_PREFS, reset to declared defaults
    (incl. _INITIAL_DEFAULTS overrides), yield the prefs, then restore the
    snapshot. The reset before yield insulates our tests from prior tests
    that mutate MP_PREFS.detailsType / stateType without restoring them.
    Uses object.__setattr__ on teardown to bypass the persistence side
    effect in MPSettings.__setattr__."""
    p = mp.MP_PREFS
    snap = {f.name: getattr(p, f.name) for f in fields(p) if not f.name.startswith("_")}
    for f in fields(p):
        if f.name.startswith("_"):
            continue
        default = p._INITIAL_DEFAULTS.get(f.name, f.default)
        object.__setattr__(p, f.name, default)
    yield p
    for k, v in snap.items():
        object.__setattr__(p, k, v)


@pytest.fixture
def dialog(prefs_snapshot):
    refresh_calls: list[int] = []
    dlg = mp.MayaPresenceSettings(
        prefs=prefs_snapshot,
        refresh_func=lambda: refresh_calls.append(1),
        app_name="Maya",
    )
    dlg._refresh_calls = refresh_calls  # type: ignore[attr-defined]
    yield dlg
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# install / uninstall menu flow
# ---------------------------------------------------------------------------


# mp_install_settings_menu installs a post-menu callback (PMC) on
# mainWindowMenu instead of creating the menuItem directly. The actual
# menuItem creation happens in _mp_add_settings_menu_item, which the PMC
# runs the first time the user opens the Window menu. This mirrors how
# MayaUSD avoids racing with Maya's main-menu construction.


def test_install_settings_menu_appends_pmc_fragment(cmds):
    """install should append MP_MENU_PMC to mainWindowMenu's postMenuCommand
    rather than touching the menu's children. The fragment is what gets
    evaluated when the user first opens the Window menu."""
    mp.mp_install_settings_menu()
    pmc = cmds.menu("mainWindowMenu", query=True, postMenuCommand=True)
    assert mp.MP_MENU_PMC in pmc


def test_install_settings_menu_idempotent(cmds):
    """A second install must not double-append the PMC fragment."""
    mp.mp_install_settings_menu()
    pmc_after_one = cmds.menu("mainWindowMenu", query=True, postMenuCommand=True)
    mp.mp_install_settings_menu()
    pmc_after_two = cmds.menu("mainWindowMenu", query=True, postMenuCommand=True)
    assert pmc_after_one == pmc_after_two
    assert pmc_after_two.count(mp.MP_MENU_PMC) == 1


def test_install_preserves_existing_pmc_callbacks(cmds):
    """install must append, not replace — other plug-ins' PMC fragments
    have to stay intact."""
    cmds.menu(
        "mainWindowMenu", edit=True,
        postMenuCommand="print('other plugin');",
    )
    mp.mp_install_settings_menu()
    pmc = cmds.menu("mainWindowMenu", query=True, postMenuCommand=True)
    assert "print('other plugin');" in pmc
    assert mp.MP_MENU_PMC in pmc


def test_install_settings_menu_does_not_register_menu_item_directly(cmds):
    """install only appends the PMC; the menuItem itself isn't created
    until the PMC runs."""
    mp.mp_install_settings_menu()
    assert "mayaPresenceSettingsMenuItem" not in cmds.get_state().menu_items


def test_add_settings_menu_item_registers_under_main_window_menu(cmds):
    """The PMC callback (or a direct test invocation) creates the actual
    menuItem under mainWindowMenu."""
    mp._mp_add_settings_menu_item()
    item = cmds.get_state().menu_items["mayaPresenceSettingsMenuItem"]
    assert item["parent"] == "mainWindowMenu"
    assert item["label"] == "Maya Presence Settings…"
    assert callable(item["command"])


def test_add_settings_menu_item_idempotent(cmds):
    """Re-running the add path (e.g., the PMC firing on every menu open)
    must not register duplicate menuItems."""
    mp._mp_add_settings_menu_item()
    mp._mp_add_settings_menu_item()
    assert "mayaPresenceSettingsMenuItem" in cmds.get_state().menu_items


def test_uninstall_strips_pmc_fragment(cmds):
    """uninstall must remove our PMC fragment so a future Window-menu open
    doesn't recreate the item we just deleted."""
    mp.mp_install_settings_menu()
    assert mp.MP_MENU_PMC in cmds.menu(
        "mainWindowMenu", query=True, postMenuCommand=True
    )
    mp.mp_uninstall_settings_menu()
    pmc = cmds.menu("mainWindowMenu", query=True, postMenuCommand=True)
    assert mp.MP_MENU_PMC not in pmc


def test_uninstall_strips_pmc_but_leaves_other_callbacks(cmds):
    """uninstall must remove only our fragment, not the whole PMC."""
    cmds.menu(
        "mainWindowMenu", edit=True,
        postMenuCommand="print('other plugin');",
    )
    mp.mp_install_settings_menu()
    mp.mp_uninstall_settings_menu()
    pmc = cmds.menu("mainWindowMenu", query=True, postMenuCommand=True)
    assert "print('other plugin');" in pmc
    assert mp.MP_MENU_PMC not in pmc


def test_uninstall_removes_menu_item_if_present(cmds):
    """uninstall must also clean up the actual menuItem if the PMC already
    fired and created it."""
    mp._mp_add_settings_menu_item()
    assert "mayaPresenceSettingsMenuItem" in cmds.get_state().menu_items
    mp.mp_uninstall_settings_menu()
    assert "mayaPresenceSettingsMenuItem" not in cmds.get_state().menu_items


def test_uninstall_no_op_when_not_installed(cmds):
    """When neither the PMC fragment nor the menuItem is present, uninstall
    must not raise."""
    assert "mayaPresenceSettingsMenuItem" not in cmds.get_state().menu_items
    mp.mp_uninstall_settings_menu()


# ---------------------------------------------------------------------------
# mp_show_settings_dialog
# ---------------------------------------------------------------------------


def test_open_settings_menu_creates_dialog(settings_window):
    returned = mp.mp_show_settings_dialog()
    assert isinstance(settings_window.MP_SETTINGS_WINDOW, mp.MayaPresenceSettings)
    assert settings_window.MP_SETTINGS_WINDOW is returned
    assert "Maya" in settings_window.MP_SETTINGS_WINDOW.windowTitle()


def test_open_settings_menu_replaces_existing(settings_window):
    """Unlike the Qt-hosted plugins (which reuse one dialog via
    RPCBasePlugin.show_qt_window), Maya closes and recreates: the dockable
    mixin's window can be torn down by Maya's own UI teardown, so a fresh
    instance each time avoids reusing a dead wrapper."""
    mp.mp_show_settings_dialog()
    first = settings_window.MP_SETTINGS_WINDOW
    mp.mp_show_settings_dialog()
    second = settings_window.MP_SETTINGS_WINDOW
    assert first is not second
    assert isinstance(second, mp.MayaPresenceSettings)


def test_install_command_opens_dialog(cmds, settings_window):
    """Wire test: firing the registered menuItem's command path should result
    in MP_SETTINGS_WINDOW being populated. The menuItem itself is created by
    _mp_add_settings_menu_item (what the PMC would call on first menu open);
    we invoke it directly here, then trigger the command the same way Maya
    would (with a positional 'state' arg the lambda ignores)."""
    mp._mp_add_settings_menu_item()
    cmd = cmds.get_state().menu_items["mayaPresenceSettingsMenuItem"]["command"]
    cmd(None)
    assert isinstance(settings_window.MP_SETTINGS_WINDOW, mp.MayaPresenceSettings)


# ---------------------------------------------------------------------------
# Field-to-widget construction
# ---------------------------------------------------------------------------


def test_maya_dialog_builds_on_the_shared_qt_menu(dialog):
    """MayaPresenceSettings is MayaQWidgetDockableMixin + QtSettingsGUIMenu, so
    every dialog behavior tested below comes from the shared base class."""
    assert issubclass(mp.MayaPresenceSettings, QtSettingsGUIMenu)
    assert isinstance(dialog, QtSettingsGUIMenu)


def test_dialog_object_name_uses_maya_app_name(dialog):
    assert dialog.objectName() == "MayaPresenceSettingsDialog"


def test_dialog_creates_widget_for_every_metadata_field(dialog):
    for f in fields(dialog._prefs):
        if f.metadata.get("group") is None:
            continue
        assert f.name in dialog._gui_widgets, f"missing widget for {f.name}"


def test_dialog_groups_include_rendering(dialog):
    """Maya's MPSettings adds a 'Rendering' group on top of the SharedSettings
    standard five."""
    assert set(dialog._groups.keys()) == {
        "General", "Icons", "Details", "State", "Buttons", "Rendering",
    }


def test_dialog_widget_types_match_maya_field_types(dialog):
    type_by_kind = {
        "checkbox": QtWidgets.QCheckBox,
        "spinbox": QtWidgets.QSpinBox,
        "lineedit": QtWidgets.QLineEdit,
        "combobox": QtWidgets.QComboBox,
    }
    for f in fields(dialog._prefs):
        if f.metadata.get("group") is None:
            continue
        widget = dialog._gui_widgets[f.name]
        kind = dialog._widget_kind(f)
        assert isinstance(widget, type_by_kind[kind]), (
            f"{f.name}: expected {type_by_kind[kind].__name__}, "
            f"got {type(widget).__name__}"
        )


def test_dialog_includes_maya_specific_details_fields(dialog):
    """The RenderSettings mixin adds four fields to the Details group on top of
    SharedSettings — each must get its own checkbox. (displayGPU is Maya's own
    and lives in the Rendering group, not here.)"""
    details_fields = {f.name for f in dialog._groups["Details"]}
    for name in (
        "displayEngine", "displayRenderStats", "displayFileName", "displayFrames",
    ):
        assert name in details_fields
        assert isinstance(dialog._gui_widgets[name], QtWidgets.QCheckBox)
    assert "displayGPU" not in details_fields


def test_dialog_rendering_group_holds_maya_render_toggles(dialog):
    """The Rendering group carries the two Maya-only render options: the MEL
    render-hook install toggle and the GPU-name display."""
    render_fields = {f.name for f in dialog._groups["Rendering"]}
    assert render_fields == {"useRenderHooks", "displayGPU"}
    for name in render_fields:
        assert isinstance(dialog._gui_widgets[name], QtWidgets.QCheckBox)


def test_dialog_count_extensions_is_a_general_toggle(dialog):
    """The per-engine countArnold/countRS/countPxr/countVRay fields were
    consolidated into one countExtensions checkbox covering all third-party
    renderers. It sits in General — it affects the light/material/texture
    counts, which are displayed whether or not a render is running."""
    assert "countExtensions" in {f.name for f in dialog._groups["General"]}
    assert isinstance(dialog._gui_widgets["countExtensions"], QtWidgets.QCheckBox)


def test_dialog_combobox_populated_with_maya_info_choices(dialog):
    """detailsType / stateType comboboxes pull MPSettings.INFO_CHOICES with
    Maya-specific keys like 'poly', 'joint', 'context'."""
    cb = dialog._gui_widgets["detailsType"]
    items = [(cb.itemText(i), cb.itemData(i)) for i in range(cb.count())]
    assert items == mp.MPSettings.INFO_CHOICES
    assert ("Poly count", "poly") in items
    assert ("Current tool context", "context") in items


def test_dialog_combobox_initial_value_from_initial_defaults(dialog):
    """_INITIAL_DEFAULTS pins detailsType='scene' and stateType='poly'."""
    assert dialog._gui_widgets["detailsType"].currentData() == "scene"
    assert dialog._gui_widgets["stateType"].currentData() == "poly"


# ---------------------------------------------------------------------------
# Controller-driven sensitivity
# ---------------------------------------------------------------------------


def test_controller_dict_includes_maya_masters_and_controls(dialog):
    controllers = dialog._controllers
    assert "enableDetails" in controllers
    assert "enableState" in controllers
    assert controllers["enableButton1"] == ["button1Label", "button1Url"]
    assert controllers["enableButton2"] == ["button2Label", "button2Url"]


def test_details_master_controls_maya_extra_fields(dialog):
    """The four RenderSettings Detail fields should be reachable by the
    Details group_master. displayGPU is in Rendering, so it is not — turning
    the details field off must not gray out a Rendering-group option."""
    controlled = dialog._controllers["enableDetails"]
    for name in (
        "displayEngine", "displayRenderStats", "displayFileName", "displayFrames",
    ):
        assert name in controlled
    assert "displayGPU" not in controlled


def test_rendering_group_has_no_master(dialog):
    """Neither the Rendering group nor countExtensions declares a
    group_master, so none of them appear as controllers. Pins that a future
    maintainer who decides to add a master notices the test."""
    controllers = dialog._controllers
    assert "countExtensions" not in controllers
    assert "useRenderHooks" not in controllers
    assert "displayGPU" not in controllers


def test_button2_disabled_widgets_grayed_by_default(dialog):
    assert dialog._gui_widgets["button2Label"].isEnabled() is False
    assert dialog._gui_widgets["button2Url"].isEnabled() is False


def test_button2_toggle_re_enables_controlled_widgets(dialog):
    dialog._gui_widgets["enableButton2"].setChecked(True)
    assert dialog._gui_widgets["button2Label"].isEnabled() is True
    assert dialog._gui_widgets["button2Url"].isEnabled() is True


def test_details_master_disable_grays_maya_extras(dialog):
    dialog._gui_widgets["enableDetails"].setChecked(False)
    for name in (
        "detailsType", "customDetails", "detailsCycle",
        "displayEngine", "displayRenderStats",
        "displayFileName", "displayFrames",
    ):
        assert dialog._gui_widgets[name].isEnabled() is False, (
            f"{name} should be disabled when enableDetails is off"
        )
    # Rendering-group options are independent of the Details master.
    assert dialog._gui_widgets["displayGPU"].isEnabled() is True


# ---------------------------------------------------------------------------
# Reset-to-defaults
# ---------------------------------------------------------------------------


def test_reset_restores_initial_defaults_combobox(dialog, prefs_snapshot, monkeypatch):
    dialog._gui_widgets["stateType"].setCurrentIndex(
        dialog._gui_widgets["stateType"].findData("context")
    )
    assert prefs_snapshot.stateType == "context"
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.stateType == "poly"
    assert dialog._gui_widgets["stateType"].currentData() == "poly"


def test_reset_restores_maya_render_extension_default(dialog, prefs_snapshot, monkeypatch):
    """countExtensions defaults to True; flip it off, reset, expect True back."""
    dialog._gui_widgets["countExtensions"].setChecked(False)
    assert prefs_snapshot.countExtensions is False
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.countExtensions is True
    assert dialog._gui_widgets["countExtensions"].isChecked() is True


def test_reset_no_op_when_user_cancels(dialog, prefs_snapshot, monkeypatch):
    dialog._gui_widgets["generalUpdate"].setValue(40)
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.No),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.generalUpdate == 40
