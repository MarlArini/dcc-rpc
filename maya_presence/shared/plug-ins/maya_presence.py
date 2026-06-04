"""
MayaPresence is a Discord Rich Presence client plugin for Autodesk Maya, based on
https://github.com/abrasic/blendpresence. MayaPresence has been tested on Maya 2026
and Maya 2027. For more info, see https://github.com/MarlArini/dcc-rpc.
"""

import atexit
import builtins
import copy
import threading
from dataclasses import dataclass, fields, field
from enum import Enum
import os
from pathlib import Path
import re
import time
from typing import (
    ClassVar,
    List,
    cast,
    Tuple,
    Any,
    get_type_hints,
    Dict,
    Optional,
    Callable,
)

# pylint: disable=import-error, no-name-in-module, line-too-long, unused-import, too-many-lines
import maya.api.OpenMaya as om  # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin  # pyright: ignore[reportMissingImports]
import maya.cmds as cmds  # pyright: ignore[reportMissingImports, reportMissingModuleSource]

from pypresence.presence import Presence
from pypresence import exceptions as pypresence_exceptions

from common import (
    RPCUpdateDetails,
    SessionInfo,
    SharedSettings,
    RenderSettings,
    QtSettingsGUIMenu,
    get_file_size_str,
    shorten_number,
    update_buttons,
    rpc_update,
    advance_cycle,
    update_slot,
    format_render_details,
    plural as mp_plural,
    on_render_start,
    on_render_end,
    on_frame_render_end,
)

# pylint: enable=import-error, no-name-in-module, line-too-long, unused-import

############
# Settings #
############


@dataclass
class MPSettings(SharedSettings, RenderSettings):
    """Store user preferences and persist across sessions with OptionVars"""

    # pylint: disable=invalid-name
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
    countExtensions: bool = field(
        default=True,
        metadata={
            "group": "General",
            "label": (
                "Count lights, materials, and textures from third-party renderers"
            ),
        },
    )
    useRenderHooks: bool = field(
        default=True,
        metadata={
            "group": "Rendering",
            "label": "Add MEL hook to scene pre/post render events for render detection",
        },
    )
    displayGPU: bool = field(
        default=False,
        metadata={
            "group": "Rendering",
            "label": "Display GPU name in details when rendering",
        },
    )

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
        # dataclass-generated __init__ runs field assignments BEFORE __post_init__)
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


MP_DISCORD_APP_ID = "1498143095852634252"
MP_CALLBACKS: set[Tuple[str, int]] = set()
MP_TIMER_CALLBACK_ID = None
MP_SETTINGS_WINDOW = None

# Maya's plug-in loader doesn't put this file in sys.modules, so any
# `import maya_presence` from a MEL hook creates a duplicate module
# with its own globals. Fix: keep the canonical instance on builtins.
MP_WORKER_ATTR = "__mayapresence_worker__"
MP_PREFS_ATTR = "__mayapresence_prefs__"
MP_SESSION_ATTR = "__mayapresence_session__"
MP_UPDATE_DETAILS_ATTR = "__mayapresence_update_details__"


def _share_via_builtins(attr: str, factory: Callable[[], Any]) -> Any:
    """First module to load calls factory() and stashes the instance on
    builtins under `attr`; later modules retrieve that instance."""
    existing = getattr(builtins, attr, None)
    if existing is not None:
        return existing
    instance = factory()
    setattr(builtins, attr, instance)
    return instance


MP_PREFS: MPSettings = _share_via_builtins(MP_PREFS_ATTR, MPSettings)
MP_SESSION: SessionInfo = _share_via_builtins(MP_SESSION_ATTR, SessionInfo)
MP_UPDATE_DETAILS: RPCUpdateDetails = _share_via_builtins(
    MP_UPDATE_DETAILS_ATTR, lambda: RPCUpdateDetails("maya")
)


def mp_print(msg: str):
    print(f"[MayaPresence] {msg}")


def _get_worker():
    return getattr(builtins, MP_WORKER_ATTR, None)


