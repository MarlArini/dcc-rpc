"""
Tests for SPContext (Painter plugin).

Qt-introspection methods (get_active_tool, get_paint_color, get_brush_material,
get_brush_alpha) are covered via an in-memory fake Qt widget tree
(_FakeQWidget in the painter fake module) that emulates findChild /
findChildren / objectName / text / isChecked / defaultAction / grab().

Two bugs surfaced during the docs cross-check; both have since been fixed in
the plugin and the regression tests below confirm the fix:
  * get_project_name used to label sp.project.name() == None as
    "No project open"; per the Painter docs that case means the project IS
    open and just hasn't been saved yet. Now returns "Unsaved Project". See
    test_get_project_name_unsaved_shows_unsaved_not_no_project.
  * get_brush_material and get_brush_alpha used to be identical (both
    walked MaskParametersView -> dropzone_text). They now target separate
    widgets (materialModeParams vs. MaskParametersView). See
    test_get_brush_material_and_alpha_target_distinct_widgets.
"""
from __future__ import annotations
import pytest

# Import once at module load. This triggers painter_presence module body
# (including SP_PLUGIN = SPPlugin() and its QTimer construction). conftest's
# session-scoped QApplication ensures that succeeds.
from substance_painter_presence.painter_presence import SPContext


# ---------------------------------------------------------------------------
# capture()
# ---------------------------------------------------------------------------

def test_capture_returns_context_when_everything_present(sp):
    stack = sp.make_stack()
    ts = [sp.make_texture_set()]
    sp.set_state(active_stack=stack, texture_sets=ts)
    ctx = SPContext.capture()
    assert ctx is not None
    assert ctx.stack is stack
    assert ctx.texture_sets == ts


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("transient"),
        # sp.exception.ProjectError / ServiceNotFoundError are also caught:
    ],
)
def test_capture_swallows_runtime_errors(sp, exc):
    sp.set_state(capture_raises=exc)
    assert SPContext.capture() is None


def test_capture_swallows_painter_exception_types(sp):
    sp.set_state(capture_raises=sp.exception.ProjectError("no project"))
    assert SPContext.capture() is None
    sp.set_state(capture_raises=sp.exception.ServiceNotFoundError("service down"))
    assert SPContext.capture() is None


# ---------------------------------------------------------------------------
# get_project_name
# ---------------------------------------------------------------------------

def test_get_project_name_with_project(sp):
    sp.set_state(project_name="MyProject")
    ctx = SPContext(texture_sets=[], stack=sp.make_stack(), main_window=None)
    assert ctx.get_project_name() == "Project: MyProject"


def test_get_project_name_unsaved_shows_unsaved_not_no_project(sp):
    """sp.project.name() returns None when the project is open but unsaved,
    per the Painter docs. Regression test: plugin used to mislabel this as
    'No project open', which is the ProjectError path (handled upstream in
    capture)."""
    sp.set_state(project_name=None)
    ctx = SPContext(texture_sets=[], stack=sp.make_stack(), main_window=None)
    out = ctx.get_project_name()
    assert out is not None
    assert "No project open" not in out
    assert "unsaved" in out.lower() or "untitled" in out.lower()


# ---------------------------------------------------------------------------
# Mesh / texture-set / channel counts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "mesh_groups, expected",
    [
        ([], "0 meshes"),
        ([["m1"]], "1 mesh"),
        ([["m1", "m2"]], "2 meshes"),
        ([["m1"], ["m2", "m3"]], "3 meshes"),
        ([["m1", "m2"], ["m3", "m4", "m5"]], "5 meshes"),
    ],
)
def test_get_num_meshes(sp, mesh_groups, expected):
    ts = [sp.make_texture_set(mesh_names=names) for names in mesh_groups]
    ctx = SPContext(texture_sets=ts, stack=sp.make_stack(), main_window=None)
    assert ctx.get_num_meshes() == expected


@pytest.mark.parametrize("n", [0, 1, 5, 100])
def test_get_num_texsets(sp, n):
    ts = [sp.make_texture_set() for _ in range(n)]
    ctx = SPContext(texture_sets=ts, stack=sp.make_stack(), main_window=None)
    assert ctx.get_num_texsets() == n


def test_get_active_texset_name(sp):
    mat = sp.make_material(name="bricks_diffuse")
    stack = sp.make_stack(material=mat)
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_active_texset_name() == "bricks_diffuse"


@pytest.mark.parametrize(
    "w, h, expected",
    [
        (1024, 1024, "1024x1024"),
        (2048, 1024, "2048x1024"),
        (4096, 4096, "4096x4096"),
        (512, 256, "512x256"),
    ],
)
def test_get_material_resolution_str(sp, w, h, expected):
    mat = sp.make_material(res_w=w, res_h=h)
    stack = sp.make_stack(material=mat)
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_material_resolution_str() == expected


def test_get_active_texset_info_combines(sp):
    mat = sp.make_material(name="bricks", res_w=2048, res_h=2048)
    stack = sp.make_stack(material=mat)
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_active_texset_info() == "Texture set: bricks (2048x2048)"


