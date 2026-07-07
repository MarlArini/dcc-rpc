"""
AI-generated (Claude Opus 4.7): tests for common.QtSettingsGUIMenu.

PySide6 supports headless widget construction once a QApplication exists
(provided by the session-scoped fixture in tests/conftest.py). These tests
build a tiny SharedSettings-derived dataclass with one field per widget
type plus the master/controls metadata patterns, instantiate the dialog,
and exercise every state-mutating path.

What we cover:
  - _build_groups: groups fields by metadata['group'], preserving order
  - _build_controller_dict: builds the group_master + controls map
  - _build: instantiates the right Qt widget per field (checkbox, spinbox,
    lineedit, combobox), with default values from prefs
  - _set: mutates prefs through signal handlers + triggers the debounce timer
  - _refresh_enabled_states: grays out controlled widgets per controller's state
  - _load_from_prefs: pushes prefs values back into widgets
  - _on_reset_clicked: calls prefs.reset() when user confirms; no-op on No
  - _widget_kind: explicit metadata vs type inference

We don't cover .show() / event loop / actual user input — those need real
event delivery; the signal-emit code path through `_set` is what matters
for behavior testing."""
from __future__ import annotations
from dataclasses import dataclass, field, fields
from typing import ClassVar, Dict, Any, List, Tuple

import pytest
from PySide6 import QtCore, QtWidgets

from common import QtSettingsGUIMenu, SharedSettings


# ---------------------------------------------------------------------------
# Test fixtures: minimal SharedSettings-derived class
# ---------------------------------------------------------------------------

@dataclass
class _GuiTestSettings(SharedSettings):
    """Stripped-down settings for exercising QtSettingsGUIMenu. Uses the
    SharedSettings base for the standard field set (generalEnable, enableTime,
    button*, etc. — those exercise the combobox and master/controls patterns
    automatically). Adds INFO_CHOICES + a reset() since SharedSettings doesn't
    provide one."""
    _INITIAL_DEFAULTS: ClassVar[Dict[str, Any]] = {"detailsType": "scene"}
    INFO_CHOICES: ClassVar[List[Tuple[str, str]]] = [
        ("Scene", "scene"),
        ("Frame", "frame"),
        ("Active object", "active"),
    ]

    def reset(self):
        """Restore every field to its dataclass default, with
        _INITIAL_DEFAULTS taking precedence."""
        for f in fields(self):
            default = self._INITIAL_DEFAULTS.get(f.name, f.default)
            object.__setattr__(self, f.name, default)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def prefs():
    return _GuiTestSettings()


@pytest.fixture
def dialog(prefs):
    """Build a QtSettingsGUIMenu against a fresh prefs object. Records refresh
    invocations into `dialog._refresh_calls` for assertion."""
    refresh_calls: list[int] = []

    def _refresh():
        refresh_calls.append(1)

    dlg = QtSettingsGUIMenu(prefs=prefs, refresh_func=_refresh, app_name="Test")
    dlg._refresh_calls = refresh_calls  # type: ignore[attr-defined]
    yield dlg
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# Constructor + meta
# ---------------------------------------------------------------------------

def test_dialog_has_expected_object_name_and_title(dialog):
    assert dialog.objectName() == "TestPresenceSettingsDialog"
    assert "Test" in dialog.windowTitle()
    assert "Settings" in dialog.windowTitle()


def test_dialog_resizes_to_minimum_width(dialog):
    assert dialog.minimumWidth() == 400


# ---------------------------------------------------------------------------
# _build_groups
# ---------------------------------------------------------------------------

def test_build_groups_produces_one_entry_per_metadata_group(dialog):
    """Every distinct 'group' value in field metadata becomes a key in
    `_groups`. Fields without a group are skipped (none in SharedSettings,
    but the filter exists)."""
    groups = dialog._groups
    expected_group_names = {"General", "Icons", "Details", "State", "Buttons"}
    assert set(groups.keys()) == expected_group_names


