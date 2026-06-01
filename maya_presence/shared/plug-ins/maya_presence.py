"""
MayaPresence is a Discord Rich Presence client plugin for Autodesk Maya, based on
https://github.com/abrasic/blendpresence. MayaPresence has been tested on Maya 2026
and Maya 2027. For more info, see https://github.com/MarlArini/dcc-rpc.
"""

import atexit
from dataclasses import dataclass, fields, field
from enum import Enum
import os
from pathlib import Path
import re
import time
from typing import ClassVar, List, cast, Tuple, Any, get_type_hints, Dict

from pypresence.presence import Presence

# pylint: disable=import-error,no-name-in-module,line-too-long,unused-import
import maya.api.OpenMaya as om  # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin  # pyright: ignore[reportMissingImports]
import maya.cmds as cmds  # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from common import (
    get_file_size_str as mp_read_size,
    RPCUpdateDetails as MPRPCUpdate,
    shorten_number as mp_shorten_number,
)
from common import update_buttons as mp_update_buttons

from common import (
    SharedSettings as MPSharedSettings,
    on_render_start as mp_on_render_start,
    on_render_end as mp_on_render_end,
    on_frame_render_end as mp_on_frame_render_end,
    force_clear_on_exit,
    SessionInfo as MPPresenceInfo,
    QtSettingsGUIMenu,
    connect_rpc as _mp_connect_rpc,
    push_rpc_update as _mp_push_rpc_update,
    advance_cycle as mp_advance_cycle,
    update_slot as mp_update_slot,
    plural as mp_plural,
)
# pylint: enable=import-error,no-name-in-module,line-too-long,unused-import

############
# Settings #
############


@dataclass
class MPSettings(MPSharedSettings):
    """Store user preferences and persist across sessions with OptionVars"""

    # pylint: disable=invalid-name
    displayEngine: bool = field(
        default=True,
        metadata={"group": "Details", "label": "Display active render engine on hover"},
    )
    displayGPU: bool = field(
        default=False,
        metadata={"group": "Details", "label": "Display GPU name in details"},
    )
    displayRenderStats: bool = field(
        default=True,
        metadata={"group": "Details", "label": "Display render stats in details"},
    )
    displayFileName: bool = field(
        default=False,
        metadata={"group": "Details", "label": "Display file name when rendering"},
    )
    displayFrames: bool = field(
        default=True,
        metadata={"group": "Details", "label": "Display frames rendered in details"},
    )
    countExtensions: bool = field(
        default=True,
        metadata={
            "group": "Render Extensions",
            "label": ("Count lights, materials, and textures from third-party renderers"),
        },
    )
    _PREFIX: ClassVar[str] = "mayaPresence_"
    INFO_CHOICES: ClassVar[List[Tuple[str, str]]] = [
        ("Scene name", "scene"),
        ("Mesh count", "mesh"),
        ("Poly count", "poly"),
        ("Joint count", "joint"),
        ("Light count", "light"),
        ("Camera count", "cam"),
        ("Blendshape count", "blendshape"),
        ("Material count", "mat"),
        ("Texture count", "tex"),
        ("File size", "size"),
        ("Current frame", "frame"),
        ("Active object", "active"),
        ("Current tool context", "context"),
    ]
    _INITIAL_DEFAULTS: ClassVar[Dict[str, Any]] = {
        "detailsType": "scene",
        "stateType": "poly",
    }

    def __post_init__(self):
        field_types = get_type_hints(MPSettings)
        for f in fields(self):
            ov = self._PREFIX + f.name
            if cmds.optionVar(exists=ov):
                v = cmds.optionVar(query=ov)
                f_type = field_types[f.name]
                if f_type is bool:
                    v = bool(v)
                object.__setattr__(self, f.name, v)
            elif f.name in self._INITIAL_DEFAULTS:
                object.__setattr__(self, f.name, self._INITIAL_DEFAULTS[f.name])
        # From here on, attribute writes persist to optionVars.
        object.__setattr__(self, "_loaded", True)

    def __setattr__(self, name: str, value: Any):
        object.__setattr__(self, name, value)
        # Skip persistence for private attrs and for the bootstrap phase (the
        # dataclass-generated __init__ runs field assignments BEFORE __post_init__;
        # without this guard those assignments would clobber the user's saved
        # optionVars with the class defaults).
        if name.startswith("_") or not getattr(self, "_loaded", False):
            return
        declared = [f.name for f in fields(self)]
        if name not in declared:
            return
        ov = self._PREFIX + name
        field_types = get_type_hints(MPSettings)
        kind = field_types[name]
        if kind is bool or kind is int:
            cmds.optionVar(intValue=(ov, int(value)))
        elif kind is float:
            cmds.optionVar(floatValue=(ov, float(value)))
        else:
            cmds.optionVar(stringValue=(ov, str(value)))

    def reset(self):
        """Restore all fields to default values (Maya-specific defaults take precedence)."""
        for f in fields(self):
            default = self._INITIAL_DEFAULTS.get(f.name, f.default)
            setattr(self, f.name, default)


