"""
Headless-Qt integration tests for the Krita settings dialog and the
KPExtension install/uninstall flow.

Krita's "install" path is different from the Substance plugins — Krita drives
the extension via its own hooks:
  - `KPExtension.setup()` wires applicationClosing -> plugin.close and turns
    the notifier active. Effectively the install step.
  - `KPExtension.createActions(window)` registers a "tools/scripts" action
    that opens the settings dialog. The user-visible menu entry.
  - There is no explicit uninstall; close is reached via the notifier.

`window.qwindow()` is documented to return a QWidget or None; the fake returns
None, which means the QtSettingsGUIMenu gets `parent=None`. That's a valid
Qt configuration for a top-level dialog, so tests don't need to monkeypatch
a real QMainWindow the way Painter/Designer do.

What we cover:
  - setup wires applicationClosing -> close and calls notifier.setActive(True)
  - setup short-circuits cleanly when instance or notifier is None
  - createActions registers a "krpresence_open_settings" action and connects
    its triggered signal to open_settings_menu; that the connected callback
    actually opens a dialog
  - createActions(None) is a no-op
  - open_settings_menu creates and replaces dialogs; no-ops when instance or
    activeWindow is None
  - close_settings_menu tears down a live dialog without raising
  - field-to-widget construction over the actual KPSettings (which mixes
    SharedSettings + ColoredIconSettings, no JSONSharedSettings)
  - controller-driven sensitivity for group_master and controls
  - reset-to-defaults restores fields including the _INITIAL_DEFAULTS overrides
"""
from __future__ import annotations
from dataclasses import fields

import pytest
from PySide6 import QtWidgets

from common import QtSettingsGUIMenu
from krita_presence import KPExtension, KPSettings


# Some tests in this file call KPExtension.open_settings_menu which calls
# QDialog.show() — that briefly flashes a window on screen. Mark the whole
# file `gui` so the default `pytest` run (-m 'not gui') skips it. Run with
# `pytest -m gui` to include.
pytestmark = pytest.mark.gui


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def extension(kr):
    """Build a fresh KPExtension parented to the fake Krita singleton, so each
    test gets its own KPPlugin (and therefore its own prefs / settings_window).
    """
    ext = KPExtension(kr.Krita.instance())
    yield ext
    # Tear down any dialog the test may have left open.
    if ext._plugin.settings_window is not None:
        try:
            ext._plugin.settings_window.deleteLater()
        except Exception:
            pass
        ext._plugin.settings_window = None


@pytest.fixture
def prefs_snapshot(extension):
    """Snapshot every public field on the extension's prefs so reset tests
    can verify defaults without permanently mutating shared module state."""
    p = extension._plugin.prefs
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
        app_name="Krita",
    )
    dlg._refresh_calls = refresh_calls  # type: ignore[attr-defined]
    yield dlg
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# setup() — Krita's install equivalent
# ---------------------------------------------------------------------------


def test_setup_connects_application_closing_to_close(kr, extension):
    """setup() should wire notifier.applicationClosing.connect(plugin.close)."""
    notifier = kr.Krita.instance().notifier()
    initial = len(notifier.applicationClosing._connections)
    extension.setup()
    assert len(notifier.applicationClosing._connections) == initial + 1


def test_setup_activates_notifier(kr, extension):
    notifier = kr.Krita.instance().notifier()
    notifier._active = False
    extension.setup()
    assert notifier._active is True


def test_setup_no_op_when_instance_none(kr, extension):
    """When Krita.instance() returns None setup should bail before touching
    the notifier."""
    kr.set_state(instance_is_none=True)
    extension.setup()  # no exception, no crash


def test_setup_no_op_when_notifier_none(kr, extension, monkeypatch):
    """If the live instance returns None for notifier(), setup must skip the
    connect/setActive calls instead of attribute-erroring."""
    monkeypatch.setattr(kr.Krita.instance(), "notifier", lambda: None)
    extension.setup()  # no exception


# ---------------------------------------------------------------------------
# createActions(window) — registers the menu entry
# ---------------------------------------------------------------------------


