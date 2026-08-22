"""
C4DPresence is a Discord Rich Presence client plugin for Cinema 4D, based on
https://github.com/abrasic/blendpresence. C4DPresence has been tested on Cinema
4D 2026.3. For more info, see https://github.com/MarlArini/dcc-rpc.
"""

import atexit
from dataclasses import dataclass, field
from enum import auto, IntEnum
import os
import sys
import time
from typing import Any, ClassVar, Dict, List, Set, Tuple
from pathlib import Path

import c4d  # pylint: disable=import-error

# Bootstrap: ensure this plugin's directory is on sys.path so the sibling
# common.py and pypresence/ resolve when loaded by the host application.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# These imports have to happen after the bootstrap; silence the linters
from pypresence.presence import Presence  # noqa: E402 pylint: disable=wrong-import-position

from common import (  # noqa: E402 pylint: disable=wrong-import-position
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
    RenderSettings,
    format_render_details,
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

# fmt: off
_LIGHTS: frozenset[int] = frozenset(
    [
        c4d.Olight, c4d.Osky, c4d.Oenvironment, # Base C4D
        1053282, 1053279, 1053276, 1053275, 1061436, 1053287,
        1053278, 1059898, 1053277, 1053281, 1053280, #V-Ray
        1036751, 1036754, # Redshift
        1030424,  # Arnold
    ] # Note: Octane lights and one V-Ray light are nulls, handled in C4DContext
)

# All deformers and generators listed in the C4D MoGraph menu
_MG_GENERATORS_DEFORMERS: frozenset[int] = frozenset(
    [
        c4d.Omgcloner, c4d.Omgmatrix, c4d.Omgscatter, c4d.Omgfracture,
        c4d.Omgvoronoifracture, c4d.Omginstance, c4d.Omgtracer,
        c4d.Omgsplinegen, c4d.Omgextrude, c4d.Omgpolyfx,
    ]
)

# All effectors listed in the C4D MoGraph menu, plus a few not listed
# but with c4d.Obaseeffector description, e.g., c4d.Omgcoffee
_MG_EFFECTORS: frozenset[int] = frozenset(
    [
        c4d.Omgplain, c4d.Omgdelay, c4d.Omgformula, c4d.Omginheritance,
        c4d.Omgpushapart, c4d.Omgpython, c4d.Omgrandom, c4d.Omgreeffector,
        c4d.Omgshader, c4d.Omgsound, c4d.Omgspline, c4d.Omgstep, c4d.Omgeffectortarget,
        c4d.Omgtime, c4d.Omgvolume, c4d.Omgcoffee, c4d.Omgroup,
    ]
)

# All objects under "Create -> Mesh"
_MESH_PRIMITIVES: frozenset[int] = frozenset(
    [
        c4d.Omgtext, c4d.Ocube, c4d.Ocylinder, c4d.Oplane, c4d.Odisc, c4d.Opolygon,
        c4d.Osphere, c4d.Ocapsule, c4d.Ocone, c4d.Ofigure, c4d.Ofractal, c4d.Ooiltank,
        c4d.Opyramid, c4d.Oplatonic, c4d.Otube, c4d.Otorus, c4d.Obezier
    ]
)

# fmt: on

# Possible responses to document.GetMode(), mapped to string names
_C4D_MODES = {
    c4d.Mcamera: "Camera",
    c4d.Mobject: "Object",
    c4d.Mtexture: "Texture",
    c4d.Mtextureaxis: "Texture Axis",
    c4d.Mpoints: "Points",
    c4d.Medges: "Edges",
    c4d.Mpolygons: "Polygons",
    c4d.Manimation: "Animation",
    c4d.Mkinematic: "IK",
    c4d.Mmodel: "Model",
    c4d.Mpaint: "Paint",
    c4d.Muvpoints: "UV Points",
    c4d.Muvedges: "UV Edges",
    c4d.Muvpolygons: "UV Polygons",
    c4d.Muvon: "UV",
    c4d.Mdrag: "Drag",
    c4d.Mpolyedgepoint: "Polygons / Edges / Points",
    c4d.Medgepoint: "Edges / Points",
    c4d.Mworkplane: "Workplane",
}


################################################################
# Preference menu enum -> preference class mapping & utilities #
################################################################


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
    C4DP.C4DPRESENCE_B1ON: ("bool", "enableButton1", False),
    C4DP.C4DPRESENCE_B1LABEL: ("str", "button1Label", ""),
    C4DP.C4DPRESENCE_B1URL: ("str", "button1Url", ""),
    C4DP.C4DPRESENCE_B2ON: ("bool", "enableButton2", False),
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
class C4DPSettings(SharedSettings, RenderSettings):
    # pylint: disable=invalid-name
    displayGPU: bool = field(
        default=True,
        metadata={"group": "Details", "label": "Display GPU name in details"},
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
        ("Color space info", "color"),
        ("Current frame", "frame"),
    ]


class C4DPSession(SessionInfo):
    def __init__(self):
        super().__init__()
        self.render_res: Tuple[int, int] = (0, 0)
        self.render_engine: str = ""
        self.rendering_doc: str = ""

C4DP_PREFS = C4DPSettings()
C4DP_SESSION = C4DPSession()
C4DP_UPDATE_DETAILS = RPCUpdateDetails("cinema4d")
C4DP_CLIENT = Presence("1510781737238528020")


def _walk_objects(roots: List[c4d.BaseObject]):
    """Helper to walk scene graph and count all objects"""
    objs: List[c4d.BaseObject] = []

    def walk(obj: c4d.BaseObject):
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
        count = sum([1 for o in self.objects if o.GetType() in _MESH_PRIMITIVES])
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
                )  # Octane lights + one V-Ray light are nulls
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
        ver_str = str(c4d.GetC4DVersion())
        year = ver_str[:4]
        major_release = ver_str[4]
        minor_release = ver_str[5:]
        minor_release = minor_release.lstrip("0")
        if minor_release:
            return f"{year}.{major_release}.{minor_release}"
        else:
            return f"{year}.{major_release}"

    def get_active_object(self) -> str | None:
        obj = self.document.GetActiveObject()
        return f"Active: {obj.GetName()}" if obj else None

    def get_fps(self) -> int | None:
        return self.document.GetFps()

    def get_current_frame(self) -> str:
        current_time = self.document.GetTime()
        fps = self.get_fps()
        frame = current_time.GetFrame(fps)
        return f"Frame {frame} ({fps}fps)"


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
            current_engine = C4DP_SESSION.render_engine
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
    "color": lambda ctx: ctx.get_color_info(),
    "frame": lambda ctx: ctx.get_current_frame(),
}


