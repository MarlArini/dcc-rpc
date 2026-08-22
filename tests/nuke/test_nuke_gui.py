"""
Headless-Qt integration tests for the Nuke settings dialog and the Discord
menu install/start/stop flow.

Nuke's menu install differs from the Substance plugins — there's no real
Qt menubar involved at install time. The plugin calls `nuke.menu("Nuke").
addMenu("Discord")`, which on a host Nuke goes through nuke's own scripted
menu API (not Qt). Our `nuke` fake records the install into a tree we can
inspect (`nk._state.top_menu.submenus`), so the install/start/stop flow is
testable without spinning up any Qt menubar of our own.

`nk_open_settings` builds a real `NukeSettingsWindow` (a QtSettingsGUIMenu
subclass) and calls `.show()` — that briefly flashes a window, hence the
`gui` marker.

What we cover:
  - NK_MENU is installed at module import with 'Discord' submenu containing
    Enable Rich Presence / Disable Rich Presence / Settings commands
  - NKMenu.start() flips prefs.generalEnable to True and the menu items'
    enabled states (start grayed, stop live)
  - NKMenu.stop() does the inverse
  - nk_open_settings creates NK_SETTINGS_WINDOW (a NukeSettingsWindow); a
    second call while the window is visible reuses it (no flicker / leak)
  - nk_open_settings creates a fresh window after the previous was hidden
  - field-to-widget construction over NKSettings, which adds
    `displayRenderStats`/`displayFrames` to Details and `displayFileName`
    to General
  - controller-driven sensitivity for group_master and controls
  - reset-to-defaults restores fields including _INITIAL_DEFAULTS overrides
"""
from __future__ import annotations
from dataclasses import fields

import pytest
from PySide6 import QtWidgets

from common import QtSettingsGUIMenu
from nuke_presence import menu as nm


# nk_open_settings calls QDialog.show() which briefly flashes a window. Mark
# the whole file `gui` so the default `pytest` run (-m 'not gui') skips it.
pytestmark = pytest.mark.gui


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def prefs_snapshot():
    """Snapshot every public field on NK_PREFS, reset to declared defaults
    (incl. _INITIAL_DEFAULTS overrides), yield the prefs, then restore the
    snapshot. The reset before yield insulates our tests from prior tests
    that mutate NK_PREFS.detailsType / stateType without restoring them."""
    p = nm.NK_PREFS
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
def menu_state_clean():
    """Snapshot/restore NK_SETTINGS_WINDOW and the enable/disable menu item
    states so tests don't leak into each other."""
    snap_window = nm.NK_SETTINGS_WINDOW
    snap_general_enable = nm.NK_PREFS.generalEnable
    snap_enable = nm.NK_MENU.enable_item.enabled
    snap_disable = nm.NK_MENU.disable_item.enabled
    yield
    nm.NK_SETTINGS_WINDOW = snap_window
    nm.NK_PREFS.generalEnable = snap_general_enable
    nm.NK_MENU.enable_item.enabled = snap_enable
    nm.NK_MENU.disable_item.enabled = snap_disable


@pytest.fixture
def dialog(prefs_snapshot):
    """Build a NukeSettingsWindow directly; bypasses nk_open_settings's
    QApplication.activeWindow() and the show() call, so this fixture itself
    doesn't flash."""
    refresh_calls: list[int] = []
    dlg = nm.NukeSettingsWindow()
    dlg._refresh = lambda: refresh_calls.append(1)  # type: ignore[method-assign]
    dlg._refresh_calls = refresh_calls  # type: ignore[attr-defined]
    yield dlg
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# NK_MENU install — happens at module import
#
# The autouse `_reset_nuke_fake_state` fixture wipes nk._state before each
# test, including top_menu — so the install done at module import time isn't
# visible here. We re-run a fresh `NKMenu(...)` to exercise the install path
# from scratch and assert on the resulting menu tree.
# ---------------------------------------------------------------------------


def test_nk_menu_install_creates_discord_submenu(nk, menu_state_clean):
    nm.NKMenu(nm.NK_PREFS)
    assert "Discord" in nk._state.top_menu.submenus


def test_nk_menu_install_adds_three_commands(nk, menu_state_clean):
    nm.NKMenu(nm.NK_PREFS)
    discord = nk._state.top_menu.submenus["Discord"]
    labels = [c.label for c in discord.commands]
    assert labels == ["Enable Rich Presence", "Disable Rich Presence", "Settings"]


def test_nk_menu_install_wires_settings_command_to_nk_open_settings(
    nk, menu_state_clean
):
    """The third command in the Discord submenu fires nk_open_settings."""
    nm.NKMenu(nm.NK_PREFS)
    discord = nk._state.top_menu.submenus["Discord"]
    settings_cmd = next(c for c in discord.commands if c.label == "Settings")
    assert settings_cmd.command is nm.nk_open_settings