def test_build_groups_preserves_declaration_order_within_group(dialog):
    """Inside a group, fields appear in declaration order."""
    general_field_names = [f.name for f in dialog._groups["General"]]
    # SharedSettings declares General fields in this order.
    assert general_field_names == [
        "generalEnable", "generalUpdate", "enableTime", "resetTimer",
    ]


# ---------------------------------------------------------------------------
# _widget_kind
# ---------------------------------------------------------------------------

def test_widget_kind_explicit_metadata_wins(dialog):
    """A field with metadata['widget']='combobox' returns 'combobox' even
    though its Python type is `str` (which would default to lineedit)."""
    details_type_field = next(
        f for f in fields(dialog._prefs) if f.name == "detailsType"
    )
    assert dialog._widget_kind(details_type_field) == "combobox"


def test_widget_kind_inferred_from_type(dialog):
    """No metadata['widget'] -> infer from the resolved type."""
    bool_field = next(
        f for f in fields(dialog._prefs) if f.name == "generalEnable"
    )
    int_field = next(
        f for f in fields(dialog._prefs) if f.name == "generalUpdate"
    )
    str_field = next(
        f for f in fields(dialog._prefs) if f.name == "customDetails"
    )
    assert dialog._widget_kind(bool_field) == "checkbox"
    assert dialog._widget_kind(int_field) == "spinbox"
    assert dialog._widget_kind(str_field) == "lineedit"


# ---------------------------------------------------------------------------
# _build (widget construction)
# ---------------------------------------------------------------------------

def test_build_creates_widget_per_field(dialog):
    widget_names = set(dialog._gui_widgets.keys())
    # At minimum, every metadata-bearing field gets a widget.
    for f in fields(dialog._prefs):
        if f.metadata.get("group"):
            assert f.name in widget_names, f"missing widget for {f.name}"


def test_build_widget_types_match_kinds(dialog):
    """Each created widget is the correct Qt class for its kind."""
    type_by_kind = {
        "checkbox": QtWidgets.QCheckBox,
        "spinbox": QtWidgets.QSpinBox,
        "lineedit": QtWidgets.QLineEdit,
        "combobox": QtWidgets.QComboBox,
    }
    for f in fields(dialog._prefs):
        if not f.metadata.get("group"):
            continue
        widget = dialog._gui_widgets[f.name]
        kind = dialog._widget_kind(f)
        assert isinstance(widget, type_by_kind[kind]), (
            f"{f.name}: expected {type_by_kind[kind].__name__}, got {type(widget).__name__}"
        )


def test_checkbox_initial_state_matches_prefs(dialog, prefs):
    """Checkbox widget reflects the bool field's value at build time."""
    cb = dialog._gui_widgets["generalEnable"]
    assert isinstance(cb, QtWidgets.QCheckBox)
    assert cb.isChecked() == prefs.generalEnable


def test_spinbox_initial_value_and_range_match_metadata(dialog, prefs):
    sb = dialog._gui_widgets["generalUpdate"]
    assert isinstance(sb, QtWidgets.QSpinBox)
    assert sb.value() == prefs.generalUpdate
    # Min/max pulled from SharedSettings.generalUpdate metadata.
    assert sb.minimum() == 12
    assert sb.maximum() == 60


def test_lineedit_initial_text_matches_prefs(dialog, prefs):
    le = dialog._gui_widgets["customDetails"]
    assert isinstance(le, QtWidgets.QLineEdit)
    assert le.text() == prefs.customDetails


def test_combobox_initial_selection_matches_prefs(dialog, prefs):
    cb = dialog._gui_widgets["detailsType"]
    assert isinstance(cb, QtWidgets.QComboBox)
    assert cb.currentData() == prefs.detailsType
    # _INITIAL_DEFAULTS overrides the base default, so this should be "scene".
    assert prefs.detailsType == "scene"


def test_combobox_populated_with_choices(dialog):
    cb = dialog._gui_widgets["detailsType"]
    items = [(cb.itemText(i), cb.itemData(i)) for i in range(cb.count())]
    assert items == _GuiTestSettings.INFO_CHOICES


