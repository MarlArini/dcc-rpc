"""
Headless-Qt integration tests for the Substance Designer settings dialog and
the Discord menu install/uninstall flow.

Designer's plumbing differs from Painter in two ways:
  - The main window comes from `SD_PLUGIN.uimgr.getMainWindow()`, not a module
    function. We monkeypatch that method on the live uimgr.
  - install/uninstall short-circuit on a None uimgr or None main_window, so
    there are explicit tests for those branches too.

What we cover:
  - install_settings_menu: 'Discord' menu added with its single Settings
    action; SD_PLUGIN.menubar_item set
  - install short-circuits cleanly when getMainWindow() returns None
  - uninstall removes the menu; no-op when never installed
  - open / close settings menu lifecycle, including that a second open reuses
    the existing dialog
  - open short-circuits when uimgr is None or main window is None
  - field-to-widget construction over the actual Designer SDSettings (which
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
    SD_PLUGIN, SDSettings,
    sd_install_settings_menu, sd_uninstall_settings_menu,
    sd_open_settings_menu, sd_close_settings_menu,
)
import designerpresence as dp


# Some tests in this file call sd_open_settings_menu which calls QDialog.show()
# — that briefly flashes a window on screen. Mark the whole file `gui` so the
# default `pytest` run (-m 'not gui') skips it. Run with `pytest -m gui` to
# include.
pytestmark = pytest.mark.gui


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def real_main_window(monkeypatch):
    """Swap SD_PLUGIN.uimgr.getMainWindow with one that returns a fresh real
    QMainWindow. The fake returns a _MainWindow, which can't parent real Qt
    widgets and doesn't share QMenuBar state between calls."""
    mw = QtWidgets.QMainWindow()
    monkeypatch.setattr(SD_PLUGIN.uimgr, "getMainWindow", lambda: mw)
    yield mw
    mw.deleteLater()


@pytest.fixture
def menu_state_clean():
    """Snapshot/restore SD_PLUGIN.menubar_item, settings_window and
    prefs.generalEnable. Any dialog a test opened is closed on the way out, so
    a `pytest -m gui` run doesn't leave windows on screen."""
    snap = (
        SD_PLUGIN.menubar_item,
        SD_PLUGIN.settings_window,
        SD_PLUGIN.prefs.generalEnable
    )
    yield
    opened = SD_PLUGIN.settings_window
    if opened is not None and opened is not snap[1]:
        try:
            opened.close()
            opened.deleteLater()
        except RuntimeError:
            pass
    (SD_PLUGIN.menubar_item,
     SD_PLUGIN.settings_window,
     SD_PLUGIN.prefs.generalEnable) = snap


@pytest.fixture
def prefs_snapshot():
    """Snapshot every public field on SD_PLUGIN.prefs so reset tests don't
    permanently alter shared state."""
    p = SD_PLUGIN.prefs
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
    sd_install_settings_menu()
    action_texts = [a.text() for a in real_main_window.menuBar().actions()]
    assert "Discord" in action_texts
    assert SD_PLUGIN.menubar_item is not None
    assert SD_PLUGIN.menubar_item.title() == "Discord"


def test_install_settings_menu_adds_settings_action(real_main_window, menu_state_clean):
    sd_install_settings_menu()
    assert SD_PLUGIN.menubar_item is not None
    action_texts = [a.text() for a in SD_PLUGIN.menubar_item.actions()]
    assert action_texts == ["Settings"]


def test_install_settings_menu_tags_menu_action_objectname(
    real_main_window, menu_state_clean
):
    """_sd_find_discord_action keys off the menuAction's objectName, not the
    QMenu's — if install stopped setting it, reloads would stack duplicates."""
    sd_install_settings_menu()
    menu_bar = real_main_window.menuBar()
    assert dp._sd_find_discord_action(menu_bar) is not None
    assert SD_PLUGIN.menubar_item.menuAction().objectName() == dp._MENU_OBJNAME


def test_install_short_circuits_when_main_window_none(monkeypatch, menu_state_clean):
    """When getMainWindow returns None the function logs and returns early —
    no menubar mutation."""
    monkeypatch.setattr(SD_PLUGIN.uimgr, "getMainWindow", lambda: None)
    SD_PLUGIN.menubar_item = None
    sd_install_settings_menu()
    assert SD_PLUGIN.menubar_item is None

def test_install_short_circuits_when_uimgr_none(monkeypatch, menu_state_clean):
    monkeypatch.setattr(SD_PLUGIN, "uimgr", None)
    SD_PLUGIN.menubar_item = None
    sd_install_settings_menu()
    assert SD_PLUGIN.menubar_item is None

def test_uninstall_settings_menu_removes_discord_menu(
    real_main_window, menu_state_clean
):
    sd_install_settings_menu()
    sd_uninstall_settings_menu()
    action_texts = [a.text() for a in real_main_window.menuBar().actions()]
    assert "Discord" not in action_texts


def test_uninstall_no_op_when_not_installed(real_main_window, menu_state_clean):
    """When the menu bar has no Discord menu, uninstall finds nothing and
    returns without raising."""
    SD_PLUGIN.menubar_item = None
    sd_uninstall_settings_menu()  # no exception