def _set_worker(worker):
    setattr(builtins, MP_WORKER_ATTR, worker)


##############
# RPC worker #
##############

_RPC_LOST_EXC = (
    pypresence_exceptions.InvalidID,
    pypresence_exceptions.PipeClosed,
    pypresence_exceptions.DiscordNotFound,
    pypresence_exceptions.ServerError,
    AssertionError,
)


class _MPRPCWorker(threading.Thread):
    """Daemon thread that owns the Presence client.
    During sequence renders and certain other events like file dialogs,
    the Maya application is not considered idle, and so om.MTimerMessage
    will never fire. Qt timers also do not tick during a sequence render.
    The solution is to have a background thread that pushes RPC updates,
    and to update presence details manually from the MEL callbacks for
    render start/end.
    The thread handles rate limiting updates, so callers can publish
    to it as frequently as they desire."""

    def __init__(self, app_id: str):
        super().__init__(name="MayaPresenceRPC", daemon=True)
        self._client = Presence(app_id)
        self._connected = False
        self._stop = threading.Event()
        self._stopped = False
        self._last_update_time = 0.0
        self._lock = threading.Lock()
        self._details = RPCUpdateDetails("maya")

    def stop(self, timeout: float = 2.0) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._stop.set()
        if self.is_alive() and threading.current_thread() is not self:
            try:
                self.join(timeout=timeout)
            except RuntimeError:
                pass
        try:
            if self._connected:
                self._client.clear()
        except BaseException:
            pass
        try:
            self._client.close()
        except BaseException:
            pass
        self._connected = False

    def _ensure_connected(self) -> bool:
        if self._connected:
            return True
        try:
            self._client.connect()
            self._connected = True
            return True
        except Exception as e:  # noqa: BLE001
            mp_print(f"worker connect failed: {e}")
            return False

    def _push(self) -> None:
        if not self._ensure_connected():
            return
        try:
            with self._lock:
                rpc_update(self._details, self._client, MP_PREFS.enableTime)
        except _RPC_LOST_EXC as e:
            self._connected = False
            mp_print(f"worker push failed: {e}")
        except Exception as e:  # noqa: BLE001
            mp_print(f"worker push error (non-fatal): {e}")

    def publish(self, details) -> None:
        """Called at the end of mp_update_presence. Makes a local copy of
        the details object which is used in RPC updates to avoid reading a
        half-updated details object with inconsistent fields if the thread
        ticks for an update between events in the mp_update_presence function.
        Prefs are not copied since they only update one-at-a-time via user
        interaction, while details need to be updated all at once.
        """
        with self._lock:
            self._details = copy.copy(details)

    def _clear(self) -> None:
        if not self._connected:
            return
        try:
            self._client.clear()
        except _RPC_LOST_EXC as e:
            self._connected = False
            mp_print(f"worker clear failed: {e}")
        except Exception as e:  # noqa: BLE001
            mp_print(f"worker clear error (non-fatal): {e}")

    def run(self) -> None:
        while not self._stopped:
            self._stop.wait(1)
            if not MP_PREFS.generalEnable:
                continue
            if time.time() - self._last_update_time > MP_PREFS.generalUpdate:
                self._push()
                self._last_update_time = time.time()


MP_WORKER: Optional[_MPRPCWorker] = None


class MPExtensionMonitor:
    """
    Watch known render engine plugins (Redshift, Arnold, V-Ray, RenderMan, Octane).
    We maintain whether the engine is loaded and a list of its custom types, so
    if the user enables counting lights, materials, or textures from the engine
    we can iterate the types and count them with `cmds.ls`.
    """

    class Engine:
        def __init__(
            self, pn: str, rn: str, light_path=None, mat_path=None, tex_path=None
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
                light_path="rendernode/octane/node",  # some non-light stuff in here - refactor?
            ),
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
            if engine.loaded and MP_PREFS.countExtensions and engine.types is not None:
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
            verts = shorten_number(int(verts))
            face_str = "face" if int(faces) == 1 else "faces"
            faces = shorten_number(int(faces))
            return f"{verts} {vert_str} | {faces} {face_str}"
        except (
            ValueError
        ):  # For some reason during startup verts is occasionally a string
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
            return get_file_size_str(os.path.getsize(p))
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
        presets = {"game": 15, "film": 24, "pal": 25, "ntsc": 30,
                   "show": 48, "palf": 50, "ntscf": 60}  # fmt: skip
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


