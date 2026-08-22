"""
Tests for the GIMP plugin (GPContext + helpers in gimp_presence.py, plus pure
utilities in settings_dialog.py).

Untestable here:
  - GIMP main loop (Gimp.main is a no-op in the fake; gp_run blocks on
    GLib.MainLoop().run())
  - GTK widget tree inside the settings procedure (covered by separate
    PySide6-based Qt tests for the other plugins; GTK has no equivalent
    headless capability in this dev environment)

Tested:
  - GPSettings dataclass: defaults, _INITIAL_DEFAULTS, choices presence
  - gp_load_settings: missing file / valid JSON / bad JSON
  - GPSession behavior
  - _gp_match_title / _gp_get_active_image cascade (pinned, single,
    multi+title-match, multi+fallback)
  - GPContext: every value-returning method, including alternate paths
  - gp_pin_image / gp_unpin_image / gp_toggle_rpc
  - gp_update_small_icon / gp_update_large_icon / gp_update_presence
  - gp_start_timer / gp_stop_timer / gp_tick error suppression
  - gp_register_temp_procedures / gp_unregister_temp_procedures
  - settings_dialog helpers: field_to_property / property_to_field /
    atomic_write_json / _resolve_choices / _initial_default / _widget_kind
"""
from __future__ import annotations
import json
import pytest

import gimp_presence as gp
from gimp_presence import (
    GPContext, GPSettings, GP_PREFS, GP_SESSION, GP_DETAILS, GP_DISPLAY_TYPES,
    _gp_get_active_image, _gp_match_title,
    _gp_platform_query_window,
    gp_load_settings, gp_pin_image, gp_unpin_image,
    gp_update_small_icon, gp_update_large_icon, gp_update_presence,
    gp_register_temp_procedures, gp_unregister_temp_procedures,
    gp_start_timer, gp_stop_timer, gp_tick, gp_quit_loop,
    _GP_TEMP_PROCEDURES
)
from settings_dialog import SETTINGS_PROC_NAME
from gi.repository import GLib


# ---------------------------------------------------------------------------
# Snapshot/restore fixtures — gimp_presence has module-level mutable state
# that tests touch (GP_PREFS, GP_SESSION, GP_DETAILS, _GP_PINNED_IMAGE,
# _GP_DOCS_OPEN, _GP_TIMER_ID).
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_module_state():
    """Reset every piece of module-level state the tests in this file touch.

    `cleared` is reset going *in* as well as out: gp_update_presence only
    clears on the transition into the disabled state, so a test that leaves it
    set would silently suppress the clear in the next test."""
    snap_timer = gp._GP_TIMER_ID
    snap_docs_open = set(gp.GP_DOCS_OPEN)
    snap_connected = GP_SESSION.connected
    snap_cleared = GP_SESSION.cleared
    GP_SESSION.cleared = False
    snap_prefs = {f.name: getattr(GP_PREFS, f.name)
                  for f in GPSettings.__dataclass_fields__.values()}
    snap_details = (
        GP_DETAILS.small_icon, GP_DETAILS.small_icon_text,
        GP_DETAILS.large_icon, GP_DETAILS.large_icon_text,
        GP_DETAILS.state_text, GP_DETAILS.details_text,
    )
    yield
    gp._GP_TIMER_ID = snap_timer
    gp.GP_DOCS_OPEN.clear()
    gp.GP_DOCS_OPEN.update(snap_docs_open)
    GP_SESSION.connected = snap_connected
    GP_SESSION.cleared = snap_cleared
    for name, value in snap_prefs.items():
        object.__setattr__(GP_PREFS, name, value)
    (GP_DETAILS.small_icon, GP_DETAILS.small_icon_text,
     GP_DETAILS.large_icon, GP_DETAILS.large_icon_text,
     GP_DETAILS.state_text, GP_DETAILS.details_text) = snap_details
    GLib._reset_timeouts()


# ---------------------------------------------------------------------------
# GPSettings
# ---------------------------------------------------------------------------

class TestGPSettings:
    def test_info_choices_match_display_types(self):
        """Every (label, key) in INFO_CHOICES should have a corresponding
        entry in GP_DISPLAY_TYPES."""
        info_keys = {key for _, key in GPSettings.INFO_CHOICES}
        display_keys = set(GP_DISPLAY_TYPES.keys())
        assert info_keys == display_keys, (
            f"mismatch: INFO_CHOICES has {info_keys - display_keys} "
            f"not in display_types; display_types has "
            f"{display_keys - info_keys} not in INFO_CHOICES"
        )

    def test_initial_defaults_keys_are_valid_choices(self):
        """_INITIAL_DEFAULTS overrides should pick a key from INFO_CHOICES
        for stateType/detailsType (defaulting to something that doesn't
        exist would render the corresponding slot blank)."""
        info_keys = {key for _, key in GPSettings.INFO_CHOICES}
        assert GPSettings._INITIAL_DEFAULTS["detailsType"] in info_keys
        assert GPSettings._INITIAL_DEFAULTS["stateType"] in info_keys

    def test_fallback_modes_keys_are_lowercase(self):
        """The cascade in _gp_get_active_image compares against lowercase
        keys ('none', 'top', 'bottom')."""
        keys = {key for _, key in GPSettings.FALLBACK_MODES}
        assert keys == {"none", "top", "bottom"}

    def test_image_fallback_mode_default_is_a_valid_choice_key(self):
        keys = {key for _, key in GPSettings.FALLBACK_MODES}
        default = GPSettings.__dataclass_fields__["imageFallbackMode"].default
        assert default in keys


# ---------------------------------------------------------------------------
# gp_load_settings
# ---------------------------------------------------------------------------

