"""
Tests for C4DContext, C4DPresencePrefs, and the small set of update
functions in c4d_presence.pyp.

The plugin lives at dist/c4d_presence/c4d_presence.pyp and is loaded
via the `c4dp` fixture (conftest.py uses SourceFileLoader to handle
the .pyp extension). Per-test state is configured by setting fields
on the fake document the plugin's BaseDocument exposes — e.g.

    c4d_mod.set_state(active_doc=c4d_mod.make_document(
        name="scene.c4d",
        objects=[c4d_mod.make_object(type_id=c4d_mod.Opolygon)],
    ))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_mesh_count() == "1 mesh"
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Module-level wiring: importing the plugin should succeed against the fake.
# ---------------------------------------------------------------------------


def test_plugin_module_imports(c4dp):
    """Importing c4d_presence triggers C4DP_PREFS / C4DP_SESSION /
    C4DP_UPDATE_DETAILS / C4DP_CLIENT construction. If anything in the fake
    is missing the import itself crashes; getting here means it didn't."""
    assert c4dp.C4DP_PREFS is not None
    assert c4dp.C4DP_SESSION is not None
    assert c4dp.C4DP_UPDATE_DETAILS is not None
    assert c4dp.C4DP_CLIENT is not None


# ---------------------------------------------------------------------------
# C4DP IntEnum — values must match c4d_presence.h.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name, expected", [
    ("C4DPRESENCE_MAIN_GROUP", 999),
    ("C4DPRESENCE_GENERAL", 1000),
    ("C4DPRESENCE_GENERALENABLE", 1001),
    ("C4DPRESENCE_DETAILS", 2000),
    ("C4DPRESENCE_DTYPE", 2002),
    ("C4DPRESENCE_STATE", 3000),
    ("C4DPRESENCE_STYPE", 3002),
    ("C4DPRESENCE_RENDERING", 4000),
    ("C4DPRESENCE_BUTTONS", 5000),
    ("C4DPRESENCE_B1", 5100),
    ("C4DPRESENCE_B2", 5200),
    ("C4DPRESENCE_RESETALL", 6000),
    ("C4DPRESENCE_INFODOC", 0),
])
def test_c4dp_enum_values_match_header(c4dp, name, expected):
    """The Python enum is the source of defaults that get written into
    the world container; its values must agree with c4d_presence.h so
    the .res file's CYCLE entries resolve to the same ints."""
    assert int(getattr(c4dp.C4DP, name)) == expected


@pytest.mark.parametrize("name, expected", [
    ("C4DPRESENCE_INFOOBJ", 1),
    ("C4DPRESENCE_INFOPLY", 2),
    ("C4DPRESENCE_INFOGEN", 3),
    ("C4DPRESENCE_INFOEFF", 4),
    ("C4DPRESENCE_INFOLIG", 5),
    ("C4DPRESENCE_INFOCAM", 6),
    ("C4DPRESENCE_INFOMAT", 7),
    ("C4DPRESENCE_INFOTEX", 8),
    ("C4DPRESENCE_INFOFRM", 9),
])
def test_c4dp_info_values_match_header(c4dp, name, expected):
    """Pinned regression: the INFO* IntEnum members were originally `auto()`
    after C4DPRESENCE_INFODOC=0, but auto() picks max(prior_values)+1 and
    saw C4DPRESENCE_RESETALL=6000, so INFOOBJ..INFOFRM landed at 6001..6009
    instead of 1..9. That meant the C4D cycle (which writes 1..9 to the
    world container) couldn't be mapped back to the Python display-type
    keys. Fixed by giving each member an explicit value."""
    assert int(getattr(c4dp.C4DP, name)) == expected


def test_set_dparameter_dtype_int_9_maps_to_frame(c4d_mod, c4dp):
    """End-to-end: picking 'Current frame' in the cycle (int 9) should
    flow through SetDParameter -> _write_pref -> _C4D_INFOTYPE_MAP and
    leave C4DP_PREFS.detailsType == 'frame'. This was broken before the
    INFO* fix."""
    prefs_instance = c4dp.C4DPresencePrefs()
    desc = c4d_mod.DescID(c4d_mod.DescLevel(
        int(c4dp.C4DP.C4DPRESENCE_DTYPE), c4d_mod.DTYPE_LONG, 0,
    ))
    prefs_instance.SetDParameter(node=None, id=desc, t_data=9, flags=0)
    assert c4dp.C4DP_PREFS.detailsType == "frame"


# ---------------------------------------------------------------------------
# C4DContext.capture()
# ---------------------------------------------------------------------------


def test_capture_returns_context_with_document(c4d_mod, c4dp):
    doc = c4d_mod.make_document(name="capture.c4d")
    c4d_mod.set_state(active_doc=doc)
    ctx = c4dp.C4DContext.capture()
    assert ctx.document is doc


