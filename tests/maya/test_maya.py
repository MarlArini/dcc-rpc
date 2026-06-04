"""
Tests for MPContext (Maya plugin).

The tail of the file contains regression tests for four bugs surfaced during
a docs cross-check:
  * MPExtensionMonitor.count crashed if listNodeTypes returned None — see
    test_extension_monitor_count_handles_none_listnodetypes.
  * get_gpu_str trimmed the final character of any GPU string that contains
    no '/' separator — see test_get_gpu_str_no_slash_preserves_full_name.
  * mp_uninstall_render_handlers used `return` instead of `continue`, so an
    empty preMel attr left stale hooks in postMel/postRenderMel — see
    test_uninstall_render_handlers_skips_empty_attrs_correctly.
  * mp_check_render_handlers_installed treated a RuntimeError on the first
    attr as 'not installed' even if later attrs had hooks — see
    test_check_render_handlers_installed_continues_past_runtimeerror.
"""
from __future__ import annotations
import pytest

from maya_presence import MPContext


# ---------------------------------------------------------------------------
# Scene + project naming
# ---------------------------------------------------------------------------

def test_get_project_name(cmds):
    cmds.set_state(project_short_name="MyMayaProject")
    ctx = MPContext.capture()
    assert ctx.get_project_name() == "MyMayaProject"


def test_get_file_name_unsaved(cmds):
    cmds.set_state(scene_name="")
    ctx = MPContext.capture()
    assert ctx.get_file_name() == ""


def test_get_file_name_saved_no_ext(cmds):
    cmds.set_state(scene_name="/projects/maya/scene01.mb")
    ctx = MPContext.capture()
    assert ctx.get_file_name(ext=False) == "scene01"


def test_get_file_name_saved_with_ext(cmds):
    cmds.set_state(scene_name="/projects/maya/scene01.mb")
    ctx = MPContext.capture()
    assert ctx.get_file_name(ext=True) == "scene01.mb"


def test_get_current_scene_both_present(cmds):
    cmds.set_state(project_short_name="MyProj", scene_name="/p/maya/scene.mb")
    ctx = MPContext.capture()
    assert ctx.get_current_scene() == "MyProj | scene"


def test_get_current_scene_only_project(cmds):
    cmds.set_state(project_short_name="MyProj", scene_name="")
    ctx = MPContext.capture()
    assert ctx.get_current_scene() == "MyProj"


def test_get_current_scene_fallback(cmds):
    cmds.set_state(project_short_name="", scene_name="")
    ctx = MPContext.capture()
    assert ctx.get_current_scene() == "Untitled Scene"


# ---------------------------------------------------------------------------
# Counts: cameras, lights, joints, blendshapes, materials, textures
# ---------------------------------------------------------------------------

def test_get_cam_count_subtracts_default_four(cmds):
    """Maya has 4 default cameras (persp, top, front, side); plugin subtracts."""
    cmds.set_state(ls_results={("cameras",): ["persp", "top", "front", "side", "shotCam"]})
    ctx = MPContext.capture()
    assert ctx.get_cam_count() == "1 camera"


def test_get_cam_count_zero(cmds):
    cmds.set_state(ls_results={("cameras",): ["persp", "top", "front", "side"]})
    ctx = MPContext.capture()
    assert ctx.get_cam_count() == "0 cameras"


@pytest.mark.parametrize("n, expected", [
    (0, "0 lights"), (1, "1 light"), (4, "4 lights"),
])
def test_get_light_count(cmds, n, expected):
    cmds.set_state(ls_results={("lights",): [f"light{i}" for i in range(n)]})
    ctx = MPContext.capture()
    assert ctx.get_light_count() == expected


@pytest.mark.parametrize("n, expected", [
    (0, "0 joints"), (1, "1 joint"), (10, "10 joints"),
])
def test_get_joint_count(cmds, n, expected):
    cmds.set_state(ls_results={("type", "joint"): [f"j{i}" for i in range(n)]})
    ctx = MPContext.capture()
    assert ctx.get_joint_count() == expected


@pytest.mark.parametrize("n, expected", [
    (0, "0 blendshapes"), (3, "3 blendshapes"),
])
def test_get_blendshape_count(cmds, n, expected):
    cmds.set_state(ls_results={("type", "blendShape"): [f"bs{i}" for i in range(n)]})
    ctx = MPContext.capture()
    assert ctx.get_blendshape_count() == expected


@pytest.mark.parametrize("n, expected", [
    (0, "0 materials"), (1, "1 material"), (12, "12 materials"),
])
def test_get_mat_count(cmds, n, expected):
    cmds.set_state(ls_results={("materials",): [f"mat{i}" for i in range(n)]})
    ctx = MPContext.capture()
    assert ctx.get_mat_count() == expected


@pytest.mark.parametrize("n, expected", [
    (0, "0 textures"), (5, "5 textures"),
])
def test_get_tex_count(cmds, n, expected):
    cmds.set_state(ls_results={("textures",): [f"tex{i}" for i in range(n)]})
    ctx = MPContext.capture()
    assert ctx.get_tex_count() == expected


# ---------------------------------------------------------------------------
# get_mesh_count — flagged in audit as passing list (not len) to plural
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("meshes, expected", [
    ([], "0 meshes"),
    (["pSphere1"], "1 mesh"),
    (["pSphere1", "pCube1"], "2 meshes"),
    ([f"m{i}" for i in range(15)], "15 meshes"),
])
def test_get_mesh_count(cmds, meshes, expected):
    """get_mesh_count uses postfix='es' for the plural form."""
    cmds.set_state(ls_results={("geometry_mesh",): meshes})
    ctx = MPContext.capture()
    assert ctx.get_mesh_count() == expected


# ---------------------------------------------------------------------------
# get_poly_count_str — flagged in audit for int("1k")==1 crash
# ---------------------------------------------------------------------------

def test_get_poly_count_str_small_uses_polyEvaluate(cmds):
    """Small counts: HUD off, polyEvaluate path; no shorten_number boundary."""
    cmds.set_state(hud_visible=False, polyevaluate_result={"vertex": 500, "face": 400})
    ctx = MPContext.capture()
    out = ctx.get_poly_count_str()
    assert "500" in out and "400" in out


@pytest.mark.parametrize("verts, faces, expected_v, expected_f", [
    (1, 1, "1 vert", "1 face"),
    (500, 400, "500 verts", "400 faces"),
    (1_000, 4_000, "1k verts", "4k faces"),
    (1_500_000, 999_000, "1m verts", "999k faces"),
])
def test_get_poly_count_str_handles_large_counts(cmds, verts, faces, expected_v, expected_f):
    """vert_str/face_str must be computed BEFORE shortening — otherwise
    int('1k') raises ValueError for counts >= 1000."""
    cmds.set_state(hud_visible=False,
                   polyevaluate_result={"vertex": verts, "face": faces})
    ctx = MPContext.capture()
    out = ctx.get_poly_count_str()
    assert expected_v in out and expected_f in out