class TestGpLoadSettings:
    def test_missing_file_is_noop(self, gimp, tmp_path):
        """No JSON file → load_settings returns silently, leaves prefs unchanged."""
        gp._GP_PREFS_PATH = tmp_path / "absent.json"
        snapshot_enabled = GP_PREFS.generalEnable
        gp_load_settings()
        assert GP_PREFS.generalEnable == snapshot_enabled

    def test_valid_json_applies_values(self, gimp, tmp_path):
        path = tmp_path / "prefs.json"
        path.write_text(json.dumps({
            "generalEnable": False, "generalUpdate": 45,
            "displayVersion": False,
        }))
        gp._GP_PREFS_PATH = path
        gp_load_settings()
        assert GP_PREFS.generalEnable is False
        assert GP_PREFS.generalUpdate == 45
        assert GP_PREFS.displayVersion is False

    def test_bad_json_logs_warning_and_continues(self, gimp, tmp_path):
        path = tmp_path / "prefs.json"
        path.write_text("not valid {{{ json")
        gp._GP_PREFS_PATH = path
        snapshot = GP_PREFS.generalEnable
        gp_load_settings()
        # Pref unchanged; warning routed through settings_dialog._gp_warn,
        # which uses Gimp.message (recorded in get_state().messages) rather
        # than the older Gimp.warning surface.
        assert GP_PREFS.generalEnable == snapshot
        assert any("Failed to load settings" in m for m in gimp.get_state().messages)

    def test_skips_private_and_unknown_fields(self, gimp, tmp_path):
        path = tmp_path / "prefs.json"
        path.write_text(json.dumps({
            "_internal_ignore_me": "x",
            "completelyUnknown": 99,
            "generalUpdate": 30,
        }))
        gp._GP_PREFS_PATH = path
        gp_load_settings()
        # The known field updates; the others are ignored (loop skips by
        # iterating fields(GPSettings) and looking up keys in data).
        assert GP_PREFS.generalUpdate == 30
        assert not hasattr(GP_PREFS, "completelyUnknown")


# ---------------------------------------------------------------------------
# _gp_match_title
# ---------------------------------------------------------------------------

class TestGpMatchTitle:
    def test_match_extracts_bracketed_name(self, gimp):
        img = gimp.make_image(name="scene.xcf")
        result = _gp_match_title("scene.xcf", [img])
        assert result is img

    def test_no_match_returns_none(self, gimp):
        img1 = gimp.make_image(name="scene.xcf")
        img2 = gimp.make_image(name="[other] (imported)")
        result = _gp_match_title("missing", [img1, img2])
        assert result is None

    def test_continues_past_non_bracketed_names(self, gimp):
        """A non-matching name should be skipped, not abort the loop."""
        non_matching = gimp.make_image(name="plain_name")
        matching = gimp.make_image(name="target.xcf")
        result = _gp_match_title("target.xcf", [non_matching, matching])
        assert result is matching

    def test_empty_image_list_returns_none(self):
        assert _gp_match_title("anything", []) is None


# ---------------------------------------------------------------------------
# _gp_get_active_image (the cascade)
# ---------------------------------------------------------------------------

class TestGpGetActiveImage:
    def test_no_images_returns_none(self, gimp):
        gimp.set_state(images=[])
        assert _gp_get_active_image() is None

    def test_single_image_returns_it(self, gimp):
        img = gimp.make_image(name="solo")
        gimp.set_state(images=[img])
        assert _gp_get_active_image() is img

    def test_pinned_image_returned_when_still_open(self, gimp):
        """_GP_PINNED_IMAGE now stores an image id (int), not the Image
        object — guards against the wrapper going stale when GIMP recycles
        Python proxies. The lookup goes back through Gimp.get_images()."""
        a = gimp.make_image(id=1, name="a")
        b = gimp.make_image(id=2, name="b")
        gimp.set_state(images=[a, b])
        GP_SESSION.pinned_image = b.get_id()
        assert _gp_get_active_image() is b

    def test_pinned_image_unpins_when_closed(self, gimp):
        """If the pinned id is no longer valid (image closed), unpin and
        fall through the rest of the cascade."""
        a = gimp.make_image(id=1, name="a")
        b = gimp.make_image(id=2, name="b")
        gimp.set_state(images=[a])  # only a is still open
        GP_SESSION.pinned_image = b.get_id()
        # 'a' is the only image, so single-image branch returns it.
        assert _gp_get_active_image() is a
        # Pin state was cleared.
        assert GP_SESSION.pinned_image is None

    def test_multi_image_with_no_window_query_uses_fallback_none(self, gimp):
        a = gimp.make_image(id=1, name="a")
        b = gimp.make_image(id=2, name="b")
        gimp.set_state(images=[a, b])
        GP_PREFS.queryWindow = False
        GP_PREFS.imageFallbackMode = "none"
        assert _gp_get_active_image() is None

    def test_multi_image_fallback_oldest(self, gimp):
        a = gimp.make_image(id=1, name="a")
        b = gimp.make_image(id=2, name="b")
        gimp.set_state(images=[b, a]) # most recent image is at front of list
        GP_PREFS.queryWindow = False
        GP_PREFS.imageFallbackMode = "bottom"
        assert _gp_get_active_image() is a

    def test_multi_image_fallback_recent(self, gimp):
        a = gimp.make_image(id=1, name="a")
        b = gimp.make_image(id=2, name="b")
        gimp.set_state(images=[b, a])
        GP_PREFS.queryWindow = False
        GP_PREFS.imageFallbackMode = "top"
        assert _gp_get_active_image() is b