###########
# Globals #
###########

MP_RPC_CLIENT = Presence("1498143095852634252")
MP_CALLBACKS: set[Tuple[str, int]] = set()
MP_TIMER_CALLBACK_ID = None
MP_SETTINGS_WINDOW = None
MP_PREFS = MPSettings()
MP_SESSION = MPPresenceInfo()
MP_UPDATE_DETAILS = MPRPCUpdate("maya")


class MPExtensionMonitor:
    """
    Watch known render engine plugins (Redshift, Arnold, V-Ray, RenderMan, Octane).
    We maintain whether the engine is loaded and a list of its custom types, so
    if the user enables counting lights, materials, or textures from the engine
    we can iterate the types and count them with `cmds.ls`
    """

    class Engine:
        def __init__(
            self,
            pn: str,
            rn: str,
            light_path=None,
            mat_path=None,
            tex_path=None,
        ):
            self.plugin_name = pn
            self.registry_name = rn
            self.light_path = light_path or f"rendernode/{rn}/light"
            self.material_path = mat_path or f"rendernode/{rn}/shader"
            self.texture_path = tex_path or f"rendernode/{rn}/texture"
            self.loaded = False
            self.types: dict | None = None

    class TypeCategory(Enum):
        LIGHT = 0
        MATERIAL = 1
        TEXTURE = 2

    def __init__(self):
        self.monitored_engines = {
            "Redshift": self.Engine("redshift4maya", "redshift"),
            "Arnold": self.Engine("mtoa", "arnold"),
            "V-Ray": self.Engine("vrayformaya", "vray"),
            "RenderMan": self.Engine(
                "RenderMan_For_Maya",
                "renderman",
                mat_path="rendernode/renderman/bxdf",
                tex_path="rendernode/renderman/pattern",
            ),
            "Octane": self.Engine(
                "octaneplugin",
                "octane",
                mat_path="rendernode/octane/material",
                light_path="rendernode/octane/node" # some non-light stuff in here - worth refactor?
            )
        }

    def init_engine(self, e: str):
        engine = self.monitored_engines[e]
        engine.loaded = True
        light_types = cmds.listNodeTypes(engine.light_path) or []
        mat_types = cmds.listNodeTypes(engine.material_path) or []
        tex_types = cmds.listNodeTypes(engine.texture_path) or []
        self.monitored_engines[e].types = {
            "light": light_types,
            "material": mat_types,
            "texture": tex_types,
        }

    def count(self, category: TypeCategory) -> int:
        types = []
        for engine in self.monitored_engines.values():
            if (
                engine.loaded
                and MP_PREFS.countExtensions
                and engine.types is not None
            ):
                types += engine.types[category.name.lower()]
        return len(cmds.ls(type=types)) if types else 0


MP_EXTENSIONS = MPExtensionMonitor()

####################
# Property Getters #
####################