def test_capture_walks_object_hierarchy(c4d_mod, c4dp):
    """_walk_objects descends GetDown() and follows GetNext() sibling chains,
    so a root with two children (each having one grandchild) yields six
    total objects (2 roots + 2 children + 2 grandchildren)."""
    grandchild_a = c4d_mod.make_object(name="ga")
    grandchild_b = c4d_mod.make_object(name="gb")
    child_a = c4d_mod.make_object(name="ca", children=[grandchild_a])
    child_b = c4d_mod.make_object(name="cb", children=[grandchild_b])
    root_a = c4d_mod.make_object(name="ra", children=[child_a])
    root_b = c4d_mod.make_object(name="rb", children=[child_b])
    c4d_mod.set_state(active_doc=c4d_mod.make_document(objects=[root_a, root_b]))
    ctx = c4dp.C4DContext.capture()
    names = [o.GetName() for o in ctx.objects]
    assert sorted(names) == ["ca", "cb", "ga", "gb", "ra", "rb"]


# ---------------------------------------------------------------------------
# Document name / path / file size
# ---------------------------------------------------------------------------


def test_get_document_name(c4d_mod, c4dp):
    c4d_mod.set_state(active_doc=c4d_mod.make_document(name="fancy.c4d"))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_document_name() == "fancy.c4d"


def test_get_file_size_none_when_path_empty(c4d_mod, c4dp):
    c4d_mod.set_state(active_doc=c4d_mod.make_document(name="x.c4d", path=""))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_file_size() is None


def test_get_file_size_none_when_file_missing(c4d_mod, c4dp, tmp_path):
    """Path is set but the actual file doesn't exist on disk."""
    c4d_mod.set_state(active_doc=c4d_mod.make_document(
        name="ghost.c4d", path=str(tmp_path),
    ))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_file_size() is None


def test_get_file_size_returns_formatted_string(c4d_mod, c4dp, tmp_path):
    """Write a small file and check that get_file_size returns the formatted
    string from get_file_size_str (units present)."""
    (tmp_path / "real.c4d").write_bytes(b"x" * 2048)
    c4d_mod.set_state(active_doc=c4d_mod.make_document(
        name="real.c4d", path=str(tmp_path),
    ))
    ctx = c4dp.C4DContext.capture()
    out = ctx.get_file_size()
    assert out is not None
    assert "KB" in out or "B" in out


# ---------------------------------------------------------------------------
# Object counts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n, expected", [
    (0, "0 objects"), (1, "1 object"), (5, "5 objects"),
])
def test_get_object_count(c4d_mod, c4dp, n, expected):
    objs = [c4d_mod.make_object(name=f"o{i}") for i in range(n)]
    c4d_mod.set_state(active_doc=c4d_mod.make_document(objects=objs))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_object_count() == expected


@pytest.mark.parametrize("n, expected", [
    (0, "0 meshes"), (1, "1 mesh"), (3, "3 meshes"),
])
def test_get_mesh_count_uses_es_plural(c4d_mod, c4dp, n, expected):
    """get_mesh_count passes postfix='es' to plural so it produces meshes."""
    objs = [c4d_mod.make_object(type_id=c4d_mod.Opolygon) for _ in range(n)]
    c4d_mod.set_state(active_doc=c4d_mod.make_document(objects=objs))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_mesh_count() == expected


def test_get_mesh_count_only_polygons(c4d_mod, c4dp):
    """Non-polygon types must not count toward the mesh count."""
    objs = [
        c4d_mod.make_object(type_id=c4d_mod.Opolygon),
        c4d_mod.make_object(type_id=c4d_mod.Olight),
        c4d_mod.make_object(type_id=c4d_mod.Ocamera),
    ]
    c4d_mod.set_state(active_doc=c4d_mod.make_document(objects=objs))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_mesh_count() == "1 mesh"


def test_get_cam_count_includes_native_and_rs(c4d_mod, c4dp):
    """Both c4d.Ocamera and c4d.Orscamera count as cameras."""
    objs = [
        c4d_mod.make_object(type_id=c4d_mod.Ocamera),
        c4d_mod.make_object(type_id=c4d_mod.Orscamera),
        c4d_mod.make_object(type_id=c4d_mod.Opolygon),  # not a cam
    ]
    c4d_mod.set_state(active_doc=c4d_mod.make_document(objects=objs))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_cam_count() == "2 cameras"


def test_get_light_count_uses_lights_set(c4d_mod, c4dp):
    """get_light_count counts anything whose GetType() is in _LIGHTS."""
    objs = [
        c4d_mod.make_object(type_id=c4d_mod.Olight),
        c4d_mod.make_object(type_id=c4d_mod.Osky),
        c4d_mod.make_object(type_id=c4d_mod.Oenvironment),
        c4d_mod.make_object(type_id=c4d_mod.Opolygon),  # not a light
    ]
    c4d_mod.set_state(active_doc=c4d_mod.make_document(objects=objs))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_light_count() == "3 lights"


def test_get_light_count_octane_null_with_light_name(c4d_mod, c4dp):
    """Octane lights are nulls (type_id 5140) whose GetTypeName() is 'Light'.
    The plugin special-cases that pair as a light."""
    objs = [
        c4d_mod.make_object(type_id=5140, type_name="Light"),
        c4d_mod.make_object(type_id=5140, type_name="Null"),  # nope
    ]
    c4d_mod.set_state(active_doc=c4d_mod.make_document(objects=objs))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_light_count() == "1 light"


