"""
Tests for SPContext (Designer plugin).

Designer's SPPlugin is class-based and instantiated at module load — the
fake's `sd.getContext()` etc. all return cooperating objects so import is
non-destructive.

Bugs flagged by docs cross-check, with regression tests marked
xfail(strict=True) so they pass-when-fixed:
  * package_name() falls back to "No package open" when SDPackage.getFilePath
    returns an empty string. Per the docs SDPackage exists at that point —
    the package is just unsaved. With a named graph, project_name() then
    produces the misleading "No package open | <graph>". See
    test_package_name_empty_path_calls_it_unsaved and
    test_project_name_unsaved_package_with_graph_no_misleading_combo.
"""
from __future__ import annotations
import pytest

# Important: import the plugin once at module top. This triggers SPPlugin
# instantiation which reaches into `sd.getContext().getSDApplication()...`
# — all of which the fake satisfies.
from designerpresence import SPContext, SP_PLUGIN  # noqa: F401


# ---------------------------------------------------------------------------
# capture()
# ---------------------------------------------------------------------------

def test_capture_returns_none_when_no_graph(sd):
    sd.set_state(current_graph=None)
    assert SPContext.capture() is None


def test_capture_returns_none_when_graph_has_no_package(sd):
    g = sd.make_graph(package=None)
    sd.set_state(current_graph=g)
    assert SPContext.capture() is None


def test_capture_returns_context_with_graph_and_package(sd):
    pkg = sd.make_package(file_path="/projects/Fabrics.sbs")
    g = sd.make_graph(package=pkg)
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx is not None
    assert ctx.graph is g
    assert ctx.package is pkg


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def test_package_name_from_path(sd):
    pkg = sd.make_package(file_path="/projects/Fabrics.sbs")
    g = sd.make_graph(package=pkg)
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx.package_name() == "Fabrics.sbs"


def test_package_name_empty_path_calls_it_unsaved(sd):
    pkg = sd.make_package(file_path="")
    g = sd.make_graph(package=pkg)
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    out = ctx.package_name()
    assert "No package open" not in out
    assert "unsaved" in out.lower() or "untitled" in out.lower()


def test_graph_name_from_annotation(sd):
    pkg = sd.make_package(file_path="/projects/Fabrics.sbs")
    g = sd.make_graph(
        package=pkg,
        annotations={"identifier": sd.make_value_string("Wool")},
    )
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx.graph_name() == "Graph: Wool"


def test_graph_name_missing_annotation_returns_unsaved_string(sd):
    """No 'identifier' annotation -> the graph is still open but unnamed; surface
    it as 'Unsaved graph' rather than returning None (which would let the slot
    fall back to a different display type and hide that there IS a graph)."""
    pkg = sd.make_package(file_path="/projects/Fabrics.sbs")
    g = sd.make_graph(package=pkg, annotations={})
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx.graph_name() == "Unsaved graph"


def test_graph_name_replaces_underscores_when_pref_set(sd):
    """SPSettings.replaceUnderscores=True swaps _ for space in the displayed
    name. Pins the on-by-default behavior."""
    SP_PLUGIN.prefs.replaceUnderscores = True
    try:
        pkg = sd.make_package(file_path="/projects/Fabrics.sbs")
        g = sd.make_graph(
            package=pkg,
            annotations={"identifier": sd.make_value_string("worn_wool_v2")},
        )
        sd.set_state(current_graph=g)
        ctx = SPContext.capture()
        assert ctx.graph_name() == "Graph: worn wool v2"
    finally:
        SP_PLUGIN.prefs.replaceUnderscores = True  # field default


def test_graph_name_preserves_underscores_when_pref_unset(sd):
    SP_PLUGIN.prefs.replaceUnderscores = False
    try:
        pkg = sd.make_package(file_path="/projects/Fabrics.sbs")
        g = sd.make_graph(
            package=pkg,
            annotations={"identifier": sd.make_value_string("worn_wool_v2")},
        )
        sd.set_state(current_graph=g)
        ctx = SPContext.capture()
        assert ctx.graph_name() == "Graph: worn_wool_v2"
    finally:
        SP_PLUGIN.prefs.replaceUnderscores = True