def test_get_layer_num_channels(sp):
    stack = sp.make_stack(channels=[object(), object(), object()])
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_layer_num_channels() == "3 channels"


# ---------------------------------------------------------------------------
# Layers (flat, nested groups, selected, blend mode)
# ---------------------------------------------------------------------------

def test_get_num_layers_flat(sp):
    leaves = [sp.make_layer(f"L{i}") for i in range(4)]
    stack = sp.make_stack(root_nodes=leaves)
    ctx = SPContext(texture_sets=[sp.make_texture_set(stacks=[stack])], stack=stack, main_window=None)
    # active_only=True walks just `stack`
    assert ctx.get_num_layers(active_only=True) == "4 active layers"
    # full walk: only one stack with the same 4 leaves
    assert ctx.get_num_layers(active_only=False) == "4 layers"


def test_get_num_layers_nested_groups(sp):
    # Tree:
    #   Group A
    #     Layer 1
    #     Group B
    #       Layer 2
    #       Layer 3
    #   Layer 4
    leaves_b = [sp.make_layer("L2"), sp.make_layer("L3")]
    group_b = sp.make_group("B", children=leaves_b)
    group_a = sp.make_group("A", children=[sp.make_layer("L1"), group_b])
    root = [group_a, sp.make_layer("L4")]
    stack = sp.make_stack(root_nodes=root)
    ctx = SPContext(
        texture_sets=[sp.make_texture_set(stacks=[stack])],
        stack=stack,
        main_window=None,
    )
    # Counts leaves only: L1, L2, L3, L4 = 4
    assert ctx.get_num_layers(active_only=True) == "4 active layers"


def test_get_num_layers_multi_texset(sp):
    s1 = sp.make_stack(root_nodes=[sp.make_layer("L1")])
    s2 = sp.make_stack(root_nodes=[sp.make_layer("L2"), sp.make_layer("L3")])
    ts = [
        sp.make_texture_set(stacks=[s1]),
        sp.make_texture_set(stacks=[s2]),
    ]
    ctx = SPContext(texture_sets=ts, stack=s1, main_window=None)
    assert ctx.get_num_layers(active_only=False) == "3 layers"


def test_get_active_layer_name_no_selection(sp):
    stack = sp.make_stack(selected_nodes=[])
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_active_layer_name() is None


def test_get_active_layer_name_single_with_word_layer(sp):
    """If the layer name already contains 'layer', no prefix added."""
    stack = sp.make_stack(selected_nodes=[sp.make_layer("Layer 3")])
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_active_layer_name() == "Layer 3"


def test_get_active_layer_name_single_without_word_layer(sp):
    """Otherwise, prefix with 'Layer:'."""
    stack = sp.make_stack(selected_nodes=[sp.make_layer("Decals")])
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_active_layer_name() == "Layer: Decals"


def test_get_active_layer_name_multi_select(sp):
    stack = sp.make_stack(selected_nodes=[
        sp.make_layer("A"), sp.make_layer("B"), sp.make_layer("C"),
    ])
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_active_layer_name() == "3 layers currently selected"


def test_get_active_layer_blend_mode_mask(sp):
    layer = sp.make_layer("Mask", blend_mode="Multiply", is_mask=True)
    stack = sp.make_stack(selected_nodes=[layer])
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_active_layer_blend_mode() == "Multiply"


def test_get_active_layer_blend_mode_non_mask_returns_none(sp):
    """Currently the plugin only reports blend mode for mask-stack layers."""
    layer = sp.make_layer("L", blend_mode="Multiply", is_mask=False)
    stack = sp.make_stack(selected_nodes=[layer])
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_active_layer_blend_mode() is None


def test_get_active_layer_info_no_blend(sp):
    layer = sp.make_layer("Decals", is_mask=False)
    stack = sp.make_stack(selected_nodes=[layer])
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_active_layer_info() == "Layer: Decals"


def test_get_active_layer_info_with_blend_on_mask(sp):
    layer = sp.make_layer("Layer 3", blend_mode="Screen", is_mask=True)
    stack = sp.make_stack(selected_nodes=[layer])
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_active_layer_info() == "Layer 3 (Screen)"


def test_get_active_layer_info_returns_none_when_unselected(sp):
    stack = sp.make_stack(selected_nodes=[])
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_active_layer_info() is None


# ---------------------------------------------------------------------------
# UV tiles
# ---------------------------------------------------------------------------

def test_get_num_uv_tiles_no_tiles_returns_none(sp):
    mat = sp.make_material(uv_tiles=None)
    stack = sp.make_stack(material=mat)
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_num_uv_tiles(active_only=True) is None


def test_get_num_uv_tiles_active_only(sp):
    tiles = [object(), object(), object()]
    mat = sp.make_material(uv_tiles=tiles)
    stack = sp.make_stack(material=mat)
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_num_uv_tiles(active_only=True) == 3


