#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GimpPresence is a Discord Rich Presence client plugin for GIMP, tested on
GIMP 3.2.4. For more info, see https://github.com/MarlArini/dcc-rpc.
"""

import csv
from dataclasses import dataclass, field, fields
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import ClassVar, List, Tuple, Dict, Callable, Set, Any

from pypresence.presence import Presence

# pylint: disable=wrong-import-position, wrong-import-order, import-error
import gi  # pyright: ignore[reportMissingImports]

gi.require_version("Gimp", "3.0")
from gi.repository import Gimp  # pyright: ignore[reportMissingImports] # noqa: E402
from gi.repository import GLib  # pyright: ignore[reportMissingImports] # noqa: E402
# pylint: enable=import-error

from common import (  # noqa: E402
    SharedSettings,
    SessionInfo,
    ColoredIconSettings,
    RPCUpdateDetails,
    plural as gp_plural,
    push_rpc_update,
    connect_rpc,
    update_slot,
    update_buttons,
    advance_cycle
)
from colors import find_closest as gp_find_closest_color  # noqa: E402
from settings_dialog import SETTINGS_PROC_NAME, build_settings_procedure, gp_warn  # noqa: E402

_GP_PREFS_PATH = Path(Gimp.directory()) / "plug-in-settings" / "gimp_presence.json"

_GP_MAIN_LOOP: GLib.MainLoop | None = None
_GP_TIMER_ID: int | None = None

# pylint: disable=unused-argument


class GPSession(SessionInfo):
    docname_was_doccount: bool = False
    pinned_image: int | None = None
    temp_procedures_registered: bool = False


GP_SESSION = GPSession()


def gp_pin_image(procedure, run_mode, image, drawables, config, *data):
    """'Pin' the currently-open image, using that image for all context queries
    until it is closed or unpinned. Registered as a temporary procedure method."""
    GP_SESSION.pinned_image = image.get_id()
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


def gp_unpin_image(procedure, run_mode, image, drawables, config, *data):
    """'Unpin' a previously pinned image. Safe to call if no image is pinned.
    Registered as a temporary procedure method."""
    GP_SESSION.pinned_image = None
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


# pylint: enable=unused-argument


############
# Settings #
############
@dataclass
class GPSettings(SharedSettings, ColoredIconSettings):
    # pylint: disable=invalid-name
    _PREFIX: ClassVar[str] = "gimpPresence_"
    INFO_CHOICES: ClassVar[List[Tuple[str, str]]] = [
        ("Active image name", "image_name"),
        ("Number of images", "image_count"),
        ("Active layer", "layer_info"),
        ("Number of layers", "layer_count"),
        ("Brush preset", "brush_preset"),
        ("Color profile", "color_info"),
        ("Image dimensions", "dimensions"),
        ("Paint mode", "paint_mode"),
    ]
    _INITIAL_DEFAULTS: ClassVar[Dict[str, Any]] = {
        "detailsType": "image_name",
        "stateType": "layer_info",
    }
    FALLBACK_MODES: ClassVar[List[Tuple[str, str]]] = [
        ("None", "none"),
        ("Most Recent / Top", "top"),
        ("Oldest / Bottom", "bottom"),
    ]
    queryWindow: bool = field(
        default=platform.system() == "Windows",
        metadata={
            "group": "General",
            "label": "Attempt to find the active image name via GIMP window title",
        },
    )
    imageFallbackMode: str = field(
        default="none",
        metadata={
            "group": "General",
            "label": "Fall back to the top image in the stack if active image queries fail",
            "widget": "combobox",
            "choices_attr": "FALLBACK_MODES",
        },
    )
    useAlternates: bool = field(
        default=True,
        metadata={
            "group": "General",
            "label": "If the active image can't be determined, display values based on all images",
        },
    )


def gp_load_settings():
    path = _GP_PREFS_PATH
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8") as settings_file:
            data = json.load(settings_file)
        for f in fields(GPSettings):
            if f.name.startswith("_") or f.metadata.get("group") is None:
                continue
            if f.name in data:
                setattr(GP_PREFS, f.name, data[f.name])
    except Exception as e:
        gp_warn(f"[GimpPresence] Failed to load settings: {e}")


GP_PREFS = GPSettings()


def _gp_platform_query_window() -> str | None:
    """Try to find the active image name from the window title of the
    GIMP application. Currently only works on Windows; safe to call on
    other platforms but will just return None."""
    if not GP_PREFS.queryWindow:
        return None
    p = platform.system()
    if p == "Windows":
        try:
            # Use Popen instead of read for faster response time / less delay
            procs = subprocess.Popen(
                ["tasklist", "/V", "/FI", "IMAGENAME eq gimp-3.exe", "/FO", "CSV"],
                stdout=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                if procs.stdout is None:
                    return None
                proc_list = (
                    procs.stdout.read().decode("utf-8").replace("\r", "").split("\n")
                )
            finally:
                if procs.stdout is not None:
                    procs.stdout.close()
                procs.poll()
            reader = csv.DictReader(proc_list)
            gimp_process_info = next(reader)
            window_title = gimp_process_info["Window Title"]

            # Non-XCF type (e.g., png/jpeg): window title is `[image name] (imported)-...`
            # Use rfind since brackets are valid characters in file names
            if ".xcf" not in window_title.lower():
                name_end = window_title.rfind("]")
                if name_end == -1 or (
                    window_title[0] != "[" and not window_title.startswith("*[")
                ):
                    return None
                return (
                    window_title[(1 if window_title[0] == "*" else 0) : name_end + 1]
                    + " (imported)"
                )
            # XCF type: window title is `image name.xcf-...`
            else:
                name_end = window_title.lower().rfind(".xcf")
                return window_title[(1 if window_title[0] == "*" else 0) : name_end + 4]

        except Exception:
            return None
    else:
        # New Linux (e.g., Ubuntu 26.04) uses Wayland, which does not expose window titles
        # Darwin development requires a MacOS device
        return None


def _gp_match_title(title: str, images: List[Gimp.Image]) -> Gimp.Image | None:
    """Given a title extracted from the window title, try to find an image with
    a matching title in the list of open images."""
    for image in images:
        if image.get_name() == title:
            return image
    return None


def _gp_get_active_image() -> Gimp.Image | None:
    """Try to find the active image. First checks if an image is pinned, then
    whether no images are open or only one is open, then tries to query the
    application window title, then finally goes to an image fallback mode."""
    pinned_image = GP_SESSION.pinned_image
    if pinned_image is not None:
        if Gimp.Image.id_is_valid(pinned_image):
            img_map = {i.get_id(): i for i in Gimp.get_images()}
            return img_map.get(pinned_image, None)
        else:
            GP_SESSION.pinned_image = None
    images = Gimp.get_images()
    if not images:
        return None
    if len(images) == 1:
        return images[0]
    else:
        title = _gp_platform_query_window()
        if title is not None:
            return _gp_match_title(title, images)
        if GP_PREFS.imageFallbackMode == "none":
            return None
        elif GP_PREFS.imageFallbackMode == "top":
            return images[0]
        else:
            return images[-1]


@dataclass
class GPContext:
    images: List[Gimp.Image]
    active_image: Gimp.Image | None

    @classmethod
    def capture(cls) -> "GPContext":
        images = Gimp.get_images()
        image = _gp_get_active_image()
        return cls(images=images, active_image=image)

    def version(self):
        return Gimp.version()

    def active_image_name(self) -> str | None:
        """Try to fetch the active image name.
        Alternate: return the number of images currently open and set a flag
        to return None on num_images calls until a fetch succeeds."""
        # Images open but unable to find active image
        if self.images and self.active_image is None:
            if GP_PREFS.useAlternates:
                num_docs = self.num_images()
                GP_SESSION.docname_was_doccount = True
                return num_docs
            else:
                return None
        GP_SESSION.docname_was_doccount = False
        # No images open
        if not self.images:
            return "No images open"
        # Found image
        elif self.active_image is not None:
            if GP_SESSION.pinned_image is not None:
                return f"📌 {self.active_image.get_name()}"
            else:
                return self.active_image.get_name()

    def num_images(self) -> str | None:
        """Return the number of images open, unless the last RPC update sent that number
        as the active image name, in which case we return None"""
        if GP_SESSION.docname_was_doccount:
            return None
        if not self.images:
            return "No images open"
        return gp_plural(len(self.images), "image") + " open"

    def num_layers(self) -> str | None:
        """Try to fetch the number of layers in the current image.
        Alternate: the number of layers across all images."""
        if not self.images:
            return "No layers (no images open)"
        if self.active_image is None:
            if GP_PREFS.useAlternates:
                count = sum(len(image.get_layers()) for image in self.images)
                vis_count = sum(
                    len([i for i in image.get_layers() if i.get_visible()])
                    for image in self.images
                )
                return (
                    f"{gp_plural(count, 'layer')} in "
                    f"{gp_plural(len(self.images), 'image')} "
                    f"({vis_count} visible)"
                )
            else:
                return None
        else:
            count = len(self.active_image.get_layers())
            vis_count = sum(
                [1 for i in self.active_image.get_layers() if i.get_visible()]
            )
            return f"{gp_plural(count, 'layer')} ({vis_count} visible)"

    def active_layer_info(self) -> str | None:
        """Try to fetch the name and blend mode of the active layer.
        If multiple layers are selected, a count of selected layers is returned.
        Alternate: return the number of layers selected across all images."""
        if self.active_image is None:
            if GP_PREFS.useAlternates and self.images:
                selected_layers = []
                for i in self.images:
                    selected_layers += i.get_selected_layers()
                count = len(selected_layers)
                return (
                    f"{gp_plural(count, 'layer')} selected in {len(self.images)} images"
                )
            else:
                return None
        layers = self.active_image.get_selected_layers()
        if layers is None or not layers:
            return None
        if len(layers) > 1:
            return f"{gp_plural(len(layers), 'layer')} selected"
        else:
            layer_name = layers[0].get_name()
            layer_blend_mode_name = layers[0].get_mode().name.title()
            blend_mode_str = (
                f" ({layer_blend_mode_name})"
                if layer_blend_mode_name != "Normal"
                else ""
            )
            if "layer" in layer_name.lower():
                return layer_name + blend_mode_str
            else:
                return f"Layer: {layer_name}" + blend_mode_str

    def active_brush_preset(self) -> str | None:
        brush_name = Gimp.context_get_brush().get_name()
        brush_hardness = Gimp.context_get_brush_hardness()
        if brush_name in [
            "2. Hardness 025",
            "2. Hardness 050",
            "2. Hardness 075",
            "2. Hardness 100",
        ]:
            brush_name = "Brush 2"
        return f"Brush: {brush_name} (Hardness {brush_hardness})"

    def _color_model(self) -> str | None:
        if self.active_image is None:
            return None
        model = self.active_image.get_base_type()
        return model.name

    def _color_profile(self) -> str | None:
        if self.active_image is None:
            return None
        profile = self.active_image.get_effective_color_profile()
        return profile.get_label()

    def color_info(self) -> str | None:
        """Try to get the color model and profile of the active image.
        Alternate: the color model[s] and profile[s] of all open images.
        """
        model, profile = self._color_model(), self._color_profile()
        if model is None or profile is None:
            if GP_PREFS.useAlternates and self.images:
                models = set(
                    [i.get_base_type().name for i in self.images]
                )
                profiles = set(
                    [i.get_effective_color_profile().get_label() for i in self.images]
                )
                images_str = f"{len(self.images)} images in "
                if len(models) == 1 and len(profiles) == 1:
                    return images_str + f"{models.pop()} ({profiles.pop()})"
                elif len(models) == 1:
                    return (
                        images_str + f"{models.pop()} ({len(profiles)} color profiles)"
                    )
                else:
                    if len(models) == 2:
                        models_str = f"{models.pop()} and {models.pop()}"
                    else:
                        models_str = (
                            f"{models.pop()}, {models.pop()}, and {models.pop()}"
                        )
                    if len(profiles) == 1:
                        profiles_str = f"({profiles.pop()})"
                    else:
                        profiles_str = f"({len(profiles)} color profiles)"
                    return images_str + models_str + profiles_str
            else:
                return None
        return f"{self._color_model()} ({self._color_profile()})"

    def _image_values(self) -> Tuple[int, int, int, int, bool] | None:
        if self.active_image is None:
            if self.images and GP_PREFS.useAlternates:
                max_w, max_h, ppi_x, ppi_y, max_area = 0, 0, 0, 0, 0
                for image in self.images:
                    w, h = image.get_width(), image.get_height()
                    res = image.get_resolution()
                    p_x, p_y = res[1], res[2]
                    area = w * h
                    if area > max_area:
                        max_w, max_h, max_area, ppi_x, ppi_y = w, h, area, p_x, p_y
                return (max_w, max_h, ppi_x, ppi_y, False)
            else:
                return None
        w, h = self.active_image.get_width(), self.active_image.get_height()
        res = self.active_image.get_resolution()
        ppi_x, ppi_y = res[1], res[2]
        return (w, h, ppi_x, ppi_y, True)

    def active_document_dimensions(self) -> str | None:
        """Try to get the size and resolution of the active image.
        Alternate: the values for the largest open image by area."""
        values = self._image_values()
        if values is None:
            return None
        dims = (values[0], values[1])
        res = (values[2], values[3])
        if values[4]:  # Active image
            if res[0] == res[1]:
                return f"{dims[0]}x{dims[1]} @ {res[0]}ppi"
            else:
                return f"{dims[0]}x{dims[1]} @ {res[0]}ppi x, {res[1]}ppi y"
        else:
            if res[0] == res[1]:
                return f"Largest open image: {dims[0]}x{dims[1]} @ {res[0]}ppi"
            else:
                return f"Largest open image: {dims[0]}x{dims[1]} @ {res[0]}ppi x, {res[1]}ppi y"

    def foreground_color(self) -> Tuple[int, int, int]:
        fg = Gimp.context_get_foreground()
        rgba = fg.get_rgba()
        return (rgba[0], rgba[1], rgba[2])

    def view_blend_mode(self) -> str:
        return f"Paint mode: {Gimp.context_get_paint_mode().name.title()}"


GP_DISPLAY_TYPES: Dict[str, Callable] = {
    "image_name": lambda ctx: ctx.active_image_name(),
    "image_count": lambda ctx: ctx.num_images(),
    "layer_info": lambda ctx: ctx.active_layer_info(),
    "layer_count": lambda ctx: ctx.num_layers(),
    "brush_preset": lambda ctx: ctx.active_brush_preset(),
    "color_info": lambda ctx: ctx.color_info(),
    "dimensions": lambda ctx: ctx.active_document_dimensions(),
    "paint_mode": lambda ctx: ctx.view_blend_mode(),
}
GP_DOCS_OPEN: Set[int] = set()
GP_DETAILS = RPCUpdateDetails("gimp")
GP_RPC_CLIENT = Presence("1510363090724720681")


def gp_update_small_icon(ctx: GPContext):  # pylint: disable=unused-argument
    GP_DETAILS.small_icon = None
    GP_DETAILS.small_icon_text = ""
    if GP_PREFS.enableColoredIcons and GP_PREFS.displaySmallIcon:
        color = ctx.foreground_color()
        closest = gp_find_closest_color(color, GP_PREFS.useEvocativeNames)
        GP_DETAILS.small_icon = f"paintbrush_{closest.icon_key_suffix}"
        GP_DETAILS.small_icon_text = (
            f"Foreground: {closest.display_name} ({closest.user_hex})"
        )


def gp_update_large_icon(ctx: GPContext):
    if GP_PREFS.displayVersion:
        GP_DETAILS.large_icon_text = f"GIMP {ctx.version()}"
    else:
        GP_DETAILS.large_icon_text = "GIMP"


def gp_push_rpc_update():
    push_rpc_update(GP_SESSION, GP_DETAILS, GP_PREFS, GP_RPC_CLIENT, "gimp", gp_warn)


def gp_update_presence():
    if not GP_PREFS.generalEnable:
        # Clear once on the transition to disabled, not on every tick.
        # push_rpc_update flips `cleared` back off on the next successful push.
        if GP_SESSION.connected and not GP_SESSION.cleared:
            try:
                GP_RPC_CLIENT.clear()
                GP_SESSION.cleared = True
            except Exception as e:  # noqa: BLE001
                gp_warn(f"[GimpPresence] clear failed: {e}")
                GP_SESSION.connected = False
        return
    ctx = GPContext.capture()
    # Update details first so if the doc name field (default) can't find the active document
    # and overrides with the document count, the state field knows to skip it on a cycle
    if GP_PREFS.detailsCycle or GP_PREFS.stateCycle:
        advance_cycle(GP_SESSION, GP_DISPLAY_TYPES)
    update_slot(ctx, "details", GP_PREFS, GP_DETAILS, GP_DISPLAY_TYPES, GP_SESSION)
    update_slot(ctx, "state", GP_PREFS, GP_DETAILS, GP_DISPLAY_TYPES, GP_SESSION)
    gp_update_large_icon(ctx)
    gp_update_small_icon(ctx)
    update_buttons(GP_DETAILS, GP_PREFS)
    # No file open callback; cache a set of open images by id between intervals
    # and if a new image appears reset the timer
    current_images = set([i.get_id() for i in Gimp.get_images()])
    global GP_DOCS_OPEN
    if current_images != GP_DOCS_OPEN:
        GP_DOCS_OPEN = current_images
        if GP_PREFS.resetTimer:
            GP_SESSION.start_time = time.time()
    gp_push_rpc_update()


_GP_PIN_DOC = (
    "Pin the currently active image",
    "Override active image detection and display statistics for the current"
    + " image until it is closed or unpinned.",
)

_GP_UNPIN_DOC = (
    "Unpin the currently pinned image",
    "Unpin the currently pinned image",
)


_GP_TEMP_PROCEDURES = {
    "gimppresence-pin-image": (gp_pin_image, "GimpPresence: Pin Image", _GP_PIN_DOC),
    "gimppresence-unpin-image": (
        gp_unpin_image,
        "GimpPresence: Unpin Image",
        _GP_UNPIN_DOC,
    ),
}


def gp_register_temp_procedures(plugin: Gimp.PlugIn):
    for proc_name, proc_details in _GP_TEMP_PROCEDURES.items():
        procedure = Gimp.ImageProcedure.new(
            plugin, proc_name, Gimp.PDBProcType.TEMPORARY, proc_details[0]
        )
        procedure.set_image_types("*")
        procedure.set_menu_label(proc_details[1])
        procedure.set_documentation(proc_details[2][0], proc_details[2][1], None)
        procedure.add_menu_path("<Image>/Filters/Discord Presence/")
        plugin.add_temp_procedure(procedure)
    settings_proc = build_settings_procedure(
        plugin,
        settings_class=GPSettings,
        current_prefs=GP_PREFS,
        settings_json_path=_GP_PREFS_PATH,  # where to atomically write
        on_settings_changed=gp_start_timer,
    )
    plugin.add_temp_procedure(settings_proc)
    GP_SESSION.temp_procedures_registered = True


def gp_unregister_temp_procedures(plugin: Gimp.PlugIn):
    if not GP_SESSION.temp_procedures_registered:
        return
    for proc_name in _GP_TEMP_PROCEDURES:
        plugin.remove_temp_procedure(proc_name)
    plugin.remove_temp_procedure(SETTINGS_PROC_NAME)
    GP_SESSION.temp_procedures_registered = False


def gp_run(procedure, config, data):  # pylint: disable=unused-argument
    global _GP_MAIN_LOOP
    plugin = procedure.get_plug_in()
    if not GP_SESSION.connected:
        GP_SESSION.connected = connect_rpc(GP_RPC_CLIENT, "gimp", gp_warn)
    gp_load_settings()
    gp_register_temp_procedures(plugin)
    gp_start_timer()
    procedure.persistent_ready()
    plugin.persistent_enable()
    _GP_MAIN_LOOP = GLib.MainLoop()
    try:
        _GP_MAIN_LOOP.run()
    finally:
        gp_stop_timer()
        gp_unregister_temp_procedures(plugin)
        if GP_SESSION.connected:
            try:
                GP_RPC_CLIENT.clear()
                GP_RPC_CLIENT.close()
            except Exception as _:
                pass
        _GP_MAIN_LOOP = None
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


def gp_start_timer():
    global _GP_TIMER_ID
    gp_stop_timer()
    interval = max(12000, GP_PREFS.generalUpdate * 1000)
    _GP_TIMER_ID = GLib.timeout_add(interval, gp_tick)


def gp_stop_timer():
    global _GP_TIMER_ID
    if _GP_TIMER_ID is not None:
        GLib.source_remove(_GP_TIMER_ID)
        _GP_TIMER_ID = None


def gp_tick():
    try:
        gp_update_presence()
    except Exception as e:
        gp_warn(f"[GimpPresence] update failed: {e}")
    return True


def gp_quit_loop():
    if _GP_MAIN_LOOP is not None:
        _GP_MAIN_LOOP.quit()


class GPPlugin(Gimp.PlugIn):
    _gp_procedures = ["gimppresence-run"]

    def do_query_procedures(self):
        return self._gp_procedures

    def do_create_procedure(self, name):
        if name == "gimppresence-run":
            procedure = Gimp.Procedure.new(
                self, name, Gimp.PDBProcType.PERSISTENT, gp_run, None
            )
            procedure.set_menu_label("GimpPresence Client (Background)")
            procedure.set_documentation(
                "GimpPresence background process."
                + " Runs continuously and sends updates to Discord."
            )
        else:
            procedure = None
        return procedure

    def do_quit(self):
        gp_quit_loop()


Gimp.main(GPPlugin.__gtype__, sys.argv)