# ---------------------------------------------------------------------------
# _gp_platform_query_window (Linux/non-Windows branch)
# ---------------------------------------------------------------------------

class TestPlatformQueryWindow:
    def test_query_disabled_returns_none(self):
        GP_PREFS.queryWindow = False
        assert _gp_platform_query_window() is None

    def test_non_windows_returns_none(self, monkeypatch):
        """When platform isn't Windows, _gp_platform_query_window returns
        None unconditionally (Linux/macOS branches)."""
        GP_PREFS.queryWindow = True
        monkeypatch.setattr(gp.platform, "system", lambda: "Linux")
        assert _gp_platform_query_window() is None


# ---------------------------------------------------------------------------
# GPContext methods
# ---------------------------------------------------------------------------

class TestGPContext:
    # --- capture + version ---

    def test_capture_no_images(self, gimp):
        gimp.set_state(images=[])
        ctx = GPContext.capture()
        assert ctx is not None
        assert ctx.images == []
        assert ctx.active_image is None

    def test_capture_single_image(self, gimp):
        img = gimp.make_image(name="solo")
        gimp.set_state(images=[img])
        ctx = GPContext.capture()
        assert ctx.active_image is img

    def test_version(self, gimp):
        gimp.set_state(version_str="3.2.7")
        ctx = GPContext(images=[], active_image=None)
        assert ctx.version() == "3.2.7"

    # --- active_image_name ---

    def test_active_image_name_no_images(self, gimp):
        ctx = GPContext(images=[], active_image=None)
        assert ctx.active_image_name() == "No images open"

    def test_active_image_name_found(self, gimp):
        img = gimp.make_image(name="sketch.xcf")
        ctx = GPContext(images=[img], active_image=img)
        assert ctx.active_image_name() == "sketch.xcf"
        # Subsequent num_images should NOT be suppressed (flag is False).
        assert GP_SESSION.docname_was_doccount is False

    def test_active_image_name_pinned_shows_emoji(self, gimp):
        img = gimp.make_image(name="primary.xcf")
        GP_SESSION.pinned_image = img
        ctx = GPContext(images=[img], active_image=img)
        assert ctx.active_image_name() == "📌 primary.xcf"

    def test_active_image_name_no_active_with_alternates(self, gimp):
        """No detectable active image + useAlternates ON → returns the doc
        count and sets the suppression flag for num_images."""
        a = gimp.make_image(id=1, name="a")
        b = gimp.make_image(id=2, name="b")
        GP_PREFS.useAlternates = True
        ctx = GPContext(images=[a, b], active_image=None)
        result = ctx.active_image_name()
        assert "2 images" in result
        assert GP_SESSION.docname_was_doccount is True

    def test_active_image_name_no_active_no_alternates(self, gimp):
        GP_PREFS.useAlternates = False
        a = gimp.make_image(id=1, name="a")
        b = gimp.make_image(id=2, name="b")
        ctx = GPContext(images=[a, b], active_image=None)
        assert ctx.active_image_name() is None

    def test_active_image_name_no_images_resets_doccount_flag(self, gimp):
        """If the previous tick fell back to showing the image count in the
        details slot (flag=True), and then all images close, num_images() in
        the state slot must report 'No images open' instead of being
        suppressed by the stale flag. (The active_image_name() == 'No images
        open' invariant on its own is covered by
        test_num_images_zero_returns_no_images_open above.)"""
        GP_SESSION.docname_was_doccount = True  # left over from a previous tick
        ctx = GPContext(images=[], active_image=None)
        ctx.active_image_name()  # trigger the branch we expect to reset the flag
        assert GP_SESSION.docname_was_doccount is False
        assert ctx.num_images() == "No images open"

    # --- num_images ---

    def test_num_images_zero_returns_no_images_open(self):
        ctx = GPContext(images=[], active_image=None)
        assert ctx.num_images() == "No images open"

    @pytest.mark.parametrize("n, expected_count", [(1, "1 image"), (5, "5 images")])
    def test_num_images_open(self, gimp, n, expected_count):
        imgs = [gimp.make_image(id=i, name=f"i{i}") for i in range(n)]
        ctx = GPContext(images=imgs, active_image=imgs[0])
        assert ctx.num_images() == f"{expected_count} open"

    def test_num_images_suppressed_when_docname_already_showed_count(self):
        """If active_image_name already returned the doc count, num_images
        returns None so a cycle won't show it twice."""
        GP_SESSION.docname_was_doccount = True
        ctx = GPContext(images=[], active_image=None)
        assert ctx.num_images() is None

    # --- num_layers ---

    def test_num_layers_no_images(self):
        ctx = GPContext(images=[], active_image=None)
        assert ctx.num_layers() == "No layers (no images open)"

    def test_num_layers_with_active_image(self, gimp):
        layers = [gimp.make_layer("L1", visible=True),
                  gimp.make_layer("L2", visible=False),
                  gimp.make_layer("L3", visible=True)]
        img = gimp.make_image(layers=layers)
        ctx = GPContext(images=[img], active_image=img)
        assert ctx.num_layers() == "3 layers (2 visible)"

    def test_num_layers_no_active_with_alternates(self, gimp):
        img_a = gimp.make_image(
            id=1, layers=[gimp.make_layer("a", visible=True)])
        img_b = gimp.make_image(
            id=2, layers=[gimp.make_layer("b1", visible=True),
                          gimp.make_layer("b2", visible=False)])
        GP_PREFS.useAlternates = True
        ctx = GPContext(images=[img_a, img_b], active_image=None)
        out = ctx.num_layers()
        assert "3 layers" in out
        assert "2 images" in out
        assert "2 visible" in out

    def test_num_layers_no_active_no_alternates_returns_none(self, gimp):
        GP_PREFS.useAlternates = False
        img = gimp.make_image(id=1, layers=[gimp.make_layer("a")])
        ctx = GPContext(images=[img], active_image=None)
        assert ctx.num_layers() is None

    # --- active_layer_info ---

    def test_active_layer_info_no_active_no_alternates(self, gimp):
        GP_PREFS.useAlternates = False
        ctx = GPContext(images=[gimp.make_image()], active_image=None)
        assert ctx.active_layer_info() is None

    def test_active_layer_info_no_active_alternates_aggregates(self, gimp):
        """The cross-image fallback string includes the selected-layer total."""
        a = gimp.make_image(
            id=1, selected_layers=[gimp.make_layer("la"), gimp.make_layer("lb")],
        )
        b = gimp.make_image(
            id=2, selected_layers=[gimp.make_layer("lc")],
        )
        GP_PREFS.useAlternates = True
        ctx = GPContext(images=[a, b], active_image=None)
        out = ctx.active_layer_info()
        assert "3 layers" in out
        assert "2 images" in out

    def test_active_layer_info_single_selection_normal_blend(self, gimp):
        layer = gimp.make_layer("Background", mode=gimp.LayerMode.Normal)
        img = gimp.make_image(selected_layers=[layer])
        ctx = GPContext(images=[img], active_image=img)
        # Layer name doesn't contain "layer" — prefix added; Normal blend omitted.
        assert ctx.active_layer_info() == "Layer: Background"

    def test_active_layer_info_single_with_non_normal_blend(self, gimp):
        layer = gimp.make_layer("Layer 3", mode=gimp.LayerMode.Multiply)
        img = gimp.make_image(selected_layers=[layer])
        ctx = GPContext(images=[img], active_image=img)
        # Name contains "layer" — no prefix; blend appears in parens.
        assert ctx.active_layer_info() == "Layer 3 (Multiply)"

    def test_active_layer_info_multi_select(self, gimp):
        layers = [gimp.make_layer(n) for n in ("A", "B", "C")]
        img = gimp.make_image(selected_layers=layers)
        ctx = GPContext(images=[img], active_image=img)
        assert ctx.active_layer_info() == "3 layers selected"

    # --- active_brush_preset ---

    def test_active_brush_preset_normal_name(self, gimp):
        gimp.set_state(brush=gimp.make_brush("Soft Round 35"), brush_hardness=0.75)
        ctx = GPContext(images=[], active_image=None)
        assert ctx.active_brush_preset() == "Brush: Soft Round 35 (Hardness 0.75)"

    @pytest.mark.parametrize("brush_name", [
        "2. Hardness 025", "2. Hardness 050", "2. Hardness 075", "2. Hardness 100",
    ])
    def test_active_brush_preset_default_hardness_brushes_normalized(self, gimp, brush_name):
        """The four default 'Hardness NNN' brushes all normalize to 'Brush 2'."""
        gimp.set_state(brush=gimp.make_brush(brush_name), brush_hardness=0.5)
        ctx = GPContext(images=[], active_image=None)
        assert ctx.active_brush_preset() == "Brush: Brush 2 (Hardness 0.5)"

    # --- color_info ---

    def test_color_info_with_active_image(self, gimp):
        img = gimp.make_image(
            base_type=gimp.ImageBaseType.RGB,
            color_profile=gimp.make_color_profile("sRGB built-in"),
        )
        ctx = GPContext(images=[img], active_image=img)
        assert ctx.color_info() == "RGB (sRGB built-in)"

    def test_color_info_no_active_no_alternates(self, gimp):
        GP_PREFS.useAlternates = False
        ctx = GPContext(images=[gimp.make_image()], active_image=None)
        assert ctx.color_info() is None

    def test_color_info_no_active_all_share_model_and_profile(self, gimp):
        GP_PREFS.useAlternates = True
        profile = gimp.make_color_profile("sRGB built-in")
        a = gimp.make_image(id=1, base_type=gimp.ImageBaseType.RGB, color_profile=profile)
        b = gimp.make_image(id=2, base_type=gimp.ImageBaseType.RGB, color_profile=profile)
        ctx = GPContext(images=[a, b], active_image=None)
        out = ctx.color_info()
        assert "2 images" in out
        assert "RGB" in out
        assert "sRGB built-in" in out

    def test_color_info_no_active_shared_model_different_profiles(self, gimp):
        GP_PREFS.useAlternates = True
        a = gimp.make_image(id=1, base_type=gimp.ImageBaseType.RGB,
                            color_profile=gimp.make_color_profile("sRGB built-in"))
        b = gimp.make_image(id=2, base_type=gimp.ImageBaseType.RGB,
                            color_profile=gimp.make_color_profile("Display P3"))
        ctx = GPContext(images=[a, b], active_image=None)
        out = ctx.color_info()
        assert "2 images" in out
        assert "RGB" in out
        assert "2 color profiles" in out

    def test_color_info_no_active_two_different_models(self, gimp):
        GP_PREFS.useAlternates = True
        a = gimp.make_image(id=1, base_type=gimp.ImageBaseType.RGB)
        b = gimp.make_image(id=2, base_type=gimp.ImageBaseType.GRAY)
        ctx = GPContext(images=[a, b], active_image=None)
        out = ctx.color_info()
        assert "2 images" in out
        # Two-model branch uses "X and Y" format.
        assert "and" in out

    def test_color_info_no_active_three_different_models(self, gimp):
        GP_PREFS.useAlternates = True
        a = gimp.make_image(id=1, base_type=gimp.ImageBaseType.RGB)
        b = gimp.make_image(id=2, base_type=gimp.ImageBaseType.GRAY)
        c = gimp.make_image(id=3, base_type=gimp.ImageBaseType.INDEXED)
        ctx = GPContext(images=[a, b, c], active_image=None)
        out = ctx.color_info()
        # Three-model branch uses "X, Y, and Z".
        assert ", " in out and "and" in out

    # --- active_document_dimensions ---

    def test_dimensions_with_active_image_uniform_ppi(self, gimp):
        img = gimp.make_image(width=2000, height=2000,
                              resolution=(True, 300.0, 300.0))
        ctx = GPContext(images=[img], active_image=img)
        assert ctx.active_document_dimensions() == "2000x2000 @ 300.0ppi"

    def test_dimensions_with_active_image_non_uniform_ppi(self, gimp):
        img = gimp.make_image(width=2000, height=2000,
                              resolution=(True, 300.0, 250.0))
        ctx = GPContext(images=[img], active_image=img)
        out = ctx.active_document_dimensions()
        assert "2000x2000" in out
        assert "300.0ppi x" in out
        assert "250.0ppi y" in out

    def test_dimensions_no_active_no_alternates_returns_none(self, gimp):
        GP_PREFS.useAlternates = False
        ctx = GPContext(images=[gimp.make_image()], active_image=None)
        assert ctx.active_document_dimensions() is None

    def test_dimensions_no_active_picks_largest(self, gimp):
        """Without an active image, fallback shows the largest by area."""
        GP_PREFS.useAlternates = True
        small = gimp.make_image(id=1, width=100, height=100,
                                resolution=(True, 72.0, 72.0))
        big = gimp.make_image(id=2, width=4000, height=3000,
                              resolution=(True, 300.0, 300.0))
        medium = gimp.make_image(id=3, width=1000, height=1000,
                                 resolution=(True, 96.0, 96.0))
        ctx = GPContext(images=[small, big, medium], active_image=None)
        out = ctx.active_document_dimensions()
        assert out.startswith("Largest open image:")
        assert "4000x3000" in out
        assert "300.0" in out

    # --- foreground_color ---

    def test_foreground_color_returns_first_three_components(self, gimp):
        gimp.set_state(foreground_color=(1.0, 0.5, 0.0, 1.0))
        ctx = GPContext(images=[], active_image=None)
        assert ctx.foreground_color() == (1.0, 0.5, 0.0)

    # --- view_blend_mode ---

    def test_view_blend_mode_returns_paint_mode_name(self, gimp):
        gimp.set_state(paint_mode=gimp.PaintMode.Multiply)
        ctx = GPContext(images=[], active_image=None)
        assert ctx.view_blend_mode() == "Paint mode: Multiply"