def test_get_mograph_generator_count(c4d_mod, c4dp):
    objs = [
        c4d_mod.make_object(type_id=c4d_mod.Omgcloner),
        c4d_mod.make_object(type_id=c4d_mod.Omgmatrix),
        c4d_mod.make_object(type_id=c4d_mod.Opolygon),  # not a gen
    ]
    c4d_mod.set_state(active_doc=c4d_mod.make_document(objects=objs))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_mograph_generator_count() == "2 MoGraph generators"


def test_get_mograph_effector_count(c4d_mod, c4dp):
    objs = [
        c4d_mod.make_object(type_id=c4d_mod.Omgplain),
        c4d_mod.make_object(type_id=c4d_mod.Opolygon),  # not an eff
    ]
    c4d_mod.set_state(active_doc=c4d_mod.make_document(objects=objs))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_mograph_effector_count() == "1 MoGraph effector"


@pytest.mark.parametrize("n, expected", [
    (0, "0 materials"), (1, "1 material"), (4, "4 materials"),
])
def test_get_mat_count(c4d_mod, c4dp, n, expected):
    c4d_mod.set_state(active_doc=c4d_mod.make_document(
        materials=[object() for _ in range(n)],
    ))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_mat_count() == expected


@pytest.mark.parametrize("n, expected", [
    (0, "0 textures"), (1, "1 texture"), (3, "3 textures"),
])
def test_get_tex_count(c4d_mod, c4dp, n, expected):
    c4d_mod.set_state(active_doc=c4d_mod.make_document(
        textures=[object() for _ in range(n)],
    ))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_tex_count() == expected


# ---------------------------------------------------------------------------
# Color / time / fps / resolution
# ---------------------------------------------------------------------------


def test_get_color_info_formats_spaces(c4d_mod, c4dp):
    """GetActiveOcioColorSpacesNames returns (config, display, view) — the
    plugin builds 'display (view)' from indices [1] and [2]."""
    c4d_mod.set_state(active_doc=c4d_mod.make_document(
        color_spaces=("ACES 1.3", "sRGB", "scene-linear Rec.709"),
    ))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_color_info() == "sRGB (scene-linear Rec.709)"


def test_get_current_frame_uses_time_and_fps(c4d_mod, c4dp):
    c4d_mod.set_state(active_doc=c4d_mod.make_document(current_time=42, fps=30))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_current_frame() == "Frame 42 (30fps)"


def test_get_fps(c4d_mod, c4dp):
    c4d_mod.set_state(active_doc=c4d_mod.make_document(fps=60))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_fps() == 60


# ---------------------------------------------------------------------------
# Active object
# ---------------------------------------------------------------------------


def test_get_active_object_none_when_unset(c4d_mod, c4dp):
    c4d_mod.set_state(active_doc=c4d_mod.make_document(active_object=None))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_active_object() is None


def test_get_active_object_returns_prefixed_name(c4d_mod, c4dp):
    obj = c4d_mod.make_object(name="Cube")
    c4d_mod.set_state(active_doc=c4d_mod.make_document(active_object=obj))
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_active_object() == "Active: Cube"


# ---------------------------------------------------------------------------
# Version string
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ver, expected", [
    (20262, "2026.2"),     # year + nonzero release
    (202621, "2026.2.1"),   # multi-digit release
    (2026301, "2026.3.1"),
    (20262000, "2026.2"),  # trailing zeros stripped
])
def test_get_version_str(c4d_mod, c4dp, ver, expected):
    c4d_mod.set_state(c4d_version=ver)
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_version_str() == expected


def test_get_version_str_release_zero_does_not_hang(c4d_mod, c4dp):
    """Regression: release=0 (e.g. version 20260) used to enter an
    infinite loop in `while release % 10 == 0: release //= 10` because
    0 // 10 stays 0. Now guarded by a `release > 0` check."""
    c4d_mod.set_state(c4d_version=20260)
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_version_str() == "2026.0"


# ---------------------------------------------------------------------------
# GPU / render engine
# ---------------------------------------------------------------------------


def test_get_gpu_str_returns_machine_value(c4d_mod, c4dp):
    """GetMachineFeatures() returns a BaseContainer; the plugin reads
    bc[DRAWPORT_RENDERER_NAME]."""
    bc = c4d_mod.BaseContainer()
    bc[c4d_mod.DRAWPORT_RENDERER_NAME] = "NVIDIA RTX 4090"
    c4d_mod.set_state(machine_features=bc)
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_gpu_str() == "NVIDIA RTX 4090"


def test_get_gpu_str_returns_none_on_runtime_error(c4d_mod, c4dp):
    c4d_mod.set_state(machine_features_raises=True)
    ctx = c4dp.C4DContext.capture()
    assert ctx.get_gpu_str() is None