def mp_update_large_icon(ctx: MPContext):
    MP_UPDATE_DETAILS.large_icon = "maya"
    if MP_PREFS.displayVersion:
        MP_UPDATE_DETAILS.large_icon_text = f"Maya {ctx.get_version_str()}"
    else:
        MP_UPDATE_DETAILS.large_icon_text = "Maya"


def mp_update_small_icon_rendering(ctx: MPContext):
    icon_file_name = None
    icon_text = ""
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
    return icon_file_name, icon_text


def mp_update_small_icon_tool():
    icon_file_name = None
    icon_text = ""
    tc = cmds.currentCtx()
    if (
        tc.startswith("poly")
        or tc.startswith("manip")
        or tc.startswith("curve")
        or tc.startswith("target")
    ):
        icon_file_name = "modeling"
        icon_text = "Modeling"
    elif tc.startswith("sculpt"):
        icon_file_name = "sculpt"
        icon_text = "Sculpting"
    elif tc.startswith("tex"):
        icon_file_name = "uv"
        icon_text = "UV Editing"
    elif tc.startswith("joint") or tc.startswith("ik") or tc.startswith("skin"):
        icon_file_name = "pose"
        icon_text = "Rigging"
    elif tc.startswith("keyframe") or tc.startswith("filter"):
        icon_file_name = "animation"
        icon_text = "Animation"
    return icon_file_name, icon_text


def mp_update_small_icon(ctx: MPContext):
    icon_file_name = None
    icon_text = ""
    if not MP_PREFS.displaySmallIcon:
        MP_UPDATE_DETAILS.small_icon = icon_file_name
        MP_UPDATE_DETAILS.small_icon_text = icon_text
        return
    if MP_PREFS.displayEngine and MP_SESSION.is_rendering:
        icon_file_name, icon_text = mp_update_small_icon_rendering(ctx)
    else:
        try:
            # "Modeling - Expert", "Pose Sculpting", etc.
            space_name = (
                cmds.workspaceLayoutManager(query=True, current=True).lower() or ""
            )
        except Exception:
            space_name = ""
        if space_name and space_name != "general":
            icon_file_name = (
                space_name[: space_name.find(" ")]
                if space_name.find(" ") > 0
                else space_name
            )
            icon_text = space_name.title()
        else:
            icon_file_name, icon_text = mp_update_small_icon_tool()
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
    if MP_PREFS.enableDetails and MP_SESSION.is_rendering:
        res = ctx.get_render_resolution()
        fname = ctx.get_file_name()
        frame_range = ctx.get_frame_range()
        fps = ctx.get_render_fps()
        MP_UPDATE_DETAILS.details_text = format_render_details(
            file_name=fname,
            res=res,
            rendered_frames=MP_SESSION.rendered_frames,
            total_frames=frame_range[1],
            fps=fps,
            prefs=MP_PREFS,
        )
    elif MP_PREFS.enableDetails:
        update_slot(
            ctx, "details", MP_PREFS, MP_UPDATE_DETAILS, MP_DISPLAY_TYPES, MP_SESSION
        )


def mp_update_presence_state(ctx: MPContext):
    update_slot(ctx, "state", MP_PREFS, MP_UPDATE_DETAILS, MP_DISPLAY_TYPES, MP_SESSION)