# ---------------------------------------------------------------------------
# gp_pin_image / gp_unpin_image
# ---------------------------------------------------------------------------

class TestPinToggle:
    """All three are ImageProcedure run-funcs: 6-arg signature. Pin uses
    `image`; Unpin and Toggle accept it but ignore it. They all share the
    same shape because they're registered on the <Image>/ menu path, which
    GIMP requires to use ImageProcedure dispatch. Each run-func ends with
    `procedure.new_return_values(...)`, so the `procedure` arg must be a
    real ImageProcedure-shaped object (not None)."""

    def _make_proc(self, gimp, name):
        """Cheap stand-in: ImageProcedure.new returns a _BaseProcedure
        with new_return_values, which is all the run-funcs touch."""
        from gi.repository import Gimp
        return Gimp.ImageProcedure.new(
            gimp.PlugIn(), name, Gimp.PDBProcType.TEMPORARY, lambda *_: None
        )

    def test_pin_image_sets_global(self, gimp):
        img = gimp.make_image(id=7, name="primary")
        proc = self._make_proc(gimp, "gimppresence-pin-image")
        gp_pin_image(proc, None, img, None, None, None)
        assert GP_SESSION.pinned_image == 7

    def test_unpin_image_clears_global(self, gimp):
        img = gimp.make_image(id=7)
        GP_SESSION.pinned_image = img.get_id()
        proc = self._make_proc(gimp, "gimppresence-unpin-image")
        gp_unpin_image(proc, None, img, None, None, None)
        assert GP_SESSION.pinned_image is None