def test_create_actions_none_window_is_no_op(extension):
    """`window=None` is the documented call shape when Krita can't supply a
    window context; createActions must short-circuit."""
    extension.createActions(None)  # no exception


def test_create_actions_registers_action_with_expected_name(kr, extension):
    """The action name is the lookup key Krita's keyboard-shortcut system
    uses; pinning it guards against accidental renames."""
    recorded: list[tuple[str, str, str]] = []
    window = kr.make_window()

    def fake_create_action(name, label, location):
        recorded.append((name, label, location))
        # Return a real Qt action so triggered.connect later in the function
        # gets a real signal/slot.
        from PySide6.QtGui import QAction
        return QAction()

    window.createAction = fake_create_action  # type: ignore[method-assign]
    extension.createActions(window)
    assert recorded == [(
        "krpresence_open_settings",
        "KritaPresence Settings",
        "tools/scripts",
    )]


def test_create_actions_connects_triggered_to_open_settings_menu(kr, extension):
    """Emitting the action's triggered signal should run the connected callback
    (open_settings_menu), which creates the dialog."""
    from PySide6.QtGui import QAction
    window = kr.make_window()
    captured: list[QAction] = []

    def fake_create_action(name, label, location):
        action = QAction()
        captured.append(action)
        return action

    window.createAction = fake_create_action  # type: ignore[method-assign]
    # Krita's active window is needed inside open_settings_menu.
    kr.set_state(active_window=window)
    extension.createActions(window)
    assert len(captured) == 1
    assert extension._plugin.settings_window is None
    captured[0].triggered.emit()
    assert isinstance(extension._plugin.settings_window, QtSettingsGUIMenu)


def test_create_actions_no_op_when_window_creates_no_action(kr, extension):
    """`window.createAction` is allowed to return None (Krita docs note that
    happens when an action with the same name is already registered). The
    plugin must not try to connect to a None action."""
    window = kr.make_window()
    window.createAction = lambda *a, **kw: None  # type: ignore[method-assign]
    extension.createActions(window)  # no exception


# ---------------------------------------------------------------------------
# open_settings_menu / close_settings_menu
# ---------------------------------------------------------------------------


def test_open_settings_menu_creates_dialog(kr, extension):
    kr.set_state(active_window=kr.make_window())
    extension.open_settings_menu()
    assert isinstance(extension._plugin.settings_window, QtSettingsGUIMenu)
    assert "Krita" in extension._plugin.settings_window.windowTitle()


def test_open_settings_menu_reuses_existing_dialog(kr, extension):
    """RPCBasePlugin.show_qt_window keeps one dialog per plugin: the second
    open reuses the same instance, refreshes it from prefs and re-raises it
    rather than building a replacement. (Maya's mp_show_settings_dialog is the
    one that closes-and-recreates; Krita goes through the shared base.)"""
    kr.set_state(active_window=kr.make_window())
    extension.open_settings_menu()
    first = extension._plugin.settings_window
    assert isinstance(first, QtSettingsGUIMenu)
    extension.open_settings_menu()
    assert extension._plugin.settings_window is first


def test_open_short_circuits_when_instance_none(kr, extension):
    kr.set_state(instance_is_none=True)
    extension._plugin.settings_window = None
    extension.open_settings_menu()
    assert extension._plugin.settings_window is None


def test_open_short_circuits_when_no_active_window(kr, extension):
    kr.set_state(active_window=None)
    extension._plugin.settings_window = None
    extension.open_settings_menu()
    assert extension._plugin.settings_window is None


def test_close_settings_menu_handles_none(extension):
    extension._plugin.settings_window = None
    extension.close_settings_menu()  # no exception


def test_close_settings_menu_tears_down_open_dialog(kr, extension):
    kr.set_state(active_window=kr.make_window())
    extension.open_settings_menu()
    assert extension._plugin.settings_window is not None
    extension.close_settings_menu()  # no exception; dialog closed Qt-side


# ---------------------------------------------------------------------------
# Field-to-widget construction
# ---------------------------------------------------------------------------


