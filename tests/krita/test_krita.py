"""
Tests for KPContext (Krita plugin).

Two bugs surfaced during the docs cross-check; both have since been fixed in
the plugin and the regression tests below confirm the fix:
  * Window.activeView() is documented to return 0 (not None) when no view
    is active. KPContext.capture() used `is None`, which 0 fails — so a
    no-view state slipped through and downstream None-checks on
    `self.view` missed it. See
    test_capture_returns_none_when_active_view_is_zero.
  * _on_file_open used to raise ValueError uncaught when editing-time had
    non-numeric text. Since _on_file_open runs as a Krita notifier
    callback, a raise terminated the dispatch chain. See
    test_on_file_open_non_numeric_editing_time_falls_back_to_zero.

Also notable from the docs (not bug-flagged, but worth knowing):
  * Document.activeNode() is documented to ALWAYS return a Node ("If there
    is no active window, the first child node is returned."), so the plugin's
    None checks for activeNode are defensive dead code per docs. Left in
    place because the project's posture (after the Nuke quirks) is to keep
    defensive guards around vendor APIs.
  * View.currentBrushPreset() returns Resource (not Preset). The plugin's
    `cast(kr.Preset, ...)` is a wrong type hint, but Resource and Preset
    both have .name(), so the runtime call works.
"""

from __future__ import annotations
import pytest

from krita_presence import KPContext, KPSettings, KP_TOOL_MAPPING


# ---------------------------------------------------------------------------
# capture()
# ---------------------------------------------------------------------------


def test_capture_returns_none_when_no_krita_instance(kr):
    kr.set_state(instance_is_none=True)
    assert KPContext.capture() is None


def test_capture_returns_none_when_no_active_document(kr):
    kr.set_state(active_document=None)
    assert KPContext.capture() is None


def test_capture_returns_none_when_no_active_window(kr):
    kr.set_state(
        active_document=kr.make_document(name="A"),
        active_window=None,
    )
    assert KPContext.capture() is None


# Per the Krita docs, Window.activeView() returns 0 (not None) when no view
# is active; capture() must treat any falsy view as 'no view'. (The 0 case
# was previously broken; this parametrize pins both.)
@pytest.mark.parametrize("active_view", [None, 0])
def test_capture_returns_none_when_no_active_view(kr, active_view):
    kr.set_state(
        active_document=kr.make_document(name="A"),
        active_window=kr.make_window(active_view=active_view),  # type: ignore[arg-type]
    )
    assert KPContext.capture() is None


def test_capture_returns_full_context(kr):
    doc = kr.make_document(name="MyImage")
    view = kr.make_view()
    window = kr.make_window(active_view=view)
    kr.set_state(active_document=doc, active_window=window)
    ctx = KPContext.capture()
    assert ctx is not None
    assert ctx.doc is doc
    assert ctx.view is view
    assert ctx.window is window


# ---------------------------------------------------------------------------
# active_document_name
# ---------------------------------------------------------------------------


def test_active_document_name_unnamed(kr):
    doc = kr.make_document(name="Unnamed")
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=doc,
        window=kr.make_window(),
        view=kr.make_view(),
    )
    assert ctx.active_document_name() == "Unsaved document"


def test_active_document_name_with_name(kr):
    doc = kr.make_document(name="cool-art")
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=doc,
        window=kr.make_window(),
        view=kr.make_view(),
    )
    assert ctx.active_document_name() == "cool-art.kra"


# ---------------------------------------------------------------------------
# num_documents
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n, expected",
    [
        (0, "0 documents"),
        (1, "1 document"),
        (3, "3 documents"),
    ],
)
def test_num_documents(kr, n, expected):
    kr.set_state(documents=[kr.make_document() for _ in range(n)])
    doc = kr.make_document()
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=doc,
        window=kr.make_window(),
        view=kr.make_view(),
    )
    assert ctx.num_documents() == expected