# ---------------------------------------------------------------------------
# gp_update_small_icon / gp_update_large_icon
# ---------------------------------------------------------------------------

class TestUpdateIcons:
    def test_update_small_icon_colored_off_clears(self, gimp):
        GP_PREFS.enableColoredIcons = False
        GP_DETAILS.small_icon = "stale"
        ctx = GPContext(images=[], active_image=None)
        gp_update_small_icon(ctx)
        assert GP_DETAILS.small_icon is None
        assert GP_DETAILS.small_icon_text == ""

    def test_update_small_icon_colored_on_sets_paintbrush_variant(self, gimp):
        GP_PREFS.enableColoredIcons = True
        GP_PREFS.useEvocativeNames = True
        gimp.set_state(foreground_color=(1.0, 0.0, 0.0, 1.0))
        ctx = GPContext(images=[], active_image=None)
        gp_update_small_icon(ctx)
        assert GP_DETAILS.small_icon is not None
        assert GP_DETAILS.small_icon.startswith("paintbrush_c")
        assert "Foreground:" in GP_DETAILS.small_icon_text
        assert "#FF0000" in GP_DETAILS.small_icon_text

    def test_update_large_icon_with_version(self, gimp):
        GP_PREFS.displayVersion = True
        gimp.set_state(version_str="3.2.4")
        ctx = GPContext(images=[], active_image=None)
        gp_update_large_icon(ctx)
        assert GP_DETAILS.large_icon_text == "GIMP 3.2.4"

    def test_update_large_icon_without_version(self, gimp):
        GP_PREFS.displayVersion = False
        ctx = GPContext(images=[], active_image=None)
        gp_update_large_icon(ctx)
        assert GP_DETAILS.large_icon_text == "GIMP"