# ---------------------------------------------------------------------------
# c4d_update_large_icon
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_details(c4dp):
    """Snapshot/restore the four update-details fields used by these tests
    so a failure in one doesn't leak into the next."""
    snap = (
        c4dp.C4DP_UPDATE_DETAILS.large_icon,
        c4dp.C4DP_UPDATE_DETAILS.large_icon_text,
        c4dp.C4DP_UPDATE_DETAILS.small_icon,
        c4dp.C4DP_UPDATE_DETAILS.small_icon_text,
        c4dp.C4DP_UPDATE_DETAILS.details_text,
    )
    yield c4dp.C4DP_UPDATE_DETAILS
    (
        c4dp.C4DP_UPDATE_DETAILS.large_icon,
        c4dp.C4DP_UPDATE_DETAILS.large_icon_text,
        c4dp.C4DP_UPDATE_DETAILS.small_icon,
        c4dp.C4DP_UPDATE_DETAILS.small_icon_text,
        c4dp.C4DP_UPDATE_DETAILS.details_text,
    ) = snap


@pytest.fixture
def fresh_prefs(c4dp):
    """Snapshot/restore the prefs flags used by the icon/detail tests."""
    p = c4dp.C4DP_PREFS
    snap = (
        p.displayVersion,
        p.displaySmallIcon,
        p.displayEngine,
        p.displayGPU,
        p.enableDetails,
        p.displayFileName,
        p.displayRenderStats,
        p.displayFrames,
    )
    yield p
    (
        p.displayVersion,
        p.displaySmallIcon,
        p.displayEngine,
        p.displayGPU,
        p.enableDetails,
        p.displayFileName,
        p.displayRenderStats,
        p.displayFrames,
    ) = snap


@pytest.fixture
def fresh_session(c4dp):
    s = c4dp.C4DP_SESSION
    snap = (
        s.is_rendering,
        s.rendered_frames,
        s.render_res,
        s.render_engine,
        s.rendering_doc,
    )
    yield s
    (
        s.is_rendering,
        s.rendered_frames,
        s.render_res,
        s.render_engine,
        s.rendering_doc,
    ) = snap


def test_update_large_icon_with_version(c4d_mod, c4dp, fresh_details, fresh_prefs):
    fresh_prefs.displayVersion = True
    c4d_mod.set_state(active_doc=c4d_mod.make_document(), c4d_version=20262)
    ctx = c4dp.C4DContext.capture()
    c4dp.c4d_update_large_icon(ctx)
    assert fresh_details.large_icon == "cinema4d"
    assert "Cinema 4D" in fresh_details.large_icon_text
    assert "2026.2" in fresh_details.large_icon_text


def test_update_large_icon_without_version(c4d_mod, c4dp, fresh_details, fresh_prefs):
    fresh_prefs.displayVersion = False
    c4d_mod.set_state(active_doc=c4d_mod.make_document())
    ctx = c4dp.C4DContext.capture()
    c4dp.c4d_update_large_icon(ctx)
    assert fresh_details.large_icon_text == "Cinema 4D"


# ---------------------------------------------------------------------------
# c4d_update_small_icon — mode path
# ---------------------------------------------------------------------------


def test_update_small_icon_disabled_pref_clears(c4d_mod, c4dp, fresh_details, fresh_prefs):
    fresh_prefs.displaySmallIcon = False
    c4d_mod.set_state(active_doc=c4d_mod.make_document(mode=c4d_mod.Mpolygons))
    ctx = c4dp.C4DContext.capture()
    c4dp.c4d_update_small_icon(ctx)
    assert fresh_details.small_icon is None
    assert fresh_details.small_icon_text == ""


def test_update_small_icon_mode_path_polygon(c4d_mod, c4dp,
                                              fresh_details, fresh_prefs,
                                              fresh_session):
    """When not rendering, the small icon comes from the document mode."""
    fresh_prefs.displaySmallIcon = True
    fresh_session.is_rendering = False
    c4d_mod.set_state(active_doc=c4d_mod.make_document(mode=c4d_mod.Mpolygons))
    ctx = c4dp.C4DContext.capture()
    c4dp.c4d_update_small_icon(ctx)
    # The Discord asset is polygons.png — plural, matching _C4D_MODES. The
    # hover text is the same _C4D_MODES value, so it is plural too.
    assert fresh_details.small_icon == "polygons"
    assert fresh_details.small_icon_text == "Polygons"


def test_update_small_icon_mode_with_space_takes_first_word(c4d_mod, c4dp,
                                                            fresh_details, fresh_prefs,
                                                            fresh_session):
    """Mmodel name 'Model', Muvpoints name 'UV Points' — the icon name is
    the lowercased first word, so 'UV Points' -> 'uv'."""
    fresh_prefs.displaySmallIcon = True
    fresh_session.is_rendering = False
    c4d_mod.set_state(active_doc=c4d_mod.make_document(mode=c4d_mod.Muvpoints))
    ctx = c4dp.C4DContext.capture()
    c4dp.c4d_update_small_icon(ctx)
    assert fresh_details.small_icon == "uv"
    assert fresh_details.small_icon_text == "UV Points"


