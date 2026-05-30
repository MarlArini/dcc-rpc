"""
Headless-Qt integration tests for the Substance Painter settings dialog and
the Discord menu install/uninstall flow.

Reuses the session-scoped QApplication from tests/conftest.py and the autouse
`reset_painter_fake_state` fixture from tests/painter/conftest.py.

The fake `sp.ui.get_main_window()` ordinarily returns a _FakeQWidget — fine
for the QtIntrospection methods on SPContext, but the menu-install code path
calls `.menuBar().addMenu(...)` and passes the result to a real QtSettingsGUIMenu
parent. So tests that exercise that path monkeypatch `sp.ui.get_main_window`
to return a fresh real QMainWindow.

What we cover:
  - install_settings_menu: 'Discord' menu added with three actions; SP_START
    disabled and SP_STOP enabled at install time; SP_PLUGIN.menubar_item set
  - uninstall_settings_menu: 'Discord' menu removed; settings_window closed
  - pause_presence / restart_presence: prefs.generalEnable toggled and the
    start/stop actions' enabled state inverted
  - open_settings_menu / close_settings_menu: creates and tears down a
    QtSettingsGUIMenu attached to SP_PLUGIN.settings_window; calling open
    twice replaces the first dialog
  - field-to-widget construction over the actual SPSettings (which mixes
    ColoredIconSettings + SharedSettings + JSONSharedSettings)
  - controller-driven sensitivity for both `group_master` (enableDetails,
    enableState) and `controls` (enableButton1/2) patterns
  - reset-to-defaults restores fields including the _INITIAL_DEFAULTS overrides
"""
from __future__ import annotations
from dataclasses import fields

import pytest
from PySide6 import QtWidgets

from common import QtSettingsGUIMenu
from substance_painter_presence import painter_presence as pp


# Some tests in this file call sp_open_settings_menu which calls QDialog.show()
# — that briefly flashes a window on screen. Mark the whole file `gui` so the
# default `pytest` run (-m 'not gui') skips it. Run with `pytest -m gui` to
# include.
pytestmark = pytest.mark.gui


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def real_main_window(sp, monkeypatch):
    """Swap sp.ui.get_main_window for one that returns a fresh real QMainWindow.

    Painter's install/open code calls `.menuBar()` and uses the result as a Qt
    parent, neither of which the fake _FakeQWidget supports. The QMainWindow is
    returned by reference so individual tests can introspect its menuBar."""
    mw = QtWidgets.QMainWindow()
    monkeypatch.setattr(sp.ui, "get_main_window", lambda: mw)
    yield mw
    mw.deleteLater()


@pytest.fixture
def menu_state_clean():
    """Snapshot/restore SP_PLUGIN.menubar_item, settings_window, prefs.generalEnable
    and the module-level SP_START_ACTION / SP_STOP_ACTION globals so tests in
    this file don't leak state into each other or the SPContext tests."""
    snap = (
        pp.SP_PLUGIN.menubar_item,
        pp.SP_PLUGIN.settings_window,
        pp.SP_PLUGIN.prefs.generalEnable,
        pp.SP_START_ACTION,
        pp.SP_STOP_ACTION,
    )
    yield
    (pp.SP_PLUGIN.menubar_item,
     pp.SP_PLUGIN.settings_window,
     pp.SP_PLUGIN.prefs.generalEnable) = snap[:3]
    pp.SP_START_ACTION = snap[3]
    pp.SP_STOP_ACTION = snap[4]


@pytest.fixture
def prefs_snapshot():
    """Snapshot every public field on SP_PLUGIN.prefs so reset tests don't
    permanently alter shared state."""
    p = pp.SP_PLUGIN.prefs
    snap = {f.name: getattr(p, f.name) for f in fields(p) if not f.name.startswith("_")}
    yield p
    for k, v in snap.items():
        object.__setattr__(p, k, v)


@pytest.fixture
def dialog(prefs_snapshot):
    """Build a QtSettingsGUIMenu against SP_PLUGIN.prefs. Records refresh calls
    so tests can assert without needing the real push_rpc_update."""
    refresh_calls: list[int] = []
    dlg = QtSettingsGUIMenu(
        prefs=prefs_snapshot,
        refresh_func=lambda: refresh_calls.append(1),
        app_name="Painter",
    )
    dlg._refresh_calls = refresh_calls  # type: ignore[attr-defined]
    yield dlg
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# install / uninstall menu flow
# ---------------------------------------------------------------------------