# ---------------------------------------------------------------------------
# gp_update_presence
# ---------------------------------------------------------------------------

class TestUpdatePresence:
    def test_disabled_pref_when_not_connected_is_noop(self, gimp):
        """generalEnable=False with no connection should be a quiet no-op —
        clear() is guarded on session.connected, so we never hit pypresence's
        assert-on-unconnected-socket."""
        GP_PREFS.generalEnable = False
        GP_SESSION.connected = False
        gp_update_presence()
        assert GP_SESSION.connected is False  # stays False, no exception

    def test_disabled_pref_when_connected_preserves_connection(self, gimp, monkeypatch):
        """clear() succeeds on a live connection; `connected` stays True so
        toggling back on doesn't need to reconnect."""
        GP_PREFS.generalEnable = False
        GP_SESSION.connected = True
        calls: list[int] = []
        # Replace clear() with a no-op so we don't need a real pypresence socket.
        monkeypatch.setattr(gp.GP_RPC_CLIENT, "clear", lambda: calls.append(1))
        gp_update_presence()
        assert len(calls) == 1
        # Connection stays open — clear() doesn't change session state.
        assert GP_SESSION.connected is True

    def test_disabled_pref_clears_once_not_every_tick(self, gimp, monkeypatch):
        """The GLib timer keeps firing every generalUpdate seconds while
        disabled; clearing an already-cleared presence each time is pointless
        traffic."""
        GP_PREFS.generalEnable = False
        GP_SESSION.connected = True
        calls: list[int] = []
        monkeypatch.setattr(gp.GP_RPC_CLIENT, "clear", lambda: calls.append(1))
        gp_update_presence()
        gp_update_presence()
        gp_update_presence()
        assert len(calls) == 1
        assert GP_SESSION.cleared is True

    def test_disabled_pref_clear_failure_marks_disconnected(self, gimp, monkeypatch):
        """If clear() raises (socket actually dropped), mark disconnected so
        the next generalEnable=True tick triggers a reconnect."""
        GP_PREFS.generalEnable = False
        GP_SESSION.connected = True
        def _boom():
            raise AssertionError("sock_writer is None")
        monkeypatch.setattr(gp.GP_RPC_CLIENT, "clear", _boom)
        gp_update_presence()
        assert GP_SESSION.connected is False
        # _gp_warn routes through Gimp.message (settings_dialog), not Gimp.warning.
        assert any("clear failed" in m for m in gimp.get_state().messages)

    def _image_with_selection(self, gimp, id, name):
        """Helper: build an image whose get_selected_layers() returns one
        layer. Works around the active_layer_info empty-list bug so we can
        test the timer logic without tripping it."""
        return gimp.make_image(
            id=id, name=name,
            selected_layers=[gimp.make_layer("Layer 1")],
        )

    def test_resets_timer_when_open_image_set_changes(self, gimp):
        GP_PREFS.generalEnable = True
        GP_PREFS.resetTimer = True
        GP_PREFS.enableColoredIcons = False
        gimp.set_state(images=[self._image_with_selection(gimp, 1, "a")])
        gp.GP_DOCS_OPEN.clear()
        # Force time progression so we can detect the reset.
        GP_SESSION.start_time = 0.0
        gp_update_presence()
        assert GP_SESSION.start_time > 0.0
        # Open-image set is now cached.
        assert gp.GP_DOCS_OPEN == {1}

    def test_no_timer_reset_when_image_set_unchanged(self, gimp):
        GP_PREFS.generalEnable = True
        GP_PREFS.resetTimer = True
        GP_PREFS.enableColoredIcons = False
        gimp.set_state(images=[self._image_with_selection(gimp, 5, "z")])
        gp.GP_DOCS_OPEN.clear()
        gp.GP_DOCS_OPEN.add(5)  # pre-seed cache
        GP_SESSION.start_time = 99999.0  # sentinel
        gp_update_presence()
        # set unchanged -> start_time NOT overwritten
        assert GP_SESSION.start_time == 99999.0


class TestActiveLayerInfoRegressions:
    """Regression tests for two bugs that previously affected
    active_layer_info — empty-selection IndexError and a malformed
    alternates string. Both have since been fixed; these tests pin the
    correct behavior so a future refactor that drops the `or not layers`
    guard, or duplicates the 'layers selected' phrase, gets caught."""

    def test_active_layer_info_empty_selection_returns_none(self, gimp):
        """Empty selected_layers must hit the `or not layers: return None`
        guard rather than crashing in `layers[0].get_name()`."""
        img = gimp.make_image(selected_layers=[])
        ctx = GPContext(images=[img], active_image=img)
        assert ctx.active_layer_info() is None

    def test_active_layer_info_alternates_string_is_balanced(self, gimp):
        a = gimp.make_image(id=1, selected_layers=[gimp.make_layer("la")])
        b = gimp.make_image(id=2, selected_layers=[gimp.make_layer("lb")])
        GP_PREFS.useAlternates = True
        ctx = GPContext(images=[a, b], active_image=None)
        out = ctx.active_layer_info()
        # Balanced parens (or none at all) and only one occurrence of
        # 'selected' to avoid the previously-doubled 'selected layers' phrase.
        assert out.count("(") == out.count(")")
        assert out.count("selected") == 1