def test_get_num_uv_tiles_all_texsets_below_two_returns_none(sp):
    """Implementation returns None when total < 2 (treats < 2 as 'no UV tiles')."""
    mat = sp.make_material(uv_tiles=None)
    stack = sp.make_stack(material=mat)
    ts = [sp.make_texture_set(stacks=[stack])]
    ctx = SPContext(texture_sets=ts, stack=stack, main_window=None)
    assert ctx.get_num_uv_tiles(active_only=False) is None


def test_get_num_uv_tiles_all_texsets_aggregates(sp):
    s1 = sp.make_stack(material=sp.make_material(uv_tiles=[object(), object()]))
    s2 = sp.make_stack(material=sp.make_material(uv_tiles=[object()]))
    ts = [
        sp.make_texture_set(stacks=[s1]),
        sp.make_texture_set(stacks=[s2]),
    ]
    ctx = SPContext(texture_sets=ts, stack=s1, main_window=None)
    assert ctx.get_num_uv_tiles(active_only=False) == 3


# ---------------------------------------------------------------------------
# Project texset info (combines texset count + UV tile count)
# ---------------------------------------------------------------------------

def test_get_project_texset_info_no_uv_tiles(sp):
    """When no stacks have UV tiles, output omits the (N UV tiles) suffix.
    (Earlier audit flagged this as buggy; the current code correctly treats
    a missing-tiles count as 'no tiles' for the project-level info.)"""
    s1 = sp.make_stack(material=sp.make_material(uv_tiles=None))
    s2 = sp.make_stack(material=sp.make_material(uv_tiles=None))
    ts = [sp.make_texture_set(stacks=[s1]), sp.make_texture_set(stacks=[s2])]
    ctx = SPContext(texture_sets=ts, stack=s1, main_window=None)
    assert ctx.get_project_texset_info() == "2 texture sets"


def test_get_project_texset_info_with_uv_tiles(sp):
    s1 = sp.make_stack(material=sp.make_material(uv_tiles=[object(), object()]))
    s2 = sp.make_stack(material=sp.make_material(uv_tiles=[object()]))
    ts = [sp.make_texture_set(stacks=[s1]), sp.make_texture_set(stacks=[s2])]
    ctx = SPContext(texture_sets=ts, stack=s1, main_window=None)
    assert ctx.get_project_texset_info() == "2 texture sets (3 UV tiles)"


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n, expected", [
    (0, "0 resources"),
    (1, "1 resource"),
    (10, "10 resources"),
])
def test_get_num_resources(sp, n, expected):
    sp.set_state(resources=list(range(n)))
    ctx = SPContext(texture_sets=[], stack=sp.make_stack(), main_window=None)
    assert ctx.get_num_resources() == expected


# ---------------------------------------------------------------------------
# Fuzz: layer-count formatting across many counts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("count", [0, 1, 2, 7, 100, 999])
def test_layer_count_pluralization_fuzz(sp, count):
    layers = [sp.make_layer(f"L{i}") for i in range(count)]
    stack = sp.make_stack(root_nodes=layers)
    ctx = SPContext(
        texture_sets=[sp.make_texture_set(stacks=[stack])],
        stack=stack,
        main_window=None,
    )
    out = ctx.get_num_layers(active_only=True)
    if count == 1:
        assert out == "1 active layer"
    else:
        assert out == f"{count} active layers"


# ---------------------------------------------------------------------------
# Qt introspection (get_active_tool, get_paint_color, get_brush_*)
# ---------------------------------------------------------------------------

import PySide6.QtWidgets as QtW  # noqa: E402,F401 — referenced by SPContext via cls= args


def _ctx_with(sp, main_window):
    """Construct an SPContext whose main_window is a fake Qt tree."""
    return SPContext(
        texture_sets=[sp.make_texture_set()],
        stack=sp.make_stack(),
        main_window=main_window,
    )


# --- get_active_tool ---

def test_get_active_tool_no_toolbar_returns_none(sp):
    mw = sp.make_qt_main_window(children=[])  # no toolbar named tools_toolbar
    ctx = _ctx_with(sp, mw)
    assert ctx.get_active_tool() is None


def test_get_active_tool_no_checked_button(sp):
    toolbar = sp.make_toolbar(buttons=[
        sp.make_tool_button(action_text="Paint", checked=False),
        sp.make_tool_button(action_text="Eraser", checked=False),
    ])
    mw = sp.make_qt_main_window(children=[toolbar])
    ctx = _ctx_with(sp, mw)
    assert ctx.get_active_tool() is None


def test_get_active_tool_multiple_checked_returns_none(sp):
    """Plugin assumes only one tool is active; 2+ checked is treated as
    ambiguous and returns None."""
    toolbar = sp.make_toolbar(buttons=[
        sp.make_tool_button(action_text="Paint", checked=True),
        sp.make_tool_button(action_text="Eraser", checked=True),
    ])
    mw = sp.make_qt_main_window(children=[toolbar])
    ctx = _ctx_with(sp, mw)
    assert ctx.get_active_tool() is None