# ---------------------------------------------------------------------------
# MP_DISPLAY_TYPES["mesh"] — flagged in audit for wrong method name
# ---------------------------------------------------------------------------

def test_display_types_mesh_lambda_resolves(cmds):
    """MP_DISPLAY_TYPES["mesh"] must call a method that exists on MPContext.
    (Earlier audit flagged this as buggy; the current code at line 555
    correctly calls ctx.get_mesh_count().)"""
    from maya_presence import MP_DISPLAY_TYPES
    cmds.set_state(ls_results={("geometry_mesh",): ["pSphere1"]})
    ctx = MPContext.capture()
    assert MP_DISPLAY_TYPES["mesh"](ctx) == "1 mesh"


def test_display_types_all_lambdas_callable_against_default_ctx(cmds):
    """Smoke-test every MP_DISPLAY_TYPES lambda against a minimally-configured
    context to surface any other mis-pointing lambdas."""
    from maya_presence import MP_DISPLAY_TYPES
    cmds.set_state(
        ls_results={
            ("geometry_mesh",): [],
            ("cameras",): ["persp", "top", "front", "side"],
            ("lights",): [],
            ("type", "joint"): [],
            ("type", "blendShape"): [],
            ("materials",): [],
            ("textures",): [],
            ("selection",): [],
        },
        polyevaluate_result={"vertex": 0, "face": 0},
    )
    ctx = MPContext.capture()
    for key, fn in MP_DISPLAY_TYPES.items():
        result = fn(ctx)
        # Result may be None (e.g., "size" when scene unsaved, "active" when
        # nothing selected) or a string; just ensure no exception.
        assert result is None or isinstance(result, str), f"{key} returned {type(result)}"


# ---------------------------------------------------------------------------
# Frame + render attrs
# ---------------------------------------------------------------------------

def test_get_current_frame(cmds):
    cmds.set_state(current_time=42.0)
    ctx = MPContext.capture()
    assert ctx.get_current_frame() == "Frame 42"


def test_get_frame_range(cmds):
    cmds.set_state(min_time=10.0, max_time=110.0, current_time=15.0)
    ctx = MPContext.capture()
    # Plugin returns (cursor - start + 1, end - start + 1) - so 6 of 101.
    assert ctx.get_frame_range() == (6, 101)


@pytest.mark.parametrize("renderer, expected", [
    ("arnold", "Arnold"),
    ("redshift", "Redshift"),
    ("renderman", "RenderMan"),
    ("vray", "V-Ray"),
    ("mayaSoftware", "Maya Software"),
    ("mayaHardware2", "Maya Hardware 2.0"),
    ("", "Unknown"),
    ("octane", "octane"),  # unknown renderer comes through verbatim
])
def test_get_render_engine_str(cmds, renderer, expected):
    cmds.set_state(attrs={**cmds.get_state().attrs,
                          "defaultRenderGlobals.currentRenderer": renderer})
    ctx = MPContext.capture()
    assert ctx.get_render_engine_str() == expected


def test_get_render_resolution(cmds):
    cmds.set_state(attrs={
        **cmds.get_state().attrs,
        "defaultResolution.width": 3840,
        "defaultResolution.height": 2160,
    })
    ctx = MPContext.capture()
    assert ctx.get_render_resolution() == (3840, 2160)


def test_get_render_resolution_raises_returns_none(cmds):
    cmds.set_state(attrs_raise={"defaultResolution.width"})
    ctx = MPContext.capture()
    assert ctx.get_render_resolution() is None


# ---------------------------------------------------------------------------
# FPS units
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unit, expected", [
    ("game", 15), ("film", 24), ("pal", 25), ("ntsc", 30),
    ("show", 48), ("palf", 50), ("ntscf", 60),
    ("24fps", 24), ("60fps", 60),
])
def test_get_render_fps_known_units(cmds, unit, expected):
    cmds.set_state(current_time_unit=unit)
    ctx = MPContext.capture()
    assert ctx.get_render_fps() == expected


def test_get_render_fps_bad_fps_returns_none(cmds):
    cmds.set_state(current_time_unit="bogusfps")
    ctx = MPContext.capture()
    assert ctx.get_render_fps() is None


# ---------------------------------------------------------------------------
# GPU + version
# ---------------------------------------------------------------------------

def test_get_gpu_str_strips_nvidia_prefix(cmds):
    cmds.set_state(gl_renderer="NVIDIA GeForce RTX 4090/PCIe/SSE2")
    ctx = MPContext.capture()
    out = ctx.get_gpu_str()
    assert "NVIDIA" not in out
    assert "RTX 4090" in out


def test_get_gpu_str_strips_radeon_prefix(cmds):
    cmds.set_state(gl_renderer="Radeon RX 7900 XTX/PCIe/SSE2")
    ctx = MPContext.capture()
    out = ctx.get_gpu_str()
    assert "Radeon " not in out
    assert "RX 7900 XTX" in out


def test_get_gpu_str_runtimeerror_returns_empty(cmds):
    cmds.set_state(raise_gl_renderer=True)
    ctx = MPContext.capture()
    assert ctx.get_gpu_str() == ""


def test_get_version_str(cmds):
    cmds.set_state(about_responses={
        "majorVersion": "2026", "minorVersion": "0", "patchVersion": "1",
        "batch": False, "version": "2026.0.1",
    })
    ctx = MPContext.capture()
    assert ctx.get_version_str() == "2026.0.1"


# ---------------------------------------------------------------------------
# Active object + user context
# ---------------------------------------------------------------------------

def test_get_active_object_with_selection(cmds):
    cmds.set_state(ls_results={("selection",): ["pCube1", "pSphere1"]})
    ctx = MPContext.capture()
    assert ctx.get_active_object() == "pCube1"


def test_get_active_object_empty_selection(cmds):
    cmds.set_state(ls_results={("selection",): []})
    ctx = MPContext.capture()
    assert ctx.get_active_object() is None


@pytest.mark.parametrize("ctx_str, expected", [
    ("polyCreateFaceCtx", "Context: PolyCreateFace"),
    ("manipMoveContext", "Context: ManipMove"),
    ("sculptMeshCacheCtx", "Context: SculptMeshCache"),
    ("", None),
])
def test_get_user_context(cmds, ctx_str, expected):
    cmds.set_state(current_ctx=ctx_str)
    ctx = MPContext.capture()
    assert ctx.get_user_context() == expected


# ---------------------------------------------------------------------------
# MPContext: None-path branches
# ---------------------------------------------------------------------------

def test_get_render_engine_str_raises_returns_unknown(cmds):
    cmds.set_state(attrs_raise={"defaultRenderGlobals.currentRenderer"})
    ctx = MPContext.capture()
    assert ctx.get_render_engine_str() == "Unknown"


def test_get_file_size_returns_none_when_unsaved(cmds, tmp_path):
    cmds.set_state(scene_name="")
    ctx = MPContext.capture()
    assert ctx.get_file_size() is None


