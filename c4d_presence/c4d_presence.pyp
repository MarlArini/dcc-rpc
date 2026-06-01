"""
C4DPresence is a Discord Rich Presence client plugin for Cinema 4D, based on
https://github.com/abrasic/blendpresence. C4DPresence has been tested on Cinema
4D 2026.2. For more info, see https://github.com/MarlArini/dcc-rpc.
"""

import atexit
from enum import IntEnum, auto
from typing import Tuple, List, ClassVar, Dict, Any
from pathlib import Path
from dataclasses import dataclass, field
import os
import sys
import time

import c4d

# Bootstrap: ensure this plugin's directory is on sys.path so the sibling
# common.py and pypresence/ resolve when loaded by the host application.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from pypresence.presence import Presence

from common import (
    get_file_size_str,
    SharedSettings,
    plural,
    SessionInfo,
    RPCUpdateDetails,
    connect_rpc,
    push_rpc_update,
    update_buttons,
    update_slot,
    advance_cycle,
    force_clear_on_exit,
)


#############
# Constants #
#############

_C4D_CORE_PLUGIN_ID = 1068734
_C4D_PREF_PLUGIN_ID = 1068749

_C4D_RENDER_ENGINES = {
    c4d.RDATA_RENDERENGINE_STANDARD: "Standard",
    c4d.RDATA_RENDERENGINE_PHYSICAL: "Physical",
    c4d.RDATA_RENDERENGINE_PREVIEWHARDWARE: "Viewport",
    c4d.RDATA_RENDERENGINE_REDSHIFT: "Redshift",
    1053272: "V-Ray",
    1029525: "Octane",
    1029988: "Arnold",
}

_LIGHTS: frozenset[int] = frozenset(
    [
        c4d.Olight,
        c4d.Osky,
        c4d.Oenvironment,
        1053282,  # V-Ray
        1053279,
        1053276,
        1053275,
        1061436,
        1053287,
        1053278,
        1059898,
        1053277,
        1053281,
        1053280,
        1036751,  # Redshift
        1036754,
        1030424,  # Arnold
    ]
)

_MG_GENERATORS_DEFORMERS: frozenset[int] = frozenset(
    [
        c4d.Omgcloner,
        c4d.Omgmatrix,
        c4d.Omgscatter,
        c4d.Omgfracture,
        c4d.Omgvoronoifracture,
        c4d.Omginstance,
        c4d.Omgtracer,
        c4d.Omgsplinegen,
        c4d.Omgextrude,
        c4d.Omgpolyfx,
    ]
)

_MG_EFFECTORS: frozenset[int] = frozenset(
    [
        c4d.Omgplain,
        c4d.Omgdelay,
        c4d.Omgformula,
        c4d.Omginheritance,
        c4d.Omgpushapart,
        c4d.Omgpython,
        c4d.Omgrandom,
        c4d.Omgreeffector,
        c4d.Omgshader,
        c4d.Omgsound,
        c4d.Omgspline,
        c4d.Omgstep,
        c4d.Omgeffectortarget,
        c4d.Omgtime,
        c4d.Omgvolume,
        c4d.Omgcoffee,
        c4d.Omgroup,
    ]
)

_C4D_MODES = {
    c4d.Mcamera: "Camera",
    c4d.Mobject: "Object",
    c4d.Mtexture: "Texture",
    c4d.Mtextureaxis: "Texture Axis",
    c4d.Mpoints: "Point",
    c4d.Medges: "Edge",
    c4d.Mpolygons: "Polygon",
    c4d.Manimation: "Animation",
    c4d.Mkinematic: "IK",
    c4d.Mmodel: "Model",
    c4d.Mpaint: "Paint",
    c4d.Muvpoints: "UV Points",
    c4d.Muvedges: "UV Edge",
    c4d.Muvpolygons: "UV Polygons",
    c4d.Muvon: "UV",
    c4d.Mdrag: "Drag",
    c4d.Mpolyedgepoint: "Poly / Edge / Point",
    c4d.Medgepoint: "Edge / Point",
    c4d.Mworkplane: "Workplane",
}