# ---------------------------------------------------------------------------
# Layer counting + info
# ---------------------------------------------------------------------------


def test_num_layers_flat(kr):
    nodes = [kr.make_node(name=f"L{i}") for i in range(3)]
    doc = kr.make_document(top_level_nodes=nodes)
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=doc,
        window=kr.make_window(),
        view=kr.make_view(),
    )
    assert ctx.num_layers() == "3 layers"


def test_num_layers_nested_groups(kr):
    """Group A with 2 children + Layer B at top level = 4 nodes total."""
    inner = [kr.make_node(name="L1"), kr.make_node(name="L2")]
    group_a = kr.make_node(name="A", children=inner)
    nodes = [group_a, kr.make_node(name="B")]
    doc = kr.make_document(top_level_nodes=nodes)
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=doc,
        window=kr.make_window(),
        view=kr.make_view(),
    )
    # Group counts as 1, inner two count as 2, plus B = 4 total
    assert ctx.num_layers() == "4 layers"


def test_layer_info_word_layer_in_name(kr):
    active = kr.make_node(name="Layer 3", children=[])
    doc = kr.make_document(active_node=active)
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=doc,
        window=kr.make_window(),
        view=kr.make_view(),
    )
    assert ctx.layer_info() == "Layer 3"


def test_layer_info_without_word_layer(kr):
    active = kr.make_node(name="Foreground", children=[])
    doc = kr.make_document(active_node=active)
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=doc,
        window=kr.make_window(),
        view=kr.make_view(),
    )
    assert ctx.layer_info() == "Layer: Foreground"


def test_layer_info_with_sublayers(kr):
    sub = [kr.make_node(name="A"), kr.make_node(name="B"), kr.make_node(name="C")]
    active = kr.make_node(name="Group 1", children=sub)
    doc = kr.make_document(active_node=active)
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=doc,
        window=kr.make_window(),
        view=kr.make_view(),
    )
    # _recurse_count counts the active node itself + its descendants. Plugin
    # subtracts 1 so "sublayers" is just descendants. 3 children = 3 sublayers.
    assert ctx.layer_info() == "Group 1 (3 sublayers)"


def test_layer_blend_mode_normal_returns_none(kr):
    active = kr.make_node(name="L", blend="Normal")
    doc = kr.make_document(active_node=active)
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=doc,
        window=kr.make_window(),
        view=kr.make_view(),
    )
    assert ctx.layer_blend_mode() is None


def test_layer_blend_mode_non_normal(kr):
    active = kr.make_node(name="L", blend="Multiply")
    doc = kr.make_document(active_node=active)
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=doc,
        window=kr.make_window(),
        view=kr.make_view(),
    )
    assert ctx.layer_blend_mode() == "Layer blend mode: Multiply"


# ---------------------------------------------------------------------------
# Color
# ---------------------------------------------------------------------------


def test_color_info(kr):
    doc = kr.make_document(color_model="RGBA", color_profile="sRGB-elle-V2-srgbtrc.icc")
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=doc,
        window=kr.make_window(),
        view=kr.make_view(),
    )
    assert ctx.color_info() == "RGBA (sRGB-elle-V2-srgbtrc.icc)"


@pytest.mark.parametrize(
    "w, h, res, expected",
    [
        (1920, 1080, 72, "1920x1080 @ 72dpi"),
        (2000, 2000, 300, "2000x2000 @ 300dpi"),
    ],
)
def test_active_document_dimensions(kr, w, h, res, expected):
    doc = kr.make_document(width=w, height=h, resolution=res)
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=doc,
        window=kr.make_window(),
        view=kr.make_view(),
    )
    assert ctx.active_document_dimensions() == expected


def test_foreground_color_none_when_no_color(kr):
    view = kr.make_view(foreground_color=None, canvas=object())
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=kr.make_document(),
        window=kr.make_window(),
        view=view,
    )
    assert ctx.foreground_color() is None