def mp_update_presence():
    try:
        if MP_PREFS.detailsCycle or MP_PREFS.stateCycle:
            advance_cycle(MP_SESSION, MP_DISPLAY_TYPES)
        ctx = MPContext.capture()
        if ctx is None:
            return
        else:
            mp_update_large_icon(ctx)
            mp_update_small_icon(ctx)
            mp_update_presence_state(ctx)
            mp_update_presence_details(ctx)
            update_buttons(MP_UPDATE_DETAILS, MP_PREFS)
            MP_UPDATE_DETAILS.start_time = MP_SESSION.start_time
    except Exception as e:  # noqa: BLE001
        mp_print(f"Failed to publish update to worker thread: {e}")
    worker = _get_worker()
    if worker is not None:
        worker.publish(MP_UPDATE_DETAILS)


###################
# Render Handlers #
###################

MP_HOOK_START = "/* MayaPresence:Hook:Begin */"
MP_HOOK_END = " /* MayaPresence:Hook:End */"


def mp_wrap_mel(
    py_call: Callable[[], None], surface_except: bool = False, wrap: bool = True
) -> str:
    """
    Accept a Python function name from this module and return a MEL expression which will invoke it.
    The Python function cannot take arguments. The MEL will be comment-wrapped with indicators
    that it came from MayaPresence, and the Python will be in a try-except that silently fails.
    """
    mp = "_mp"
    start = f"{MP_HOOK_START} " if wrap else ""  # fmt: skip
    end = f"{MP_HOOK_END}" if wrap else ""  # fmt:skip
    exc = ' as e:","\tprint(e)")' if surface_except else ':","\tpass")'
    exc = f'"except Exception{exc}'
    return (
        f"{start}"
        f'python("try:","\timport maya_presence as {mp}",'
        f'"\t{mp}.{py_call.__name__}()",'
        f"{exc}"
        f"{end}"
    )


def mp_on_render_start():
    on_render_start(MP_SESSION)
    mp_update_presence()


def mp_on_render_end():
    on_render_end(MP_SESSION)
    mp_update_presence()


def mp_on_frame_render_end():
    on_frame_render_end(MP_SESSION)
    mp_update_presence()


# Render-hook install sites: (node, attr, py_call).
#
#   defaultRenderGlobals  — Maya's stock node, used by Maya Software,
#                           Maya Hardware, Arnold, V-Ray, RenderMan, etc.
#                           Per empirical observation, preMel/postMel
#                           fire per-frame and postRenderMel fires once
#                           at the end of a sequence.
#
#   redshiftOptions       — Redshift's own options node, only exists when
#                           the Redshift plug-in is loaded. Redshift's
#                           semantics are cleaner: preRenderMel and
#                           postRenderMel bracket the entire render;
#                           postRenderFrameMel fires per frame.
#
_RENDER_HOOK_SITES: "List[Tuple[str, str, Callable[[], None]]]" = [
    ("defaultRenderGlobals", "preMel", mp_on_render_start),
    ("defaultRenderGlobals", "postMel", mp_on_render_end),
    ("defaultRenderGlobals", "postRenderMel", mp_on_frame_render_end),
    ("redshiftOptions", "preRenderMel", mp_on_render_start),
    ("redshiftOptions", "postRenderMel", mp_on_render_end),
    ("redshiftOptions", "postRenderFrameMel", mp_on_frame_render_end),
]


def _hook_state(node: str, attr: str) -> bool:
    """Returns True if a hook is currently installed at <node>.<attr> or
    the attribute doesn't exist (e.g., an engine that isn't loaded), and
    False if the attr exists but our fragment isn't there."""
    try:
        existing = cmds.getAttr(f"{node}.{attr}")
    except (RuntimeError, ValueError): # fmt: skip
        return True
    if existing is None:
        return False
    return MP_HOOK_START in existing


def mp_check_render_handlers_installed() -> bool:
    """Return True if all hooks are installed."""
    for node, attr, _py in _RENDER_HOOK_SITES:
        if not _hook_state(node, attr):
            return False
    return True