class C4DP(IntEnum):
    C4DPRESENCE_INFODOC = 0
    C4DPRESENCE_INFOOBJ = auto()
    C4DPRESENCE_INFOPLY = auto()
    C4DPRESENCE_INFOGEN = auto()
    C4DPRESENCE_INFOEFF = auto()
    C4DPRESENCE_INFOLIG = auto()
    C4DPRESENCE_INFOCAM = auto()
    C4DPRESENCE_INFOMAT = auto()
    C4DPRESENCE_INFOTEX = auto()
    C4DPRESENCE_INFOFRM = auto()
    C4DPRESENCE_MAIN_GROUP = 999
    C4DPRESENCE_GENERAL = 1000
    C4DPRESENCE_GENERALENABLE = auto()
    C4DPRESENCE_GENERALUPDATE = auto()
    C4DPRESENCE_ENABLETIME = auto()
    C4DPRESENCE_RESETTIMER = auto()
    C4DPRESENCE_ICONS = auto()
    C4DPRESENCE_SHOWVERSION = auto()
    C4DPRESENCE_SMALLICONS = auto()
    C4DPRESENCE_DETAILS = 2000
    C4DPRESENCE_DFIELD = auto()
    C4DPRESENCE_DTYPE = auto()
    C4DPRESENCE_DCUSTOM = auto()
    C4DPRESENCE_DCYCLE = auto()
    C4DPRESENCE_STATE = 3000
    C4DPRESENCE_SFIELD = auto()
    C4DPRESENCE_STYPE = auto()
    C4DPRESENCE_SCUSTOM = auto()
    C4DPRESENCE_SCYCLE = auto()
    C4DPRESENCE_RENDERING = 4000
    C4DPRESENCE_RENDERICON = auto()
    C4DPRESENCE_GPUSTR = auto()
    C4DPRESENCE_RENDERSTATS = auto()
    C4DPRESENCE_RENDERFILE = auto()
    C4DPRESENCE_RENDERFRAME = auto()
    C4DPRESENCE_BUTTONS = 5000
    C4DPRESENCE_B1 = 5100
    C4DPRESENCE_B1ON = auto()
    C4DPRESENCE_B1LABEL = auto()
    C4DPRESENCE_B1URL = auto()
    C4DPRESENCE_B2 = 5200
    C4DPRESENCE_B2ON = auto()
    C4DPRESENCE_B2LABEL = auto()
    C4DPRESENCE_B2URL = auto()
    C4DPRESENCE_RESETALL = 6000


_C4D_INFOTYPE_MAP = {
    C4DP.C4DPRESENCE_INFODOC: "document",
    C4DP.C4DPRESENCE_INFOOBJ: "object",
    C4DP.C4DPRESENCE_INFOPLY: "mesh",
    C4DP.C4DPRESENCE_INFOGEN: "generator",
    C4DP.C4DPRESENCE_INFOEFF: "effector",
    C4DP.C4DPRESENCE_INFOLIG: "light",
    C4DP.C4DPRESENCE_INFOCAM: "cam",
    C4DP.C4DPRESENCE_INFOMAT: "mat",
    C4DP.C4DPRESENCE_INFOTEX: "tex",
    C4DP.C4DPRESENCE_INFOFRM: "frame",
}