def test_uninstall_handles_stale_menubar_item_wrapper(
    real_main_window, menu_state_clean
):
    """Regression for the runtime bug: Designer's plugin reload can leave
    SD_PLUGIN.menubar_item with a destroyed C++ side ("Internal C++ object
    already deleted") while the underlying QMenu remains in the menu bar.

    We simulate that by installing the menu, deleting the C++ side of the
    QMenu wrapper via shiboken6, and forcing SD_PLUGIN.menubar_item to a
    fresh-but-stale wrapper that mirrors the post-reload state. The
    uninstall must find and remove the Discord menu anyway, then clear
    menubar_item to None — not raise."""
    import shiboken6

    sd_install_settings_menu()
    assert "Discord" in [a.text() for a in real_main_window.menuBar().actions()]
    # Re-add a second Discord menu to mimic the "menu still in bar, wrapper
    # stale" condition: we delete the C++ side of the cached wrapper and add
    # a new Discord menu directly to the menu bar so the visible state
    # matches what the user reported. It gets tagged the way
    # sd_install_settings_menu tags its own, since a menu left behind by a
    # previous install carries that objectName — that tag is what
    # _sd_find_discord_action matches on.
    stale_menu = SD_PLUGIN.menubar_item
    fresh_menu = real_main_window.menuBar().addMenu("Discord")
    fresh_menu.menuAction().setObjectName(dp._MENU_OBJNAME)
    SD_PLUGIN.menubar_item = stale_menu
    shiboken6.delete(stale_menu)
    # Sanity: accessing the stale wrapper now raises (confirms our setup).
    with pytest.raises(RuntimeError):
        stale_menu.menuAction()
    sd_uninstall_settings_menu()
    # Both Discord menus should be gone — the walk-by-title removes any
    # Discord submenu it finds. menubar_item is reset for future installs.
    assert "Discord" not in [a.text() for a in real_main_window.menuBar().actions()]
    assert SD_PLUGIN.menubar_item is None
    # Keep fresh_menu alive through the assertion above so the menu bar
    # still has a real reference until removal.
    del fresh_menu


def test_install_strips_preexisting_discord_menu(real_main_window, menu_state_clean):
    """If a previous failed uninstall left a Discord menu in the bar, a
    subsequent install must not stack a second one on top — it should
    remove the stale entry first. The leftover carries the install
    objectName because that is how a real leftover would look."""
    # Manually inject a "pre-existing" Discord menu, then run install.
    leftover = real_main_window.menuBar().addMenu("Discord")
    leftover.menuAction().setObjectName(dp._MENU_OBJNAME)
    sd_install_settings_menu()
    discord_actions = [
        a for a in real_main_window.menuBar().actions() if a.text() == "Discord"
    ]
    assert len(discord_actions) == 1


# ---------------------------------------------------------------------------
# open_settings_menu / close_settings_menu
# ---------------------------------------------------------------------------


def test_open_settings_menu_creates_dialog(real_main_window, menu_state_clean):
    sd_open_settings_menu()
    assert isinstance(SD_PLUGIN.settings_window, QtSettingsGUIMenu)
    assert "Designer" in SD_PLUGIN.settings_window.windowTitle()


def test_open_settings_menu_reuses_existing_dialog(real_main_window, menu_state_clean):
    """RPCBasePlugin.show_qt_window keeps one dialog per plugin: the second
    open reuses the same instance, refreshes it from prefs and re-raises it
    rather than building a replacement. (Maya's mp_show_settings_dialog is the
    one that closes-and-recreates; Designer goes through the shared base.)"""
    sd_open_settings_menu()
    first = SD_PLUGIN.settings_window
    assert isinstance(first, QtSettingsGUIMenu)
    sd_open_settings_menu()
    assert SD_PLUGIN.settings_window is first
    assert first.isVisible() is True


def test_open_settings_menu_reloads_widgets_from_prefs(
    real_main_window, menu_state_clean, prefs_snapshot
):
    """Reopening re-syncs the widgets, so a pref changed behind the dialog's
    back shows up on reopen."""
    sd_open_settings_menu()
    window = SD_PLUGIN.settings_window
    object.__setattr__(prefs_snapshot, "generalUpdate", 42)
    sd_open_settings_menu()
    assert window._gui_widgets["generalUpdate"].value() == 42


def test_open_short_circuits_when_uimgr_none(monkeypatch, menu_state_clean):
    """open should bail before constructing the dialog if uimgr is None."""
    monkeypatch.setattr(SD_PLUGIN, "uimgr", None)
    SD_PLUGIN.settings_window = None
    sd_open_settings_menu()
    assert SD_PLUGIN.settings_window is None


def test_open_short_circuits_when_main_window_none(monkeypatch, menu_state_clean):
    monkeypatch.setattr(SD_PLUGIN.uimgr, "getMainWindow", lambda: None)
    SD_PLUGIN.settings_window = None
    sd_open_settings_menu()
    assert SD_PLUGIN.settings_window is None


def test_close_settings_menu_handles_none(menu_state_clean):
    SD_PLUGIN.settings_window = None
    sd_close_settings_menu()  # no exception


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
    """Designer's SDSettings doesn't mix in ColoredIconSettings, but the base
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
    """detailsType / stateType comboboxes pull SDSettings.INFO_CHOICES with
    Designer-specific keys like 'material_model' and 'resource_count'."""
    cb = dialog._gui_widgets["detailsType"]
    items = [(cb.itemText(i), cb.itemData(i)) for i in range(cb.count())]
    assert items == SDSettings.INFO_CHOICES
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