def test_foreground_color_none_when_no_canvas(kr):
    view = kr.make_view(foreground_color=kr.make_managed_color(255, 0, 0), canvas=None)
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=kr.make_document(),
        window=kr.make_window(),
        view=view,
    )
    assert ctx.foreground_color() is None


def test_foreground_color_returns_rgb(kr):
    view = kr.make_view(
        foreground_color=kr.make_managed_color(255, 128, 0), canvas=object()
    )
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=kr.make_document(),
        window=kr.make_window(),
        view=view,
    )
    assert ctx.foreground_color() == (255, 128, 0)


def test_view_blend_mode(kr):
    view = kr.make_view(blending_mode="Multiply")
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=kr.make_document(),
        window=kr.make_window(),
        view=view,
    )
    assert ctx.view_blend_mode() == "Multiply"


# ---------------------------------------------------------------------------
# active_brush_preset
# ---------------------------------------------------------------------------


def test_active_brush_preset_no_preset(kr):
    view = kr.make_view(brush_preset=None)
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=kr.make_document(),
        window=kr.make_window(),
        view=view,
    )
    assert ctx.active_brush_preset() is None


def test_active_brush_preset_none_when_no_active_tool(kr):
    """A preset is selected but no ToolBox docker is wired up, so
    active_tool_name() returns None. None is not in the brush-tool whitelist,
    so the function bails to None before reading preset.name()."""
    view = kr.make_view(brush_preset=kr.make_preset("a) Basic-5"))
    ctx = KPContext(
        instance=kr.Krita.instance(),
        doc=kr.make_document(),
        window=kr.make_window(),
        view=view,
    )
    assert ctx.active_brush_preset() is None


def test_kpsettings_includes_colored_icon_fields(kr):
    """KPSettings inherits from SharedSettings AND ColoredIconSettings; both
    parents' fields should appear in fields(KPSettings_instance). Earlier
    audit noted this would fail without an @dataclass decorator on KPSettings;
    the current code has the decorator (or equivalent), so all four expected
    fields are present.
    """
    from dataclasses import fields

    s = KPSettings()
    field_names = {f.name for f in fields(s)}
    # ColoredIconSettings fields:
    assert "enableColoredIcons" in field_names
    assert "useEvocativeNames" in field_names
    # SharedSettings fields:
    assert "generalEnable" in field_names
    assert "displaySmallIcon" in field_names


def test_kp_tool_mapping_has_expected_keys():
    """Sanity check the tool-name registry has the brush we tint icons for."""
    assert "KritaShape/KisToolBrush" in KP_TOOL_MAPPING
    assert KP_TOOL_MAPPING["KritaShape/KisToolBrush"] == "Freehand Brush Tool"


# ---------------------------------------------------------------------------
# KPPlugin: update_small_icon, update_large_icon, _on_file_open, doc_time
# ---------------------------------------------------------------------------

import time as _time  # noqa: E402
from krita_presence import KPPlugin, IdleDetector  # noqa: E402


@pytest.fixture
def kp_plugin(kr):
    """Construct a fresh KPPlugin and reset module-level ClassVar state
    (doc_times dict, idle_monitor). Avoids test-order pollution."""
    plugin = KPPlugin()
    snap_doc_times = dict(KPPlugin.doc_times)
    snap_idle_last = KPPlugin.idle_monitor._last_input
    KPPlugin.doc_times.clear()
    yield plugin
    KPPlugin.doc_times.clear()
    KPPlugin.doc_times.update(snap_doc_times)
    KPPlugin.idle_monitor._last_input = snap_idle_last