_C4DP_CONST_DISPATCH = {  # id: (type, name, default)
    C4DP.C4DPRESENCE_GENERALENABLE: ("bool", "generalEnable", True),
    C4DP.C4DPRESENCE_GENERALUPDATE: ("int", "generalUpdate", 15),
    C4DP.C4DPRESENCE_ENABLETIME: ("bool", "enableTime", True),
    C4DP.C4DPRESENCE_RESETTIMER: ("bool", "resetTimer", True),
    C4DP.C4DPRESENCE_SHOWVERSION: ("bool", "displayVersion", True),
    C4DP.C4DPRESENCE_SMALLICONS: ("bool", "displaySmallIcon", True),
    C4DP.C4DPRESENCE_DFIELD: ("bool", "enableDetails", True),
    C4DP.C4DPRESENCE_DTYPE: ("int", "detailsType", C4DP.C4DPRESENCE_INFODOC),
    C4DP.C4DPRESENCE_DCUSTOM: ("str", "customDetails", ""),
    C4DP.C4DPRESENCE_DCYCLE: ("bool", "detailsCycle", False),
    C4DP.C4DPRESENCE_SFIELD: ("bool", "enableState", True),
    C4DP.C4DPRESENCE_STYPE: ("int", "stateType", C4DP.C4DPRESENCE_INFOOBJ),
    C4DP.C4DPRESENCE_SCUSTOM: ("str", "customState", ""),
    C4DP.C4DPRESENCE_SCYCLE: ("bool", "stateCycle", False),
    C4DP.C4DPRESENCE_RENDERICON: ("bool", "displayEngine", True),
    C4DP.C4DPRESENCE_GPUSTR: ("bool", "displayGPU", True),
    C4DP.C4DPRESENCE_RENDERSTATS: ("bool", "displayRenderStats", True),
    C4DP.C4DPRESENCE_RENDERFILE: ("bool", "displayFileName", True),
    C4DP.C4DPRESENCE_RENDERFRAME: ("bool", "displayFrames", True),
    C4DP.C4DPRESENCE_B1ON: ("bool", "enableButton1", True),
    C4DP.C4DPRESENCE_B1LABEL: ("str", "button1Label", ""),
    C4DP.C4DPRESENCE_B1URL: ("str", "button1Url", ""),
    C4DP.C4DPRESENCE_B2ON: ("bool", "enableButton2", True),
    C4DP.C4DPRESENCE_B2LABEL: ("str", "button2Label", ""),
    C4DP.C4DPRESENCE_B2URL: ("str", "button2Url", ""),
}

_C4D_TYPE_GETTERS = {"bool": "GetBool", "int": "GetInt32", "str": "GetString"}
_C4D_TYPE_SETTERS = {"bool": "SetBool", "int": "SetInt32", "str": "SetString"}
_C4DP_TYPE_DISPATCH = {
    "bool": c4d.DTYPE_BOOL,
    "int": c4d.DTYPE_LONG,
    "str": c4d.DTYPE_STRING,
}

_C4DP_CONTROLLERS = {
    C4DP.C4DPRESENCE_DTYPE: C4DP.C4DPRESENCE_DFIELD,
    C4DP.C4DPRESENCE_DCUSTOM: C4DP.C4DPRESENCE_DFIELD,
    C4DP.C4DPRESENCE_DCYCLE: C4DP.C4DPRESENCE_DFIELD,
    C4DP.C4DPRESENCE_STYPE: C4DP.C4DPRESENCE_SFIELD,
    C4DP.C4DPRESENCE_SCUSTOM: C4DP.C4DPRESENCE_SFIELD,
    C4DP.C4DPRESENCE_SCYCLE: C4DP.C4DPRESENCE_SFIELD,
    C4DP.C4DPRESENCE_B1LABEL: C4DP.C4DPRESENCE_B1ON,
    C4DP.C4DPRESENCE_B1URL: C4DP.C4DPRESENCE_B1ON,
    C4DP.C4DPRESENCE_B2LABEL: C4DP.C4DPRESENCE_B2ON,
    C4DP.C4DPRESENCE_B2URL: C4DP.C4DPRESENCE_B2ON,
}


def _c4d_get(basecontainer, kind, param_id):
    return getattr(basecontainer, _C4D_TYPE_GETTERS[kind])(param_id)


def _c4d_set(basecontainer, kind, param_id, value):
    getattr(basecontainer, _C4D_TYPE_SETTERS[kind])(param_id, value)


############
# Settings #
############