def test_update_small_icon_render_engine_redshift(c4d_mod, c4dp,
                                                   fresh_details, fresh_prefs,
                                                   fresh_session):
    """While rendering with a recognized engine, that engine's name becomes
    the icon (lowercased)."""
    fresh_prefs.displaySmallIcon = True
    fresh_prefs.displayEngine = True
    fresh_prefs.displayGPU = False
    fresh_session.is_rendering = True
    fresh_session.render_engine = "Redshift"
    c4d_mod.set_state(active_doc=c4d_mod.make_document())
    ctx = c4dp.C4DContext.capture()
    c4dp.c4d_update_small_icon(ctx)
    assert fresh_details.small_icon == "redshift"
    assert fresh_details.small_icon_text == "Redshift"


def test_update_small_icon_render_engine_with_gpu(c4d_mod, c4dp,
                                                   fresh_details, fresh_prefs,
                                                   fresh_session):
    fresh_prefs.displaySmallIcon = True
    fresh_prefs.displayEngine = True
    fresh_prefs.displayGPU = True
    fresh_session.is_rendering = True
    fresh_session.render_engine = "Redshift"
    bc = c4d_mod.BaseContainer()
    bc[c4d_mod.DRAWPORT_RENDERER_NAME] = "RTX 4090"
    c4d_mod.set_state(active_doc=c4d_mod.make_document(), machine_features=bc)
    ctx = c4dp.C4DContext.capture()
    c4dp.c4d_update_small_icon(ctx)
    assert fresh_details.small_icon_text == "Redshift | RTX 4090"


# ---------------------------------------------------------------------------
# c4d_update_presence_details — rendering path
# ---------------------------------------------------------------------------


def test_update_presence_details_rendering_full(c4d_mod, c4dp,
                                                 fresh_details, fresh_prefs,
                                                 fresh_session):
    fresh_prefs.enableDetails = True
    fresh_prefs.displayFileName = True
    fresh_prefs.displayRenderStats = True
    fresh_prefs.displayFrames = True
    fresh_session.is_rendering = True
    fresh_session.rendered_frames = 17
    fresh_session.rendering_doc = "big_render.c4d"
    fresh_session.render_res = (1920, 1080)
    c4d_mod.set_state(active_doc=c4d_mod.make_document())
    ctx = c4dp.C4DContext.capture()
    c4dp.c4d_update_presence_details(ctx)
    text = fresh_details.details_text
    assert "big_render.c4d" in text
    assert "1920x1080" in text
    assert "Frame 17" in text


def test_update_presence_details_rendering_no_filename(c4d_mod, c4dp,
                                                       fresh_details, fresh_prefs,
                                                       fresh_session):
    fresh_prefs.enableDetails = True
    fresh_prefs.displayFileName = False
    fresh_prefs.displayRenderStats = False
    fresh_prefs.displayFrames = False
    fresh_session.is_rendering = True
    fresh_session.rendering_doc = "hidden.c4d"
    c4d_mod.set_state(active_doc=c4d_mod.make_document())
    ctx = c4dp.C4DContext.capture()
    c4dp.c4d_update_presence_details(ctx)
    assert "hidden.c4d" not in fresh_details.details_text


def test_update_presence_details_not_rendering_uses_slot(c4d_mod, c4dp,
                                                         fresh_details, fresh_prefs,
                                                         fresh_session):
    """When not rendering, update_slot routes through C4DP_DISPLAY_TYPES based
    on prefs.detailsType. Setting detailsType='document' should yield the
    document name in details_text."""
    fresh_prefs.enableDetails = True
    fresh_session.is_rendering = False
    c4dp.C4DP_PREFS.detailsType = "document"
    c4dp.C4DP_PREFS.customDetails = ""
    c4d_mod.set_state(active_doc=c4d_mod.make_document(name="slot_test.c4d"))
    ctx = c4dp.C4DContext.capture()
    c4dp.c4d_update_presence_details(ctx)
    assert fresh_details.details_text == "slot_test.c4d"


# ---------------------------------------------------------------------------
# C4DPresencePrefs — Init / SetDParameter / GetDParameter / GetDEnabling
# ---------------------------------------------------------------------------


@pytest.fixture
def prefs_instance(c4dp):
    """Fresh C4DPresencePrefs against the (per-test, autouse-reset) world container."""
    return c4dp.C4DPresencePrefs()


def test_get_base_container_creates_if_missing(c4d_mod, prefs_instance, c4dp):
    """First GetBaseContainer call on a world container with no plugin entry
    should create a fresh sub-container."""
    bc = prefs_instance.GetBaseContainer()
    assert isinstance(bc, c4d_mod.BaseContainer)
    # Subsequent calls return the same container.
    assert prefs_instance.GetBaseContainer() is bc


def test_get_base_container_raises_when_world_missing(c4d_mod, prefs_instance):
    c4d_mod.set_state(world_container=None)
    with pytest.raises(RuntimeError):
        prefs_instance.GetBaseContainer()