def _make_doc_with_editing_time(kr, name="Doc", seconds=0, *, about_inner=None):
    """Build a document whose documentInfo XML has the given <about> body.

    `seconds=N` is the common case: emit `<editing-time>N</editing-time>`.
    Pass `about_inner=...` for the malformed/missing cases (e.g. `""` for the
    missing-editing-time test or `"<editing-time>not-a-number</editing-time>"`
    for the non-numeric test).
    """
    if about_inner is None:
        about_inner = f"<editing-time>{seconds}</editing-time>"
    xml = (
        '<?xml version="1.0"?>'
        '<document-info xmlns="http://www.calligra.org/DTD/document-info">'
        f"<about>{about_inner}</about>"
        "</document-info>"
    )
    return kr.make_document(name=name, document_info_xml=xml)


# --- _on_file_open ---


def test_on_file_open_resets_session_timer(kr, kp_plugin):
    kp_plugin.prefs.resetTimer = True
    kp_plugin.session.start_time = 0.0
    doc = _make_doc_with_editing_time(kr, seconds=0)
    kp_plugin._on_file_open(doc)
    assert kp_plugin.session.start_time > 0.0


def test_on_file_open_skips_reset_when_pref_unset(kr, kp_plugin):
    kp_plugin.prefs.resetTimer = False
    kp_plugin.session.start_time = 99.0
    doc = _make_doc_with_editing_time(kr, seconds=0)
    kp_plugin._on_file_open(doc)
    assert kp_plugin.session.start_time == 99.0


# Parametrized editing-time behavior: well-formed integer is stored; missing
# element and non-numeric text both fall back to 0. The non-numeric case used
# to raise an uncaught ValueError and terminate the notifier dispatch chain.
@pytest.mark.parametrize("about_inner, expected", [
    ("<editing-time>3600</editing-time>", 3600),
    ("", 0),  # no editing-time element
    ("<editing-time>not-a-number</editing-time>", 0),  # malformed value
])
def test_on_file_open_editing_time(kr, kp_plugin, about_inner, expected):
    doc = _make_doc_with_editing_time(kr, name="X", about_inner=about_inner)
    kp_plugin._on_file_open(doc)
    assert KPPlugin.doc_times.get(id(doc)) == expected


# --- doc_time (formatter) ---


def test_doc_time_returns_none_when_no_record(kr, kp_plugin):
    """A document with no recorded time should produce None."""
    doc = kr.make_document(name="Untracked")
    view = kr.make_view()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    assert KPPlugin.doc_time(ctx) is None


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "0m"),
        (60, "1m"),
        (1800, "30m"),
        (3600, "1h 0m"),
        (3720, "1h 2m"),
        (7320, "2h 2m"),
    ],
)
def test_doc_time_formats_hours_and_minutes(kr, kp_plugin, seconds, expected):
    doc = kr.make_document(name="Tracked")
    view = kr.make_view()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    KPPlugin.doc_times[id(doc)] = seconds
    # Force not idle so we get the clean "Document time: …" form.
    KPPlugin.idle_monitor._last_input = _time.time()
    out = KPPlugin.doc_time(ctx)
    assert out == f"Document time: {expected}"


def test_doc_time_appends_idle_marker(kr, kp_plugin):
    doc = kr.make_document(name="Idle")
    view = kr.make_view()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    KPPlugin.doc_times[id(doc)] = 120
    # Force idle by pushing _last_input far into the past.
    KPPlugin.idle_monitor._last_input = _time.time() - 10_000
    out = KPPlugin.doc_time(ctx)
    assert out is not None
    assert "(Idle)" in out
    assert "2m" in out


# --- update_small_icon ---


def test_update_small_icon_disabled_pref(kr, kp_plugin):
    kp_plugin.prefs.displaySmallIcon = False
    doc = kr.make_document()
    view = kr.make_view()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    kp_plugin.update_small_icon(ctx)
    assert kp_plugin.details.small_icon is None
    assert kp_plugin.details.small_icon_text == ""


def test_update_small_icon_no_tool_clears(kr, kp_plugin):
    """If active_tool_name returns None (no ToolBox docker), small_icon
    should stay None."""
    kp_plugin.prefs.displaySmallIcon = True
    doc = kr.make_document()
    view = kr.make_view()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    # No dockers configured -> active_tool_name() returns None
    kp_plugin.update_small_icon(ctx)
    assert kp_plugin.details.small_icon is None