class MPContext:
    @classmethod
    def capture(cls) -> "MPContext | None":
        return cls()

    def get_gpu_str(self) -> str:
        try:
            card = cmds.openGLExtension(renderer=True) or ""
            if card:
                if "NVIDIA GeForce " in card:
                    card = card.replace("NVIDIA GeForce", "")
                if "Radeon " in card:
                    card = card.replace("Radeon", "")
                slash_loc = card.find("/")
                if slash_loc != -1:
                    return card[: card.find("/")]
                return card
            return ""
        except RuntimeError:
            return ""

    def get_project_name(self) -> str:
        return cast(str, cmds.workspace(query=True, shortName=True))

    def get_file_name(self, ext: bool = False) -> str:
        """
        Return the file name of the scene, if it is saved.
        `ext` determines whether to include the .mb extension
        """
        p = cast(str, cmds.file(query=True, sceneName=True))
        if p:
            return Path(p).name if ext else Path(p).stem
        return ""

    def get_current_scene(self) -> str:
        project_name = self.get_project_name()
        file_name = self.get_file_name()
        fallback_name = "Untitled Scene"
        if project_name and file_name:
            return project_name + " | " + file_name
        elif project_name:
            return project_name
        elif file_name:
            return file_name
        return fallback_name

    def get_cam_count(self) -> str:
        cams = len(cmds.ls(cameras=True)) - 4  # persp,top,front,side
        return mp_plural(cams, "camera")

    def get_light_count(self) -> str:
        maya_light_count = len(cmds.ls(lights=True))
        extension_light_count = MP_EXTENSIONS.count(
            MPExtensionMonitor.TypeCategory.LIGHT
        )
        lights = maya_light_count + extension_light_count
        return mp_plural(lights, "light")

    def get_mesh_count(self) -> str:
        meshes = cmds.ls(geometry=True, visible=True, noIntermediate=True, type="mesh")
        return mp_plural(len(meshes), "mesh", "es")

    def get_poly_count_str(self) -> str:
        # Ideal: HUD Poly Count enabled (includes smoothing)
        if cmds.headsUpDisplay("HUDPolyCountVerts", query=True, visible=True) == 1:
            verts = cast(
                List[int],
                cmds.headsUpDisplay("HUDPolyCountVerts", query=True, scriptResult=True),
            )[0]
            faces = cast(
                List[int],
                cmds.headsUpDisplay("HUDPolyCountFaces", query=True, scriptResult=True),
            )[0]
        # Fallback: raw values
        else:
            meshes = cmds.ls(type="mesh", visible=True)
            polys = cmds.polyEvaluate(meshes, vertex=True, face=True)  # type: ignore[arg-type]
            if isinstance(polys, str):
                verts, faces = 0, 0  # polyEvaluate with no selection returns a string
            else:
                verts = polys["vertex"]
                faces = polys["face"]
        try:
            vert_str = "vert" if int(verts) == 1 else "verts"
            verts = mp_shorten_number(int(verts))
            face_str = "face" if int(faces) == 1 else "faces"
            faces = mp_shorten_number(int(faces))
            return f"{verts} {vert_str} | {faces} {face_str}"
        except ValueError: # For some reason during startup verts is occasionally a string
            return "Unknown polygon count"

    def get_joint_count(self) -> str:
        joints = len(cmds.ls(type="joint"))
        return mp_plural(joints, "joint")

    def get_blendshape_count(self) -> str:
        blendshapes = len(cmds.ls(type="blendShape"))
        return mp_plural(blendshapes, "blendshape")

    def get_mat_count(self) -> str:
        maya_mat_count = len(cmds.ls(materials=True))
        extension_mat_count = MP_EXTENSIONS.count(
            MPExtensionMonitor.TypeCategory.MATERIAL
        )
        mats = maya_mat_count + extension_mat_count
        return mp_plural(mats, "material")

    def get_tex_count(self) -> str:
        maya_tex_count = len(cmds.ls(textures=True))
        extension_tex_count = MP_EXTENSIONS.count(
            MPExtensionMonitor.TypeCategory.TEXTURE
        )
        texs = maya_tex_count + extension_tex_count
        return mp_plural(texs, "texture")

    def get_current_frame(self) -> str:
        return f"Frame {int(cmds.currentTime(query=True))}"

    def get_file_size(self) -> str | None:
        p = cast(str, cmds.file(query=True, sceneName=True))
        if p and os.path.exists(p):
            return mp_read_size(os.path.getsize(p))
        return None

    def get_version_str(self) -> str:
        try:
            major = cmds.about(majorVersion=True)
            minor = cmds.about(minorVersion=True)
            patch = cmds.about(patchVersion=True)
            return f"{major}.{minor}.{patch}"
        except Exception:
            return cmds.about(version=True)

    def get_render_engine_str(self) -> str:
        try:
            i = cmds.getAttr("defaultRenderGlobals.currentRenderer") or ""
        except RuntimeError:
            return "Unknown"
        mp_render_map = {
            "arnold": "Arnold",
            "redshift": "Redshift",
            "renderman": "RenderMan",
            "renderManRIS": "RenderMan",
            "vray": "V-Ray",
            "mayaSoftware": "Maya Software",
            "mayaHardware2": "Maya Hardware 2.0",
        }
        if i in mp_render_map:
            return mp_render_map[i]
        return i if i else "Unknown"

    def get_frame_range(self) -> Tuple[int, int]:
        start = int(cmds.playbackOptions(query=True, minTime=True))
        end = int(cmds.playbackOptions(query=True, maxTime=True))
        cursor = int(cmds.currentTime(query=True))
        return (cursor - start + 1, end - start + 1)

    def get_active_object(self) -> str | None:
        sel = cmds.ls(selection=True) or []
        return sel[0] if sel else None

    def get_render_resolution(self) -> Tuple[int, int] | None:
        try:
            return (
                cmds.getAttr("defaultResolution.width"),
                cmds.getAttr("defaultResolution.height"),
            )
        except RuntimeError:
            return None

    def get_render_fps(self) -> int | None:
        try:
            u = cast(str, cmds.currentUnit(query=True, time=True)) or ""
        except RuntimeError:
            return 24
        presets = {
            "game": 15,
            "film": 24,
            "pal": 25,
            "ntsc": 30,
            "show": 48,
            "palf": 50,
            "ntscf": 60,
        }
        if u in presets:
            return presets[u]
        if u.endswith("fps"):
            try:
                return int(round(float(u[:-3])))
            except ValueError:
                return None
        return 24

    def get_user_context(self) -> str | None:
        current_ctx = cmds.currentCtx()
        if current_ctx.endswith("Ctx"):
            current_ctx = current_ctx[:-3]
        elif current_ctx.endswith("Context"):
            current_ctx = current_ctx[:-7]
        if not current_ctx:
            return None
        return f"Context: {current_ctx[0].upper()}{current_ctx[1:]}"