def test_get_file_size_returns_none_when_path_missing(cmds, tmp_path):
    missing = str(tmp_path / "does_not_exist.mb")
    cmds.set_state(scene_name=missing)
    ctx = MPContext.capture()
    assert ctx.get_file_size() is None


def test_get_file_size_returns_string_for_existing(cmds, tmp_path):
    scene_file = tmp_path / "scene.mb"
    scene_file.write_bytes(b"a" * 2048)
    cmds.set_state(scene_name=str(scene_file))
    ctx = MPContext.capture()
    out = ctx.get_file_size()
    assert out is not None
    assert "KB" in out


def test_get_poly_count_str_hud_visible(cmds):
    """When the HUD reports verts/faces directly, get_poly_count_str uses those
    (this is the if-branch; the else uses polyEvaluate)."""
    cmds.set_state(hud_visible=True, hud_verts=1234, hud_faces=2222)
    ctx = MPContext.capture()
    out = ctx.get_poly_count_str()
    # 1234 -> "1k", 2222 -> "2k"
    assert "1k verts" in out and "2k faces" in out


def test_get_poly_count_str_polyevaluate_string_means_zero(cmds):
    """polyEvaluate with no selection returns a string; the plugin treats
    that as (0, 0)."""
    cmds.set_state(hud_visible=False, polyevaluate_result="No meshes selected")
    ctx = MPContext.capture()
    out = ctx.get_poly_count_str()
    assert out == "0 verts | 0 faces"


# ---------------------------------------------------------------------------
# MPSettings: optionVar persistence and reset
# ---------------------------------------------------------------------------

from maya_presence import MPSettings  # noqa: E402


def test_mpsettings_loads_from_optionvar_with_bool_coercion(cmds):
    """An existing optionVar value takes precedence over the dataclass default,
    AND bool-typed fields come back as Python bools (not the int 0/1 that
    Maya's optionVar stores)."""
    cmds.set_state(option_vars={
        "mayaPresence_generalEnable": 0,  # bool stored as int(0)/int(1)
        "mayaPresence_generalUpdate": 30,
        "mayaPresence_displayVersion": 1,
    })
    s = MPSettings()
    assert s.generalEnable is False
    assert isinstance(s.generalEnable, bool)
    assert s.displayVersion is True
    assert isinstance(s.displayVersion, bool)
    assert s.generalUpdate == 30


def test_mpsettings_falls_back_to_initial_defaults(cmds):
    """Field with no optionVar but in _INITIAL_DEFAULTS uses the Maya override."""
    cmds.set_state(option_vars={})  # nothing persisted
    s = MPSettings()
    # _INITIAL_DEFAULTS has "stateType" -> "poly", "detailsType" -> "scene"
    assert s.stateType == "poly"
    assert s.detailsType == "scene"


def test_mpsettings_falls_back_to_field_defaults(cmds):
    """Field with no optionVar and not in _INITIAL_DEFAULTS uses dataclass default."""
    cmds.set_state(option_vars={})
    s = MPSettings()
    # generalUpdate default is 12 from SharedSettings.
    assert s.generalUpdate == 12
    assert s.generalEnable is True


def test_mpsettings_setattr_persists_bool(cmds):
    cmds.set_state(option_vars={})
    s = MPSettings()
    s.displayGPU = True
    assert cmds.get_state().option_vars.get("mayaPresence_displayGPU") == 1


def test_mpsettings_setattr_persists_int(cmds):
    cmds.set_state(option_vars={})
    s = MPSettings()
    s.generalUpdate = 25
    assert cmds.get_state().option_vars.get("mayaPresence_generalUpdate") == 25


def test_mpsettings_setattr_persists_string(cmds):
    cmds.set_state(option_vars={})
    s = MPSettings()
    s.customDetails = "Test text"
    stored = cmds.get_state().option_vars.get("mayaPresence_customDetails")
    assert stored == "Test text"


def test_mpsettings_setattr_skips_private(cmds):
    """Underscore-prefixed attrs and non-field attrs shouldn't write optionVars."""
    cmds.set_state(option_vars={})
    s = MPSettings()
    s._something_internal = "x"
    # No optionVar starting with _something_internal.
    keys = list(cmds.get_state().option_vars.keys())
    assert all("_something_internal" not in k for k in keys)


def test_mpsettings_reset_restores_initial_defaults(cmds):
    cmds.set_state(option_vars={})
    s = MPSettings()
    s.stateType = "frame"
    s.generalUpdate = 60
    s.reset()
    # _INITIAL_DEFAULTS["stateType"] = "poly"; generalUpdate default is 12.
    assert s.stateType == "poly"
    assert s.generalUpdate == 12


# ---------------------------------------------------------------------------
# MPExtensionMonitor (render-engine plugin watcher)
# ---------------------------------------------------------------------------

from maya_presence import MPExtensionMonitor, MP_EXTENSIONS, MP_PREFS  # noqa: E402


def test_extension_monitor_init_engine_populates_types(cmds):
    cmds.set_state(node_types_by_path={
        "rendernode/redshift/light": ["RedshiftPhysicalLight", "RedshiftSpot"],
        "rendernode/redshift/shader": ["RedshiftMaterial"],
        "rendernode/redshift/texture": ["RedshiftBitmap"],
    })
    mon = MPExtensionMonitor()
    mon.init_engine("Redshift")
    engine = mon.monitored_engines["Redshift"]
    assert engine.loaded is True
    assert engine.types == {
        "light": ["RedshiftPhysicalLight", "RedshiftSpot"],
        "material": ["RedshiftMaterial"],
        "texture": ["RedshiftBitmap"],
    }


def test_extension_monitor_count_zero_when_engine_not_loaded(cmds):
    mon = MPExtensionMonitor()
    # No engine initialized => count returns 0
    assert mon.count(MPExtensionMonitor.TypeCategory.LIGHT) == 0


def test_extension_monitor_count_uses_types_when_pref_enabled(cmds):
    """When countExtensions is on, count() sums ls() matches across all
    loaded engines' type lists. (The previous per-engine countArnold /
    countRS / countPxr / countVRay flags were consolidated into a single
    countExtensions toggle.)"""
    cmds.set_state(node_types_by_path={
        "rendernode/arnold/light": ["aiAreaLight"],
    })
    mon = MPExtensionMonitor()
    mon.init_engine("Arnold")
    # ls(type=["aiAreaLight"]) needs to return some count.
    cmds.set_state(ls_results={("type_multi", ("aiAreaLight",)): ["lt1", "lt2"]})
    snap = MP_PREFS.countExtensions
    MP_PREFS.countExtensions = True
    try:
        assert mon.count(MPExtensionMonitor.TypeCategory.LIGHT) == 2
    finally:
        MP_PREFS.countExtensions = snap