def test_update_small_icon_unknown_tool_clears(kr, kp_plugin, monkeypatch):
    """A tool name not in KP_TOOL_MAPPING should leave small_icon as None."""
    kp_plugin.prefs.displaySmallIcon = True
    doc = kr.make_document()
    view = kr.make_view()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    monkeypatch.setattr(ctx, "active_tool_name", lambda: "SomeUnknownTool")
    kp_plugin.update_small_icon(ctx)
    assert kp_plugin.details.small_icon is None


def test_update_small_icon_known_non_brush_tool(kr, kp_plugin, monkeypatch):
    """A known tool that isn't the colorized brush should get the monochrome
    icon name (lowercased, slash -> underscore) and the tool's display name
    as hover text."""
    kp_plugin.prefs.displaySmallIcon = True
    kp_plugin.prefs.enableColoredIcons = True  # irrelevant for non-brush tools
    doc = kr.make_document()
    view = kr.make_view()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    monkeypatch.setattr(ctx, "active_tool_name", lambda: "KisToolCrop")
    kp_plugin.update_small_icon(ctx)
    assert kp_plugin.details.small_icon == "kistoolcrop"
    assert kp_plugin.details.small_icon_text == "Crop Tool"


def test_update_small_icon_brush_tool_without_colored(kr, kp_plugin, monkeypatch):
    """Freehand Brush active but enableColoredIcons=False should use the
    monochrome brush icon, not a colored variant."""
    kp_plugin.prefs.displaySmallIcon = True
    kp_plugin.prefs.enableColoredIcons = False
    doc = kr.make_document()
    view = kr.make_view()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    monkeypatch.setattr(ctx, "active_tool_name", lambda: "KritaShape/KisToolBrush")
    kp_plugin.update_small_icon(ctx)
    assert kp_plugin.details.small_icon == "kritashape_kistoolbrush"
    assert kp_plugin.details.small_icon_text == "Freehand Brush Tool"


def test_update_small_icon_brush_tool_with_color(kr, kp_plugin, monkeypatch):
    """Freehand Brush + enableColoredIcons=True + foreground color present
    should set kbrush_cNNN and hover text 'Painting in <name> (#HEX)'."""
    kp_plugin.prefs.displaySmallIcon = True
    kp_plugin.prefs.enableColoredIcons = True
    doc = kr.make_document()
    view = kr.make_view(
        foreground_color=kr.make_managed_color(255, 0, 0),
        canvas=object(),
    )
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    monkeypatch.setattr(ctx, "active_tool_name", lambda: "KritaShape/KisToolBrush")
    kp_plugin.update_small_icon(ctx)
    assert kp_plugin.details.small_icon is not None
    assert kp_plugin.details.small_icon.startswith("kbrush_c")
    assert "Painting in " in kp_plugin.details.small_icon_text
    assert "#FF0000" in kp_plugin.details.small_icon_text


def test_update_small_icon_brush_tool_no_color_falls_back(kr, kp_plugin, monkeypatch):
    """If foreground_color() returns None, we keep the monochrome brush icon."""
    kp_plugin.prefs.displaySmallIcon = True
    kp_plugin.prefs.enableColoredIcons = True
    doc = kr.make_document()
    view = kr.make_view(foreground_color=None, canvas=None)
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    monkeypatch.setattr(ctx, "active_tool_name", lambda: "KritaShape/KisToolBrush")
    kp_plugin.update_small_icon(ctx)
    # Stayed on the monochrome brush icon.
    assert kp_plugin.details.small_icon == "kritashape_kistoolbrush"


# --- update_large_icon ---


def test_update_large_icon_with_version(kr, kp_plugin):
    kp_plugin.prefs.displayVersion = True
    doc = kr.make_document()
    view = kr.make_view()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    kp_plugin.update_large_icon(ctx)
    assert kp_plugin.details.large_icon_text == "Krita 5.3.1"


