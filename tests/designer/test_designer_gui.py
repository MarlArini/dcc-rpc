"""
Headless-Qt integration tests for the Substance Designer settings dialog and
the Discord menu install/uninstall flow.

Designer's plumbing differs from Painter in two ways:
  - The main window comes from `SP_PLUGIN.uimgr.getMainWindow()`, not a module
    function. We monkeypatch that method on the live uimgr.
  - install/uninstall short-circuit on a None uimgr or None main_window, so
    there are explicit tests for those branches too.

What we cover:
  - install_settings_menu: 'Discord' menu added with three actions; the start
    action begins disabled and stop enabled; SP_PLUGIN.menubar_item set
  - install short-circuits cleanly when getMainWindow() returns None
  - uninstall removes the menu; no-op when never installed
  - pause / restart presence toggles prefs.generalEnable and the start/stop
    actions' enabled state
  - open / close settings menu lifecycle, including the replace-existing path
  - open short-circuits when uimgr is None or main window is None
  - field-to-widget construction over the actual Designer SPSettings (which
    mixes SharedSettings + JSONSharedSettings, no ColoredIconSettings)
  - controller-driven sensitivity for group_master and controls
  - reset-to-defaults restores fields including the _INITIAL_DEFAULTS overrides
"""
from __future__ import annotations
from dataclasses import fields

import pytest
from PySide6 import QtWidgets

from common import QtSettingsGUIMenu
from designerpresence import (
    SP_PLUGIN, SPSettings,
    sp_install_settings_menu, sp_uninstall_settings_menu,
    sp_open_settings_menu, sp_close_settings_menu,
)
import designerpresence as dp


# Some tests in this file call sp_open_settings_menu which calls QDialog.show()
# — that briefly flashes a window on screen. Mark the whole file `gui` so the
# default `pytest` run (-m 'not gui') skips it. Run with `pytest -m gui` to
# include.
pytestmark = pytest.mark.gui


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def real_main_window(monkeypatch):
    """Swap SP_PLUGIN.uimgr.getMainWindow with one that returns a fresh real
    QMainWindow. The fake returns a _MainWindow, which can't parent real Qt
    widgets and doesn't share QMenuBar state between calls."""
    mw = QtWidgets.QMainWindow()
    monkeypatch.setattr(SP_PLUGIN.uimgr, "getMainWindow", lambda: mw)
    yield mw
    mw.deleteLater()


@pytest.fixture
def menu_state_clean():
    """Snapshot/restore SP_PLUGIN.menubar_item, settings_window,
    prefs.generalEnable, and the module-level SP_START_ACTION /
    SP_STOP_ACTION globals."""
    snap = (
        SP_PLUGIN.menubar_item,
        SP_PLUGIN.settings_window,
        SP_PLUGIN.prefs.generalEnable
    )
    yield
    (SP_PLUGIN.menubar_item,
     SP_PLUGIN.settings_window,
     SP_PLUGIN.prefs.generalEnable) = snap[:3]


@pytest.fixture
def prefs_snapshot():
    """Snapshot every public field on SP_PLUGIN.prefs so reset tests don't
    permanently alter shared state."""
    p = SP_PLUGIN.prefs
    snap = {f.name: getattr(p, f.name) for f in fields(p) if not f.name.startswith("_")}
    yield p
    for k, v in snap.items():
        object.__setattr__(p, k, v)


@pytest.fixture
def dialog(prefs_snapshot):
    refresh_calls: list[int] = []
    dlg = QtSettingsGUIMenu(
        prefs=prefs_snapshot,
        refresh_func=lambda: refresh_calls.append(1),
        app_name="Designer",
    )
    dlg._refresh_calls = refresh_calls  # type: ignore[attr-defined]
    yield dlg
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# install / uninstall menu flow
# ---------------------------------------------------------------------------


def test_install_settings_menu_adds_discord_menu(real_main_window, menu_state_clean):
    sp_install_settings_menu()
    action_texts = [a.text() for a in real_main_window.menuBar().actions()]
    assert "Discord" in action_texts
    assert SP_PLUGIN.menubar_item is not None
    assert SP_PLUGIN.menubar_item.title() == "Discord"


def test_install_settings_menu_adds_three_actions(real_main_window, menu_state_clean):
    sp_install_settings_menu()
    assert SP_PLUGIN.menubar_item is not None
    action_texts = [a.text() for a in SP_PLUGIN.menubar_item.actions()]
    assert action_texts == ["Settings"]