def test_extension_monitor_count_zero_when_pref_disabled(cmds):
    cmds.set_state(node_types_by_path={
        "rendernode/arnold/light": ["aiAreaLight"],
    })
    mon = MPExtensionMonitor()
    mon.init_engine("Arnold")
    cmds.set_state(ls_results={("type_multi", ("aiAreaLight",)): ["lt1"]})
    snap = MP_PREFS.countExtensions
    MP_PREFS.countExtensions = False
    try:
        # Pref off => types excluded => count returns 0.
        assert mon.count(MPExtensionMonitor.TypeCategory.LIGHT) == 0
    finally:
        MP_PREFS.countExtensions = snap


# ---------------------------------------------------------------------------
# Plugin load/unload observers
# ---------------------------------------------------------------------------

from maya_presence import mp_observe_plugin_load, mp_observe_plugin_unload  # noqa: E402


@pytest.fixture
def reset_monitored_engines():
    """Snapshot/restore each monitored engine's loaded flag so observers
    don't pollute other tests."""
    snap = {name: (eng.loaded, eng.types) for name, eng in MP_EXTENSIONS.monitored_engines.items()}
    yield
    for name, (loaded, types) in snap.items():
        MP_EXTENSIONS.monitored_engines[name].loaded = loaded
        MP_EXTENSIONS.monitored_engines[name].types = types


def test_observe_plugin_load_initializes_known_engine(cmds, reset_monitored_engines):
    cmds.set_state(node_types_by_path={
        "rendernode/redshift/light": ["RedshiftLight"],
        "rendernode/redshift/shader": ["RedshiftMat"],
        "rendernode/redshift/texture": ["RedshiftTex"],
    })
    # The kAfterPluginLoad string array is [plugin_path, plugin_name]; observers
    # use string_array[-1] (the name).
    mp_observe_plugin_load(["/path/to/redshift4maya.so", "redshift4maya"], None)
    assert MP_EXTENSIONS.monitored_engines["Redshift"].loaded is True


def test_observe_plugin_load_ignores_unknown_plugin(cmds, reset_monitored_engines):
    # Reset to a known state first.
    for eng in MP_EXTENSIONS.monitored_engines.values():
        eng.loaded = False
    mp_observe_plugin_load(["/path", "some_unrelated_plugin"], None)
    for name, eng in MP_EXTENSIONS.monitored_engines.items():
        assert eng.loaded is False


def test_observe_plugin_load_empty_string_array_noop(cmds, reset_monitored_engines):
    for eng in MP_EXTENSIONS.monitored_engines.values():
        eng.loaded = False
    mp_observe_plugin_load([], None)
    for name, eng in MP_EXTENSIONS.monitored_engines.items():
        assert eng.loaded is False


def test_observe_plugin_unload_marks_engine_unloaded(cmds, reset_monitored_engines):
    # Pre-load Arnold so we can verify the unload.
    MP_EXTENSIONS.monitored_engines["Arnold"].loaded = True
    # The kAfterPluginUnload string array is [plugin_name, plugin_path];
    # observers use string_array[0] (the name).
    mp_observe_plugin_unload(["mtoa", "/path/to/mtoa.so"], None)
    assert MP_EXTENSIONS.monitored_engines["Arnold"].loaded is False


# ---------------------------------------------------------------------------
# Render handler install/uninstall
# ---------------------------------------------------------------------------

from maya_presence import (  # noqa: E402
    mp_install_render_handlers,
    mp_uninstall_render_handlers,
    mp_check_render_handlers_installed,
    MP_HOOK_START,
)


def test_check_render_handlers_installed_false_when_clean(cmds):
    cmds.set_state(attrs={
        **cmds.get_state().attrs,
        "defaultRenderGlobals.preMel": "",
        "defaultRenderGlobals.postMel": "",
        "defaultRenderGlobals.postRenderMel": "",
    })
    assert mp_check_render_handlers_installed() is False


def test_install_render_handlers_writes_hooks(cmds):
    cmds.set_state(attrs={
        **cmds.get_state().attrs,
        "defaultRenderGlobals.preMel": "",
        "defaultRenderGlobals.postMel": "",
        "defaultRenderGlobals.postRenderMel": "",
    })
    mp_install_render_handlers()
    for attr in ("preMel", "postMel", "postRenderMel"):
        v = cmds.get_state().attrs[f"defaultRenderGlobals.{attr}"]
        assert MP_HOOK_START in v


def test_install_render_handlers_idempotent(cmds):
    cmds.set_state(attrs={
        **cmds.get_state().attrs,
        "defaultRenderGlobals.preMel": "",
        "defaultRenderGlobals.postMel": "",
        "defaultRenderGlobals.postRenderMel": "",
    })
    mp_install_render_handlers()
    pre_len = len(cmds.get_state().attrs["defaultRenderGlobals.preMel"])
    mp_install_render_handlers()  # second call should be no-op
    assert len(cmds.get_state().attrs["defaultRenderGlobals.preMel"]) == pre_len


def test_uninstall_render_handlers_restores_clean_state(cmds):
    cmds.set_state(attrs={
        **cmds.get_state().attrs,
        "defaultRenderGlobals.preMel": "",
        "defaultRenderGlobals.postMel": "",
        "defaultRenderGlobals.postRenderMel": "",
    })
    mp_install_render_handlers()
    mp_uninstall_render_handlers()
    assert mp_check_render_handlers_installed() is False


def test_uninstall_render_handlers_preserves_unrelated_mel(cmds):
    """Pre-existing MEL outside our hook markers should survive uninstall."""
    cmds.set_state(attrs={
        **cmds.get_state().attrs,
        "defaultRenderGlobals.preMel": "print(\"hello\");",
        "defaultRenderGlobals.postMel": "",
        "defaultRenderGlobals.postRenderMel": "",
    })
    mp_install_render_handlers()
    mp_uninstall_render_handlers()
    assert cmds.get_state().attrs["defaultRenderGlobals.preMel"] == "print(\"hello\");"


# ---------------------------------------------------------------------------
# mp_update_small_icon + mp_update_large_icon + mp_update_presence_details
# ---------------------------------------------------------------------------

from maya_presence import (  # noqa: E402
    mp_update_small_icon, mp_update_large_icon, mp_update_presence_details,
    MP_SESSION, MP_UPDATE_DETAILS,
)


@pytest.fixture
def maya_globals_clean():
    """Snapshot/restore module-level Maya globals (MP_PREFS, MP_SESSION,
    MP_UPDATE_DETAILS) touched by update_* functions."""
    snap = (
        MP_PREFS.displaySmallIcon, MP_PREFS.displayEngine, MP_PREFS.displayGPU,
        MP_PREFS.displayVersion, MP_PREFS.enableDetails, MP_PREFS.displayRenderStats,
        MP_PREFS.displayFrames, MP_PREFS.displayFileName,
        MP_SESSION.is_rendering, MP_SESSION.rendered_frames,
        MP_UPDATE_DETAILS.small_icon, MP_UPDATE_DETAILS.large_icon,
        MP_UPDATE_DETAILS.large_icon_text, MP_UPDATE_DETAILS.details_text,
    )
    yield
    (MP_PREFS.displaySmallIcon, MP_PREFS.displayEngine, MP_PREFS.displayGPU,
     MP_PREFS.displayVersion, MP_PREFS.enableDetails, MP_PREFS.displayRenderStats,
     MP_PREFS.displayFrames, MP_PREFS.displayFileName,
     MP_SESSION.is_rendering, MP_SESSION.rendered_frames,
     MP_UPDATE_DETAILS.small_icon, MP_UPDATE_DETAILS.large_icon,
     MP_UPDATE_DETAILS.large_icon_text, MP_UPDATE_DETAILS.details_text) = snap