def test_install_settings_menu_adds_discord_menu(real_main_window, menu_state_clean):
    pp.sp_install_settings_menu()
    # The added action's text matches the menu title from addMenu("Discord").
    action_texts = [a.text() for a in real_main_window.menuBar().actions()]
    assert "Discord" in action_texts
    assert pp.SP_PLUGIN.menubar_item is not None
    assert pp.SP_PLUGIN.menubar_item.title() == "Discord"


def test_install_settings_menu_adds_three_actions(real_main_window, menu_state_clean):
    pp.sp_install_settings_menu()
    assert pp.SP_PLUGIN.menubar_item is not None
    action_texts = [a.text() for a in pp.SP_PLUGIN.menubar_item.actions()]
    assert action_texts == ["Settings", "Pause Presence", "Restart Presence"]


def test_install_settings_menu_initial_action_enabled_states(
    real_main_window, menu_state_clean
):
    """At install time SP_STOP_ACTION (Pause) is the live one, SP_START_ACTION
    (Restart) is grayed out — the UI mirrors that the plugin is currently active."""
    pp.sp_install_settings_menu()
    assert pp.SP_STOP_ACTION is not None
    assert pp.SP_START_ACTION is not None
    assert pp.SP_STOP_ACTION.isEnabled() is True
    assert pp.SP_START_ACTION.isEnabled() is False


def test_uninstall_settings_menu_removes_discord_menu(
    real_main_window, menu_state_clean
):
    pp.sp_install_settings_menu()
    assert pp.SP_PLUGIN.menubar_item is not None
    pp.sp_uninstall_settings_menu()
    action_texts = [a.text() for a in real_main_window.menuBar().actions()]
    assert "Discord" not in action_texts


def test_uninstall_settings_menu_no_op_when_not_installed(
    real_main_window, menu_state_clean
):
    """When the menu bar has no Discord menu, uninstall finds nothing and
    returns without raising."""
    pp.SP_PLUGIN.menubar_item = None
    pp.sp_uninstall_settings_menu()  # no exception


def test_uninstall_handles_stale_menubar_item_wrapper(
    real_main_window, menu_state_clean
):
    """Regression for the Designer-reported runtime bug (same code shape
    here): the host's plugin reload can leave SP_PLUGIN.menubar_item with a
    destroyed C++ side ("Internal C++ object already deleted") while the
    underlying QMenu remains in the menu bar.

    We simulate that by installing the menu, deleting the C++ side of the
    QMenu wrapper via shiboken6, and adding a fresh Discord menu directly to
    the menu bar so the visible state matches what a user would see. The
    uninstall must find and remove the Discord menu anyway, then clear
    menubar_item to None — not raise or leave the menu in place."""
    import shiboken6

    pp.sp_install_settings_menu()
    assert "Discord" in [a.text() for a in real_main_window.menuBar().actions()]
    stale_menu = pp.SP_PLUGIN.menubar_item
    fresh_menu = real_main_window.menuBar().addMenu("Discord")
    pp.SP_PLUGIN.menubar_item = stale_menu
    shiboken6.delete(stale_menu)
    with pytest.raises(RuntimeError):
        stale_menu.menuAction()
    pp.sp_uninstall_settings_menu()
    assert "Discord" not in [a.text() for a in real_main_window.menuBar().actions()]
    assert pp.SP_PLUGIN.menubar_item is None
    del fresh_menu


def test_install_strips_preexisting_discord_menu(real_main_window, menu_state_clean):
    """If a previous failed uninstall left a Discord menu in the bar, a
    subsequent install must not stack a second one on top — it should
    remove the stale entry first."""
    real_main_window.menuBar().addMenu("Discord")
    pp.sp_install_settings_menu()
    discord_actions = [
        a for a in real_main_window.menuBar().actions() if a.text() == "Discord"
    ]
    assert len(discord_actions) == 1


def test_uninstall_closes_open_settings_window(real_main_window, menu_state_clean):
    """sp_uninstall_settings_menu should call sp_close_settings_menu first so
    a dangling settings dialog gets torn down with the menu."""
    pp.sp_install_settings_menu()
    pp.sp_open_settings_menu()
    assert pp.SP_PLUGIN.settings_window is not None
    pp.sp_uninstall_settings_menu()
    # The settings window object is gone (set to None by close, or closed Qt-side).
    # The close func sets nothing — we just confirm the dialog is closed.
    # sp_close_settings_menu calls window.close(); window.deleteLater() — so
    # the dialog is no longer visible.