#################
# Rich Presence #
#################


def mp_connect_rpc():
    return _mp_connect_rpc(MP_RPC_CLIENT, "Maya")


def mp_push_rpc_update(*args):  # pylint: disable=unused-argument
    _mp_push_rpc_update(MP_SESSION, MP_UPDATE_DETAILS, MP_PREFS, MP_RPC_CLIENT, "Maya")


def mp_update_large_icon(ctx: MPContext):
    MP_UPDATE_DETAILS.large_icon = "maya"
    if MP_PREFS.displayVersion:
        MP_UPDATE_DETAILS.large_icon_text = f"Maya {ctx.get_version_str()}"
    else:
        MP_UPDATE_DETAILS.large_icon_text = "Maya"


def mp_update_small_icon(ctx: MPContext):
    icon_file_name = None
    icon_text = ""
    if MP_PREFS.displaySmallIcon:
        if MP_PREFS.displayEngine and MP_SESSION.is_rendering:
            # No icons for Maya Software / Maya Hardware
            engines = ["Arnold", "Redshift", "RenderMan", "V-Ray", "Octane"]
            current_engine = ctx.get_render_engine_str()
            if current_engine in engines:
                icon_file_name = current_engine.lower().replace("-", "")
                icon_text = current_engine
            # GPU
            if MP_PREFS.displayGPU:
                gpustr = ctx.get_gpu_str()
                if gpustr and icon_text:
                    icon_text += " | " + gpustr
        else:
            try:
                # "Modeling - Expert", "Pose Sculpting", etc.
                space_name = (
                    cast(
                        str, cmds.workspaceLayoutManager(query=True, current=True)
                    ).lower()
                    or ""
                )
            except Exception:
                space_name = ""
            if space_name and space_name != "general":
                icon_file_name = (
                    space_name[: space_name.find(" ")]
                    if space_name.find(" ") > 0
                    else space_name
                )
                icon_text = space_name
            else:
                tool_context = cmds.currentCtx()
                if (
                    tool_context.startswith("poly")
                    or tool_context.startswith("manip")
                    or tool_context.startswith("curve")
                    or tool_context.startswith("target")
                ):
                    icon_file_name = "modeling"
                    icon_text = "Modeling"
                elif tool_context.startswith("sculpt"):
                    icon_file_name = "sculpt"
                    icon_text = "Sculpting"
                elif tool_context.startswith("tex"):
                    icon_file_name = "uv"
                    icon_text = "UV Editing"
                elif (
                    tool_context.startswith("joint")
                    or tool_context.startswith("ik")
                    or tool_context.startswith("skin")
                ):
                    icon_file_name = "pose"
                    icon_text = "Rigging"
                elif tool_context.startswith("keyframe") or tool_context.startswith(
                    "filter"
                ):
                    icon_file_name = "animation"
                    icon_text = "Animation"
    MP_UPDATE_DETAILS.small_icon = icon_file_name
    MP_UPDATE_DETAILS.small_icon_text = icon_text