def test_update_small_icon_disabled_pref_empty(cmds, maya_globals_clean):
    MP_PREFS.displaySmallIcon = False
    ctx = MPContext.capture()
    mp_update_small_icon(ctx)
    # The function initializes icon_file_name to None; when displaySmallIcon
    # is False, the body is skipped and small_icon stays at None.
    assert MP_UPDATE_DETAILS.small_icon is None


@pytest.mark.parametrize("renderer, expected_icon", [
    ("arnold", "arnold"),
    ("redshift", "redshift"),
    ("renderman", "renderman"),
    ("vray", "vray"),
])
def test_update_small_icon_engine_during_render(cmds, maya_globals_clean,
                                                  renderer, expected_icon):
    MP_PREFS.displaySmallIcon = True
    MP_PREFS.displayEngine = True
    MP_SESSION.is_rendering = True
    cmds.set_state(attrs={
        **cmds.get_state().attrs,
        "defaultRenderGlobals.currentRenderer": renderer,
    })
    ctx = MPContext.capture()
    mp_update_small_icon(ctx)
    assert MP_UPDATE_DETAILS.small_icon == expected_icon


def test_update_small_icon_workspace_layout(cmds, maya_globals_clean):
    """A non-'general' workspace layout drives the icon name (first word)."""
    MP_PREFS.displaySmallIcon = True
    MP_PREFS.displayEngine = False
    MP_SESSION.is_rendering = False
    cmds.set_state(workspace_layout="modeling - expert")
    ctx = MPContext.capture()
    mp_update_small_icon(ctx)
    assert MP_UPDATE_DETAILS.small_icon == "modeling"


def test_update_small_icon_workspace_single_word(cmds, maya_globals_clean):
    """A single-word workspace name (no space) becomes the icon as-is."""
    MP_PREFS.displaySmallIcon = True
    MP_PREFS.displayEngine = False
    MP_SESSION.is_rendering = False
    cmds.set_state(workspace_layout="rigging")
    ctx = MPContext.capture()
    mp_update_small_icon(ctx)
    assert MP_UPDATE_DETAILS.small_icon == "rigging"


@pytest.mark.parametrize("tool_ctx, expected", [
    ("polyCreateFaceCtx", "modeling"),
    ("manipMoveContext", "modeling"),
    ("curveCV_Ctx", "modeling"),
    ("targetWeldCtx", "modeling"),
    ("sculptMeshCacheCtx", "sculpt"),
    ("texSelectCtx", "uv"),
    ("jointCtx", "pose"),
    ("ikHandleCtx", "pose"),
    ("skinPaintCtx", "pose"),
    ("keyframeTangentMarkingMenuCtx", "animation"),
    ("filterScaleKeysCtx", "animation"),
])
def test_update_small_icon_tool_context_falls_through_to_currentctx(
        cmds, maya_globals_clean, tool_ctx, expected):
    """When workspace_layout is 'general' (or absent), the tool-context
    prefix decides the icon."""
    MP_PREFS.displaySmallIcon = True
    MP_PREFS.displayEngine = False
    MP_SESSION.is_rendering = False
    cmds.set_state(workspace_layout="general", current_ctx=tool_ctx)
    ctx = MPContext.capture()
    mp_update_small_icon(ctx)
    assert MP_UPDATE_DETAILS.small_icon == expected


def test_update_small_icon_unknown_tool_no_icon(cmds, maya_globals_clean):
    """A tool context that doesn't match any known prefix leaves small_icon
    at its initial None (no branch taken)."""
    MP_PREFS.displaySmallIcon = True
    MP_PREFS.displayEngine = False
    MP_SESSION.is_rendering = False
    cmds.set_state(workspace_layout="general", current_ctx="someUnknownCtx")
    ctx = MPContext.capture()
    mp_update_small_icon(ctx)
    assert MP_UPDATE_DETAILS.small_icon is None


def test_update_large_icon_with_version(cmds, maya_globals_clean):
    MP_PREFS.displayVersion = True
    cmds.set_state(about_responses={
        **cmds.get_state().about_responses,
        "majorVersion": "2026", "minorVersion": "0", "patchVersion": "5",
    })
    ctx = MPContext.capture()
    mp_update_large_icon(ctx)
    assert MP_UPDATE_DETAILS.large_icon == "maya"
    assert "2026.0.5" in MP_UPDATE_DETAILS.large_icon_text
    assert "Maya" in MP_UPDATE_DETAILS.large_icon_text


def test_update_large_icon_without_version(cmds, maya_globals_clean):
    MP_PREFS.displayVersion = False
    ctx = MPContext.capture()
    mp_update_large_icon(ctx)
    assert MP_UPDATE_DETAILS.large_icon_text == "Maya"


def test_get_gpu_str_empty_card_returns_empty(cmds):
    """When openGLExtension returns an empty string, get_gpu_str returns ''."""
    cmds.set_state(gl_renderer="")
    ctx = MPContext.capture()
    assert ctx.get_gpu_str() == ""


def test_get_current_scene_file_only_no_project(cmds):
    """When the project query returns empty but the file has a name, fall
    through to returning just the file stem."""
    cmds.set_state(project_short_name="", scene_name="/p/maya/lonely_scene.mb")
    ctx = MPContext.capture()
    assert ctx.get_current_scene() == "lonely_scene"


def test_get_version_str_falls_back_to_version_kwarg(cmds):
    """If the per-component about() queries raise, get_version_str falls back
    to about(version=True)."""
    cmds.set_state(
        about_raises={"majorVersion", "minorVersion", "patchVersion"},
        about_responses={**cmds.get_state().about_responses, "version": "2026.5"},
    )
    ctx = MPContext.capture()
    assert ctx.get_version_str() == "2026.5"


def test_get_render_fps_unknown_unit_returns_24(cmds):
    """A unit string that isn't in the presets dict and doesn't end in 'fps'
    falls through to the final `return 24` line."""
    cmds.set_state(current_time_unit="freeform")  # not a preset, no "fps" suffix
    ctx = MPContext.capture()
    assert ctx.get_render_fps() == 24


def test_get_render_fps_runtimeerror_returns_24(cmds):
    """If currentUnit raises (no current unit), return 24 as a safe default."""
    cmds.set_state(current_time_unit="")  # empty -> fake raises RuntimeError
    ctx = MPContext.capture()
    assert ctx.get_render_fps() == 24