def mp_install_render_handlers(*args):  # pylint: disable=unused-argument
    """Append our hook fragment to each render-hook site that exists and
    doesn't already have our fragment."""
    if not MP_PREFS.useRenderHooks:
        return
    for node, attr, py_call in _RENDER_HOOK_SITES:
        state = _hook_state(node, attr)
        if state:
            continue  # already installed or does not exist
        plug = f"{node}.{attr}"
        try:
            existing = cmds.getAttr(plug) or ""
            cmds.setAttr(plug, existing + mp_wrap_mel(py_call), type="string")
        except (RuntimeError, ValueError) as e:
            mp_print(f"could not install handler {plug}: {e}")


def mp_uninstall_render_handlers(*args):  # pylint: disable=unused-argument
    """Strip hooks from every applicable site."""
    pattern = re.compile(
        re.escape(MP_HOOK_START) + r".*?" + re.escape(MP_HOOK_END), re.DOTALL
    )
    for node, attr, _py in _RENDER_HOOK_SITES:
        plug = f"{node}.{attr}"
        try:
            existing = cmds.getAttr(plug)
        except RuntimeError:
            continue  # node not present
        if not existing:
            continue
        stripped = pattern.sub("", existing)
        if stripped == existing:
            continue
        try:
            cmds.setAttr(plug, stripped, type="string")
        except (RuntimeError, ValueError) as e:
            mp_print(f"could not restore handler {plug}: {e}")


#####################
# GUI Settings Menu #
#####################


class MayaPresenceSettings(MayaQWidgetDockableMixin, QtSettingsGUIMenu):
    pass


def mp_on_setting_change():
    if not MP_PREFS.useRenderHooks and mp_check_render_handlers_installed():
        mp_uninstall_render_handlers()
    elif MP_PREFS.useRenderHooks and not mp_check_render_handlers_installed():
        mp_install_render_handlers()
    mp_update_presence()
    mp_refresh_timer()


def mp_show_settings_dialog():
    global MP_SETTINGS_WINDOW
    if MP_SETTINGS_WINDOW is not None:
        try:
            MP_SETTINGS_WINDOW.close()
            MP_SETTINGS_WINDOW.deleteLater()
        except Exception:
            pass
    MP_SETTINGS_WINDOW = MayaPresenceSettings(
        prefs=MP_PREFS, refresh_func=mp_on_setting_change, app_name="Maya"
    )
    MP_SETTINGS_WINDOW.show()
    MP_SETTINGS_WINDOW.raise_()
    MP_SETTINGS_WINDOW.activateWindow()
    return MP_SETTINGS_WINDOW


def _mp_add_settings_menu_item():
    """Add the settings menuItem under mainWindowMenu. Called from the PMC
    the first time the user opens the Window menu, or directly by tests."""
    if cmds.menuItem("mayaPresenceSettingsMenuItem", exists=True):
        return
    cmds.menuItem(
        "mayaPresenceSettingsMenuItem",
        label="Maya Presence Settings…",
        parent="mainWindowMenu",
        command=lambda *_: mp_show_settings_dialog(),
    )


MP_MENU_PMC = mp_wrap_mel(_mp_add_settings_menu_item, True, False)


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
    cmds.menu(
        "mainWindowMenu", edit=True, postMenuCommand=existing_pmc + ";;" + MP_MENU_PMC
    )


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


#############
# Callbacks #
#############


def mp_observe_plugin_load(string_array, clientData):  # pylint: disable=unused-argument,invalid-name
    """
    See if a render engine was loaded and update the extensions data if so.
    """
    if not string_array:
        return
    # kAfterPluginLoad string array: [plugin_path, plugin_name]
    loaded_plugin_name = string_array[-1]
    for engine_name, engine in MP_EXTENSIONS.monitored_engines.items():
        if engine.plugin_name == loaded_plugin_name:
            MP_EXTENSIONS.init_engine(engine_name)
            return


def mp_observe_plugin_unload(string_array, clientData):  # pylint: disable=unused-argument,invalid-name
    """
    Check if plugin unloading removed a render engine
    """
    if not string_array:
        return
    # kAfterPluginUnload string array: [plugin_name, plugin_path]
    unloaded_plugin_name = string_array[0]
    for _, engine in MP_EXTENSIONS.monitored_engines.items():
        if engine.plugin_name == unloaded_plugin_name:
            engine.loaded = False