# ---------------------------------------------------------------------------
# _set (signal handler that mutates prefs + triggers refresh timer)
# ---------------------------------------------------------------------------

def test_set_updates_prefs(dialog, prefs):
    dialog._set("generalEnable", False)
    assert prefs.generalEnable is False


def test_set_starts_refresh_timer(dialog):
    dialog._timer.stop()  # clean state
    assert not dialog._timer.isActive()
    dialog._set("generalEnable", False)
    assert dialog._timer.isActive()


def test_set_skipped_while_building(dialog, prefs):
    """When _building is True, _set short-circuits without mutating prefs.
    The flag exists so _load_from_prefs can refresh widgets without
    re-triggering writes."""
    original = prefs.generalEnable
    dialog._building = True
    try:
        dialog._set("generalEnable", not original)
    finally:
        dialog._building = False
    # Pref unchanged because _set early-returned.
    assert prefs.generalEnable == original


def test_checkbox_toggle_calls_set_via_signal(dialog, prefs):
    """Programmatically toggling a checkbox emits 'toggled', which the
    constructor wired to _set via lambda."""
    cb = dialog._gui_widgets["generalEnable"]
    initial = prefs.generalEnable
    cb.setChecked(not initial)
    assert prefs.generalEnable == (not initial)


def test_spinbox_change_calls_set_via_signal(dialog, prefs):
    sb = dialog._gui_widgets["generalUpdate"]
    sb.setValue(45)
    assert prefs.generalUpdate == 45


def test_combobox_change_calls_set_via_signal(dialog, prefs):
    cb = dialog._gui_widgets["detailsType"]
    # Select the third choice ("active").
    cb.setCurrentIndex(2)
    assert prefs.detailsType == "active"


def test_set_invalid_key_raises_via_setattr(dialog):
    """SharedSettings doesn't define unknown attrs; setattr on an unknown
    name still succeeds (Python lets it through), but pref consumers won't
    see it. We document this lenient behavior."""
    # Just ensure no crash — confirms _set doesn't blow up on a weird key.
    dialog._set("nonexistent_field", True)


# ---------------------------------------------------------------------------
# _build_controller_dict and _refresh_enabled_states
# ---------------------------------------------------------------------------

def test_controller_dict_includes_group_master_and_controls(dialog):
    controllers = dialog._controllers
    # Group masters from SharedSettings:
    assert "enableDetails" in controllers  # controls everything in Details group
    assert "enableState" in controllers
    # Controls-based (from enableButton1/enableButton2):
    assert "enableButton1" in controllers
    assert controllers["enableButton1"] == ["button1Label", "button1Url"]
    assert controllers["enableButton2"] == ["button2Label", "button2Url"]


def test_group_master_controls_all_other_fields_in_group(dialog):
    """A group_master should control every OTHER field in its group."""
    details_controlled = dialog._controllers["enableDetails"]
    assert "enableDetails" not in details_controlled  # master excluded
    assert "detailsType" in details_controlled
    assert "customDetails" in details_controlled
    assert "detailsCycle" in details_controlled


def test_refresh_enabled_states_grays_controlled_widgets(dialog, prefs):
    """Turning a controller off should disable its controlled widgets;
    turning it back on should re-enable them."""
    # enableButton1 is False by default; button1Label/Url should be disabled.
    assert dialog._gui_widgets["button1Label"].isEnabled() is False
    assert dialog._gui_widgets["button1Url"].isEnabled() is False
    # Toggle enableButton1 to True via the checkbox -> _set -> refresh.
    dialog._gui_widgets["enableButton1"].setChecked(True)
    assert dialog._gui_widgets["button1Label"].isEnabled() is True
    assert dialog._gui_widgets["button1Url"].isEnabled() is True


# ---------------------------------------------------------------------------
# _load_from_prefs (used after Reset)
# ---------------------------------------------------------------------------