def test_update_presence_details_rendering_branch(cmds, maya_globals_clean):
    """When rendering, details_text incorporates resolution + rendered-frame
    counter + fps. The frame number comes from MP_SESSION.rendered_frames
    (driven by render callbacks) — not from the cursor position."""
    MP_PREFS.enableDetails = True
    MP_PREFS.displayRenderStats = True
    MP_PREFS.displayFrames = True
    MP_PREFS.displayFileName = True
    MP_SESSION.is_rendering = True
    MP_SESSION.rendered_frames = 17
    cmds.set_state(
        scene_name="/p/maya/scene01.mb",
        current_time=15.0, min_time=10.0, max_time=110.0,
        current_time_unit="film",  # → 24fps
        attrs={
            **cmds.get_state().attrs,
            "defaultResolution.width": 1920,
            "defaultResolution.height": 1080,
        },
    )
    ctx = MPContext.capture()
    mp_update_presence_details(ctx)
    out = MP_UPDATE_DETAILS.details_text
    assert "Rendering" in out
    assert "scene01" in out
    assert "1920x1080" in out
    assert "Frame 17 of 101" in out
    assert "24fps" in out


def test_update_presence_details_non_rendering_uses_update_slot(cmds, maya_globals_clean):
    """When not rendering, the function delegates to mp_update_slot which
    reads detailsType and feeds in the matching display lambda's result."""
    MP_PREFS.enableDetails = True
    MP_PREFS.detailsType = "scene"
    MP_PREFS.customDetails = ""
    MP_PREFS.detailsCycle = False
    MP_SESSION.is_rendering = False
    cmds.set_state(project_short_name="ScenicProject", scene_name="")
    ctx = MPContext.capture()
    mp_update_presence_details(ctx)
    assert "ScenicProject" in MP_UPDATE_DETAILS.details_text


# --- mp_update_presence_state ---

from maya_presence import mp_update_presence_state  # noqa: E402


def test_update_presence_state_writes_state_text(cmds, maya_globals_clean):
    """update_presence_state delegates to mp_update_slot for the state field."""
    MP_PREFS.enableState = True
    MP_PREFS.stateType = "scene"
    MP_PREFS.customState = ""
    MP_PREFS.stateCycle = False
    MP_PREFS.detailsType = "frame"  # peer must differ to not get skipped
    cmds.set_state(project_short_name="StateProject", scene_name="")
    ctx = MPContext.capture()
    mp_update_presence_state(ctx)
    assert "StateProject" in MP_UPDATE_DETAILS.state_text


def test_update_presence_state_disabled_clears(cmds, maya_globals_clean):
    MP_PREFS.enableState = False
    MP_UPDATE_DETAILS.state_text = "stale"
    ctx = MPContext.capture()
    mp_update_presence_state(ctx)
    assert MP_UPDATE_DETAILS.state_text == ""


# ---------------------------------------------------------------------------
# update_small_icon: remaining branches
# ---------------------------------------------------------------------------

def test_update_small_icon_engine_not_in_engines_clears_text(cmds, maya_globals_clean):
    """A render-time engine that isn't in the mapped set (Arnold/Redshift/
    RenderMan/V-Ray/Octane) yields no icon AND no text — the rule is that
    icon_text never appears without an icon to go with it."""
    MP_PREFS.displaySmallIcon = True
    MP_PREFS.displayEngine = True
    MP_PREFS.displayGPU = False
    MP_SESSION.is_rendering = True
    cmds.set_state(attrs={**cmds.get_state().attrs,
                          "defaultRenderGlobals.currentRenderer": "mayaSoftware"})
    ctx = MPContext.capture()
    mp_update_small_icon(ctx)
    assert MP_UPDATE_DETAILS.small_icon is None
    assert MP_UPDATE_DETAILS.small_icon_text == ""


def test_update_small_icon_gpu_not_shown_without_engine_icon(cmds, maya_globals_clean):
    """displayGPU only piggybacks onto existing icon_text — for an unmapped
    engine there's no icon and no text, so the GPU string is suppressed too."""
    MP_PREFS.displaySmallIcon = True
    MP_PREFS.displayEngine = True
    MP_PREFS.displayGPU = True
    MP_SESSION.is_rendering = True
    cmds.set_state(
        attrs={**cmds.get_state().attrs,
               "defaultRenderGlobals.currentRenderer": "mayaSoftware"},
        gl_renderer="NVIDIA GeForce RTX 4090/PCIe/SSE2",
    )
    ctx = MPContext.capture()
    mp_update_small_icon(ctx)
    assert MP_UPDATE_DETAILS.small_icon is None
    assert MP_UPDATE_DETAILS.small_icon_text == ""


def test_update_small_icon_mapped_engine_appends_gpu(cmds, maya_globals_clean):
    """Mapped engine -> icon_file_name AND icon_text set to engine name;
    displayGPU then appends ' | <gpu>'."""
    MP_PREFS.displaySmallIcon = True
    MP_PREFS.displayEngine = True
    MP_PREFS.displayGPU = True
    MP_SESSION.is_rendering = True
    cmds.set_state(
        attrs={**cmds.get_state().attrs,
               "defaultRenderGlobals.currentRenderer": "arnold"},
        gl_renderer="NVIDIA GeForce RTX 5090/PCIe/SSE2",
    )
    ctx = MPContext.capture()
    mp_update_small_icon(ctx)
    assert MP_UPDATE_DETAILS.small_icon == "arnold"
    assert MP_UPDATE_DETAILS.small_icon_text.startswith("Arnold")
    assert "|" in MP_UPDATE_DETAILS.small_icon_text
    assert "RTX 5090" in MP_UPDATE_DETAILS.small_icon_text


def test_update_small_icon_octane_now_recognized(cmds, maya_globals_clean):
    """Regression: Octane was added to the mapped engines set so it gets the
    same icon-plus-text treatment as Arnold/Redshift/RenderMan/V-Ray."""
    MP_PREFS.displaySmallIcon = True
    MP_PREFS.displayEngine = True
    MP_PREFS.displayGPU = False
    MP_SESSION.is_rendering = True
    cmds.set_state(attrs={**cmds.get_state().attrs,
                          "defaultRenderGlobals.currentRenderer": "Octane"})
    ctx = MPContext.capture()
    mp_update_small_icon(ctx)
    assert MP_UPDATE_DETAILS.small_icon == "octane"
    assert MP_UPDATE_DETAILS.small_icon_text == "Octane"


def test_update_small_icon_workspace_layout_exception_falls_through(cmds, maya_globals_clean):
    """If workspaceLayoutManager raises, we fall through to the tool-context
    cascade rather than blowing up."""
    MP_PREFS.displaySmallIcon = True
    MP_PREFS.displayEngine = False
    MP_SESSION.is_rendering = False
    cmds.set_state(raise_workspace_layout=True, current_ctx="polyCreateFaceCtx")
    ctx = MPContext.capture()
    mp_update_small_icon(ctx)
    assert MP_UPDATE_DETAILS.small_icon == "modeling"