@dataclass
class C4DPSettings(SharedSettings):
    # pylint: disable=invalid-name
    displayEngine: bool = field(
        default=True,
        metadata={"group": "Details", "label": "Display active render engine on hover"},
    )
    displayGPU: bool = field(
        default=True,
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
    _INITIAL_DEFAULTS: ClassVar[Dict[str, Any]] = {
        "detailsType": "document",
        "stateType": "object",
    }
    INFO_CHOICES: ClassVar[List[Tuple[str, str]]] = [
        ("Active document", "document"),
        ("Active object", "object"),
        ("Poly object count", "mesh"),
        ("MoGraph generator count", "generator"),
        ("MoGraph effector count", "effector"),
        ("Light count", "light"),
        ("Camera count", "cam"),
        ("Material count", "mat"),
        ("Texture count", "tex"),
        ("Current frame", "frame"),
    ]


class C4DPSession(SessionInfo):
    render_is_animated: bool = False


C4DP_PREFS = C4DPSettings()
C4DP_SESSION = C4DPSession()
C4DP_UPDATE_DETAILS = RPCUpdateDetails("cinema4d")
C4DP_CLIENT = Presence("1510781737238528020")


def _walk_objects(roots: List[c4d.BaseObject]):
    objs: List[c4d.BaseObject] = []

    def walk(obj: c4d.BaseObject):
        nonlocal objs
        objs.append(obj)
        child = obj.GetDown()
        while child:
            walk(child)
            child = child.GetNext()

    for obj in roots:
        walk(obj)
    return objs


###########
# Context #
###########


@dataclass
class C4DContext:
    document: c4d.documents.BaseDocument
    objects: List[c4d.BaseObject]

    @classmethod
    def capture(cls) -> "C4DContext":
        doc = c4d.documents.GetActiveDocument()
        return cls(document=doc, objects=_walk_objects(doc.GetObjects()))

    def get_gpu_str(self) -> str | None:
        try:
            bc = c4d.GetMachineFeatures()
            return bc[c4d.DRAWPORT_RENDERER_NAME]
        except RuntimeError:
            return None

    def get_document_name(self) -> str:
        return self.document.GetDocumentName()

    def get_object_count(self) -> str:
        count = len(self.objects)
        return plural(count, "object")

    def get_mesh_count(self) -> str:
        count = sum([1 for o in self.objects if o.GetType() == c4d.Opolygon])
        return plural(count, "mesh", "es")

    def get_cam_count(self) -> str:
        cams = sum(
            [
                1
                for o in self.objects
                if o.GetType() == c4d.Ocamera or o.GetType() == c4d.Orscamera
            ]
        )
        # Octane, V-Ray, Arnold use default c4d.Ocamera type
        return plural(cams, "camera")

    def get_light_count(self) -> str:
        lights = sum(
            [
                1
                for o in self.objects
                if o.GetType() in _LIGHTS
                or (
                    o.GetType() == 5140 and o.GetTypeName() == "Light"
                )  # Octane lights are nulls
            ]
        )
        return plural(lights, "light")

    def get_mograph_generator_count(self) -> str:
        count = sum(
            [1 for o in self.objects if o.GetType() in _MG_GENERATORS_DEFORMERS]
        )
        return plural(count, "MoGraph generator")

    def get_mograph_effector_count(self) -> str:
        count = sum([1 for o in self.objects if o.GetType() in _MG_EFFECTORS])
        return plural(count, "MoGraph effector")

    def get_mat_count(self) -> str:
        # Includes extension materials
        count = len(self.document.GetMaterials())
        return plural(count, "material")

    def get_tex_count(self) -> str:
        # Includes extension textures
        count = len(self.document.GetAllTextures())
        return plural(count, "texture")

    def get_color_info(self) -> str:
        spaces = self.document.GetActiveOcioColorSpacesNames()
        return f"{spaces[1]} ({spaces[2]})"

    def get_current_frame(self) -> str:
        current_time = self.document.GetTime()
        fps = self.get_fps()
        frame = current_time.GetFrame(fps)
        return f"Frame {frame}"

    def get_file_size(self) -> str | None:
        file_path = self.document.GetDocumentPath()
        if not file_path:
            return None
        file_name = self.get_document_name()
        p = Path(file_path) / Path(file_name)
        if not p.exists():
            return None
        sz = os.path.getsize(p)
        return get_file_size_str(sz)

    def get_version_str(self) -> str:
        ver = c4d.GetC4DVersion()
        year = str(ver)[:4]
        release = int(str(ver)[4:])
        while release % 10 == 0 and release > 0:
            release = release // 10
        return f"{year}.{str(release)}"

    def get_render_engine_str(self) -> str:
        render_info = self.document.GetActiveRenderData()
        engine_id = render_info[c4d.RDATA_RENDERENGINE]
        if (engine := _C4D_RENDER_ENGINES.get(engine_id, None)) is not None:
            return engine
        return "Unknown render engine"

    def get_frame_range(self) -> Tuple[int, int]:
        fps = self.get_fps()
        min_time = self.document.GetMinTime()
        max_time = self.document.GetMaxTime()
        return (min_time.GetFrame(fps), max_time.GetFrame(fps))

    def get_active_object(self) -> str | None:
        obj = self.document.GetActiveObject()
        return f"Active: {obj.GetName()}" if obj else None

    def get_render_resolution(self) -> Tuple[int, int] | None:
        render_info = self.document.GetActiveRenderData()
        res_info = render_info.GetResolution()
        return (res_info[0], res_info[1])

    def get_fps(self) -> int | None:
        return self.document.GetFps()


#################
# Rich Presence #
#################


def c4d_connect_rpc():
    return connect_rpc(C4DP_CLIENT, "Cinema 4D")


def c4d_push_rpc_update(*args):  # pylint: disable=unused-argument
    push_rpc_update(
        C4DP_SESSION, C4DP_UPDATE_DETAILS, C4DP_PREFS, C4DP_CLIENT, "Cinema 4D"
    )


def c4d_update_large_icon(ctx: C4DContext):
    C4DP_UPDATE_DETAILS.large_icon = "cinema4d"
    if C4DP_PREFS.displayVersion:
        C4DP_UPDATE_DETAILS.large_icon_text = f"Cinema 4D {ctx.get_version_str()}"
    else:
        C4DP_UPDATE_DETAILS.large_icon_text = "Cinema 4D"


def c4d_update_small_icon(ctx: C4DContext):
    icon_file_name = None
    icon_text = ""
    if C4DP_PREFS.displaySmallIcon:
        if C4DP_PREFS.displayEngine and C4DP_SESSION.is_rendering:
            # No icons for Viewport / Standard / Physical
            engines = ["Arnold", "Redshift", "V-Ray", "Octane"]
            current_engine = ctx.get_render_engine_str()
            if current_engine in engines:
                icon_file_name = current_engine.lower().replace("-", "")
                icon_text = current_engine
            # GPU
            if C4DP_PREFS.displayGPU:
                gpustr = ctx.get_gpu_str()
                if gpustr and icon_text:
                    icon_text += " | " + gpustr
        else:
            mode = ctx.document.GetMode()
            mode_name = _C4D_MODES.get(mode, None)
            if mode_name:
                icon_name = mode_name.lower().split(" ")[0]
                icon_file_name = icon_name
                icon_text = mode_name

    C4DP_UPDATE_DETAILS.small_icon = icon_file_name
    C4DP_UPDATE_DETAILS.small_icon_text = icon_text


C4DP_DISPLAY_TYPES = {
    "document": lambda ctx: ctx.get_document_name(),
    "object": lambda ctx: ctx.get_active_object(),
    "mesh": lambda ctx: ctx.get_mesh_count(),
    "generator": lambda ctx: ctx.get_mograph_generator_count(),
    "effector": lambda ctx: ctx.get_mograph_effector_count(),
    "light": lambda ctx: ctx.get_light_count(),
    "cam": lambda ctx: ctx.get_cam_count(),
    "mat": lambda ctx: ctx.get_mat_count(),
    "tex": lambda ctx: ctx.get_tex_count(),
    "frame": lambda ctx: ctx.get_current_frame(),
}


def c4d_update_presence_details(ctx: C4DContext):
    # Rendering Details
    # TODO simplify string build
    if C4DP_PREFS.enableDetails and C4DP_SESSION.is_rendering:
        res = ctx.get_render_resolution()
        fname = ctx.get_document_name()
        frame_range = ctx.get_frame_range()
        fps = ctx.get_fps()
        C4DP_UPDATE_DETAILS.details_text = (
            "Rendering"
            + (f" {fname}" if fname and C4DP_PREFS.displayFileName else "")
            + (
                ": "
                if (res is not None and C4DP_PREFS.displayRenderStats)
                or (C4DP_PREFS.displayFrames and frame_range[1])
                else ""
            )
            + (
                f"{res[0]}x{res[1]}, "
                if res is not None and C4DP_PREFS.displayRenderStats
                else ""
            )
            + (
                f"Frame {C4DP_SESSION.rendered_frames} of {frame_range[1]}"
                if C4DP_PREFS.displayFrames and frame_range[1]
                else ""
            )
            + (f" @{fps}fps" if fps is not None else "")
        )
    elif C4DP_PREFS.enableDetails:
        update_slot(
            ctx,
            "details",
            C4DP_PREFS,
            C4DP_UPDATE_DETAILS,
            C4DP_DISPLAY_TYPES,
            C4DP_SESSION,
        )


def c4d_update_presence_state(ctx: C4DContext):
    update_slot(
        ctx, "state", C4DP_PREFS, C4DP_UPDATE_DETAILS, C4DP_DISPLAY_TYPES, C4DP_SESSION
    )


def c4d_update_presence():
    if C4DP_PREFS.generalEnable:
        if C4DP_PREFS.detailsCycle or C4DP_PREFS.stateCycle:
            advance_cycle(C4DP_SESSION, C4DP_DISPLAY_TYPES)
        ctx = C4DContext.capture()
        if ctx is None:
            return
        c4d_update_large_icon(ctx)
        c4d_update_small_icon(ctx)
        c4d_update_presence_state(ctx)
        c4d_update_presence_details(ctx)
        update_buttons(C4DP_UPDATE_DETAILS, C4DP_PREFS)
        c4d_push_rpc_update()
    elif C4DP_SESSION.connected:
        try:
            C4DP_CLIENT.clear()
        except Exception as e:  # noqa: BLE001
            print(f"[C4DPresence] clear failed: {e}")
            C4DP_SESSION.connected = False


####################
# Preferences Menu #
####################


def _write_pref(param_id, attr, t_data):
    if param_id in (C4DP.C4DPRESENCE_DTYPE, C4DP.C4DPRESENCE_STYPE):
        setattr(C4DP_PREFS, attr, _C4D_INFOTYPE_MAP.get(t_data, "document"))
    else:
        setattr(C4DP_PREFS, attr, t_data)


def _sync_prefs(basecontainer):
    for field_id, (kind, attr, default) in _C4DP_CONST_DISPATCH.items():
        raw = _c4d_get(basecontainer, kind, field_id)
        if field_id in (C4DP.C4DPRESENCE_DTYPE, C4DP.C4DPRESENCE_STYPE):
            setattr(C4DP_PREFS, attr, _C4D_INFOTYPE_MAP.get(raw, default))
        else:
            setattr(C4DP_PREFS, attr, raw)


def _reset_prefs(basecontainer):
    for field_id, (kind, _attr, default) in _C4DP_CONST_DISPATCH.items():
        _c4d_set(basecontainer, kind, field_id, default)
    _sync_prefs(basecontainer)


class C4DPresencePrefs(c4d.plugins.PreferenceData):
    # pylint: disable=invalid-name, unused-argument, redefined-builtin

    def GetBaseContainer(self) -> c4d.BaseContainer:
        world = c4d.GetWorldContainerInstance()
        if world is None:
            raise RuntimeError(
                "[C4DPresence] warning: could not retrieve world container"
            )
        pref_menu = world.GetContainerInstance(_C4D_PREF_PLUGIN_ID)
        if pref_menu is None:
            world.SetContainer(_C4D_PREF_PLUGIN_ID, c4d.BaseContainer())
            pref_menu = world.GetContainerInstance(_C4D_PREF_PLUGIN_ID)
            if pref_menu is None:
                raise MemoryError(
                    "[C4DPresence] warning: could not create preferences menu"
                )
        return pref_menu

    def Init(self, node: c4d.GeListNode, isCloneInit: bool) -> bool:
        basecontainer = self.GetBaseContainer()
        for field_id, (kind, _attr, default) in _C4DP_CONST_DISPATCH.items():
            desc_id = c4d.DescID(c4d.DescLevel(field_id, _C4DP_TYPE_DISPATCH[kind], 0))
            self.InitPreferenceValue(field_id, default, None, desc_id, basecontainer)
        _sync_prefs(basecontainer)
        return True

    def GetDDescription(
        self, node: c4d.GeListNode, description: c4d.Description, flags: int
    ) -> bool | Tuple[bool, int]:
        if not description.LoadDescription("c4d_presence"):
            return False
        if flags & c4d.DESCFLAGS_DESC_NEEDDEFAULTVALUE:
            basecontainer = self.GetBaseContainer()
            for field_id, (kind, _attr, default) in _C4DP_CONST_DISPATCH.items():
                desc_id = c4d.DescID(
                    c4d.DescLevel(field_id, _C4DP_TYPE_DISPATCH[kind], 0)
                )
                self.InitPreferenceValue(
                    field_id, default, None, desc_id, basecontainer
                )
        return True, flags | c4d.DESCFLAGS_DESC_LOADED

    def SetDParameter(
        self, node: c4d.GeListNode, id: c4d.DescID, t_data: object, flags: int
    ) -> bool | Tuple[bool, int]:
        basecontainer = self.GetBaseContainer()
        param_id = id[0].id
        entry = _C4DP_CONST_DISPATCH.get(param_id)  # pyright: ignore[reportArgumentType]
        if entry is None:
            return False
        kind, attr, _default = entry
        _c4d_set(basecontainer, kind, param_id, t_data)
        _write_pref(param_id, attr, t_data)
        return True, flags | c4d.DESCFLAGS_SET_PARAM_SET

    def GetDParameter(
        self, node: c4d.GeListNode, id: c4d.DescID, flags: int
    ) -> bool | Tuple[bool, int]:
        basecontainer = self.GetBaseContainer()
        param_id = id[0].id
        entry = _C4DP_CONST_DISPATCH.get(param_id)  # pyright: ignore[reportArgumentType]
        if entry is None:
            return False
        kind, _attr, _default = entry
        return (
            True,
            _c4d_get(basecontainer, kind, param_id),
            flags | c4d.DESCFLAGS_GET_PARAM_GET,
        )  # pyright: ignore[reportReturnType]
        # stubs are wrong: docs confirm a Tuple[bool, any, int) as return type

    def GetDEnabling(
        self,
        node: c4d.GeListNode,
        id: c4d.DescID,
        t_data: object,
        flags: int,
        itemdesc: c4d.BaseContainer,
    ) -> bool:
        basecontainer = self.GetBaseContainer()
        param_id = id[0].id
        controller = _C4DP_CONTROLLERS.get(param_id)  # pyright: ignore[reportArgumentType]
        if controller is None:
            return True
        return bool(basecontainer.GetBool(controller))

    def Message(self, node: c4d.GeListNode, type: int, data: object) -> bool:
        if type == c4d.MSG_DESCRIPTION_COMMAND:
            if data["id"][0].id == C4DP.C4DPRESENCE_RESETALL:  # pyright: ignore[reportIndexIssue]
                _reset_prefs(self.GetBaseContainer())
                return True
        if type == c4d.MSG_MULTI_RENDERNOTIFICATION:
            c4d.WriteConsole("Render notification caught")
            is_start = data["start"]  # pyright: ignore[reportIndexIssue]
            is_animated = data["animated"]  # pyright: ignore[reportIndexIssue]
            if is_start:
                C4DP_SESSION.is_rendering = True
                C4DP_SESSION.render_is_animated = is_animated
            else:
                C4DP_SESSION.is_rendering = False
        if type == c4d.MSG_DOCUMENTINFO:
            c4d.WriteConsole("Document notification caught")
            info_type = data["type"]  # pyright: ignore[reportIndexIssue]
            if (
                info_type == c4d.MSG_DOCUMENTINFO_TYPE_LOAD
                or info_type == c4d.MSG_DOCUMENTINFO_TYPE_NEWPROJECT_AFTER
            ) and C4DP_PREFS.resetTimer:
                C4DP_SESSION.start_time = time.time()
        return True


#######################
# Plugin Registration #
#######################


class C4DPPresenceMessage(c4d.plugins.MessageData):
    # pylint: disable=invalid-name, unused-argument, redefined-builtin
    last_update: float = time.time()

    def GetTimer(self) -> int:
        return 1000

    def CoreMessage(self, id: int, bc: c4d.BaseContainer) -> bool:
        if id == c4d.MSG_TIMER:
            t = time.time()
            if t - self.last_update > C4DP_PREFS.generalUpdate:
                c4d_update_presence()
                self.last_update = t
        return True


atexit.register(force_clear_on_exit, C4DP_CLIENT)

if __name__ == "__main__":
    c4d.plugins.RegisterPreferencePlugin(
        _C4D_PREF_PLUGIN_ID,
        g=C4DPresencePrefs,
        name="C4DPresence",
        description="c4d_presence",
        parentid=0,
        sortid=0,
    )
    c4d.plugins.RegisterMessagePlugin(
        _C4D_CORE_PLUGIN_ID, str="C4DPresence Core", info=0, dat=C4DPPresenceMessage()
    )
