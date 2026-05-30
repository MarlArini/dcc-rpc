#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GimpPresence is a Discord Rich Presence client plugin for GIMP, tested on
GIMP 3.2.4. For more info, see https://github.com/MarlArini/dcc-rpc.
"""

import csv
from dataclasses import dataclass, field, fields
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from typing import ClassVar, List, Tuple, Dict, Callable, Set

from pypresence.presence import Presence

# pylint:disable=wrong-import-position,wrong-import-order, import-error
import gi  # pyright: ignore[reportMissingImports]

gi.require_version("Gimp", "3.0")
from gi.repository import Gimp  # pyright: ignore[reportMissingImports] # noqa: E402
from gi.repository import GLib  # pyright: ignore[reportMissingImports] # noqa: E402
# pylint: enable=import-error

from common import (  # noqa: E402
    SharedSettings,
    SessionInfo,
    ColoredIconSettings,
    plural as gp_plural,
    JSONSharedSettings,
    RPCUpdateDetails,
    push_rpc_update,
    connect_rpc,
    update_slot,
    update_buttons,
)
from colors import find_closest as gp_find_closest_color  # noqa: E402
from settings_dialog import SETTINGS_PROC_NAME, build_settings_procedure  # noqa: E402


# Bootstrap: ensure this plugin's directory is on sys.path so the sibling
# common.py and pypresence/ resolve when loaded by the host application.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_GP_PATTERN = re.compile(r"\[(\w+)\]")
_GP_PINNED_IMAGE: Gimp.Image | None = None
_GP_PREFS_PATH = Path(Gimp.directory()) / "plug-in-settings" / "gimp_presence.json"
_GP_DOCNAME_WAS_DOCCOUNT: bool = False
_GP_TEMP_PROCEDURES_REGISTERED: bool = False

_GP_MAIN_LOOP: GLib.MainLoop | None = None
_GP_TIMER_ID: int | None = None

def gp_pin_image(procedure, run_mode, image, drawables, config, data):  # pylint: disable=unused-argument
    global _GP_PINNED_IMAGE
    _GP_PINNED_IMAGE = image


def gp_unpin_image(*args):  # pylint: disable=unused-argument
    global _GP_PINNED_IMAGE
    _GP_PINNED_IMAGE = None


def gp_toggle_rpc(*args):  # pylint: disable=unused-argument
    GP_PREFS.generalEnable = not GP_PREFS.generalEnable


############
# Settings #
############
@dataclass
class GPSettings(SharedSettings, ColoredIconSettings, JSONSharedSettings):
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
    _INITIAL_DEFAULTS: ClassVar[dict] = {
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
            "label": "Attempt to find the active image name via GIMP Window title",
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
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for f in fields(GPSettings):
            if f.name.startswith("_") or f.metadata.get("group") is None:
                continue
            if f.name in data:
                object.__setattr__(GP_PREFS, f.name, data[f.name])
    except Exception as e:
        Gimp.warning(f"[GimpPresence] Failed to load settings: {e}")


GP_PREFS = GPSettings()
GP_SESSION = SessionInfo()


def _gp_platform_query_window() -> str | None:
    if not GP_PREFS.queryWindow:
        return None
    p = platform.system()
    if p == "Windows":
        try:
            procs = subprocess.Popen(
                ["tasklist", "/V", "/FI", "IMAGENAME eq gimp-3.exe", "/FO", "CSV"],
                stdout=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            s = procs.stdout
            if s is None:
                return
            proc_list = s.read().decode("utf-8").replace("\r", "").split("\n")
            reader = csv.DictReader(proc_list)
            gimp_process_info = next(reader)
            window_title = gimp_process_info["Window Title"]
            doc_name = _GP_PATTERN.search(window_title)
            if doc_name is None:
                return None
            return doc_name.group(1)
        except:  # noqa: E722 | pylint: disable=bare-except
            return None
    else:
        # New Linux (e.g., Ubuntu 26.04) uses Wayland, which does not expose window titles
        # Darwin development requires a MacOS device to even install pyobjc
        return None


def _gp_match_title(title: str, images: List[Gimp.Image]) -> Gimp.Image | None:
    for image in images:
        image_name = image.get_name()
        image_name_extracted = _GP_PATTERN.match(image_name)
        if image_name_extracted is None:
            continue
        if title == image_name_extracted.group(1):
            return image
    return None


def _gp_get_active_image() -> Gimp.Image | None:
    if _GP_PINNED_IMAGE is not None:
        if _GP_PINNED_IMAGE in Gimp.get_images():
            return _GP_PINNED_IMAGE
        else:
            gp_unpin_image()
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


def _gp_get_enum_name(enumerated_value) -> str:
    m = type(enumerated_value)._member_map_  # pylint: disable=protected-access
    m_inv = {v: k for k, v in m.items()}
    return m_inv[enumerated_value]


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
        global _GP_DOCNAME_WAS_DOCCOUNT
        # Images open but unable to find active image
        if self.images and self.active_image is None:
            if GP_PREFS.useAlternates:
                num_docs = self.num_images()
                _GP_DOCNAME_WAS_DOCCOUNT = True
                return num_docs
            else:
                return None
        _GP_DOCNAME_WAS_DOCCOUNT = False
        # No images open
        if not self.images:
            return "No images open"
        # Found image
        elif self.active_image is not None:
            if _GP_PINNED_IMAGE is not None:
                return f"📌 {self.active_image.get_name()}"
            else:
                return self.active_image.get_name()

    def num_images(self) -> str | None:
        """Return the number of images open, unless the last RPC update sent that number
        as the active image name, in which case we return None"""
        if _GP_DOCNAME_WAS_DOCCOUNT:
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
                return f"{gp_plural(count, 'layer')} selected in {len(self.images)} images"
            else:
                return None
        layers = self.active_image.get_selected_layers()
        if layers is None or not layers:
            return None
        if len(layers) > 1:
            return f"{gp_plural(len(layers), 'layer')} selected"
        else:
            layer_name = layers[0].get_name()
            layer_blend_mode = layers[0].get_mode()
            layer_blend_mode_name = _gp_get_enum_name(layer_blend_mode)
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
        return _gp_get_enum_name(model)

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
                    [_gp_get_enum_name(i.get_base_type()) for i in self.images]
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

    def foreground_color(self) -> Tuple[int, int, int] | None:
        fg = Gimp.context_get_foreground()
        rgba = fg.get_rgba()
        return (rgba[0], rgba[1], rgba[2])

    def view_blend_mode(self) -> str:
        return f"Paint mode: {_gp_get_enum_name(Gimp.context_get_paint_mode())}"


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
GP_RPC_CLIENT = Presence("")  # TODO


def gp_update_small_icon(ctx: GPContext):  # pylint: disable=unused-argument
    GP_DETAILS.small_icon = None
    GP_DETAILS.small_icon_text = ""
    if GP_PREFS.enableColoredIcons:
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
    push_rpc_update(
        GP_SESSION, GP_DETAILS, GP_PREFS, GP_RPC_CLIENT, "gimp", Gimp.warning
    )


def gp_update_presence():
    if not GP_PREFS.generalEnable:
        if GP_SESSION.connected:
            try:
                GP_RPC_CLIENT.clear()
            except Exception as e:  # noqa: BLE001
                Gimp.warning(f"[GimpPresence] clear failed: {e}")
                GP_SESSION.connected = False
        return
    ctx = GPContext.capture()
    # Update details first so if the doc name field (default) can't find the active document
    # and overrides with the document count, the state field knows to skip it on a cycle
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
    + "image until it is closed or unpinned.",
)

_GP_UNPIN_DOC = (
    "Unpin the currently pinned image",
    "Unpin the currently pinned image",
)

_GP_TOGGLE_DOC = (
    "Toggle Rich Presence updates on or off",
    "Toggle Rich Presence updates. A console message will alert you as to whether "
    + "updates are now on or off.",
)

_GP_TEMP_PROCEDURES = {
    "gimppresence_pin_image": (gp_pin_image, "GimpPresence: Pin Image", _GP_PIN_DOC),
    "gimppresence_unpin_image": (
        gp_unpin_image,
        "GimpPresence: Unpin Image",
        _GP_UNPIN_DOC,
    ),
    "gimppresence_toggle_rpc": (
        gp_toggle_rpc,
        "GimpPresence: Toggle RPC Connection",
        _GP_TOGGLE_DOC,
    ),
}


def _gp_on_settings_changed():
    gp_start_timer()


def gp_register_temp_procedures(plugin: Gimp.PlugIn):
    global _GP_TEMP_PROCEDURES_REGISTERED
    for proc_name, proc_details in _GP_TEMP_PROCEDURES.items():
        if proc_name == "gimppresence_pin_image":
            procedure = Gimp.ImageProcedure.new(
                plugin, proc_name, Gimp.PDBProcType.TEMPORARY, proc_details[0], None
            )
        else:
            procedure = Gimp.Procedure.new(
                plugin, proc_name, Gimp.PDBProcType.TEMPORARY, proc_details[0], None
            )
        procedure.set_menu_label(proc_details[1])
        procedure.set_documentation(proc_details[2][0], proc_details[2][1], None)
        procedure.add_menu_path("<Image>/Filters/Discord Presence/")
        plugin.add_temp_procedure(procedure)
    settings_proc = build_settings_procedure(
        plugin,
        settings_class=GPSettings,
        current_prefs=GP_PREFS,
        settings_json_path=_GP_PREFS_PATH,  # where to atomically write
        on_settings_changed=_gp_on_settings_changed,
    )
    plugin.add_temp_procedure(settings_proc)
    _GP_TEMP_PROCEDURES_REGISTERED = True


def gp_unregister_temp_procedures(plugin: Gimp.PlugIn):
    global _GP_TEMP_PROCEDURES_REGISTERED
    if not _GP_TEMP_PROCEDURES_REGISTERED:
        return
    for proc_name in _GP_TEMP_PROCEDURES:
        plugin.remove_temp_procedure(proc_name)
    plugin.remove_temp_procedure(SETTINGS_PROC_NAME)
    _GP_TEMP_PROCEDURES_REGISTERED = False


def gp_run(procedure, config, data):  # pylint: disable=unused-argument
    global _GP_MAIN_LOOP
    plugin = procedure.get_plug_in()
    if not GP_SESSION.connected:
        GP_SESSION.connected = connect_rpc(GP_RPC_CLIENT, "gimp", Gimp.warning)
    gp_load_settings()
    gp_register_temp_procedures(plugin)
    gp_start_timer()
    procedure.persistent_ready()
    plugin.persistent_enable()
    _GP_MAIN_LOOP = GLib.MainLoop()
    if _GP_MAIN_LOOP is None:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR)
    try:
        _GP_MAIN_LOOP.run()
    finally:
        gp_stop_timer()
        gp_unregister_temp_procedures(plugin)
        if GP_SESSION.connected:
            GP_RPC_CLIENT.clear()
            GP_RPC_CLIENT.close()
        _GP_MAIN_LOOP = None
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


def gp_start_timer():
    global _GP_TIMER_ID
    gp_stop_timer()
    interval = max(1000, GP_PREFS.generalUpdate * 1000)
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
        Gimp.warning(f"[GimpPresence] update failed: {e}")
    return True


def gp_quit_loop():
    if _GP_MAIN_LOOP is not None:
        _GP_MAIN_LOOP.quit()


class GPPlugin(Gimp.PlugIn):
    _gp_procedures = ["gimppresence_run"]

    def do_query_procedures(self):
        return self._gp_procedures

    def do_create_procedure(self, name):
        if name == "gimppresence_run":
            procedure = Gimp.Procedure.new(
                self, name, Gimp.PDBProcType.PERSISTENT, gp_run, None
            )
            procedure.set_menu_label("GimpPresence Client (Background)")
            procedure.set_documentation(
                "GimpPresence background process."
                + "Runs continuously and sends updates to Discord."
            )
        else:
            procedure = None
        return procedure

    def do_quit(self):
        gp_quit_loop()


Gimp.main(GPPlugin.__gtype__, sys.argv)