def test_dialog_object_name_uses_krita_app_name(dialog):
    assert dialog.objectName() == "KritaPresenceSettingsDialog"


def test_dialog_creates_widget_for_every_metadata_field(dialog):
    for f in fields(dialog._prefs):
        if f.metadata.get("group") is None:
            continue
        assert f.name in dialog._gui_widgets, f"missing widget for {f.name}"


def test_dialog_groups_match_krita_settings(dialog):
    assert set(dialog._groups.keys()) == {
        "General", "Icons", "Details", "State", "Buttons",
    }


def test_dialog_widget_types_match_krita_field_types(dialog):
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


def test_dialog_combobox_populated_with_krita_info_choices(dialog):
    """detailsType / stateType comboboxes pull KPSettings.INFO_CHOICES with
    Krita-specific keys like 'brush_preset' and 'document_time'."""
    cb = dialog._gui_widgets["detailsType"]
    items = [(cb.itemText(i), cb.itemData(i)) for i in range(cb.count())]
    assert items == KPSettings.INFO_CHOICES
    assert ("Brush preset", "brush_preset") in items
    assert ("Total time on document", "document_time") in items


def test_dialog_combobox_initial_value_from_initial_defaults(dialog):
    """_INITIAL_DEFAULTS pins detailsType='doc_name' and stateType='layer_info'."""
    assert dialog._gui_widgets["detailsType"].currentData() == "doc_name"
    assert dialog._gui_widgets["stateType"].currentData() == "layer_info"


def test_dialog_includes_colored_icon_fields(dialog):
    """ColoredIconSettings adds enableColoredIcons + useEvocativeNames to the
    Icons group."""
    icons_field_names = [f.name for f in dialog._groups["Icons"]]
    assert "enableColoredIcons" in icons_field_names
    assert "useEvocativeNames" in icons_field_names


# ---------------------------------------------------------------------------
# Controller-driven sensitivity
# ---------------------------------------------------------------------------


def test_controller_dict_includes_krita_masters_and_controls(dialog):
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
    assert dialog._gui_widgets["button1Label"].isEnabled() is False
    assert dialog._gui_widgets["button1Url"].isEnabled() is False


def test_button1_toggle_re_enables_controlled_widgets(dialog):
    dialog._gui_widgets["enableButton1"].setChecked(True)
    assert dialog._gui_widgets["button1Label"].isEnabled() is True
    assert dialog._gui_widgets["button1Url"].isEnabled() is True


def test_details_master_disable_grays_all_details_widgets(dialog):
    dialog._gui_widgets["enableDetails"].setChecked(False)
    for name in ("detailsType", "customDetails", "detailsCycle"):
        assert dialog._gui_widgets[name].isEnabled() is False


# ---------------------------------------------------------------------------
# Reset-to-defaults
# ---------------------------------------------------------------------------


def test_reset_restores_initial_defaults_combobox(dialog, prefs_snapshot, monkeypatch):
    dialog._gui_widgets["detailsType"].setCurrentIndex(
        dialog._gui_widgets["detailsType"].findData("brush_preset")
    )
    assert prefs_snapshot.detailsType == "brush_preset"
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.detailsType == "doc_name"
    assert dialog._gui_widgets["detailsType"].currentData() == "doc_name"


def test_reset_restores_base_defaults(dialog, prefs_snapshot, monkeypatch):
    """generalUpdate has no _INITIAL_DEFAULTS override in KPSettings, so reset
    lands on the SharedSettings base default (15) — not the 12s floor from the
    field's `min` metadata."""
    dialog._gui_widgets["generalUpdate"].setValue(50)
    assert prefs_snapshot.generalUpdate == 50
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.generalUpdate == 15
    assert dialog._gui_widgets["generalUpdate"].value() == 15


def test_reset_no_op_when_user_cancels(dialog, prefs_snapshot, monkeypatch):
    dialog._gui_widgets["generalUpdate"].setValue(50)
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.No),
    )
    dialog._on_reset_clicked()
    assert prefs_snapshot.generalUpdate == 50