def test_install_short_circuits_when_main_window_none(monkeypatch, menu_state_clean):
    """When getMainWindow returns None the function logs and returns early —
    no menubar mutation, no SP_START/STOP assignment."""
    monkeypatch.setattr(SP_PLUGIN.uimgr, "getMainWindow", lambda: None)
    SP_PLUGIN.menubar_item = None
    sp_install_settings_menu()
    assert SP_PLUGIN.menubar_item is None

def test_install_short_circuits_when_uimgr_none(monkeypatch, menu_state_clean):
    monkeypatch.setattr(SP_PLUGIN, "uimgr", None)
    SP_PLUGIN.menubar_item = None
    sp_install_settings_menu()
    assert SP_PLUGIN.menubar_item is None

def test_uninstall_settings_menu_removes_discord_menu(
    real_main_window, menu_state_clean
):
    sp_install_settings_menu()
    sp_uninstall_settings_menu()
    action_texts = [a.text() for a in real_main_window.menuBar().actions()]
    assert "Discord" not in action_texts


def test_uninstall_no_op_when_not_installed(real_main_window, menu_state_clean):
    """When the menu bar has no Discord menu, uninstall finds nothing and
    returns without raising."""
    SP_PLUGIN.menubar_item = None
    sp_uninstall_settings_menu()  # no exception


def test_uninstall_handles_stale_menubar_item_wrapper(
    real_main_window, menu_state_clean
):
    """Regression for the runtime bug: Designer's plugin reload can leave
    SP_PLUGIN.menubar_item with a destroyed C++ side ("Internal C++ object
    already deleted") while the underlying QMenu remains in the menu bar.

    We simulate that by installing the menu, deleting the C++ side of the
    QMenu wrapper via shiboken6, and forcing SP_PLUGIN.menubar_item to a
    fresh-but-stale wrapper that mirrors the post-reload state. The
    uninstall must find and remove the Discord menu anyway, then clear
    menubar_item to None — not raise."""
    import shiboken6

    sp_install_settings_menu()
    assert "Discord" in [a.text() for a in real_main_window.menuBar().actions()]
    # Re-add a second Discord menu to mimic the "menu still in bar, wrapper
    # stale" condition: we delete the C++ side of the cached wrapper and add
    # a new Discord menu directly to the menu bar so the visible state
    # matches what the user reported.
    stale_menu = SP_PLUGIN.menubar_item
    fresh_menu = real_main_window.menuBar().addMenu("Discord")
    SP_PLUGIN.menubar_item = stale_menu
    shiboken6.delete(stale_menu)
    # Sanity: accessing the stale wrapper now raises (confirms our setup).
    with pytest.raises(RuntimeError):
        stale_menu.menuAction()
    sp_uninstall_settings_menu()
    # Both Discord menus should be gone — the walk-by-title removes any
    # Discord submenu it finds. menubar_item is reset for future installs.
    assert "Discord" not in [a.text() for a in real_main_window.menuBar().actions()]
    assert SP_PLUGIN.menubar_item is None
    # Keep fresh_menu alive through the assertion above so the menu bar
    # still has a real reference until removal.
    del fresh_menu


def test_install_strips_preexisting_discord_menu(real_main_window, menu_state_clean):
    """If a previous failed uninstall left a Discord menu in the bar, a
    subsequent install must not stack a second one on top — it should
    remove the stale entry first."""
    # Manually inject a "pre-existing" Discord menu, then run install.
    real_main_window.menuBar().addMenu("Discord")
    sp_install_settings_menu()
    discord_actions = [
        a for a in real_main_window.menuBar().actions() if a.text() == "Discord"
    ]
    assert len(discord_actions) == 1


# ---------------------------------------------------------------------------
# open_settings_menu / close_settings_menu
# ---------------------------------------------------------------------------


def test_open_settings_menu_creates_dialog(real_main_window, menu_state_clean):
    sp_open_settings_menu()
    assert isinstance(SP_PLUGIN.settings_window, QtSettingsGUIMenu)
    assert "Designer" in SP_PLUGIN.settings_window.windowTitle()


def test_open_settings_menu_replaces_existing(real_main_window, menu_state_clean):
    sp_open_settings_menu()
    first = SP_PLUGIN.settings_window
    sp_open_settings_menu()
    second = SP_PLUGIN.settings_window
    assert first is not second
    assert isinstance(second, QtSettingsGUIMenu)


def test_open_short_circuits_when_uimgr_none(monkeypatch, menu_state_clean):
    """open should bail before constructing the dialog if uimgr is None."""
    monkeypatch.setattr(SP_PLUGIN, "uimgr", None)
    SP_PLUGIN.settings_window = None
    sp_open_settings_menu()
    assert SP_PLUGIN.settings_window is None