def test_update_large_icon_without_version(kr, kp_plugin):
    kp_plugin.prefs.displayVersion = False
    doc = kr.make_document()
    view = kr.make_view()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    kp_plugin.update_large_icon(ctx)
    assert kp_plugin.details.large_icon_text == "Krita"


# ---------------------------------------------------------------------------
# IdleDetector
# ---------------------------------------------------------------------------


def test_idle_detector_not_idle_at_init():
    d = IdleDetector(threshold_seconds=180)
    assert d.is_idle() is False


def test_idle_detector_becomes_idle_past_threshold():
    d = IdleDetector(threshold_seconds=60)
    d._last_input = _time.time() - 120  # 2 minutes ago
    assert d.is_idle() is True


def test_idle_detector_event_filter_updates_on_input():
    """eventFilter should bump _last_input when a recognized event arrives,
    pushing is_idle() back to False."""
    from PySide6.QtCore import QEvent

    d = IdleDetector(threshold_seconds=60)
    d._last_input = _time.time() - 120  # past threshold
    assert d.is_idle() is True
    # MouseButtonPress is one of the recognized event types.
    fake_event = QEvent(QEvent.Type.MouseButtonPress)
    d.eventFilter(None, fake_event)
    assert d.is_idle() is False


def test_idle_detector_event_filter_ignores_unrelated_events():
    from PySide6.QtCore import QEvent

    d = IdleDetector(threshold_seconds=60)
    d._last_input = _time.time() - 120
    # Type.Paint isn't on the recognized list.
    fake_event = QEvent(QEvent.Type.Paint)
    d.eventFilter(None, fake_event)
    assert d.is_idle() is True


def test_idle_detector_event_filter_returns_false():
    """eventFilter must return False so Qt continues normal event delivery."""
    from PySide6.QtCore import QEvent

    d = IdleDetector(threshold_seconds=60)
    e = QEvent(QEvent.Type.MouseButtonPress)
    assert d.eventFilter(None, e) is False


# ---------------------------------------------------------------------------
# active_tool_name + active_brush_preset (Qt docker introspection)
# ---------------------------------------------------------------------------


def _ctx_with_dockers(kr, dockers):
    """Build a KPContext, swapping in a fake `dockers()` value via set_state."""
    kr.set_state(dockers=dockers)
    doc = kr.make_document(name="X")
    view = kr.make_view()
    return KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )


def test_active_tool_name_no_toolbox_docker(kr):
    """If no docker has objectName() == 'ToolBox', return None."""
    from PySide6.QtWidgets import QDockWidget

    not_toolbox = QDockWidget()
    not_toolbox.setObjectName("OtherDocker")
    ctx = _ctx_with_dockers(kr, [not_toolbox])
    assert ctx.active_tool_name() is None


def test_active_tool_name_toolbox_without_button_group(kr):
    """ToolBox docker present but no QButtonGroup child -> None."""
    from PySide6.QtWidgets import QDockWidget

    docker = QDockWidget()
    docker.setObjectName("ToolBox")
    ctx = _ctx_with_dockers(kr, [docker])
    assert ctx.active_tool_name() is None


def test_active_tool_name_no_checked_button(kr):
    """ToolBox + QButtonGroup with no checked button -> None."""
    docker = kr.make_toolbox_with_active_tool(None)
    ctx = _ctx_with_dockers(kr, [docker])
    assert ctx.active_tool_name() is None


@pytest.mark.parametrize(
    "tool_name",
    [
        "KritaShape/KisToolBrush",
        "KritaShape/KisToolMultiBrush",
        "KritaShape/KisToolDyna",
        "KisToolCrop",
        "InteractionTool",
    ],
)
def test_active_tool_name_returns_checked_button_object_name(kr, tool_name):
    docker = kr.make_toolbox_with_active_tool(tool_name)
    ctx = _ctx_with_dockers(kr, [docker])
    assert ctx.active_tool_name() == tool_name