@pytest.mark.parametrize("active_label", [
    "Paint", "Physical paint", "Eraser", "Smudge", "Clone (absolute source)",
])
def test_get_active_tool_returns_checked_action_text(sp, active_label):
    toolbar = sp.make_toolbar(buttons=[
        sp.make_tool_button(action_text="Paint", checked=False),
        sp.make_tool_button(action_text=active_label, checked=True),
        sp.make_tool_button(action_text="Eraser", checked=False),
    ])
    mw = sp.make_qt_main_window(children=[toolbar])
    ctx = _ctx_with(sp, mw)
    assert ctx.get_active_tool() == active_label


def test_get_active_tool_swallows_runtimeerror(sp):
    """If the Qt widget has been destroyed, findChild raises RuntimeError;
    the method should return None rather than propagate."""
    mw = sp.make_qt_widget(widget_class="QMainWindow", raise_on_find=True)
    ctx = _ctx_with(sp, mw)
    assert ctx.get_active_tool() is None


def test_get_active_tool_no_default_action_returns_none(sp):
    """A QToolButton without a default action shouldn't crash; return None."""
    button_no_action = sp.make_qt_widget(
        widget_class="QToolButton", checked=True, default_action=None,
    )
    toolbar = sp.make_toolbar(buttons=[button_no_action])
    mw = sp.make_qt_main_window(children=[toolbar])
    ctx = _ctx_with(sp, mw)
    assert ctx.get_active_tool() is None


# --- get_paint_color ---

def test_get_paint_color_no_source_parameters_view(sp):
    mw = sp.make_qt_main_window(children=[])  # no SourceParametersView
    ctx = _ctx_with(sp, mw)
    assert ctx.get_paint_color() is None


def test_get_paint_color_view_without_base_color_label(sp):
    """SourceParametersView exists but its dropzone_title labels don't
    contain 'Base color' — should not match."""
    spv = sp.make_qt_widget(
        widget_class="QFrame",
        object_name="SourceParametersView",
        children=[sp.make_qt_widget(
            widget_class="QLabel",
            object_name="dropzone_title",
            text="Roughness",  # not Base color
        )],
    )
    mw = sp.make_qt_main_window(children=[spv])
    ctx = _ctx_with(sp, mw)
    assert ctx.get_paint_color() is None


def test_get_paint_color_no_color_zone(sp):
    """Base color frame found, but no colorZone QToolButton inside."""
    spv = sp.make_qt_widget(
        widget_class="QFrame",
        object_name="SourceParametersView",
        children=[sp.make_qt_widget(
            widget_class="QLabel",
            object_name="dropzone_title",
            text="Base color",
        )],
    )
    mw = sp.make_qt_main_window(children=[spv])
    ctx = _ctx_with(sp, mw)
    assert ctx.get_paint_color() is None


@pytest.mark.parametrize("color", [
    (255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 64, 200), (0, 0, 0), (255, 255, 255),
])
def test_get_paint_color_samples_color_zone_pixel(sp, color):
    """Happy path: SourceParametersView -> Base color label -> colorZone
    QToolButton -> grab() -> pixelColor() -> (r, g, b) tuple."""
    color_zone = sp.make_qt_widget(
        widget_class="QToolButton",
        object_name="colorZone",
        paint_color=color,
    )
    spv = sp.make_qt_widget(
        widget_class="QFrame",
        object_name="SourceParametersView",
        children=[
            sp.make_qt_widget(
                widget_class="QLabel",
                object_name="dropzone_title",
                text="Base color",
            ),
            color_zone,
        ],
    )
    mw = sp.make_qt_main_window(children=[spv])
    ctx = _ctx_with(sp, mw)
    assert ctx.get_paint_color() == color


def test_get_paint_color_swallows_runtimeerror(sp):
    mw = sp.make_qt_widget(widget_class="QMainWindow", raise_on_find=True)
    ctx = _ctx_with(sp, mw)
    assert ctx.get_paint_color() is None


def test_get_paint_color_picks_matching_view_among_many(sp):
    """Several QFrames named SourceParametersView exist; only one has the
    Base color label. Verify we pick the right one."""
    wrong = sp.make_qt_widget(
        widget_class="QFrame",
        object_name="SourceParametersView",
        children=[sp.make_qt_widget(
            widget_class="QLabel", object_name="dropzone_title", text="Roughness",
        ), sp.make_qt_widget(
            widget_class="QToolButton", object_name="colorZone",
            paint_color=(99, 99, 99),
        )],
    )
    right = sp.make_qt_widget(
        widget_class="QFrame",
        object_name="SourceParametersView",
        children=[sp.make_qt_widget(
            widget_class="QLabel", object_name="dropzone_title", text="Base color",
        ), sp.make_qt_widget(
            widget_class="QToolButton", object_name="colorZone",
            paint_color=(11, 22, 33),
        )],
    )
    mw = sp.make_qt_main_window(children=[wrong, right])
    ctx = _ctx_with(sp, mw)
    assert ctx.get_paint_color() == (11, 22, 33)


# --- get_brush_material / get_brush_alpha ---