def test_init_writes_defaults_for_all_dispatch_entries(c4dp, prefs_instance):
    """Init() must populate the basecontainer with every key in
    _C4DP_CONST_DISPATCH using its declared default."""
    prefs_instance.Init(node=None, isCloneInit=False)
    bc = prefs_instance.GetBaseContainer()
    for field_id, (kind, _attr, default) in c4dp._C4DP_CONST_DISPATCH.items():
        if kind == "bool":
            assert bc.GetBool(int(field_id)) == bool(default)
        elif kind == "int":
            assert bc.GetInt32(int(field_id)) == int(default)
        elif kind == "str":
            assert bc.GetString(int(field_id)) == str(default)


def test_init_state_default_is_active_object(c4dp, prefs_instance):
    """The default for C4DPRESENCE_STYPE in the dispatch is INFOOBJ (1) —
    this was the symptom-source of the earlier whitespace-in-header bug,
    so it's worth pinning."""
    prefs_instance.Init(node=None, isCloneInit=False)
    bc = prefs_instance.GetBaseContainer()
    assert bc.GetInt32(int(c4dp.C4DP.C4DPRESENCE_STYPE)) == int(c4dp.C4DP.C4DPRESENCE_INFOOBJ)


def test_set_get_dparameter_bool_roundtrip(c4d_mod, c4dp, prefs_instance):
    """A SetDParameter followed by GetDParameter should roundtrip a bool."""
    prefs_instance.Init(node=None, isCloneInit=False)
    desc = c4d_mod.DescID(c4d_mod.DescLevel(
        int(c4dp.C4DP.C4DPRESENCE_GENERALENABLE), c4d_mod.DTYPE_BOOL, 0,
    ))
    prefs_instance.SetDParameter(node=None, id=desc, t_data=False, flags=0)
    ok, value, _flags = prefs_instance.GetDParameter(node=None, id=desc, flags=0)
    assert ok is True
    assert value is False


def test_set_dparameter_writes_to_python_prefs(c4d_mod, c4dp, prefs_instance):
    """SetDParameter on the *Type fields runs through _write_pref, which
    translates the int to the string key via _C4D_INFOTYPE_MAP."""
    desc = c4d_mod.DescID(c4d_mod.DescLevel(
        int(c4dp.C4DP.C4DPRESENCE_DTYPE), c4d_mod.DTYPE_LONG, 0,
    ))
    prefs_instance.SetDParameter(
        node=None, id=desc,
        t_data=int(c4dp.C4DP.C4DPRESENCE_INFOFRM),
        flags=0,
    )
    assert c4dp.C4DP_PREFS.detailsType == "frame"


def test_get_denabling_returns_controller_state(c4d_mod, c4dp, prefs_instance):
    """C4DPRESENCE_STYPE is gated by C4DPRESENCE_SFIELD. Toggling SFIELD in
    the basecontainer should flip GetDEnabling's answer for STYPE."""
    prefs_instance.Init(node=None, isCloneInit=False)
    bc = prefs_instance.GetBaseContainer()
    desc = c4d_mod.DescID(c4d_mod.DescLevel(
        int(c4dp.C4DP.C4DPRESENCE_STYPE), c4d_mod.DTYPE_LONG, 0,
    ))
    bc.SetBool(int(c4dp.C4DP.C4DPRESENCE_SFIELD), True)
    assert prefs_instance.GetDEnabling(None, desc, None, 0, None) is True
    bc.SetBool(int(c4dp.C4DP.C4DPRESENCE_SFIELD), False)
    assert prefs_instance.GetDEnabling(None, desc, None, 0, None) is False


def test_get_denabling_returns_true_when_no_controller(c4d_mod, c4dp, prefs_instance):
    """Fields with no controller in _C4DP_CONTROLLERS are always enabled."""
    prefs_instance.Init(node=None, isCloneInit=False)
    desc = c4d_mod.DescID(c4d_mod.DescLevel(
        int(c4dp.C4DP.C4DPRESENCE_GENERALENABLE), c4d_mod.DTYPE_BOOL, 0,
    ))
    assert prefs_instance.GetDEnabling(None, desc, None, 0, None) is True


def test_get_ddescription_loads_named_resource(c4d_mod, c4dp, prefs_instance):
    """GetDDescription must call description.LoadDescription('c4d_presence')
    — that string must match the .res file name."""
    description = c4d_mod.Description()
    ok = prefs_instance.GetDDescription(None, description, 0)
    assert ok != False  # noqa: E712 — could be True or (True, flags)
    assert "c4d_presence" in description.loaded_names


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------


def test_message_reset_all_restores_bool_default(c4d_mod, c4dp, prefs_instance):
    """Regression: 'Reset All' button used to dispatch to self.Init(),
    which only writes defaults for empty slots — so user-modified values
    weren't actually reset. Now the RESETALL branch calls _reset_prefs
    which overwrites every dispatched slot with its declared default."""
    prefs_instance.Init(node=None, isCloneInit=False)
    bc = prefs_instance.GetBaseContainer()
    bc.SetBool(int(c4dp.C4DP.C4DPRESENCE_GENERALENABLE), False)
    data = {"id": c4d_mod.DescID(c4d_mod.DescLevel(
        int(c4dp.C4DP.C4DPRESENCE_RESETALL),
    ))}
    prefs_instance.Message(None, c4d_mod.MSG_DESCRIPTION_COMMAND, data)
    assert bc.GetBool(int(c4dp.C4DP.C4DPRESENCE_GENERALENABLE)) is True