def test_load_from_prefs_pushes_values_into_widgets(dialog, prefs):
    """Modify prefs directly (bypassing widgets), then call _load_from_prefs
    and check that widget displays update."""
    # Change every kind of widget's underlying pref. Use a generalUpdate
    # value within the spinbox's [12, 60] range so QSpinBox doesn't clamp.
    prefs.generalEnable = False
    prefs.generalUpdate = 30
    prefs.customDetails = "Hello world"
    prefs.detailsType = "frame"

    dialog._building = True  # mirror _on_reset_clicked's pattern
    dialog.load_from_prefs()
    dialog._building = False

    assert dialog._gui_widgets["generalEnable"].isChecked() is False
    assert dialog._gui_widgets["generalUpdate"].value() == 30
    assert dialog._gui_widgets["customDetails"].text() == "Hello world"
    assert dialog._gui_widgets["detailsType"].currentData() == "frame"


def test_load_from_prefs_unknown_choice_falls_to_index_zero(dialog, prefs):
    """If prefs has a combobox value that isn't in the choices, the widget
    falls back to index 0."""
    prefs.detailsType = "totally_invented"
    dialog._building = True
    dialog.load_from_prefs()
    dialog._building = False
    cb = dialog._gui_widgets["detailsType"]
    assert cb.currentIndex() == 0


# ---------------------------------------------------------------------------
# _on_reset_clicked (the user-confirmation dialog branches)
# ---------------------------------------------------------------------------

def test_on_reset_clicked_yes_resets_prefs(dialog, prefs, monkeypatch):
    """Patch QMessageBox.question to return Yes and verify prefs.reset() runs."""
    prefs.generalEnable = False
    prefs.generalUpdate = 42
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes),
    )
    dialog._on_reset_clicked()
    # _GuiTestSettings.reset() restores SharedSettings field defaults
    # (with _INITIAL_DEFAULTS overrides applied).
    assert prefs.generalEnable is True
    assert prefs.generalUpdate == 15


def test_on_reset_clicked_no_does_nothing(dialog, prefs, monkeypatch):
    prefs.generalEnable = False
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.No),
    )
    dialog._on_reset_clicked()
    # Pref unchanged.
    assert prefs.generalEnable is False


def test_on_reset_clicked_fires_refresh_callback(dialog, prefs, monkeypatch):
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes),
    )
    refresh_calls_before = len(dialog._refresh_calls)
    dialog._on_reset_clicked()
    assert len(dialog._refresh_calls) == refresh_calls_before + 1


def test_on_reset_clicked_updates_widgets_from_prefs(dialog, prefs, monkeypatch):
    """After a confirmed reset, widget values should reflect the reset prefs."""
    prefs.generalUpdate = 55
    dialog._gui_widgets["generalUpdate"].setValue(55)  # sync widget
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes),
    )
    dialog._on_reset_clicked()
    # Default for generalUpdate (after reset) is 15.
    assert dialog._gui_widgets["generalUpdate"].value() == 15


# ---------------------------------------------------------------------------
# _assemble (layout structure — light coverage, since visible widgets aren't
# tested without a display)
# ---------------------------------------------------------------------------

def test_assemble_creates_reset_and_close_buttons(dialog):
    """The bottom bar should contain two QPushButtons: 'Reset to defaults'
    and 'Close'."""
    buttons = dialog.findChildren(QtWidgets.QPushButton)
    labels = [b.text() for b in buttons]
    assert "Reset to defaults" in labels
    assert "Close" in labels


def test_assemble_wraps_groups_in_a_scrollarea(dialog):
    """Settings panels live inside a QScrollArea so the dialog remains usable
    when the field list is taller than the window."""
    scroll_areas = dialog.findChildren(QtWidgets.QScrollArea)
    assert len(scroll_areas) >= 1


def test_assemble_creates_one_groupbox_per_group(dialog):
    """Each unique metadata['group'] becomes a QGroupBox in the dialog."""
    boxes = dialog.findChildren(QtWidgets.QGroupBox)
    titles = {b.title() for b in boxes}
    assert {"General", "Icons", "Details", "State", "Buttons"}.issubset(titles)