# ---------------------------------------------------------------------------
# Node info
# ---------------------------------------------------------------------------

def test_node_name_returns_none_when_no_selection(sd):
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(package=pkg)
    sd.set_state(current_graph=g, selected_nodes=None)
    ctx = SPContext.capture()
    assert ctx.node_name() is None


def test_node_name_returns_none_when_multi_selection(sd):
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(package=pkg)
    sel = sd.make_array(items=[sd.make_node("Blend"), sd.make_node("Blur")])
    sd.set_state(current_graph=g, selected_nodes=sel)
    ctx = SPContext.capture()
    assert ctx.node_name() is None


def test_node_name_returns_label_when_single_selection(sd):
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(package=pkg)
    sel = sd.make_array(items=[sd.make_node("Uniform color")])
    sd.set_state(current_graph=g, selected_nodes=sel)
    ctx = SPContext.capture()
    assert ctx.node_name() == "Uniform color"


# ---------------------------------------------------------------------------
# Counts (nodes, outputs, resources)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n, expected", [
    (0, "0 nodes"),
    (1, "1 node"),
    (12, "12 nodes"),
])
def test_num_nodes(sd, n, expected):
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(package=pkg, nodes=[sd.make_node() for _ in range(n)])
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx.num_nodes() == expected


@pytest.mark.parametrize("n, expected", [
    (0, "0 output nodes"),
    (1, "1 output node"),
    (4, "4 output nodes"),
])
def test_num_output_nodes(sd, n, expected):
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(package=pkg, output_nodes=[sd.make_node() for _ in range(n)])
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx.num_output_nodes() == expected


def test_resource_count_excludes_subgraphs_and_folders(sd):
    """SDSBSCompGraph and SDResourceFolder don't count as resources."""
    pkg = sd.make_package(file_path="/a.sbs", resources=[
        sd.make_resource("SDResourceBitmap"),
        sd.make_resource("SDResourceBitmap"),
        sd.make_resource("SDSBSCompGraph"),  # excluded
        sd.make_resource("SDResourceFolder"),  # excluded
        sd.make_resource("SDResourceLight"),
    ])
    g = sd.make_graph(package=pkg)
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    # 2 bitmaps + 1 light = 3 countable resources
    assert ctx.resource_count() == "3 resources"


# ---------------------------------------------------------------------------
# parent_size / output_resolution (only comp graphs)
# ---------------------------------------------------------------------------

def test_parent_size_none_for_non_comp_graph(sd):
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(package=pkg, is_comp_graph=False)
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx.parent_size() is None


def test_parent_size_for_comp_graph(sd):
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(
        package=pkg, is_comp_graph=True, default_parent_size=sd.make_int2(1024, 1024)
    )
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx.parent_size() == (1024, 1024)


def test_output_resolution_default(sd):
    """outputsize property values are powers-of-2 exponents above parent size."""
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(
        package=pkg,
        is_comp_graph=True,
        default_parent_size=sd.make_int2(2048, 2048),
        input_properties={"$outputsize": sd.make_value_int2(0, 0)},
    )
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    # 2048 * 2^0 = 2048
    assert ctx.output_resolution() == "Export resolution: 2048x2048"


def test_output_resolution_scaled(sd):
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(
        package=pkg,
        is_comp_graph=True,
        default_parent_size=sd.make_int2(1024, 1024),
        input_properties={"$outputsize": sd.make_value_int2(1, 2)},
    )
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    # 1024 * 2^1 = 2048; 1024 * 2^2 = 4096
    assert ctx.output_resolution() == "Export resolution: 2048x4096"