def test_get_brush_material_none_when_view_missing(sp):
    mw = sp.make_qt_main_window(children=[])
    ctx = _ctx_with(sp, mw)
    assert ctx.get_brush_material() is None


def test_get_brush_material_returns_dropzone_text(sp):
    """Material lives in materialModeParams (a QWidget), not in the alpha's
    MaskParametersView frame."""
    mmp = sp.make_material_mode_params(dropzone_text="Worn Leather")
    mw = sp.make_qt_main_window(children=[mmp])
    ctx = _ctx_with(sp, mw)
    assert ctx.get_brush_material() == "Worn Leather"


def test_get_brush_alpha_uniform_color_filtered_to_none(sp):
    """The 'uniform color' alpha is the default-unset state in Painter and is
    suppressed (returns None) rather than surfaced as
    'Brush Alpha: uniform color'. Regression test: an earlier refactor briefly
    compared the QLabel widget object to the string instead of its .text(),
    which silently disabled the filter."""
    mpv = sp.make_mask_parameters_view(dropzone_text="uniform color")
    mw = sp.make_qt_main_window(children=[mpv])
    ctx = _ctx_with(sp, mw)
    assert ctx.get_brush_alpha() is None


def test_get_brush_alpha_returns_prefixed_dropzone_text(sp):
    """get_brush_alpha now self-formats with a 'Brush Alpha: ' prefix so the
    return value is display-ready for use as a state/details slot."""
    mpv = sp.make_mask_parameters_view(dropzone_text="Soft brush 01")
    mw = sp.make_qt_main_window(children=[mpv])
    ctx = _ctx_with(sp, mw)
    assert ctx.get_brush_alpha() == "Brush Alpha: Soft brush 01"


def test_get_brush_material_runtimeerror_returns_none(sp):
    mw = sp.make_qt_widget(widget_class="QMainWindow", raise_on_find=True)
    ctx = _ctx_with(sp, mw)
    assert ctx.get_brush_material() is None


# ---------------------------------------------------------------------------
# SPPlugin: update_small_icon / update_large_icon / callbacks / update_details
# ---------------------------------------------------------------------------

from substance_painter_presence.painter_presence import SP_PLUGIN  # noqa: E402


@pytest.fixture
def sp_plugin_clean():
    """Snapshot/restore SP_PLUGIN.prefs and session fields the small-icon
    tests touch. Avoids cross-test pollution from module-level singleton state."""
    snap = (
        SP_PLUGIN.prefs.displaySmallIcon,
        SP_PLUGIN.prefs.displayVersion,
        SP_PLUGIN.prefs.enableColoredIcons,
        SP_PLUGIN.prefs.enableDetails,
        SP_PLUGIN.prefs.resetTimer,
        SP_PLUGIN.session.is_rendering,
        SP_PLUGIN.session.rendered_frames,
        SP_PLUGIN.session.start_time,
        SP_PLUGIN.details.small_icon,
        SP_PLUGIN.details.small_icon_text,
        SP_PLUGIN.details.large_icon_text,
        SP_PLUGIN.details.details_text,
    )
    yield SP_PLUGIN
    (SP_PLUGIN.prefs.displaySmallIcon,
     SP_PLUGIN.prefs.displayVersion,
     SP_PLUGIN.prefs.enableColoredIcons,
     SP_PLUGIN.prefs.enableDetails,
     SP_PLUGIN.prefs.resetTimer,
     SP_PLUGIN.session.is_rendering,
     SP_PLUGIN.session.rendered_frames,
     SP_PLUGIN.session.start_time,
     SP_PLUGIN.details.small_icon,
     SP_PLUGIN.details.small_icon_text,
     SP_PLUGIN.details.large_icon_text,
     SP_PLUGIN.details.details_text) = snap


def test_update_small_icon_disabled_pref(sp, sp_plugin_clean):
    sp_plugin_clean.prefs.displaySmallIcon = False
    sp_plugin_clean.session.is_rendering = False
    ctx = _ctx_with(sp, sp.make_qt_main_window())
    sp_plugin_clean.update_small_icon(ctx)
    assert sp_plugin_clean.details.small_icon is None
    assert sp_plugin_clean.details.small_icon_text == ""


def test_update_small_icon_rendering_uses_baking_icon(sp, sp_plugin_clean):
    sp_plugin_clean.prefs.displaySmallIcon = True
    sp_plugin_clean.session.is_rendering = True
    ctx = _ctx_with(sp, sp.make_qt_main_window())
    sp_plugin_clean.update_small_icon(ctx)
    assert sp_plugin_clean.details.small_icon == "baking"