def test_nk_menu_install_mirrors_loaded_general_enable_true(nk, menu_state_clean):
    """NKMenu.__init__ mirrors prefs.generalEnable into the menu items rather
    than forcing it on. With generalEnable=True at install time, the Enable
    item is grayed out and the Disable item is live."""
    nm.NK_PREFS.generalEnable = True
    fresh = nm.NKMenu(nm.NK_PREFS)
    assert fresh.enable_item.enabled is False
    assert fresh.disable_item.enabled is True


def test_nk_menu_install_mirrors_loaded_general_enable_false(nk, menu_state_clean):
    """Regression: with generalEnable=False at install time (the user paused
    presence in a previous session), the menu must reflect that, NOT
    silently flip back to enabled."""
    nm.NK_PREFS.generalEnable = False
    fresh = nm.NKMenu(nm.NK_PREFS)
    assert fresh.enable_item.enabled is True
    assert fresh.disable_item.enabled is False
    # And the value was preserved, not clobbered by NKMenu.__init__.
    assert nm.NK_PREFS.generalEnable is False


# ---------------------------------------------------------------------------
# NKMenu.start / .stop — pause/restart equivalent
# ---------------------------------------------------------------------------


def test_nk_menu_stop_disables_general_enable(nk, menu_state_clean):
    nm.NK_PREFS.generalEnable = True
    nm.NK_MENU.stop()
    assert nm.NK_PREFS.generalEnable is False


def test_nk_menu_stop_toggles_item_enabled_state(nk, menu_state_clean):
    nm.NK_MENU.start()  # reset to known state
    nm.NK_MENU.stop()
    assert nm.NK_MENU.enable_item.enabled is True
    assert nm.NK_MENU.disable_item.enabled is False


def test_nk_menu_start_enables_general_enable(nk, menu_state_clean):
    nm.NK_PREFS.generalEnable = False
    nm.NK_MENU.start()
    assert nm.NK_PREFS.generalEnable is True


def test_nk_menu_start_toggles_item_enabled_state(nk, menu_state_clean):
    nm.NK_MENU.stop()
    nm.NK_MENU.start()
    assert nm.NK_MENU.enable_item.enabled is False
    assert nm.NK_MENU.disable_item.enabled is True


def test_nk_menu_start_stop_round_trips(nk, menu_state_clean):
    nm.NK_PREFS.generalEnable = True
    nm.NK_MENU.stop()
    assert nm.NK_PREFS.generalEnable is False
    nm.NK_MENU.start()
    assert nm.NK_PREFS.generalEnable is True


# ---------------------------------------------------------------------------
# nk_open_settings — creates and shows the settings dialog
# ---------------------------------------------------------------------------


def test_nk_open_settings_creates_window(menu_state_clean):
    nm.NK_SETTINGS_WINDOW = None
    nm.nk_open_settings()
    assert isinstance(nm.NK_SETTINGS_WINDOW, nm.NukeSettingsWindow)
    assert "Nuke" in nm.NK_SETTINGS_WINDOW.windowTitle()


def test_nk_open_settings_visible_window_is_reused(menu_state_clean):
    """If a window already exists AND is visible, the function should NOT
    recreate it — just raise/activate. Pins the no-flicker contract."""
    nm.NK_SETTINGS_WINDOW = None
    nm.nk_open_settings()
    first = nm.NK_SETTINGS_WINDOW
    assert first.isVisible()
    nm.nk_open_settings()
    assert nm.NK_SETTINGS_WINDOW is first


def test_nk_open_settings_creates_new_after_hide(menu_state_clean):
    """If the window exists but isn't visible, a new one is constructed."""
    nm.NK_SETTINGS_WINDOW = None
    nm.nk_open_settings()
    first = nm.NK_SETTINGS_WINDOW
    first.hide()
    nm.nk_open_settings()
    assert nm.NK_SETTINGS_WINDOW is not None
    # First was hidden; second is a fresh visible window.
    assert nm.NK_SETTINGS_WINDOW is not first or first.isVisible()


# ---------------------------------------------------------------------------
# Field-to-widget construction
# ---------------------------------------------------------------------------


def test_nuke_settings_window_builds_on_the_shared_qt_menu(dialog):
    """NukeSettingsWindow is a QtSettingsGUIMenu bound to NK_PREFS, so every
    dialog behavior tested below comes from the shared base class."""
    assert issubclass(nm.NukeSettingsWindow, QtSettingsGUIMenu)
    assert dialog._prefs is nm.NK_PREFS


def test_dialog_object_name_uses_nuke_app_name(dialog):
    assert dialog.objectName() == "NukePresenceSettingsDialog"


def test_dialog_creates_widget_for_every_metadata_field(dialog):
    for f in fields(dialog._prefs):
        if f.metadata.get("group") is None:
            continue
        assert f.name in dialog._gui_widgets, f"missing widget for {f.name}"


def test_dialog_groups_match_nuke_settings(dialog):
    """NKSettings extends SharedSettings + JSONSharedSettings without adding
    new groups — Nuke-specific extras (displayRenderStats, displayFrames,
    disableNodeQueries, disableUpscaledNodes) all attach to existing groups."""
    assert set(dialog._groups.keys()) == {
        "General", "Icons", "Details", "State", "Buttons",
    }