MP_DISPLAY_TYPES = {
    "scene": lambda ctx: ctx.get_current_scene(),
    "mesh": lambda ctx: ctx.get_mesh_count(),
    "poly": lambda ctx: ctx.get_poly_count_str(),
    "joint": lambda ctx: ctx.get_joint_count(),
    "light": lambda ctx: ctx.get_light_count(),
    "cam": lambda ctx: ctx.get_cam_count(),
    "blendshape": lambda ctx: ctx.get_blendshape_count(),
    "mat": lambda ctx: ctx.get_mat_count(),
    "tex": lambda ctx: ctx.get_tex_count(),
    "size": lambda ctx: ctx.get_file_size(),
    "frame": lambda ctx: ctx.get_current_frame(),
    "active": lambda ctx: ctx.get_active_object(),
    "context": lambda ctx: ctx.get_user_context(),
}


def mp_update_presence_details(ctx: MPContext):
    # Rendering Details
    # TODO simplify string build
    if MP_PREFS.enableDetails and MP_SESSION.is_rendering:
        res = ctx.get_render_resolution()
        fname = ctx.get_file_name()
        frame_range = ctx.get_frame_range()
        fps = ctx.get_render_fps()
        MP_UPDATE_DETAILS.details_text = (
            "Rendering"
            + (f" {fname}" if fname and MP_PREFS.displayFileName else "")
            + (
                ": "
                if (res is not None and MP_PREFS.displayRenderStats)
                or (MP_PREFS.displayFrames and frame_range[1])
                else ""
            )
            + (
                f"{res[0]}x{res[1]}, "
                if res is not None and MP_PREFS.displayRenderStats
                else ""
            )
            + (
                f"Frame {MP_SESSION.rendered_frames} of {frame_range[1]}"
                if MP_PREFS.displayFrames and frame_range[1]
                else ""
            )
            + (f" @{fps}fps" if fps is not None else "")
        )
    elif MP_PREFS.enableDetails:
        mp_update_slot(
            ctx, "details", MP_PREFS, MP_UPDATE_DETAILS, MP_DISPLAY_TYPES, MP_SESSION
        )


def mp_update_presence_state(ctx: MPContext):
    mp_update_slot(
        ctx, "state", MP_PREFS, MP_UPDATE_DETAILS, MP_DISPLAY_TYPES, MP_SESSION
    )


def mp_update_presence():
    if MP_PREFS.generalEnable:
        if MP_PREFS.detailsCycle or MP_PREFS.stateCycle:
            mp_advance_cycle(MP_SESSION, MP_DISPLAY_TYPES)
        ctx = MPContext.capture()
        if ctx is None:
            return
        mp_update_large_icon(ctx)
        mp_update_small_icon(ctx)
        mp_update_presence_state(ctx)
        mp_update_presence_details(ctx)
        mp_update_buttons(MP_UPDATE_DETAILS, MP_PREFS)
        mp_push_rpc_update()
    elif MP_SESSION.connected:
        try:
            MP_RPC_CLIENT.clear()
        except Exception as e:  # noqa: BLE001
            print(f"[MayaPresence] clear failed: {e}")
            MP_SESSION.connected = False