def test_message_reset_all_restores_int_default(c4d_mod, c4dp, prefs_instance):
    """Same as above but for the int slot used by the state-type cycle —
    the symptom that originally surfaced the IntEnum and reset bugs
    together. STYPE's dispatched default is INFOOBJ (1)."""
    prefs_instance.Init(node=None, isCloneInit=False)
    bc = prefs_instance.GetBaseContainer()
    bc.SetInt32(int(c4dp.C4DP.C4DPRESENCE_STYPE), 5)
    data = {"id": c4d_mod.DescID(c4d_mod.DescLevel(
        int(c4dp.C4DP.C4DPRESENCE_RESETALL),
    ))}
    prefs_instance.Message(None, c4d_mod.MSG_DESCRIPTION_COMMAND, data)
    assert bc.GetInt32(int(c4dp.C4DP.C4DPRESENCE_STYPE)) == int(
        c4dp.C4DP.C4DPRESENCE_INFOOBJ
    )

def test_message_documentinfo_load_preserves_timer_when_pref_unset(c4d_mod, c4dp,
                                                                   prefs_instance):
    original_start = c4dp.C4DP_SESSION.start_time
    original_reset = c4dp.C4DP_PREFS.resetTimer
    try:
        c4dp.C4DP_PREFS.resetTimer = False
        c4dp.C4DP_SESSION.start_time = 12345.0
        prefs_instance.Message(None, c4d_mod.MSG_DOCUMENTINFO,
                               {"type": c4d_mod.MSG_DOCUMENTINFO_TYPE_LOAD})
        assert c4dp.C4DP_SESSION.start_time == 12345.0
    finally:
        c4dp.C4DP_SESSION.start_time = original_start
        c4dp.C4DP_PREFS.resetTimer = original_reset


# ---------------------------------------------------------------------------
# _sync_prefs translates int -> Python attr (string for *Type fields).
# ---------------------------------------------------------------------------


def test_sync_prefs_translates_type_fields_to_strings(c4d_mod, c4dp, prefs_instance):
    """After Init writes int defaults, _sync_prefs should mirror them onto
    the Python dataclass — and the DTYPE/STYPE fields must come out as
    the string keys from _C4D_INFOTYPE_MAP, not the raw int."""
    prefs_instance.Init(node=None, isCloneInit=False)
    # Defaults: DTYPE=INFODOC=0 -> "document"; STYPE=INFOOBJ=1 -> "object"
    assert c4dp.C4DP_PREFS.detailsType == "document"
    assert c4dp.C4DP_PREFS.stateType == "object"


def test_sync_prefs_unknown_int_falls_back_to_default(c4d_mod, c4dp, prefs_instance):
    """If the basecontainer holds a value not in _C4D_INFOTYPE_MAP,
    _sync_prefs should fall back to the dispatch's declared default."""
    prefs_instance.Init(node=None, isCloneInit=False)
    bc = prefs_instance.GetBaseContainer()
    bc.SetInt32(int(c4dp.C4DP.C4DPRESENCE_DTYPE), 9999)
    c4dp._sync_prefs(bc)
    # The fallback has to be a *string* key from C4DP_DISPATCH_TYPES. Falling
    # back to the dispatch table's declared default would leave the IntEnum
    # C4DP.C4DPRESENCE_INFODOC on the prefs object, and the display-type lookup
    # would then miss and blank the field.
    assert c4dp.C4DP_PREFS.detailsType == "document"
    assert isinstance(c4dp.C4DP_PREFS.detailsType, str)


def test_sync_prefs_unknown_state_int_falls_back_to_object(
    c4d_mod, c4dp, prefs_instance
):
    """The state slot's fallback is its own declared default ("object"), not
    the details slot's."""
    prefs_instance.Init(node=None, isCloneInit=False)
    bc = prefs_instance.GetBaseContainer()
    bc.SetInt32(int(c4dp.C4DP.C4DPRESENCE_STYPE), 9999)
    c4dp._sync_prefs(bc)
    assert c4dp.C4DP_PREFS.stateType == "object"


# ---------------------------------------------------------------------------
# C4DPPresenceMessage.CoreMessage — the seen-document memo.
#
# The memo exists so switching back to an already-visited document does not
# re-reset the elapsed timer. It used to grow for the life of the session and
# keep every BaseDocument wrapper the user ever opened alive with it; the tick
# now prunes it against C4D's open-document list.
# ---------------------------------------------------------------------------


def test_core_message_prunes_closed_documents_from_memo(c4d_mod, c4dp):
    """A document that is no longer in the open-document list is dropped from
    the memo, so its BaseDocument wrapper stops being reachable."""
    kept = c4d_mod.make_document(name="kept.c4d")
    closed = c4d_mod.make_document(name="closed.c4d")
    handler = c4dp.C4DPPresenceMessage()
    handler.seen_documents = {kept, closed}
    c4d_mod.set_state(active_doc=kept, open_docs=[kept])

    handler.CoreMessage(c4d_mod.MSG_TIMER, c4d_mod.BaseContainer())

    assert kept in handler.seen_documents
    assert closed not in handler.seen_documents