# ---------------------------------------------------------------------------
# Render handler edge cases: exceptions on getAttr / setAttr
# ---------------------------------------------------------------------------

def test_check_render_handlers_installed_swallows_runtimeerror(cmds):
    """If getAttr raises on any of the three plugs, check returns False
    (assumed not installed) rather than propagating."""
    cmds.set_state(attrs_raise={"defaultRenderGlobals.preMel"})
    assert mp_check_render_handlers_installed() is False


def test_install_render_handlers_logs_and_continues_on_setattr_error(cmds, capsys):
    """If setAttr raises on one of the three plugs, install_render_handlers
    logs but continues to the next plug. Other attrs should still be written."""
    cmds.set_state(
        attrs={
            **cmds.get_state().attrs,
            "defaultRenderGlobals.preMel": "",
            "defaultRenderGlobals.postMel": "",
            "defaultRenderGlobals.postRenderMel": "",
        },
        setattr_raises={"defaultRenderGlobals.preMel"},
    )
    mp_install_render_handlers()
    captured = capsys.readouterr()
    assert "MayaPresence" in captured.out
    # preMel didn't get written (raised), but the other two did:
    assert MP_HOOK_START in cmds.get_state().attrs["defaultRenderGlobals.postMel"]
    assert MP_HOOK_START in cmds.get_state().attrs["defaultRenderGlobals.postRenderMel"]


def test_install_render_handlers_handles_missing_attr(cmds):
    """If getAttr returns None (attr exists but has no value), use '' so we
    can still concatenate the hook MEL."""
    cmds.set_state(attrs={
        **cmds.get_state().attrs,
        "defaultRenderGlobals.preMel": None,
        "defaultRenderGlobals.postMel": None,
        "defaultRenderGlobals.postRenderMel": None,
    })
    mp_install_render_handlers()
    assert MP_HOOK_START in cmds.get_state().attrs["defaultRenderGlobals.preMel"]


def test_uninstall_render_handlers_handles_setattr_error(cmds, capsys):
    """A RuntimeError from setAttr during uninstall is logged but doesn't kill
    the call; subsequent attrs still get cleaned up."""
    cmds.set_state(attrs={
        **cmds.get_state().attrs,
        "defaultRenderGlobals.preMel": "",
        "defaultRenderGlobals.postMel": "",
        "defaultRenderGlobals.postRenderMel": "",
    })
    mp_install_render_handlers()
    cmds.set_state(setattr_raises={"defaultRenderGlobals.preMel"})
    mp_uninstall_render_handlers()
    captured = capsys.readouterr()
    assert "MayaPresence" in captured.out
    # The two unaffected attrs should now be clean.
    assert MP_HOOK_START not in cmds.get_state().attrs["defaultRenderGlobals.postMel"]
    assert MP_HOOK_START not in cmds.get_state().attrs["defaultRenderGlobals.postRenderMel"]


# ---------------------------------------------------------------------------
# Maya OpenMaya callbacks: mp_add_callbacks / mp_remove_callbacks
# ---------------------------------------------------------------------------

from maya_presence import mp_add_callbacks, mp_remove_callbacks, MP_CALLBACKS  # noqa: E402


@pytest.fixture
def maya_callbacks_clean():
    """Snapshot/restore MP_CALLBACKS to prevent test pollution."""
    snap = set(MP_CALLBACKS)
    yield
    MP_CALLBACKS.clear()
    MP_CALLBACKS.update(snap)


def test_mp_add_callbacks_registers_expected_events(maya_callbacks_clean):
    """add_callbacks registers four MSceneMessage callbacks: kAfterNew /
    kAfterOpen (install render handlers into fresh or opened scenes) plus
    kAfterPluginLoad / kAfterPluginUnload (monitor render-engine plugins).
    kBeforeSave / kAfterSave used to be here for a remove-then-reinstall
    dance around saves, but that kept the scene permanently dirty after
    every save — handlers now persist across saves and the try/except MEL
    wrapper keeps non-plugin collaborators from seeing errors."""
    MP_CALLBACKS.clear()
    mp_add_callbacks()
    names = {name for name, _ in MP_CALLBACKS}
    assert names == {
        "kAfterNew", "kAfterOpen", "kAfterPluginLoad", "kAfterPluginUnload",
    }
    # kBeforeSave / kAfterSave are intentionally absent now.
    assert "kBeforeSave" not in names
    assert "kAfterSave" not in names
    # Each entry has a unique callback id (an int from the fake).
    ids = [cid for _, cid in MP_CALLBACKS]
    assert len(set(ids)) == len(ids)


def test_mp_remove_callbacks_clears_set(maya_callbacks_clean):
    MP_CALLBACKS.clear()
    mp_add_callbacks()
    assert len(MP_CALLBACKS) == 4
    mp_remove_callbacks()
    assert len(MP_CALLBACKS) == 0


def test_mp_remove_callbacks_idempotent(maya_callbacks_clean):
    """Calling remove on an already-empty set is a no-op."""
    MP_CALLBACKS.clear()
    mp_remove_callbacks()  # nothing to remove
    assert len(MP_CALLBACKS) == 0


# ---------------------------------------------------------------------------
# mp_update_presence: generalEnable=False clear semantics
# (the bug: clear() raises on unconnected pypresence client; clear is a
# write not a close, so connected stays True on success.)
# ---------------------------------------------------------------------------

import maya_presence as _mp_module  # noqa: E402
from maya_presence import mp_update_presence  # noqa: E402


# The RPC-client interaction is owned by an in-process worker that
# mp_update_presence reaches via _get_worker() — which reads the canonical
# worker reference from `builtins.__mayapresence_worker__`. That indirection
# exists because Maya's plug-in loader can create more than one copy of
# maya_presence's module namespace (the MEL render hooks' `import
# maya_presence` doesn't get cached in sys.modules), so we can't rely on
# module-level MP_WORKER being non-None in every caller's namespace.
#
# These tests install a fake worker into builtins for the duration of the
# test, then assert against the publishes it recorded.

import builtins as _builtins  # noqa: E402


class _FakeWorker:
    """Minimal stand-in for _MPRPCWorker that records publishes."""

    def __init__(self):
        self.publishes: List[Tuple[Any, Any]] = []
        self.last_published = None
        self.last_publish_enable = None
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self, timeout=2.0):
        self.stopped = True

    def publish(self, details):
        # Mirror _MPRPCWorker.publish — record the details snapshot.
        # (Prefs are no longer published; the real worker reads its
        # _general_enable flag directly. Tests treat any publish call
        # as "enabled" since mp_update_presence is the only caller and
        # only calls publish when generalEnable is True.)
        self.publishes.append(details)
        self.last_published = details
        self.last_publish_enable = True