#####################
# GUI Settings Menu #
#####################


class MayaPresenceSettings(MayaQWidgetDockableMixin, QtSettingsGUIMenu):
    pass


def mp_show_settings_dialog(prefs, on_change=None):
    global MP_SETTINGS_WINDOW
    if MP_SETTINGS_WINDOW is not None:
        try:
            MP_SETTINGS_WINDOW.close()
            MP_SETTINGS_WINDOW.deleteLater()
        except Exception:
            pass
    MP_SETTINGS_WINDOW = MayaPresenceSettings(
        prefs=prefs, refresh_func=on_change, app_name="Maya"
    )
    MP_SETTINGS_WINDOW.show()
    MP_SETTINGS_WINDOW.raise_()
    MP_SETTINGS_WINDOW.activateWindow()
    return MP_SETTINGS_WINDOW


def mp_open_settings_menu():
    mp_show_settings_dialog(MP_PREFS, on_change=mp_push_rpc_update)


def _mp_add_settings_menu_item():
    """Add the settings menuItem under mainWindowMenu. Called from the PMC
    the first time the user opens the Window menu, or directly by tests."""
    if cmds.menuItem("mayaPresenceSettingsMenuItem", exists=True):
        return
    cmds.menuItem(
        "mayaPresenceSettingsMenuItem",
        label="Maya Presence Settings…",
        parent="mainWindowMenu",
        command=lambda *_: mp_open_settings_menu(),
    )


# MEL fragment appended to mainWindowMenu's post-menu callback.
# Same approach as MayaUSD's addMenuCallback / mayaUsdMenu_windowMenuCallback.
MP_MENU_PMC = (
    f'python("try:","\timport maya_presence as _mp",'
    f'"\t_mp.{_mp_add_settings_menu_item.__name__}()","except:","\tpass")'
)


def mp_install_settings_menu():
    """Append a post-menu callback to mainWindowMenu instead of inserting the
    menuItem now."""
    try:
        existing_pmc = (
            cmds.menu("mainWindowMenu", query=True, postMenuCommand=True) or ""
        )
    except RuntimeError:
        return
    if MP_MENU_PMC in existing_pmc:
        return  # already hooked
    cmds.menu("mainWindowMenu", edit=True, postMenuCommand=existing_pmc + ";;" + MP_MENU_PMC)


def mp_uninstall_settings_menu():
    """Remove our menuItem AND strip our PMC fragment, so the Window menu's
    post-menu callback doesn't try to recreate the item on the next open."""
    if cmds.menuItem("mayaPresenceSettingsMenuItem", exists=True):
        cmds.deleteUI("mayaPresenceSettingsMenuItem", menuItem=True)
    try:
        existing_pmc = (
            cmds.menu("mainWindowMenu", query=True, postMenuCommand=True) or ""
        )
    except RuntimeError:
        return
    new_pmc = existing_pmc.replace(MP_MENU_PMC, "")
    if new_pmc != existing_pmc:
        try:
            cmds.menu("mainWindowMenu", edit=True, postMenuCommand=new_pmc)
        except RuntimeError:
            pass


###################
# Render Handlers #
###################

MP_HOOK_START = "/* MayaPresence:Hook:Begin */"
MP_HOOK_END = " /* MayaPresence:Hook:End */"


def mp_wrap_mel(py_call: str) -> str:
    """
    Accept a Python function name from this module and return a MEL expression which will invoke it.
    The Python function cannot take arguments. The MEL will be comment-wrapped with indicators
    that it came from MayaPresence, and the Python will be in a try-except that silently fails.
    """
    return (
        f"{MP_HOOK_START} "
        f'python("try:","\timport maya_presence as _mp","\t_mp.{py_call}","except:","\tpass")'
        f"{MP_HOOK_END}"
    )


def mp_check_render_handlers_installed() -> bool:
    """Check if any render handlers are already installed"""
    for attr in ["preMel", "postMel", "postRenderMel"]:
        try:
            existing = cmds.getAttr(f"defaultRenderGlobals.{attr}")
            if existing is not None and MP_HOOK_START in existing:
                return True
        except RuntimeError as e:
            print(
                f"[MayaPresence] could not check render events for handler {attr}: ", e
            )
            continue
    return False