def test_active_tool_name_skips_non_toolbox_dockers(kr):
    """When multiple dockers exist, only the one named 'ToolBox' is picked."""
    from PySide6.QtWidgets import QDockWidget

    other = QDockWidget()
    other.setObjectName("Brushes")
    toolbox = kr.make_toolbox_with_active_tool("KritaShape/KisToolBrush")
    ctx = _ctx_with_dockers(kr, [other, toolbox])
    assert ctx.active_tool_name() == "KritaShape/KisToolBrush"


# ---------------------------------------------------------------------------
# active_brush_preset (depends on active_tool_name to choose whether to report)
# ---------------------------------------------------------------------------


def test_active_brush_preset_returns_none_for_non_brush_tool(kr):
    """Even with a preset selected, non-brush tools should report None."""
    docker = kr.make_toolbox_with_active_tool("KisToolCrop")  # not a brush
    kr.set_state(dockers=[docker])
    view = kr.make_view(brush_preset=kr.make_preset("a) Basic-5"))
    doc = kr.make_document()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    assert ctx.active_brush_preset() is None


@pytest.mark.parametrize(
    "tool_name",
    [
        "KritaShape/KisToolBrush",
        "KritaShape/KisToolMultiBrush",
        "KritaShape/KisToolDyna",
    ],
)
def test_active_brush_preset_returns_clean_name_for_brush_tools(kr, tool_name):
    """For brush-family tools, the preset name is returned with letter-prefix
    and (mypaint) marker stripped."""
    docker = kr.make_toolbox_with_active_tool(tool_name)
    kr.set_state(dockers=[docker])
    view = kr.make_view(brush_preset=kr.make_preset("b) Basic-5 Size Default"))
    doc = kr.make_document()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    assert ctx.active_brush_preset() == "Preset: Basic-5 Size Default"


def test_active_brush_preset_strips_mypaint_marker(kr):
    docker = kr.make_toolbox_with_active_tool("KritaShape/KisToolBrush")
    kr.set_state(dockers=[docker])
    view = kr.make_view(brush_preset=kr.make_preset("c) Pencil-1 Sketch (mypaint)"))
    doc = kr.make_document()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    out = ctx.active_brush_preset()
    assert out == "Preset: Pencil-1 Sketch"


def test_active_brush_preset_strips_mypaint_prev_marker(kr):
    docker = kr.make_toolbox_with_active_tool("KritaShape/KisToolBrush")
    kr.set_state(dockers=[docker])
    view = kr.make_view(brush_preset=kr.make_preset("d) Custom (mypaint)_prev"))
    doc = kr.make_document()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    assert ctx.active_brush_preset() == "Preset: Custom"


# ---------------------------------------------------------------------------
# tool_info (combines active_tool_name + blend mode)
# ---------------------------------------------------------------------------


def test_tool_info_no_tool_returns_none(kr):
    """No ToolBox docker -> None."""
    ctx = _ctx_with_dockers(kr, [])
    assert ctx.tool_info() is None


def test_tool_info_normal_blend_omits_suffix(kr):
    docker = kr.make_toolbox_with_active_tool("KritaShape/KisToolBrush")
    kr.set_state(dockers=[docker])
    view = kr.make_view(blending_mode="Normal")
    doc = kr.make_document()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    assert ctx.tool_info() == "Freehand Brush Tool"


def test_tool_info_non_normal_blend_appended(kr):
    docker = kr.make_toolbox_with_active_tool("KritaShape/KisToolBrush")
    kr.set_state(dockers=[docker])
    view = kr.make_view(blending_mode="Multiply")
    doc = kr.make_document()
    ctx = KPContext(
        instance=kr.Krita.instance(), doc=doc, window=kr.make_window(), view=view
    )
    assert ctx.tool_info() == "Freehand Brush Tool (Multiply)"