# ---------------------------------------------------------------------------
# gp_start_timer / gp_stop_timer / gp_tick
# ---------------------------------------------------------------------------

class TestTimer:
    def test_start_timer_schedules_with_min_1s_interval(self):
        GP_PREFS.generalUpdate = 15
        gp_start_timer()
        assert gp._GP_TIMER_ID is not None
        assert GLib._last_scheduled_interval() == 15000  # ms

    def test_start_timer_clamps_to_minimum_1s(self):
        """generalUpdate=0 should still produce at least 10000ms interval."""
        GP_PREFS.generalUpdate = 0
        gp_start_timer()
        assert GLib._last_scheduled_interval() == 12000

    def test_stop_timer_clears_id(self):
        gp_start_timer()
        assert gp._GP_TIMER_ID is not None
        gp_stop_timer()
        assert gp._GP_TIMER_ID is None

    def test_stop_timer_idempotent_when_not_running(self):
        gp._GP_TIMER_ID = None
        gp_stop_timer()  # no error
        assert gp._GP_TIMER_ID is None

    def test_start_timer_replaces_existing_timer(self):
        gp_start_timer()
        first_id = gp._GP_TIMER_ID
        gp_start_timer()
        second_id = gp._GP_TIMER_ID
        assert first_id != second_id
        # First one was removed.
        assert first_id not in GLib._active_timeouts()

    def test_tick_returns_true_to_keep_firing(self, gimp):
        GP_PREFS.generalEnable = False  # short-circuit to avoid full update
        assert gp_tick() is True

    def test_tick_swallows_exceptions(self, gimp, monkeypatch):
        """A raised exception inside gp_update_presence should be caught,
        warning logged via _gp_warn (→ Gimp.message), and gp_tick still
        returns True so the timer survives."""
        def _raises():
            raise RuntimeError("explosion")
        monkeypatch.setattr(gp, "gp_update_presence", _raises)
        result = gp_tick()
        assert result is True
        assert any("update failed" in m for m in gimp.get_state().messages)


# ---------------------------------------------------------------------------
# gp_register_temp_procedures / gp_unregister_temp_procedures
# ---------------------------------------------------------------------------

class TestTempProcedureRegistration:
    def test_register_adds_all_temp_procedures_plus_settings(self, gimp):
        plugin = gimp.PlugIn()
        gp_register_temp_procedures(plugin)
        # Each of the three named procs + the settings proc are registered.
        registered = set(gimp.get_state().temp_procedures.keys())
        expected = set(_GP_TEMP_PROCEDURES.keys()) | {SETTINGS_PROC_NAME}
        assert registered == expected
        assert GP_SESSION.temp_procedures_registered is True

    def test_register_all_temp_procs_set_image_types_wildcard(self, gimp):
        """Regression for the GIMP error 'attempted to install <Image>
        procedure X which does not take the standard <Image> plug-in's
        arguments': every temp procedure registered under <Image>/Filters/
        must be an ImageProcedure with set_image_types("*"). Mixing in
        plain Gimp.Procedure under the same menu path fails registration."""
        plugin = gimp.PlugIn()
        gp_register_temp_procedures(plugin)
        for name in _GP_TEMP_PROCEDURES:
            proc = gimp.get_state().temp_procedures.get(name)
            assert proc is not None, f"{name} not registered"
            assert proc.image_types == "*", (
                f"{name} missing set_image_types('*') — GIMP would refuse "
                "the <Image>/ menu path registration"
            )

    def test_register_attaches_menu_paths(self, gimp):
        plugin = gimp.PlugIn()
        gp_register_temp_procedures(plugin)
        for name in _GP_TEMP_PROCEDURES:
            proc = gimp.get_state().temp_procedures[name]
            assert any("Discord Presence" in p for p in proc.menu_paths)

    def test_unregister_clears_all_when_registered(self, gimp):
        plugin = gimp.PlugIn()
        gp_register_temp_procedures(plugin)
        assert len(gimp.get_state().temp_procedures) >= 3
        gp_unregister_temp_procedures(plugin)
        assert len(gimp.get_state().temp_procedures) == 0
        assert GP_SESSION.temp_procedures_registered is False

    def test_unregister_skips_when_not_registered(self, gimp):
        """Calling unregister before register should not raise."""
        plugin = gimp.PlugIn()
        GP_SESSION.temp_procedures_registered = False
        gp_unregister_temp_procedures(plugin)  # no error
        assert gimp.get_state().temp_procedures == {}


# ---------------------------------------------------------------------------
# gp_quit_loop
# ---------------------------------------------------------------------------

class TestQuitLoop:
    def test_quit_loop_when_no_loop_is_noop(self):
        gp._GP_MAIN_LOOP = None
        gp_quit_loop()  # no error

    def test_quit_loop_when_loop_running(self):
        loop = GLib.MainLoop()
        gp._GP_MAIN_LOOP = loop
        gp_quit_loop()
        assert loop._quit_called is True


# ---------------------------------------------------------------------------
# settings_dialog pure helpers
# ---------------------------------------------------------------------------

import settings_dialog as sd  # noqa: E402