def mp_add_callbacks():
    """
    Register all callbacks.
    1. kAfterNew, kAfterOpen: Call the render hook installers on new or opened
        scenes. The handlers respect the user install preferences.
    2. kAfterPluginLoad: check if the plugin clobbered the callbacks. Also,
       check if the plugin is a known render engine and load its types.
    3. kAfterPluginUnload: check if hooks were clobbered on unload, and if a
       monitored engine is no longer present.
    """
    k_new = om.MSceneMessage.addCallback(
        om.MSceneMessage.kAfterNew, mp_install_render_handlers
    )
    k_open = om.MSceneMessage.addCallback(
        om.MSceneMessage.kAfterOpen, mp_install_render_handlers
    )
    k_load = om.MSceneMessage.addStringArrayCallback(
        om.MSceneMessage.kAfterPluginLoad, mp_observe_plugin_load
    )
    k_unload = om.MSceneMessage.addStringArrayCallback(
        om.MSceneMessage.kAfterPluginUnload, mp_observe_plugin_unload
    )
    MP_CALLBACKS.add(("kAfterNew", k_new))
    MP_CALLBACKS.add(("kAfterOpen", k_open))
    MP_CALLBACKS.add(("kAfterPluginLoad", k_load))
    MP_CALLBACKS.add(("kAfterPluginUnload", k_unload))


def mp_remove_callbacks():
    """
    Attempt to uninstall all of the handler callbacks.
    """
    for cb in MP_CALLBACKS.copy():
        cb_name, cb_id = cb
        try:
            om.MMessage.removeCallback(cb_id)
        except RuntimeError as e:
            mp_print(f"failed to remove callback {cb_name}: {e}")
    MP_CALLBACKS.clear()


#############
# Threading #
#############


def mp_on_timer(elapsed_time, last_time, client_data):  # pylint: disable=unused-argument
    # Redshift appears to lazily install its MEL callbacks, only creating the objects
    # when the Redshift render settings are first opened.
    if not mp_check_render_handlers_installed():
        mp_install_render_handlers()
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
    MP_SESSION.start_time = time.time()
    global MP_WORKER
    existing_worker = _get_worker()
    if existing_worker is not None:
        MP_WORKER = existing_worker
    else:
        MP_WORKER = _MPRPCWorker(MP_DISCORD_APP_ID)
        MP_WORKER.start()
        _set_worker(MP_WORKER)
    mp_update_presence()
    if MP_PREFS.displayRenderStats:
        mp_install_render_handlers()
    mp_install_settings_menu()
    mp_check_loaded_engines()
    mp_add_callbacks()
    mp_schedule()


def mp_stop():
    if cmds.about(batch=True):
        return
    global MP_WORKER
    worker = MP_WORKER
    cleanup_steps = [
        ("cancel timer", mp_cancel),
        ("stop RPC worker", worker.stop if worker is not None else None),
        ("remove callbacks", mp_remove_callbacks),
        ("uninstall render handlers", mp_uninstall_render_handlers),
        ("uninstall settings menu", mp_uninstall_settings_menu),
    ]
    for description, step in cleanup_steps:
        if step is None:
            continue
        try:
            step()
        except Exception as e:
            mp_print(f"failed to {description}: {e}")
    MP_WORKER = None
    delattr(builtins, MP_WORKER_ATTR)


def initializePlugin(mobject):
    # pylint: disable=unused-variable
    fn = om.MFnPlugin(mobject, "MarlArini", "1.0", "Any")  # noqa: F841
    mp_start()


def uninitializePlugin(plugin):
    mp_stop()


def _mp_atexit():
    """Insurance against process exit without uninitializePlugin (e.g. Maya
    killed). stop() drains clear+close from inside the worker."""
    worker = MP_WORKER
    if worker is not None:
        try:
            worker.stop(timeout=1.0)
        except BaseException:
            pass


atexit.register(_mp_atexit)