def c4d_update_presence_details(ctx: C4DContext):
    # Rendering Details
    if C4DP_PREFS.enableDetails and C4DP_SESSION.is_rendering:
        res = C4DP_SESSION.render_res
        fname = C4DP_SESSION.rendering_doc
        C4DP_UPDATE_DETAILS.details_text = format_render_details(
            file_name=fname,
            res=res,
            rendered_frames=C4DP_SESSION.rendered_frames,
            prefs=C4DP_PREFS,
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
        c4d_update_large_icon(ctx)
        c4d_update_small_icon(ctx)
        c4d_update_presence_state(ctx)
        c4d_update_presence_details(ctx)
        update_buttons(C4DP_UPDATE_DETAILS, C4DP_PREFS)
        c4d_push_rpc_update()
    elif C4DP_SESSION.connected and not C4DP_SESSION.cleared:
        # Clear once on the transition to disabled, not on every tick.
        # push_rpc_update flips `cleared` back off on the next successful push.
        try:
            C4DP_CLIENT.clear()
            C4DP_SESSION.cleared = True
        except Exception as e:  # noqa: BLE001
            print(f"[C4DPresence] clear failed: {e}")
            C4DP_SESSION.connected = False


####################
# Preferences Menu #
####################


# The *Type prefs are stored in the container as ints but held on C4DP_PREFS as
# the string keys of C4DP_DISPATCH_TYPES. If the container ever holds an int
# that isn't in _C4D_INFOTYPE_MAP, fall back to a *string* — falling back to the
# dispatch table's declared default would leave an IntEnum on the prefs object,
# and the display-type lookup would silently return nothing.
_C4DP_INFOTYPE_FALLBACK = {
    C4DP.C4DPRESENCE_DTYPE: "document",
    C4DP.C4DPRESENCE_STYPE: "object",
}


def _write_pref(param_id, attr, t_data):
    fallback = _C4DP_INFOTYPE_FALLBACK.get(param_id)
    if fallback is not None:
        setattr(C4DP_PREFS, attr, _C4D_INFOTYPE_MAP.get(t_data, fallback))
    else:
        setattr(C4DP_PREFS, attr, t_data)


def _sync_prefs(basecontainer):
    for field_id, (kind, attr, _default) in _C4DP_CONST_DISPATCH.items():
        _write_pref(field_id, attr, _c4d_get(basecontainer, kind, field_id))


def _reset_prefs(basecontainer):
    for field_id, (kind, _attr, default) in _C4DP_CONST_DISPATCH.items():
        _c4d_set(basecontainer, kind, field_id, default)
    _sync_prefs(basecontainer)


class C4DPresencePrefs(c4d.plugins.PreferenceData):
    """Registers a container in the Cinema 4D preferences menu for plugin
    settings. Also catches messages, since the MessageData plugin can only
    handle CoreMessage events and events related to rendering and files
    are regular messages."""

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
        return True


#######################
# Plugin Registration #
#######################


class C4DPPresenceMessage(c4d.plugins.MessageData):
    """Simple core of the plugin. Registers a MessageData plugin that fires a
    timer every 1000ms and checks whether enough time has elapsed since the
    last update to do another one. This also means there's no need for a special
    handler for settings updates where the generalUpdate rate is changed, since
    the settings are effectively checked every second. The active document is also
    polled here, with a set of documents maintained to implement the reset timer
    functionality of the plugin since CoreMessage does not get MSG_DOCUMENTINFO
    messages; the render state of the application is polled for the same reason."""

    # pylint: disable=invalid-name, unused-argument, redefined-builtin
    def __init__(self):
        super().__init__()
        self.last_update: float = time.time()
        self.seen_documents: Set[c4d.documents.BaseDocument] = set()

    def GetTimer(self) -> int:
        return 1000

    @staticmethod
    def _open_documents() -> List[c4d.documents.BaseDocument] | None:
        """Walk C4D's open-document list. Returns None rather than an empty
        list if the walk yields nothing, so a query that comes back empty
        never wipes the seen-document memo."""
        docs: List[c4d.documents.BaseDocument] = []
        doc = c4d.documents.GetFirstDocument()
        while doc:
            docs.append(doc)
            doc = doc.GetNext()
        return docs or None

    def CoreMessage(self, id: int, bc: c4d.BaseContainer) -> bool:
        if id == c4d.MSG_TIMER:
            # Drop closed documents from the memo. Without this it grows for
            # the life of the session and keeps every BaseDocument wrapper the
            # user ever opened alive along with it.
            if (open_docs := self._open_documents()) is not None:
                self.seen_documents.intersection_update(open_docs)
            # Poll active document
            if (doc := c4d.documents.GetActiveDocument()) not in self.seen_documents:
                self.seen_documents.add(doc)
                if C4DP_PREFS.resetTimer:
                    C4DP_SESSION.start_time = time.time()
            # Poll render start
            if not C4DP_SESSION.is_rendering and (
                c4d.CheckIsRunning(c4d.CHECKISRUNNING_EDITORRENDERING)
                or c4d.CheckIsRunning(c4d.CHECKISRUNNING_EXTERNALRENDERING)
            ):
                # Is rendering
                C4DP_SESSION.is_rendering = True
                # Get document name
                C4DP_SESSION.rendering_doc = doc.GetDocumentName()
                # Get document render data
                render_info = doc.GetActiveRenderData()
                # Get resolution
                res_info = render_info.GetResolution()
                C4DP_SESSION.render_res = (int(res_info[0]), int(res_info[1]))
                # Get engine
                e_id = render_info[c4d.RDATA_RENDERENGINE]
                C4DP_SESSION.render_engine = _C4D_RENDER_ENGINES.get(
                    e_id, "Unknown render engine"
                )
            # Poll render stop
            elif C4DP_SESSION.is_rendering and not (
                c4d.CheckIsRunning(c4d.CHECKISRUNNING_EDITORRENDERING)
                or c4d.CheckIsRunning(c4d.CHECKISRUNNING_EXTERNALRENDERING)
            ):
                # No longer rendering
                C4DP_SESSION.is_rendering = False
            # Rich Presence update
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
    c4d_connect_rpc()