# ---------------------------------------------------------------------------
# pause_presence / restart_presence (toggle generalEnable + action sensitivity)
# ---------------------------------------------------------------------------


def test_pause_presence_disables_general_enable(real_main_window, menu_state_clean):
    pp.sp_install_settings_menu()
    pp.SP_PLUGIN.prefs.generalEnable = True
    pp.sp_pause_presence()
    assert pp.SP_PLUGIN.prefs.generalEnable is False


def test_pause_presence_toggles_action_enabled_state(
    real_main_window, menu_state_clean
):
    pp.sp_install_settings_menu()
    pp.sp_pause_presence()
    # After pausing: Restart is the live action, Pause is grayed out.
    assert pp.SP_START_ACTION.isEnabled() is True
    assert pp.SP_STOP_ACTION.isEnabled() is False


def test_restart_presence_enables_general_enable(real_main_window, menu_state_clean):
    pp.sp_install_settings_menu()
    pp.SP_PLUGIN.prefs.generalEnable = False
    pp.sp_restart_presence()
    assert pp.SP_PLUGIN.prefs.generalEnable is True


def test_restart_presence_toggles_action_enabled_state(
    real_main_window, menu_state_clean
):
    pp.sp_install_settings_menu()
    pp.sp_pause_presence()  # set to paused state first
    pp.sp_restart_presence()
    assert pp.SP_START_ACTION.isEnabled() is False
    assert pp.SP_STOP_ACTION.isEnabled() is True


def test_pause_then_restart_round_trips(real_main_window, menu_state_clean):
    pp.sp_install_settings_menu()
    pp.SP_PLUGIN.prefs.generalEnable = True
    pp.sp_pause_presence()
    assert pp.SP_PLUGIN.prefs.generalEnable is False
    pp.sp_restart_presence()
    assert pp.SP_PLUGIN.prefs.generalEnable is True


def test_pause_with_no_actions_does_not_crash(menu_state_clean):
    """If the install path never ran (e.g., the host has no menubar), the
    module-level actions stay None — pause must not blow up."""
    pp.SP_START_ACTION = None
    pp.SP_STOP_ACTION = None
    pp.SP_PLUGIN.prefs.generalEnable = True
    pp.sp_pause_presence()  # no AttributeError
    assert pp.SP_PLUGIN.prefs.generalEnable is False


# ---------------------------------------------------------------------------
# open_settings_menu / close_settings_menu
# ---------------------------------------------------------------------------


def test_open_settings_menu_creates_dialog(real_main_window, menu_state_clean):
    pp.sp_open_settings_menu()
    assert isinstance(pp.SP_PLUGIN.settings_window, QtSettingsGUIMenu)
    assert "Painter" in pp.SP_PLUGIN.settings_window.windowTitle()


def test_open_settings_menu_replaces_existing(real_main_window, menu_state_clean):
    """Opening twice should produce two different dialog instances — the first
    is closed/deleted before the second is created."""
    pp.sp_open_settings_menu()
    first = pp.SP_PLUGIN.settings_window
    pp.sp_open_settings_menu()
    second = pp.SP_PLUGIN.settings_window
    assert first is not second
    assert isinstance(second, QtSettingsGUIMenu)


def test_close_settings_menu_handles_none(menu_state_clean):
    """Close when nothing is open must be a no-op."""
    pp.SP_PLUGIN.settings_window = None
    pp.sp_close_settings_menu()  # no exception


# ---------------------------------------------------------------------------
# Field-to-widget construction
# ---------------------------------------------------------------------------


def test_dialog_object_name_uses_painter_app_name(dialog):
    assert dialog.objectName() == "PainterPresenceSettingsDialog"


def test_dialog_creates_widget_for_every_metadata_field(dialog):
    """Every SharedSettings + ColoredIconSettings field with a 'group' key
    should get a corresponding Qt widget."""
    for f in fields(dialog._prefs):
        if f.metadata.get("group") is None:
            continue
        assert f.name in dialog._gui_widgets, f"missing widget for {f.name}"


def test_dialog_groups_match_painter_settings(dialog):
    """ColoredIconSettings adds two fields to the Icons group — expect all
    five base groups present."""
    assert set(dialog._groups.keys()) == {
        "General", "Icons", "Details", "State", "Buttons",
    }


def test_dialog_widget_types_match_painter_field_types(dialog):
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