def test_update_small_icon_paint_tool_sets_colored_icon(sp, sp_plugin_clean):
    sp_plugin_clean.prefs.displaySmallIcon = True
    sp_plugin_clean.prefs.enableColoredIcons = True
    sp_plugin_clean.session.is_rendering = False

    color_zone = sp.make_qt_widget(
        widget_class="QToolButton", object_name="colorZone", paint_color=(255, 0, 0),
    )
    spv = sp.make_qt_widget(
        widget_class="QFrame", object_name="SourceParametersView",
        children=[
            sp.make_qt_widget(widget_class="QLabel", object_name="dropzone_title",
                              text="Base color"),
            color_zone,
        ],
    )
    toolbar = sp.make_toolbar(buttons=[sp.make_tool_button("Paint", checked=True)])
    mw = sp.make_qt_main_window(children=[toolbar, spv])
    ctx = _ctx_with(sp, mw)

    sp_plugin_clean.update_small_icon(ctx)
    assert sp_plugin_clean.details.small_icon is not None
    assert sp_plugin_clean.details.small_icon.startswith("paint_c")
    out = sp_plugin_clean.details.small_icon_text
    assert "Painting in " in out
    assert "#FF0000" in out
    # No alpha widget present → tooltip should NOT include the alpha suffix.
    assert "Alpha:" not in out


def test_update_small_icon_colored_paint_tooltip_excludes_alpha(
    sp, sp_plugin_clean
):
    """The colored-icon tooltip is now intentionally short — just
    'Painting in <name> (#HEX)' — even when an alpha widget is present.
    Alpha is surfaced via its own details/state slot instead."""
    sp_plugin_clean.prefs.displaySmallIcon = True
    sp_plugin_clean.prefs.enableColoredIcons = True
    sp_plugin_clean.session.is_rendering = False

    # make_source_parameters_view hardcodes paint_color=(255, 0, 0) — matches
    # the #FF0000 assertion below.
    spv = sp.make_source_parameters_view()
    mpv = sp.make_mask_parameters_view(dropzone_text="Soft Brush")
    toolbar = sp.make_toolbar(buttons=[sp.make_tool_button("Paint", checked=True)])
    mw = sp.make_qt_main_window(children=[toolbar, spv, mpv])
    ctx = _ctx_with(sp, mw)

    sp_plugin_clean.update_small_icon(ctx)
    out = sp_plugin_clean.details.small_icon_text
    assert "Alpha" not in out
    assert "#FF0000" in out
    assert out.endswith(")")


def test_update_small_icon_physical_paint_uses_pphys_prefix(sp, sp_plugin_clean):
    sp_plugin_clean.prefs.displaySmallIcon = True
    sp_plugin_clean.prefs.enableColoredIcons = True
    sp_plugin_clean.session.is_rendering = False

    color_zone = sp.make_qt_widget(
        widget_class="QToolButton", object_name="colorZone", paint_color=(0, 255, 0),
    )
    spv = sp.make_qt_widget(
        widget_class="QFrame", object_name="SourceParametersView",
        children=[
            sp.make_qt_widget(widget_class="QLabel", object_name="dropzone_title",
                              text="Base color"),
            color_zone,
        ],
    )
    toolbar = sp.make_toolbar(buttons=[
        sp.make_tool_button("Physical paint", checked=True),
    ])
    mw = sp.make_qt_main_window(children=[toolbar, spv])
    ctx = _ctx_with(sp, mw)

    sp_plugin_clean.update_small_icon(ctx)
    assert sp_plugin_clean.details.small_icon is not None
    assert sp_plugin_clean.details.small_icon.startswith("pphys_c")


def test_update_small_icon_non_paint_tool_uses_tool_name_icon(sp, sp_plugin_clean):
    """A non-Paint/Physical-paint tool falls through to the generic tool-icon
    branch: small_icon is the lowercased, underscored tool name; small_icon_text
    is the title-cased original."""
    sp_plugin_clean.prefs.displaySmallIcon = True
    sp_plugin_clean.prefs.enableColoredIcons = True
    sp_plugin_clean.session.is_rendering = False

    toolbar = sp.make_toolbar(buttons=[sp.make_tool_button("Eraser", checked=True)])
    mw = sp.make_qt_main_window(children=[toolbar])
    ctx = _ctx_with(sp, mw)

    sp_plugin_clean.update_small_icon(ctx)
    assert sp_plugin_clean.details.small_icon == "eraser"
    assert sp_plugin_clean.details.small_icon_text == "Eraser"


def test_update_small_icon_multi_word_tool_underscored(sp, sp_plugin_clean):
    """Multi-word tool name like 'Clone' or 'Projection' — verify the
    name->icon-key transform turns spaces into underscores."""
    sp_plugin_clean.prefs.displaySmallIcon = True
    sp_plugin_clean.prefs.enableColoredIcons = True
    sp_plugin_clean.session.is_rendering = False

    toolbar = sp.make_toolbar(buttons=[
        sp.make_tool_button("Clone (absolute source)", checked=True),
    ])
    mw = sp.make_qt_main_window(children=[toolbar])
    ctx = _ctx_with(sp, mw)

    sp_plugin_clean.update_small_icon(ctx)
    assert sp_plugin_clean.details.small_icon == "clone_(absolute_source)"