def test_core_message_empty_document_walk_leaves_memo_alone(c4d_mod, c4dp):
    """If the open-document walk yields nothing, treat it as 'no answer' and
    keep the memo — wiping it would spuriously reset the timer."""
    doc = c4d_mod.make_document(name="scene.c4d")
    handler = c4dp.C4DPPresenceMessage()
    handler.seen_documents = {doc}
    c4d_mod.set_state(active_doc=doc, open_docs=[])

    handler.CoreMessage(c4d_mod.MSG_TIMER, c4d_mod.BaseContainer())

    assert doc in handler.seen_documents


def test_core_message_reopened_document_resets_timer_again(c4d_mod, c4dp):
    """Because closed documents leave the memo, reopening one counts as new
    and resets the elapsed timer (matching 'reset when a new file is opened')."""
    first = c4d_mod.make_document(name="a.c4d")
    second = c4d_mod.make_document(name="b.c4d")
    handler = c4dp.C4DPPresenceMessage()
    c4dp.C4DP_PREFS.resetTimer = True

    c4d_mod.set_state(active_doc=first, open_docs=[first])
    handler.CoreMessage(c4d_mod.MSG_TIMER, c4d_mod.BaseContainer())
    assert handler.seen_documents == {first}

    # a.c4d closed, b.c4d opened.
    c4d_mod.set_state(active_doc=second, open_docs=[second])
    handler.CoreMessage(c4d_mod.MSG_TIMER, c4d_mod.BaseContainer())
    assert handler.seen_documents == {second}


def test_core_message_second_tick_same_document_is_not_new(c4d_mod, c4dp):
    """The memo still does its job: a document already in it isn't re-added
    and doesn't re-reset the timer."""
    doc = c4d_mod.make_document(name="scene.c4d")
    handler = c4dp.C4DPPresenceMessage()
    c4d_mod.set_state(active_doc=doc, open_docs=[doc])

    handler.CoreMessage(c4d_mod.MSG_TIMER, c4d_mod.BaseContainer())
    c4dp.C4DP_SESSION.start_time = 0.0
    handler.CoreMessage(c4d_mod.MSG_TIMER, c4d_mod.BaseContainer())

    assert c4dp.C4DP_SESSION.start_time == 0.0


# ---------------------------------------------------------------------------
# C4DPPresenceMessage.CoreMessage — render start/stop polling.
#
# C4D delivers no CoreMessage for render begin/end, so the 1s tick polls
# CheckIsRunning and latches the render metadata on the transition.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("running_flag", ["editor_rendering", "external_rendering"])
def test_core_message_latches_render_info_on_start(c4d_mod, c4dp, running_flag):
    """Either render mode flips is_rendering and captures the document name,
    resolution and engine once, at the transition."""
    doc = c4d_mod.make_document(
        name="shot.c4d",
        render_engine=c4d_mod.RDATA_RENDERENGINE_REDSHIFT,
        render_resolution=(1920, 1080),
    )
    handler = c4dp.C4DPPresenceMessage()
    c4dp.C4DP_SESSION.is_rendering = False
    c4d_mod.set_state(active_doc=doc, open_docs=[doc], **{running_flag: True})

    handler.CoreMessage(c4d_mod.MSG_TIMER, c4d_mod.BaseContainer())

    assert c4dp.C4DP_SESSION.is_rendering is True
    assert c4dp.C4DP_SESSION.rendering_doc == "shot.c4d"
    assert c4dp.C4DP_SESSION.render_res == (1920, 1080)
    assert c4dp.C4DP_SESSION.render_engine == "Redshift"


def test_core_message_unknown_engine_id_falls_back_to_label(c4d_mod, c4dp):
    """An engine id outside _C4D_RENDER_ENGINES still yields a displayable
    string rather than a raw int."""
    doc = c4d_mod.make_document(name="shot.c4d", render_engine=123456789)
    handler = c4dp.C4DPPresenceMessage()
    c4dp.C4DP_SESSION.is_rendering = False
    c4d_mod.set_state(active_doc=doc, open_docs=[doc], editor_rendering=True)

    handler.CoreMessage(c4d_mod.MSG_TIMER, c4d_mod.BaseContainer())

    assert c4dp.C4DP_SESSION.render_engine == "Unknown render engine"


def test_core_message_clears_is_rendering_when_render_stops(c4d_mod, c4dp):
    doc = c4d_mod.make_document(name="shot.c4d")
    handler = c4dp.C4DPPresenceMessage()
    c4dp.C4DP_SESSION.is_rendering = True
    c4d_mod.set_state(
        active_doc=doc, open_docs=[doc],
        editor_rendering=False, external_rendering=False,
    )

    handler.CoreMessage(c4d_mod.MSG_TIMER, c4d_mod.BaseContainer())

    assert c4dp.C4DP_SESSION.is_rendering is False