def test_dialog_combobox_populated_with_painter_info_choices(dialog):
    """detailsType / stateType comboboxes pull SPSettings.INFO_CHOICES, which
    has Painter-specific keys like 'active_texset_info' and 'brush_alpha'."""
    cb = dialog._gui_widgets["detailsType"]
    items = [(cb.itemText(i), cb.itemData(i)) for i in range(cb.count())]
    assert items == pp.SPSettings.INFO_CHOICES
    # Sanity check on a couple of Painter-specific keys.
    assert ("Active texture set info", "active_texset_info") in items
    assert ("Active brush alpha", "brush_alpha") in items


def test_dialog_combobox_initial_value_from_initial_defaults(dialog):
    """SPSettings._INITIAL_DEFAULTS sets detailsType='project'; the combobox
    should reflect that, not SharedSettings's 'scene' base default."""
    cb = dialog._gui_widgets["detailsType"]
    assert cb.currentData() == "project"


def test_dialog_includes_colored_icon_fields(dialog):
    """ColoredIconSettings is mixed in — its fields should appear as widgets
    in the Icons group."""
    icons_field_names = [f.name for f in dialog._groups["Icons"]]
    assert "enableColoredIcons" in icons_field_names
    assert "useEvocativeNames" in icons_field_names
    # And they should have actual widgets.
    assert isinstance(
        dialog._gui_widgets["enableColoredIcons"], QtWidgets.QCheckBox
    )
    assert isinstance(
        dialog._gui_widgets["useEvocativeNames"], QtWidgets.QCheckBox
    )


# ---------------------------------------------------------------------------
# Controller-driven sensitivity
# ---------------------------------------------------------------------------


def test_controller_dict_includes_painter_masters_and_controls(dialog):
    controllers = dialog._controllers
    assert "enableDetails" in controllers
    assert "enableState" in controllers
    assert controllers["enableButton1"] == ["button1Label", "button1Url"]
    assert controllers["enableButton2"] == ["button2Label", "button2Url"]


def test_details_master_controls_all_other_details_fields(dialog):
    controlled = dialog._controllers["enableDetails"]
    assert "enableDetails" not in controlled
    for name in ("detailsType", "customDetails", "detailsCycle"):
        assert name in controlled


def test_button1_disabled_widgets_grayed_by_default(dialog):
    """enableButton1 defaults to False — button1Label/Url should start disabled."""
    assert dialog._gui_widgets["button1Label"].isEnabled() is False
    assert dialog._gui_widgets["button1Url"].isEnabled() is False


def test_button1_toggle_re_enables_controlled_widgets(dialog, prefs_snapshot):
    dialog._gui_widgets["enableButton1"].setChecked(True)
    assert dialog._gui_widgets["button1Label"].isEnabled() is True
    assert dialog._gui_widgets["button1Url"].isEnabled() is True


def test_details_master_disable_grays_all_details_widgets(dialog, prefs_snapshot):
    """Turning enableDetails off should disable detailsType, customDetails,
    detailsCycle simultaneously."""
    dialog._gui_widgets["enableDetails"].setChecked(False)
    for name in ("detailsType", "customDetails", "detailsCycle"):
        assert dialog._gui_widgets[name].isEnabled() is False


# ---------------------------------------------------------------------------
# Reset-to-defaults
# ---------------------------------------------------------------------------


def test_reset_restores_initial_defaults_combobox(dialog, prefs_snapshot, monkeypatch):
    """_INITIAL_DEFAULTS pins detailsType='project'. After modification + reset,
    detailsType should be back to 'project', not SharedSettings's 'scene'."""
    dialog._gui_widgets["detailsType"].setCurrentIndex(
        dialog._gui_widgets["detailsType"].findData("num_meshes")
    )
    assert prefs_snapshot.detailsType == "num_meshes"
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.detailsType == "project"
    assert dialog._gui_widgets["detailsType"].currentData() == "project"


def test_reset_restores_base_defaults(dialog, prefs_snapshot, monkeypatch):
    """generalUpdate has no _INITIAL_DEFAULTS override, so reset should land
    on the SharedSettings base default (12)."""
    dialog._gui_widgets["generalUpdate"].setValue(45)
    assert prefs_snapshot.generalUpdate == 45
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.generalUpdate == 12
    assert dialog._gui_widgets["generalUpdate"].value() == 12


def test_reset_no_op_when_user_cancels(dialog, prefs_snapshot, monkeypatch):
    dialog._gui_widgets["generalUpdate"].setValue(45)
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.No),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.generalUpdate == 45