def test_output_resolution_none_when_property_missing(sd):
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(
        package=pkg, is_comp_graph=True, input_properties={},  # no $outputsize
    )
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx.output_resolution() is None


# ---------------------------------------------------------------------------
# material_model + color_space
# ---------------------------------------------------------------------------

def test_material_model_returns_formatted(sd):
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(
        package=pkg, annotations={"material_model": sd.make_value_string("OpenPBR v1.1")}
    )
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx.material_model() == "Material model: OpenPBR v1.1"


def test_material_model_undefined_returns_none(sd):
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(
        package=pkg, annotations={"material_model": sd.make_value_string("Undefined")}
    )
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx.material_model() is None


def test_material_model_missing_annotation_returns_none(sd):
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(package=pkg, annotations={})
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx.material_model() is None


def test_color_space_returns_formatted(sd):
    sd.set_state(color_management_engine_name="ACES")
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(package=pkg)
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx.color_space() == "Color space: ACES"


def test_color_space_none_when_engine_unavailable(sd):
    sd.set_state(color_management_engine_is_none=True)
    pkg = sd.make_package(file_path="/a.sbs")
    g = sd.make_graph(package=pkg)
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx.color_space() is None


# ---------------------------------------------------------------------------
# SPPlugin: update_small_icon / update_large_icon / on_file_open
# ---------------------------------------------------------------------------


@pytest.fixture
def designer_plugin_clean():
    """Snapshot/restore SP_PLUGIN.prefs and details fields between tests."""
    snap = (
        SP_PLUGIN.prefs.displaySmallIcon,
        SP_PLUGIN.prefs.displayVersion,
        SP_PLUGIN.prefs.resetTimer,
        SP_PLUGIN.session.start_time,
        SP_PLUGIN.details.small_icon,
        SP_PLUGIN.details.small_icon_text,
        SP_PLUGIN.details.large_icon_text,
    )
    yield SP_PLUGIN
    (SP_PLUGIN.prefs.displaySmallIcon,
     SP_PLUGIN.prefs.displayVersion,
     SP_PLUGIN.prefs.resetTimer,
     SP_PLUGIN.session.start_time,
     SP_PLUGIN.details.small_icon,
     SP_PLUGIN.details.small_icon_text,
     SP_PLUGIN.details.large_icon_text) = snap


def _designer_ctx_with_selected_node(sd, label):
    """Helper: build an SPContext whose selected node has the given definition label."""
    pkg = sd.make_package(file_path="/p.sbs")
    g = sd.make_graph(package=pkg)
    sd.set_state(
        current_graph=g,
        selected_nodes=sd.make_array(items=[sd.make_node(label)]),
    )
    return SPContext.capture()


def test_update_small_icon_disabled_pref(sd, designer_plugin_clean):
    designer_plugin_clean.prefs.displaySmallIcon = False
    ctx = _designer_ctx_with_selected_node(sd, "blend")
    designer_plugin_clean.update_small_icon(ctx)
    assert designer_plugin_clean.details.small_icon is None
    assert designer_plugin_clean.details.small_icon_text == ""


def test_update_small_icon_no_selection_clears(sd, designer_plugin_clean):
    """When node_name returns None, both icon and text reset to ''."""
    designer_plugin_clean.prefs.displaySmallIcon = True
    pkg = sd.make_package(file_path="/p.sbs")
    g = sd.make_graph(package=pkg)
    sd.set_state(current_graph=g, selected_nodes=None)
    ctx = SPContext.capture()
    designer_plugin_clean.update_small_icon(ctx)
    assert designer_plugin_clean.details.small_icon is None
    assert designer_plugin_clean.details.small_icon_text == ""