@pytest.fixture
def fake_worker(monkeypatch):
    """Swap the canonical worker (on builtins) and the module-level
    MP_WORKER for a recording fake. Both reads (the _get_worker() path
    and any direct module references) resolve to the fake during the
    test, and the previous value (if any) is restored on teardown."""
    fw = _FakeWorker()
    attr = _mp_module.MP_WORKER_ATTR
    had_prior = hasattr(_builtins, attr)
    prior = getattr(_builtins, attr, None) if had_prior else None
    setattr(_builtins, attr, fw)
    monkeypatch.setattr(_mp_module, "MP_WORKER", fw)
    yield fw
    # Restore builtins state (monkeypatch handles the module attribute).
    if had_prior:
        setattr(_builtins, attr, prior)
    else:
        try:
            delattr(_builtins, attr)
        except AttributeError:
            pass


def test_update_presence_always_publishes_details(cmds, maya_globals_clean, fake_worker):
    """mp_update_presence always hands the latest composed details to
    the worker; the decision of whether to push or clear is made inside
    the worker's tick (which reads its own _general_enable snapshot)."""
    MP_PREFS.generalEnable = False
    mp_update_presence()
    assert fake_worker.last_published is not None
    # The publish is unconditional from the caller's side.
    assert len(fake_worker.publishes) == 1


def test_update_presence_enabled_publishes_details(cmds, maya_globals_clean, fake_worker):
    """generalEnable=True publishes the current RPCUpdateDetails to the
    worker. The worker is responsible for converting that into the
    pypresence client.update() kwargs via rpc_update."""
    MP_PREFS.generalEnable = True
    MP_PREFS.generalUpdate = 25
    MP_PREFS.enableTime = True
    mp_update_presence()
    assert fake_worker.last_publish_enable is True
    details = fake_worker.last_published
    assert details is not None
    # The worker is handed the RPCUpdateDetails directly; verify the
    # expected fields are populated.
    assert details.large_icon == "maya"
    assert hasattr(details, "state_text")
    assert hasattr(details, "details_text")


def test_update_presence_handles_missing_worker(cmds, maya_globals_clean, monkeypatch):
    """If the canonical worker is unset (plugin not started yet, or torn
    down), mp_update_presence must not crash — just compose-and-skip."""
    attr = _mp_module.MP_WORKER_ATTR
    had_prior = hasattr(_builtins, attr)
    prior = getattr(_builtins, attr, None) if had_prior else None
    if had_prior:
        delattr(_builtins, attr)
    monkeypatch.setattr(_mp_module, "MP_WORKER", None)
    try:
        MP_PREFS.generalEnable = True
        mp_update_presence()  # should not raise
    finally:
        if had_prior:
            setattr(_builtins, attr, prior)


def test_update_presence_reads_worker_from_builtins(cmds, maya_globals_clean,
                                                    monkeypatch):
    """Dual-module guarantee: mp_update_presence MUST read the worker
    from the builtins-stash, not from the module-level MP_WORKER, so a
    MEL-imported duplicate of maya_presence (which has MP_WORKER=None)
    still publishes to the original module's worker."""
    fw = _FakeWorker()
    attr = _mp_module.MP_WORKER_ATTR
    had_prior = hasattr(_builtins, attr)
    prior = getattr(_builtins, attr, None) if had_prior else None
    setattr(_builtins, attr, fw)
    # Simulate the duplicate module having a None module-level MP_WORKER.
    monkeypatch.setattr(_mp_module, "MP_WORKER", None)
    try:
        MP_PREFS.generalEnable = True
        mp_update_presence()
        assert fw.last_publish_enable is True
    finally:
        if had_prior:
            setattr(_builtins, attr, prior)
        else:
            try:
                delattr(_builtins, attr)
            except AttributeError:
                pass


# Note: the previous build_payload tests were removed when _build_payload
# stopped existing — the threaded worker stores RPCUpdateDetails directly
# and hands it to common.rpc_update, which owns the empty-details-text
# substitution. That behavior is covered by tests in tests/common.


def test_shared_state_across_module_copies():
    """Dual-module guarantee for prefs/session/details: a second import
    of maya_presence should observe the same canonical instances on
    builtins. We can't actually import a duplicate module in-process
    (sys.modules caches the first one) — but we can verify the stash
    contract: the module-level names ARE the builtins-stashed instances."""
    import builtins as _b  # noqa: PLC0415
    import maya_presence as _mp  # noqa: PLC0415
    assert _mp.MP_PREFS is getattr(_b, _mp.MP_PREFS_ATTR)
    assert _mp.MP_SESSION is getattr(_b, _mp.MP_SESSION_ATTR)
    assert _mp.MP_UPDATE_DETAILS is getattr(_b, _mp.MP_UPDATE_DETAILS_ATTR)


def test_get_gpu_str_no_slash_preserves_full_name(cmds):
    cmds.set_state(gl_renderer="Intel Iris Xe Graphics")
    ctx = MPContext.capture()
    assert ctx.get_gpu_str() == "Intel Iris Xe Graphics"


def test_extension_monitor_count_handles_none_listnodetypes(cmds):
    cmds.set_state(node_types_by_path={
        "rendernode/arnold/light": None,  # plugin loaded but no light types
        "rendernode/arnold/shader": ["aiStandardSurface"],
        "rendernode/arnold/texture": ["aiImage"],
    })
    mon = MPExtensionMonitor()
    mon.init_engine("Arnold")
    snap = MP_PREFS.countExtensions
    MP_PREFS.countExtensions = True
    try:
        # Should treat the missing light category as zero, not crash.
        assert mon.count(MPExtensionMonitor.TypeCategory.LIGHT) == 0
    finally:
        MP_PREFS.countExtensions = snap


def test_uninstall_render_handlers_skips_empty_attrs_correctly(cmds):
    cmds.set_state(attrs={
        **cmds.get_state().attrs,
        "defaultRenderGlobals.preMel": "",  # never had hooks
        "defaultRenderGlobals.postMel":
            f"{MP_HOOK_START} python(\"pass\") /* MayaPresence:Hook:End */",
        "defaultRenderGlobals.postRenderMel":
            f"{MP_HOOK_START} python(\"pass\") /* MayaPresence:Hook:End */",
    })
    mp_uninstall_render_handlers()
    assert MP_HOOK_START not in cmds.get_state().attrs["defaultRenderGlobals.postMel"]
    assert MP_HOOK_START not in cmds.get_state().attrs["defaultRenderGlobals.postRenderMel"]


def test_check_render_handlers_installed_continues_past_runtimeerror(cmds):
    cmds.set_state(
        attrs={
            **cmds.get_state().attrs,
            "defaultRenderGlobals.postMel":
                f"{MP_HOOK_START} python(\"pass\") /* MayaPresence:Hook:End */",
        },
        attrs_raise={"defaultRenderGlobals.preMel"},
    )
    assert mp_check_render_handlers_installed() is True