def mp_install_render_handlers(*args):  # pylint: disable=unused-argument
    """
    Add hooks to the preMel, postMel, and postRenderMel events that will update the session
    information when rendering starts and ends, and when a frame finishes rendering. Use
    __name__ on the functions instead of passing as strings to prevent unused import messages
    and accidental deletion of the imports, making the calls fail at runtime.
    """
    if mp_check_render_handlers_installed():
        return
    pairs = [
        ("preMel", f"{mp_on_render_start.__name__}(MP_SESSION, MP_PREFS)"),
        ("postMel", f"{mp_on_render_end.__name__}(MP_SESSION, MP_PREFS)"),
        ("postRenderMel", f"{mp_on_frame_render_end.__name__}(MP_SESSION)"),
    ]
    for attr, py_call in pairs:
        plug = f"defaultRenderGlobals.{attr}"
        try:
            existing = cmds.getAttr(plug) or ""
            mel = mp_wrap_mel(py_call)
            merged = existing + mel
            cmds.setAttr(plug, merged, type="string")
        except RuntimeError as e:
            print(f"[MayaPresence] Could not install handler {attr}:", e)


def mp_uninstall_render_handlers(*args):  # pylint: disable=unused-argument
    """
    Remove the render event hooks by searching for the MayaPresence tags surrounding them
    and removing all MEL between them from the preMel, postMel, and postRenderMel events.
    """
    if not mp_check_render_handlers_installed():
        return
    pattern = re.compile(
        re.escape(MP_HOOK_START) + r".*?" + re.escape(MP_HOOK_END), re.DOTALL
    )
    for attr in ["preMel", "postMel", "postRenderMel"]:
        plug = f"defaultRenderGlobals.{attr}"
        try:
            existing = cmds.getAttr(plug)
            if not existing:
                continue
            stripped = pattern.sub("", existing)
            cmds.setAttr(plug, stripped, type="string")
        except (RuntimeError, ValueError) as e:
            print(f"[MayaPresence] Could not restore handler {attr}:", e)


#############
# Callbacks #
#############


def mp_observe_plugin_load(string_array, clientData):  # pylint: disable=unused-argument,invalid-name
    """
    If render stats are on, check if plugin loading removed the handlers.
    See if a render engine was loaded and update the extensions data if so.
    """
    if not string_array:
        return
    # kAfterPluginLoad string array: [plugin_path, plugin_name]
    loaded_plugin_name = string_array[-1]
    if MP_PREFS.displayRenderStats and not mp_check_render_handlers_installed():
        mp_install_render_handlers()
    for engine_name, engine in MP_EXTENSIONS.monitored_engines.items():
        if engine.plugin_name == loaded_plugin_name:
            MP_EXTENSIONS.init_engine(engine_name)
            return


def mp_observe_plugin_unload(string_array, clientData):  # pylint: disable=unused-argument,invalid-name
    """
    If render stats are on, check if plugin unloading removed the handlers.
    If a render engine was unloaded, update the extensions data.
    """
    if not string_array:
        return
    # kAfterPluginUnload string array: [plugin_name, plugin_path]
    unloaded_plugin_name = string_array[0]
    if MP_PREFS.displayRenderStats and not mp_check_render_handlers_installed():
        mp_install_render_handlers()
    for _, engine in MP_EXTENSIONS.monitored_engines.items():
        if engine.plugin_name == unloaded_plugin_name:
            engine.loaded = False