def test_update_small_icon_colored_disabled_falls_back_to_tool_icon(sp, sp_plugin_clean):
    """When enableColoredIcons is False the colored-icon flow is skipped and
    Paint resolves to the generic tool icon (not the colored palette icon)."""
    sp_plugin_clean.prefs.displaySmallIcon = True
    sp_plugin_clean.prefs.enableColoredIcons = False
    sp_plugin_clean.session.is_rendering = False

    toolbar = sp.make_toolbar(buttons=[sp.make_tool_button("Paint", checked=True)])
    mw = sp.make_qt_main_window(children=[toolbar])
    ctx = _ctx_with(sp, mw)

    sp_plugin_clean.update_small_icon(ctx)
    # 'paint' is the bare tool name, not 'paint_c...' (colored-palette icon).
    assert sp_plugin_clean.details.small_icon == "paint"


def test_update_small_icon_colored_disabled_paint_with_material_shows_painting_in(
    sp, sp_plugin_clean
):
    """When colored icons are off but the tool IS Paint AND a brush material
    drop-zone is present, the icon text becomes 'Painting in <mat>'
    (with optional ' (alpha)' suffix)."""
    sp_plugin_clean.prefs.displaySmallIcon = True
    sp_plugin_clean.prefs.enableColoredIcons = False
    sp_plugin_clean.session.is_rendering = False

    toolbar = sp.make_toolbar(buttons=[sp.make_tool_button("Paint", checked=True)])
    mmp = sp.make_material_mode_params(dropzone_text="Worn Leather")
    mw = sp.make_qt_main_window(children=[toolbar, mmp])
    ctx = _ctx_with(sp, mw)

    sp_plugin_clean.update_small_icon(ctx)
    assert sp_plugin_clean.details.small_icon == "paint"
    assert sp_plugin_clean.details.small_icon_text == "Painting in Worn Leather"


def test_update_small_icon_no_active_tool_clears_icon(sp, sp_plugin_clean):
    """If get_active_tool returns None (no toolbar, no checked button, etc.)
    we leave small_icon at None without crashing in the new branch."""
    sp_plugin_clean.prefs.displaySmallIcon = True
    sp_plugin_clean.prefs.enableColoredIcons = True
    sp_plugin_clean.session.is_rendering = False
    mw = sp.make_qt_main_window(children=[])  # no toolbar
    ctx = _ctx_with(sp, mw)
    sp_plugin_clean.update_small_icon(ctx)
    assert sp_plugin_clean.details.small_icon is None
    assert sp_plugin_clean.details.small_icon_text == ""


def test_update_small_icon_paint_tool_but_no_color(sp, sp_plugin_clean):
    """Paint is active but get_paint_color returns None (no SourceParametersView)
    — should leave small_icon as None rather than crash."""
    sp_plugin_clean.prefs.displaySmallIcon = True
    sp_plugin_clean.prefs.enableColoredIcons = True
    sp_plugin_clean.session.is_rendering = False

    toolbar = sp.make_toolbar(buttons=[sp.make_tool_button("Paint", checked=True)])
    mw = sp.make_qt_main_window(children=[toolbar])  # no SourceParametersView
    ctx = _ctx_with(sp, mw)

    sp_plugin_clean.update_small_icon(ctx)
    assert sp_plugin_clean.details.small_icon is None


# --- update_large_icon ---

def test_update_large_icon_with_version(sp, sp_plugin_clean):
    sp_plugin_clean.prefs.displayVersion = True
    sp.set_state(application_version="12.0.3")
    ctx = _ctx_with(sp, sp.make_qt_main_window())
    sp_plugin_clean.update_large_icon(ctx)
    assert "12.0.3" in sp_plugin_clean.details.large_icon_text
    assert "Adobe Substance Painter" in sp_plugin_clean.details.large_icon_text


def test_update_large_icon_without_version(sp, sp_plugin_clean):
    sp_plugin_clean.prefs.displayVersion = False
    ctx = _ctx_with(sp, sp.make_qt_main_window())
    sp_plugin_clean.update_large_icon(ctx)
    assert sp_plugin_clean.details.large_icon_text == "Adobe Substance Painter"


# --- callbacks ---

def test_on_file_open_resets_timer_when_pref_set(sp_plugin_clean):
    sp_plugin_clean.prefs.resetTimer = True
    sp_plugin_clean.session.start_time = 0.0
    sp_plugin_clean._on_file_open()
    assert sp_plugin_clean.session.start_time > 0.0


def test_on_file_open_skips_reset_when_pref_unset(sp_plugin_clean):
    sp_plugin_clean.prefs.resetTimer = False
    sp_plugin_clean.session.start_time = 12345.0
    sp_plugin_clean._on_file_open()
    assert sp_plugin_clean.session.start_time == 12345.0


def test_on_bake_start_sets_rendering(sp_plugin_clean):
    sp_plugin_clean.session.is_rendering = False
    sp_plugin_clean._on_bake_start()
    assert sp_plugin_clean.session.is_rendering is True


def test_on_bake_end_clears_rendering(sp_plugin_clean):
    sp_plugin_clean.session.is_rendering = True
    sp_plugin_clean._on_bake_end()
    assert sp_plugin_clean.session.is_rendering is False