@pytest.mark.parametrize("label, expected_icon", [
    ("blend", "blend"),
    ("blur", "blur"),
    ("Uniform color", "uniform_color"),  # spaces -> underscores
    ("Pixel Processor", "pixel_processor"),
    ("Gradient (dynamic)", "gradient_dynamic"),  # parens stripped
    ("Channels Shuffle", "channels_shuffle"),
])
def test_update_small_icon_atomic_node_sets_icon(sd, designer_plugin_clean,
                                                  label, expected_icon):
    designer_plugin_clean.prefs.displaySmallIcon = True
    ctx = _designer_ctx_with_selected_node(sd, label)
    designer_plugin_clean.update_small_icon(ctx)
    assert designer_plugin_clean.details.small_icon == expected_icon
    assert designer_plugin_clean.details.small_icon_text == label


def test_update_small_icon_non_atomic_node_no_icon(sd, designer_plugin_clean):
    """A node not in the atomic_nodes set leaves small_icon at None."""
    designer_plugin_clean.prefs.displaySmallIcon = True
    ctx = _designer_ctx_with_selected_node(sd, "Some Custom Subgraph")
    designer_plugin_clean.update_small_icon(ctx)
    assert designer_plugin_clean.details.small_icon is None


def test_update_large_icon_with_version(sd, designer_plugin_clean):
    designer_plugin_clean.prefs.displayVersion = True
    sd.set_state(application_version="16.0.1")
    pkg = sd.make_package(file_path="/p.sbs")
    g = sd.make_graph(package=pkg)
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    designer_plugin_clean.update_large_icon(ctx)
    assert "16.0.1" in designer_plugin_clean.details.large_icon_text
    assert "Adobe Substance 3D Designer" in designer_plugin_clean.details.large_icon_text


def test_update_large_icon_without_version(sd, designer_plugin_clean):
    designer_plugin_clean.prefs.displayVersion = False
    pkg = sd.make_package(file_path="/p.sbs")
    g = sd.make_graph(package=pkg)
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    designer_plugin_clean.update_large_icon(ctx)
    assert designer_plugin_clean.details.large_icon_text == "Adobe Substance 3D Designer"


def test_on_file_open_resets_timer_when_pref_set(sd, designer_plugin_clean):
    designer_plugin_clean.prefs.resetTimer = True
    designer_plugin_clean.session.start_time = 0.0
    designer_plugin_clean.on_file_open()
    assert designer_plugin_clean.session.start_time > 0.0


def test_on_file_open_preserves_timer_when_pref_unset(sd, designer_plugin_clean):
    designer_plugin_clean.prefs.resetTimer = False
    designer_plugin_clean.session.start_time = 12345.0
    designer_plugin_clean.on_file_open()
    assert designer_plugin_clean.session.start_time == 12345.0


# ---------------------------------------------------------------------------
# None-path branches (capture, project_name, node_name, output_resolution)
# ---------------------------------------------------------------------------

def test_capture_returns_none_when_uimgr_is_none(monkeypatch):
    """If the global SP_PLUGIN's uimgr happens to be None at capture time,
    return None. We monkeypatch the plugin's uimgr to simulate that."""
    monkeypatch.setattr(SP_PLUGIN, "uimgr", None)
    assert SPContext.capture() is None

def test_node_name_returns_none_when_definition_is_none(sd):
    """A single-selected node whose getDefinition() returns None should make
    node_name return None rather than crash on getLabel()."""
    pkg = sd.make_package(file_path="/p.sbs")
    g = sd.make_graph(package=pkg)
    # Build a node whose _definition is None.
    from sd import _Node
    node_with_no_def = _Node(_definition=None)
    sd.set_state(current_graph=g,
                 selected_nodes=sd.make_array(items=[node_with_no_def]))
    ctx = SPContext.capture()
    assert ctx.node_name() is None


def test_output_resolution_none_when_parent_size_none(sd):
    """parent_size returns None for non-comp graphs; output_resolution should
    short-circuit and return None too."""
    pkg = sd.make_package(file_path="/p.sbs")
    g = sd.make_graph(package=pkg, is_comp_graph=False)
    sd.set_state(current_graph=g)
    ctx = SPContext.capture()
    assert ctx.output_resolution() is None