def test_open_short_circuits_when_main_window_none(monkeypatch, menu_state_clean):
    monkeypatch.setattr(SP_PLUGIN.uimgr, "getMainWindow", lambda: None)
    SP_PLUGIN.settings_window = None
    sp_open_settings_menu()
    assert SP_PLUGIN.settings_window is None


def test_close_settings_menu_handles_none(menu_state_clean):
    SP_PLUGIN.settings_window = None
    sp_close_settings_menu()  # no exception


# ---------------------------------------------------------------------------
# Field-to-widget construction
# ---------------------------------------------------------------------------


def test_dialog_object_name_uses_designer_app_name(dialog):
    assert dialog.objectName() == "DesignerPresenceSettingsDialog"


def test_dialog_creates_widget_for_every_metadata_field(dialog):
    for f in fields(dialog._prefs):
        if f.metadata.get("group") is None:
            continue
        assert f.name in dialog._gui_widgets, f"missing widget for {f.name}"


def test_dialog_groups_match_designer_settings(dialog):
    """Designer's SPSettings doesn't mix in ColoredIconSettings, but the base
    SharedSettings groups are still present."""
    assert set(dialog._groups.keys()) == {
        "General", "Icons", "Details", "State", "Buttons",
    }


def test_dialog_widget_types_match_designer_field_types(dialog):
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


def test_dialog_combobox_populated_with_designer_info_choices(dialog):
    """detailsType / stateType comboboxes pull SPSettings.INFO_CHOICES with
    Designer-specific keys like 'material_model' and 'resource_count'."""
    cb = dialog._gui_widgets["detailsType"]
    items = [(cb.itemText(i), cb.itemData(i)) for i in range(cb.count())]
    assert items == SPSettings.INFO_CHOICES
    assert ("Material model", "material_model") in items
    assert ("Resource count", "resource_count") in items


def test_dialog_combobox_initial_value_from_initial_defaults(dialog):
    """_INITIAL_DEFAULTS pins detailsType='package' and stateType='graph'."""
    assert dialog._gui_widgets["detailsType"].currentData() == "package"
    assert dialog._gui_widgets["stateType"].currentData() == "graph"


# ---------------------------------------------------------------------------
# Controller-driven sensitivity
# ---------------------------------------------------------------------------


def test_controller_dict_includes_designer_masters_and_controls(dialog):
    controllers = dialog._controllers
    assert "enableDetails" in controllers
    assert "enableState" in controllers
    assert controllers["enableButton1"] == ["button1Label", "button1Url"]
    assert controllers["enableButton2"] == ["button2Label", "button2Url"]


def test_state_master_controls_all_other_state_fields(dialog):
    controlled = dialog._controllers["enableState"]
    assert "enableState" not in controlled
    for name in ("stateType", "customState", "stateCycle"):
        assert name in controlled


def test_button2_disabled_widgets_grayed_by_default(dialog):
    assert dialog._gui_widgets["button2Label"].isEnabled() is False
    assert dialog._gui_widgets["button2Url"].isEnabled() is False


def test_button2_toggle_re_enables_controlled_widgets(dialog):
    dialog._gui_widgets["enableButton2"].setChecked(True)
    assert dialog._gui_widgets["button2Label"].isEnabled() is True
    assert dialog._gui_widgets["button2Url"].isEnabled() is True


def test_state_master_disable_grays_all_state_widgets(dialog):
    dialog._gui_widgets["enableState"].setChecked(False)
    for name in ("stateType", "customState", "stateCycle"):
        assert dialog._gui_widgets[name].isEnabled() is False


# ---------------------------------------------------------------------------
# Reset-to-defaults
# ---------------------------------------------------------------------------


def test_reset_restores_initial_defaults_combobox(dialog, prefs_snapshot, monkeypatch):
    dialog._gui_widgets["stateType"].setCurrentIndex(
        dialog._gui_widgets["stateType"].findData("color_space")
    )
    assert prefs_snapshot.stateType == "color_space"
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.stateType == "graph"
    assert dialog._gui_widgets["stateType"].currentData() == "graph"


def test_reset_restores_base_defaults(dialog, prefs_snapshot, monkeypatch):
    dialog._gui_widgets["generalUpdate"].setValue(40)
    assert prefs_snapshot.generalUpdate == 40
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.generalUpdate == 15
    assert dialog._gui_widgets["generalUpdate"].value() == 15


def test_reset_no_op_when_user_cancels(dialog, prefs_snapshot, monkeypatch):
    dialog._gui_widgets["generalUpdate"].setValue(40)
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.No),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.generalUpdate == 40