def test_on_bake_update_records_progress(sp_plugin_clean):
    sp_plugin_clean._on_bake_update(0.5)
    assert sp_plugin_clean.session.rendered_frames == 50
    sp_plugin_clean._on_bake_update(0.0)
    assert sp_plugin_clean.session.rendered_frames == 0
    sp_plugin_clean._on_bake_update(1.0)
    assert sp_plugin_clean.session.rendered_frames == 100


# --- update_details override (rendering branch) ---

def test_update_details_rendering_branch_uses_bake_progress(sp, sp_plugin_clean):
    sp_plugin_clean.prefs.enableDetails = True
    sp_plugin_clean.session.is_rendering = True
    sp_plugin_clean.session.rendered_frames = 42
    sp.set_state(project_name="MyTextures")
    ctx = _ctx_with(sp, sp.make_qt_main_window())
    sp_plugin_clean.update_details(ctx)
    assert "Baking" in sp_plugin_clean.details.details_text
    assert "MyTextures" in sp_plugin_clean.details.details_text
    assert "42%" in sp_plugin_clean.details.details_text


# --- Additional None-edges in Painter Context ---

def test_get_active_layer_blend_mode_no_selection_returns_none(sp):
    """get_active_layer_blend_mode's empty-selection branch returns None.
    Exercises the `else: return None` at the bottom of the function."""
    stack = sp.make_stack(selected_nodes=[])
    ctx = SPContext(texture_sets=[], stack=stack, main_window=None)
    assert ctx.get_active_layer_blend_mode() is None


def test_find_named_with_none_parent_returns_none(sp):
    """_find_named's `if parent is None: return None` branch."""
    ctx = SPContext(texture_sets=[], stack=sp.make_stack(), main_window=None)
    # Pass None as parent directly — exercises the early return.
    assert ctx._find_named(None, object, "anything") is None


def test_get_brush_material_view_found_but_no_label_returns_none(sp):
    """MaskParametersView exists but has no dropzone_text QLabel inside —
    returns None instead of crashing."""
    mpv = sp.make_qt_widget(
        widget_class="QFrame",
        object_name="MaskParametersView",
        children=[],  # no QLabel
    )
    mw = sp.make_qt_main_window(children=[mpv])
    ctx = SPContext(texture_sets=[], stack=sp.make_stack(), main_window=mw)
    assert ctx.get_brush_material() is None


def test_get_brush_alpha_view_found_but_no_label_returns_none(sp):
    mpv = sp.make_qt_widget(
        widget_class="QFrame",
        object_name="MaskParametersView",
        children=[],
    )
    mw = sp.make_qt_main_window(children=[mpv])
    ctx = SPContext(texture_sets=[], stack=sp.make_stack(), main_window=mw)
    assert ctx.get_brush_alpha() is None


def test_get_brush_alpha_runtimeerror_returns_none(sp):
    """get_brush_alpha's RuntimeError catch."""
    mw = sp.make_qt_widget(widget_class="QMainWindow", raise_on_find=True)
    ctx = SPContext(texture_sets=[], stack=sp.make_stack(), main_window=mw)
    assert ctx.get_brush_alpha() is None


def test_update_details_not_rendering_delegates_to_super(sp, sp_plugin_clean):
    """When not rendering, update_details falls back to the base-class
    update_slot — exercises the else branch."""
    sp_plugin_clean.prefs.enableDetails = True
    sp_plugin_clean.prefs.detailsType = "project"
    sp_plugin_clean.prefs.customDetails = ""
    sp_plugin_clean.prefs.detailsCycle = False
    sp_plugin_clean.session.is_rendering = False
    sp.set_state(project_name="AnotherProject")
    ctx = _ctx_with(sp, sp.make_qt_main_window())
    sp_plugin_clean.update_details(ctx)
    assert "AnotherProject" in sp_plugin_clean.details.details_text


# ---------------------------------------------------------------------------
# Regression: get_brush_material and get_brush_alpha used to be implemented
# identically (both walked the same MaskParametersView -> dropzone_text path).
# The plugin now targets materialModeParams for the material drop-zone, so
# the two getters return independent values.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("widget,expected_alpha,expected_material", [
    ("alpha", "Brush Alpha: Soft Brush", None),
    ("material", None, "Worn Leather"),
])
def test_get_brush_material_and_alpha_target_distinct_widgets(
    sp, widget, expected_alpha, expected_material,
):
    """Each getter reads only its own drop-zone widget: with only the alpha
    view wired up, get_brush_material returns None (and vice versa)."""
    child = (sp.make_mask_parameters_view(dropzone_text="Soft Brush")
             if widget == "alpha"
             else sp.make_material_mode_params(dropzone_text="Worn Leather"))
    mw = sp.make_qt_main_window(children=[child])
    ctx = SPContext(texture_sets=[], stack=sp.make_stack(), main_window=mw)
    assert ctx.get_brush_alpha() == expected_alpha
    assert ctx.get_brush_material() == expected_material