def mp_add_callbacks():
    """
    Register all callbacks.
    1. kAfterNew, kAfterOpen: Add the render handlers to fresh / opened
       scenes if displayRenderStats is on. The handlers stay in the scene
       across saves.
    2. kAfterPluginLoad: check if the plugin clobbered the callbacks. Also,
       check if the plugin is a known render engine (Arnold, Redshift, V-Ray,
       RMan) and, if so, flag this to possibly enable counting engine-specific
       types.
    3. kAfterPluginUnload: check if hooks were clobbered on unload, and if a
       monitored engine is no longer present.
    """
    MP_CALLBACKS.add(
        (
            "kAfterNew",
            om.MSceneMessage.addCallback(
                om.MSceneMessage.kAfterNew, mp_install_render_handlers
            ),
        )
    )
    MP_CALLBACKS.add(
        (
            "kAfterOpen",
            om.MSceneMessage.addCallback(
                om.MSceneMessage.kAfterOpen, mp_install_render_handlers
            ),
        )
    )
    MP_CALLBACKS.add(
        (
            "kAfterPluginLoad",
            om.MSceneMessage.addStringArrayCallback(
                om.MSceneMessage.kAfterPluginLoad, mp_observe_plugin_load
            ),
        )
    )
    MP_CALLBACKS.add(
        (
            "kAfterPluginUnload",
            om.MSceneMessage.addStringArrayCallback(
                om.MSceneMessage.kAfterPluginUnload, mp_observe_plugin_unload
            ),
        )
    )


def mp_remove_callbacks():
    """
    Attempt to uninstall all of the handler callbacks.
    """
    for cb in MP_CALLBACKS.copy():
        cb_name, cb_id = cb
        try:
            om.MMessage.removeCallback(cb_id)
        except RuntimeError as e:
            print(f"[MayaPresence] Failed to remove callback {cb_name}: ", e)
    MP_CALLBACKS.clear()


#############
# Threading #
#############


def mp_on_timer(elapsed_time, last_time, client_data):  # pylint: disable=unused-argument
    mp_update_presence()


def mp_schedule():
    global MP_TIMER_CALLBACK_ID
    if MP_TIMER_CALLBACK_ID is not None:
        return
    MP_TIMER_CALLBACK_ID = om.MTimerMessage.addTimerCallback(
        MP_PREFS.generalUpdate, mp_on_timer
    )


def mp_cancel():
    global MP_TIMER_CALLBACK_ID
    if MP_TIMER_CALLBACK_ID is not None:
        try:
            om.MMessage.removeCallback(MP_TIMER_CALLBACK_ID)
        except RuntimeError:
            pass
        MP_TIMER_CALLBACK_ID = None


def mp_refresh_timer():
    """If a user changes the update period, remove and re-add the callback"""
    mp_cancel()
    mp_schedule()


###################
# Plugin Lifetime #
###################
# pylint: disable=invalid-name,unused-argument


def maya_useNewAPI():
    pass


def mp_check_loaded_engines():
    plugins = cast(List[str], cmds.pluginInfo(query=True, listPlugins=True))
    for engine_name, engine in MP_EXTENSIONS.monitored_engines.items():
        if engine.plugin_name in plugins:
            MP_EXTENSIONS.init_engine(engine_name)


def mp_start():
    if cmds.about(batch=True):
        return
    MP_SESSION.connected = mp_connect_rpc()
    MP_SESSION.start_time = time.time()
    if MP_PREFS.displayRenderStats:
        mp_install_render_handlers()
    mp_install_settings_menu()
    mp_check_loaded_engines()
    mp_add_callbacks()
    mp_schedule()


def mp_stop():
    if cmds.about(batch=True):
        return
    cleanup_steps = [
        ("cancel timer", mp_cancel),
        ("clear presence", lambda: MP_RPC_CLIENT.clear() if MP_RPC_CLIENT else None),
        ("close RPC client", lambda: MP_RPC_CLIENT.close() if MP_RPC_CLIENT else None),
        ("remove callbacks", mp_remove_callbacks),
        ("uninstall render handlers", mp_uninstall_render_handlers),
        ("uninstall settings menu", mp_uninstall_settings_menu),
    ]
    for description, step in cleanup_steps:
        try:
            step()
        except Exception as e:
            print(f"[MayaPresence] Failed to {description}: {e}")
    MP_SESSION.connected = False


def initializePlugin(mobject):
    # pylint: disable=unused-variable
    fn = om.MFnPlugin(mobject, "MarlArini", "1.0", "Any")  # noqa: F841
    mp_start()


def uninitializePlugin(plugin):
    mp_stop()


atexit.register(force_clear_on_exit, MP_RPC_CLIENT)