def test_dialog_widget_types_match_nuke_field_types(dialog):
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


def test_dialog_includes_nuke_specific_fields(dialog):
    """The Nuke plugin adds three render fields on top of SharedSettings; each
    should get a checkbox. (The earlier disableUpscaledNodes Icons-group field
    was dropped when the HD and upscaled icon lists were merged into a single
    NK_ICONS catalog, and disableNodeQueries went with the non-commercial API
    rework.)"""
    details_fields = {f.name for f in dialog._groups["Details"]}
    general_fields = {f.name for f in dialog._groups["General"]}
    assert "displayRenderStats" in details_fields
    assert "displayFrames" in details_fields
    assert "displayFileName" in general_fields
    for name in ("displayRenderStats", "displayFrames", "displayFileName"):
        assert isinstance(dialog._gui_widgets[name], QtWidgets.QCheckBox)


def test_dialog_combobox_populated_with_nuke_info_choices(dialog):
    """detailsType / stateType comboboxes pull NKSettings.INFO_CHOICES with
    Nuke-specific keys like 'memory_usage' and 'viewer_info'. Spot-checks go by
    key, not label — the labels carry a '(commercial)' suffix on the entries
    that need a full license, and that wording is free to change."""
    cb = dialog._gui_widgets["detailsType"]
    items = [(cb.itemText(i), cb.itemData(i)) for i in range(cb.count())]
    assert items == nm.NKSettings.INFO_CHOICES
    keys = [key for _label, key in items]
    assert "memory_usage" in keys
    assert "viewer_info" in keys


def test_dialog_combobox_initial_value_from_initial_defaults(dialog):
    """_INITIAL_DEFAULTS pins detailsType='comp_name' and stateType='num_nodes'."""
    assert dialog._gui_widgets["detailsType"].currentData() == "comp_name"
    assert dialog._gui_widgets["stateType"].currentData() == "num_nodes"


# ---------------------------------------------------------------------------
# Controller-driven sensitivity
# ---------------------------------------------------------------------------


def test_controller_dict_includes_nuke_masters_and_controls(dialog):
    controllers = dialog._controllers
    assert "enableDetails" in controllers
    assert "enableState" in controllers
    assert controllers["enableButton1"] == ["button1Label", "button1Url"]
    assert controllers["enableButton2"] == ["button2Label", "button2Url"]


def test_details_master_controls_nuke_extra_fields(dialog):
    """The Details group_master should reach the Nuke-specific extras too —
    displayRenderStats and displayFrames live in Details, so disabling the
    master should gray them out."""
    controlled = dialog._controllers["enableDetails"]
    assert "displayRenderStats" in controlled
    assert "displayFrames" in controlled


def test_button1_disabled_widgets_grayed_by_default(dialog):
    assert dialog._gui_widgets["button1Label"].isEnabled() is False
    assert dialog._gui_widgets["button1Url"].isEnabled() is False


def test_button1_toggle_re_enables_controlled_widgets(dialog):
    dialog._gui_widgets["enableButton1"].setChecked(True)
    assert dialog._gui_widgets["button1Label"].isEnabled() is True
    assert dialog._gui_widgets["button1Url"].isEnabled() is True


def test_details_master_disable_grays_nuke_extras(dialog):
    """Turning enableDetails off must also gray out the Nuke-specific
    Details fields, not just the SharedSettings ones."""
    dialog._gui_widgets["enableDetails"].setChecked(False)
    for name in (
        "detailsType", "customDetails", "detailsCycle",
        "displayRenderStats", "displayFrames",
    ):
        assert dialog._gui_widgets[name].isEnabled() is False, (
            f"{name} should be disabled when enableDetails is off"
        )


# ---------------------------------------------------------------------------
# Reset-to-defaults
# ---------------------------------------------------------------------------


def test_reset_restores_initial_defaults_combobox(dialog, prefs_snapshot, monkeypatch):
    dialog._gui_widgets["stateType"].setCurrentIndex(
        dialog._gui_widgets["stateType"].findData("memory_usage")
    )
    assert prefs_snapshot.stateType == "memory_usage"
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.stateType == "num_nodes"
    assert dialog._gui_widgets["stateType"].currentData() == "num_nodes"


def test_reset_restores_nuke_specific_field(dialog, prefs_snapshot, monkeypatch):
    """displayFrames is a Nuke-only field with a True default; flip it off,
    reset, expect True back."""
    dialog._gui_widgets["displayFrames"].setChecked(False)
    assert prefs_snapshot.displayFrames is False
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.displayFrames is True
    assert dialog._gui_widgets["displayFrames"].isChecked() is True


def test_reset_no_op_when_user_cancels(dialog, prefs_snapshot, monkeypatch):
    dialog._gui_widgets["generalUpdate"].setValue(40)
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.No),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.generalUpdate == 40