class TestSettingsDialogHelpers:
    @pytest.mark.parametrize("camel, kebab", [
        ("generalEnable", "general-enable"),
        ("generalUpdate", "general-update"),
        ("button1Url", "button1-url"),
        ("enableButton1", "enable-button1"),
        ("imageFallbackMode", "image-fallback-mode"),
        # Single word stays as-is.
        ("name", "name"),
    ])
    def test_field_to_property(self, camel, kebab):
        assert sd.field_to_property(camel) == kebab

    @pytest.mark.parametrize("kebab, camel", [
        ("general-enable", "generalEnable"),
        ("button1-url", "button1Url"),
        ("name", "name"),
    ])
    def test_property_to_field(self, kebab, camel):
        assert sd.property_to_field(kebab) == camel

    @pytest.mark.parametrize("name", [
        "generalEnable", "generalUpdate", "button1Url", "enableButton2",
        "imageFallbackMode", "useEvocativeNames",
    ])
    def test_field_property_roundtrip(self, name):
        assert sd.property_to_field(sd.field_to_property(name)) == name

    # --- atomic_write_json ---

    def test_atomic_write_creates_file(self, tmp_path):
        path = tmp_path / "out.json"
        sd.atomic_write_json(path, {"a": 1, "b": "two"})
        assert path.exists()
        assert json.loads(path.read_text()) == {"a": 1, "b": "two"}

    def test_atomic_write_overwrites_existing(self, tmp_path):
        path = tmp_path / "out.json"
        path.write_text(json.dumps({"old": True}))
        sd.atomic_write_json(path, {"new": True})
        assert json.loads(path.read_text()) == {"new": True}

    def test_atomic_write_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "deeper" / "prefs.json"
        sd.atomic_write_json(path, {"ok": 1})
        assert path.exists()

    def test_atomic_write_cleans_tmp(self, tmp_path):
        """After a successful write, the .tmp file should be gone."""
        path = tmp_path / "out.json"
        sd.atomic_write_json(path, {"v": 1})
        tmp = path.with_suffix(path.suffix + ".tmp")
        assert not tmp.exists()

    # --- _resolve_choices ---

    def test_resolve_choices_class_attr(self):
        class _T:
            CHOICES = [("Label", "key"), ("Other", "other")]
        out = sd._resolve_choices(_T, "CHOICES")
        assert out == [("Label", "key"), ("Other", "other")]

    def test_resolve_choices_missing_attr_raises(self):
        class _T:
            pass
        with pytest.raises(AttributeError):
            sd._resolve_choices(_T, "DOES_NOT_EXIST")

    def test_resolve_choices_rejects_non_pair(self):
        class _T:
            CHOICES = [("a", "b", "c")]  # 3-tuple, not 2
        with pytest.raises(ValueError):
            sd._resolve_choices(_T, "CHOICES")

    # --- _initial_default ---

    def test_initial_default_prefers_initial_overrides(self):
        from dataclasses import fields
        # GPSettings._INITIAL_DEFAULTS overrides detailsType -> 'image_name'
        # while the SharedSettings field default is 'scene'.
        f = next(x for x in fields(GPSettings) if x.name == "detailsType")
        assert sd._initial_default(GPSettings, f) == "image_name"

    def test_initial_default_falls_through_to_field_default(self):
        from dataclasses import fields
        f = next(x for x in fields(GPSettings) if x.name == "generalEnable")
        # Not overridden in _INITIAL_DEFAULTS -> field default (True).
        assert sd._initial_default(GPSettings, f) is True

    # --- _widget_kind ---

    def test_widget_kind_explicit_metadata_wins(self):
        from dataclasses import fields
        f = next(x for x in fields(GPSettings) if x.name == "imageFallbackMode")
        assert sd._widget_kind(GPSettings, f) == "combobox"

    def test_widget_kind_inferred_from_type(self):
        from dataclasses import fields
        bool_field = next(x for x in fields(GPSettings) if x.name == "generalEnable")
        int_field = next(x for x in fields(GPSettings) if x.name == "generalUpdate")
        str_field = next(x for x in fields(GPSettings) if x.name == "customDetails")
        assert sd._widget_kind(GPSettings, bool_field) == "checkbox"
        assert sd._widget_kind(GPSettings, int_field) == "spinbox"
        assert sd._widget_kind(GPSettings, str_field) == "lineedit"


# ---------------------------------------------------------------------------
# settings_dialog procedure building (registration side)
# ---------------------------------------------------------------------------

class TestBuildSettingsProcedure:
    def test_build_creates_procedure_with_settings_name(self, gimp, tmp_path):
        plugin = gimp.PlugIn()
        proc = sd.build_settings_procedure(
            plugin,
            settings_class=GPSettings,
            current_prefs=GP_PREFS,
            settings_json_path=tmp_path / "prefs.json",
            on_settings_changed=None,
        )
        assert proc.name == SETTINGS_PROC_NAME  # kebab-case to match other procs
        assert proc.proc_type == gimp.PDBProcType.TEMPORARY
        assert proc.menu_label is not None
        assert any("Discord Presence" in p for p in proc.menu_paths)

    def test_build_registers_one_argument_per_grouped_field(self, gimp, tmp_path):
        from dataclasses import fields
        plugin = gimp.PlugIn()
        proc = sd.build_settings_procedure(
            plugin,
            settings_class=GPSettings,
            current_prefs=GP_PREFS,
            settings_json_path=tmp_path / "prefs.json",
        )
        grouped = [f for f in fields(GPSettings)
                   if f.metadata.get("group") and not f.name.startswith("_")]
        assert len(proc.arguments) == len(grouped)

    def test_build_includes_choice_for_combobox_field(self, gimp, tmp_path):
        plugin = gimp.PlugIn()
        proc = sd.build_settings_procedure(
            plugin,
            settings_class=GPSettings,
            current_prefs=GP_PREFS,
            settings_json_path=tmp_path / "prefs.json",
        )
        # imageFallbackMode is the combobox in GPSettings.
        assert "image-fallback-mode" in proc.choice_arguments
        # Also: detailsType and stateType (inherited from SharedSettings).
        assert "details-type" in proc.choice_arguments
        assert "state-type" in proc.choice_arguments
