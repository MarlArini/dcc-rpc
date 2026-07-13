"""
AI-generated (Claude Opus 4.7): fake `c4d` module for tests.

Covers the c4d API surface that c4d_presence.pyp imports and that C4DContext
methods touch:

  - BaseContainer with GetBool/SetBool/GetInt32/SetInt32/GetString/SetString
    and item access (used by Message handlers and GetMachineFeatures).
  - DescID/DescLevel — for parameter ID building.
  - documents.BaseDocument with the full surface used by C4DContext.
  - documents.GetActiveDocument().
  - BaseObject (GetDown / GetNext / GetType / GetTypeName / GetName).
  - GetMachineFeatures, GetC4DVersion, GetWorldContainerInstance,
    WriteConsole.
  - plugins.PreferenceData / plugins.MessageData base classes plus the two
    Register* functions used at __main__ time (no-ops with bookkeeping).
  - All the mode / object-type / render-engine / message / desc-flag /
    dtype constants the plugin references.

Submodules `c4d.documents` and `c4d.plugins` are real Python packages so
`from c4d.documents import ...` works the natural way.

State pattern, like the other plugin fakes:

    c4d.set_state(doc=c4d.make_document(name="scene.c4d"), ...)
    ctx = C4DContext.capture()
    assert ctx.get_document_name() == "scene.c4d"
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# ===========================================================================
# Constants the plugin references on c4d.*
# ===========================================================================

# Mode constants (document.GetMode() values).
Mcamera = 0
Mobject = 1
Mtexture = 2
Mtextureaxis = 3
Mpoints = 4
Medges = 5
Mpolygons = 6
Manimation = 7
Mkinematic = 8
Mmodel = 9
Mpaint = 10
Muvpoints = 11
Muvedges = 12
Muvpolygons = 13
Muvon = 14
Mdrag = 15
Mpolyedgepoint = 16
Medgepoint = 17
Mworkplane = 18

# Object type IDs (BaseObject.GetType() values).
Opolygon = 5100
Ocamera = 5103
Orscamera = 1057516
Olight = 5102
Osky = 5105
Oenvironment = 5106


# Mesh type IDs
Omgtext = 1019268
Ocube = 5159
Ocylinder = 5170
Oplane = 5168
Odisc = 5164
Osphere = 5160
Ocapsule = 5171
Ocone = 5162
Ofigure = 5166
Ofractal = 5169
Ooiltank = 5172
Opyramid = 5167
Oplatonic = 5161
Otube = 5165
Otorus = 5163
Obezier = 5120


# MoGraph generator/deformer types.
Omgcloner = 1018544
Omgmatrix = 1018545
Omgscatter = 1018791
Omgfracture = 1018792
Omgvoronoifracture = 1036557
Omginstance = 1018957
Omgtracer = 1018655
Omgsplinegen = 440000277
Omgextrude = 1019358
Omgpolyfx = 1019222

# MoGraph effector types.
Omgplain = 1018643
Omgdelay = 1019034
Omgformula = 1019351
Omginheritance = 1018883
Omgpushapart = 1019353
Omgpython = 1025800
Omgrandom = 1018643
Omgreeffector = 1019034
Omgshader = 1018571
Omgsound = 1018589
Omgspline = 1018774
Omgstep = 1018881
Omgeffectortarget = 1019226
Omgtime = 1018596
Omgvolume = 1019358
Omgcoffee = 1019351
Omgroup = 1019353

# Render engine IDs (RenderData[RDATA_RENDERENGINE] values).
RDATA_RENDERENGINE = 1000
RDATA_RENDERENGINE_STANDARD = 0
RDATA_RENDERENGINE_PHYSICAL = 1023342
RDATA_RENDERENGINE_PREVIEWHARDWARE = 300001061
RDATA_RENDERENGINE_REDSHIFT = 1036219

# Miscellaneous.
DRAWPORT_RENDERER_NAME = 5000

# Description / parameter flags + dtype ids.
DESCFLAGS_DESC_NEEDDEFAULTVALUE = 1 << 0
DESCFLAGS_DESC_LOADED = 1 << 1
DESCFLAGS_SET_PARAM_SET = 1 << 2
DESCFLAGS_GET_PARAM_GET = 1 << 3

DTYPE_BOOL = 400006001
DTYPE_LONG = 400006002
DTYPE_STRING = 400006003

# Message IDs.
MSG_DESCRIPTION_COMMAND = 1000
MSG_MULTI_RENDERNOTIFICATION = 1001
MSG_DOCUMENTINFO = 1002
MSG_DOCUMENTINFO_TYPE_LOAD = 10
MSG_DOCUMENTINFO_TYPE_NEWPROJECT_AFTER = 11
MSG_TIMER = 1003


# ===========================================================================
# BaseContainer — used as world container + GetMachineFeatures result.
# ===========================================================================


class BaseContainer:
    """Tracks typed slots separately, mirroring C4D's per-type accessors.

    The plugin uses GetBool/SetBool/GetInt32/SetInt32/GetString/SetString,
    plus dict-style `bc[KEY]` lookup for GetMachineFeatures. We also support
    nested sub-containers via GetContainerInstance/SetContainer."""

    def __init__(self):
        self._bools: Dict[int, bool] = {}
        self._ints: Dict[int, int] = {}
        self._strings: Dict[int, str] = {}
        self._items: Dict[int, Any] = {}
        self._sub: Dict[int, "BaseContainer"] = {}

    # Typed getters/setters
    def GetBool(self, key: int) -> bool:  # noqa: N802
        return self._bools.get(key, False)

    def SetBool(self, key: int, value: bool) -> None:  # noqa: N802
        self._bools[key] = bool(value)

    def GetInt32(self, key: int) -> int:  # noqa: N802
        return self._ints.get(key, 0)

    def SetInt32(self, key: int, value: int) -> None:  # noqa: N802
        self._ints[key] = int(value)

    def GetString(self, key: int) -> str:  # noqa: N802
        return self._strings.get(key, "")

    def SetString(self, key: int, value: str) -> None:  # noqa: N802
        self._strings[key] = str(value)

    # Item access (bc[KEY] used by get_gpu_str).
    def __getitem__(self, key: int) -> Any:
        if key not in self._items:
            raise RuntimeError(f"BaseContainer key {key} not set")
        return self._items[key]

    def __setitem__(self, key: int, value: Any) -> None:
        self._items[key] = value

    def __contains__(self, key: int) -> bool:
        return key in self._items

    # Sub-container access (world container -> per-plugin container).
    def GetContainerInstance(self, key: int) -> Optional["BaseContainer"]:  # noqa: N802
        return self._sub.get(key)

    def SetContainer(self, key: int, value: "BaseContainer") -> None:  # noqa: N802
        self._sub[key] = value


# ===========================================================================
# DescLevel / DescID — used by the preferences plugin to build parameter IDs.
# ===========================================================================


class DescLevel:
    def __init__(self, id: int, dtype: int = 0, creator: int = 0):  # noqa: A002
        self.id = int(id)
        self.dtype = int(dtype)
        self.creator = int(creator)


class DescID:
    """Sequence of DescLevels. C4D supports nested IDs but the plugin only
    ever builds single-level ones, so __getitem__ returns the i-th level."""

    def __init__(self, *levels: DescLevel):
        self._levels: List[DescLevel] = list(levels)

    def __getitem__(self, idx: int) -> DescLevel:
        return self._levels[idx]


class Description:
    """Used by GetDDescription. The real Description holds parameter UI
    metadata; tests only need LoadDescription to return True."""

    def __init__(self):
        self.loaded_names: List[str] = []
        self.load_result: bool = True

    def LoadDescription(self, name: str) -> bool:  # noqa: N802
        self.loaded_names.append(name)
        return self.load_result


# ===========================================================================
# GeListNode — base for many C4D node types. The prefs plugin only uses it
# as a type annotation, never reads any attribute, so a bare class is fine.
# ===========================================================================


class GeListNode:
    pass


# ===========================================================================
# BaseObject — scene tree node with hierarchy / type info.
# ===========================================================================


class BaseObject:
    def __init__(
        self,
        name: str = "Object",
        type_id: int = Opolygon,
        type_name: str = "Polygon",
        down: Optional["BaseObject"] = None,
        next: Optional["BaseObject"] = None,  # noqa: A002
    ):
        self._name = name
        self._type = type_id
        self._type_name = type_name
        self._down = down
        self._next = next

    def GetName(self) -> str:  # noqa: N802
        return self._name

    def GetType(self) -> int:  # noqa: N802
        return self._type

    def GetTypeName(self) -> str:  # noqa: N802
        return self._type_name

    def GetDown(self) -> Optional["BaseObject"]:  # noqa: N802
        return self._down

    def GetNext(self) -> Optional["BaseObject"]:  # noqa: N802
        return self._next


# ===========================================================================
# BaseTime — wraps a frame number / fps and exposes GetFrame(fps).
# ===========================================================================


@dataclass
class BaseTime:
    _frame: int = 0

    def GetFrame(self, fps: int) -> int:  # noqa: N802,ARG002
        return self._frame


# ===========================================================================
# RenderData — minimal; supports [c4d.RDATA_RENDERENGINE] and GetResolution().
# ===========================================================================


class RenderData:
    def __init__(self, engine: int = RDATA_RENDERENGINE_STANDARD,
                 resolution: Tuple[int, int] = (1920, 1080)):
        self._engine = engine
        self._resolution = resolution

    def __getitem__(self, key: int) -> Any:
        if key == RDATA_RENDERENGINE:
            return self._engine
        raise RuntimeError(f"RenderData key {key} not set")

    def GetResolution(self) -> Tuple[int, int]:  # noqa: N802
        return self._resolution


# ===========================================================================
# Module-level state — what tests configure via set_state(...).
# ===========================================================================


@dataclass
class _State:
    # documents.GetActiveDocument()
    active_doc: Optional["BaseDocument"] = None

    # GetMachineFeatures() — a BaseContainer; tests can set
    # bc[DRAWPORT_RENDERER_NAME] = "NVIDIA RTX 4090" then assign here.
    machine_features: Optional[BaseContainer] = None
    machine_features_raises: bool = False

    # GetC4DVersion()
    c4d_version: int = 20262

    # World container (used by GetWorldContainerInstance).
    world_container: Optional[BaseContainer] = None

    # WriteConsole() captures.
    console_lines: List[str] = field(default_factory=list)

    # Plugin registration captures.
    registered_pref_plugins: List[dict] = field(default_factory=list)
    registered_msg_plugins: List[dict] = field(default_factory=list)


_state = _State()


def reset_state() -> None:
    global _state
    _state = _State()
    # Defaults that the plugin imports at module load:
    _state.world_container = BaseContainer()
    _state.active_doc = make_document()
    _state.machine_features = BaseContainer()
    _state.machine_features[DRAWPORT_RENDERER_NAME] = "NVIDIA RTX 4090"


def set_state(**kwargs) -> None:
    for k, v in kwargs.items():
        if not hasattr(_state, k):
            raise AttributeError(f"unknown state field: {k}")
        setattr(_state, k, v)


def get_state() -> _State:
    return _state


# ===========================================================================
# Top-level functions on the c4d namespace.
# ===========================================================================


def GetMachineFeatures() -> BaseContainer:  # noqa: N802
    if _state.machine_features_raises:
        raise RuntimeError("GetMachineFeatures unavailable")
    assert _state.machine_features is not None
    return _state.machine_features


def GetC4DVersion() -> int:  # noqa: N802
    return _state.c4d_version


def GetWorldContainerInstance() -> Optional[BaseContainer]:  # noqa: N802
    return _state.world_container


def WriteConsole(msg: str) -> None:  # noqa: N802
    _state.console_lines.append(str(msg))


# ===========================================================================
# Factories.
# ===========================================================================


def make_object(
    name: str = "Object",
    type_id: int = Opolygon,
    type_name: str = "Polygon",
    children: Optional[List["BaseObject"]] = None,
    siblings: Optional[List["BaseObject"]] = None,
) -> BaseObject:
    """Build a BaseObject. `children` become a sibling chain under .GetDown(),
    and `siblings` become a chain accessible via .GetNext() from this node."""
    down = None
    if children:
        # Link children as a sibling chain.
        for i in range(len(children) - 1):
            children[i]._next = children[i + 1]
        down = children[0]
    sibling_chain = None
    if siblings:
        for i in range(len(siblings) - 1):
            siblings[i]._next = siblings[i + 1]
        sibling_chain = siblings[0]
    return BaseObject(
        name=name, type_id=type_id, type_name=type_name,
        down=down, next=sibling_chain,
    )


def make_document(
    name: str = "scene.c4d",
    path: str = "",
    objects: Optional[List[BaseObject]] = None,
    materials: Optional[List[Any]] = None,
    textures: Optional[List[Any]] = None,
    color_spaces: Tuple[str, str, str] = ("config", "ACES 1.3", "scene-linear"),
    current_time: int = 0,
    min_frame: int = 0,
    max_frame: int = 100,
    render_engine: int = RDATA_RENDERENGINE_STANDARD,
    render_resolution: Tuple[int, int] = (1920, 1080),
    active_object: Optional[BaseObject] = None,
    fps: int = 30,
    mode: int = Mmodel,
) -> "BaseDocument":
    doc = BaseDocument()
    doc._name = name
    doc._path = path
    doc._objects = list(objects) if objects else []
    doc._materials = list(materials) if materials else []
    doc._textures = list(textures) if textures else []
    doc._color_spaces = tuple(color_spaces)
    doc._time = BaseTime(_frame=current_time)
    doc._min_time = BaseTime(_frame=min_frame)
    doc._max_time = BaseTime(_frame=max_frame)
    doc._render_data = RenderData(engine=render_engine, resolution=render_resolution)
    doc._active_object = active_object
    doc._fps = fps
    doc._mode = mode
    return doc


# Make the BaseDocument class visible at this scope before the submodule
# import below — c4d.documents.BaseDocument is the canonical export, but
# the plugin annotates parameters with `c4d.documents.BaseDocument` so we
# also re-export from the documents subpackage.

# Forward-declare so the factory above can reference it.
class BaseDocument:
    """Active document. Methods mirror what C4DContext uses."""

    def __init__(self):
        self._name: str = ""
        self._path: str = ""
        self._objects: List[BaseObject] = []
        self._materials: List[Any] = []
        self._textures: List[Any] = []
        self._color_spaces: Tuple[str, str, str] = ("", "", "")
        self._time: BaseTime = BaseTime()
        self._min_time: BaseTime = BaseTime()
        self._max_time: BaseTime = BaseTime()
        self._render_data: RenderData = RenderData()
        self._active_object: Optional[BaseObject] = None
        self._fps: int = 30
        self._mode: int = Mmodel

    def GetDocumentName(self) -> str:  # noqa: N802
        return self._name

    def GetDocumentPath(self) -> str:  # noqa: N802
        return self._path

    def GetObjects(self) -> List[BaseObject]:  # noqa: N802
        return list(self._objects)

    def GetMaterials(self) -> List[Any]:  # noqa: N802
        return list(self._materials)

    def GetAllTextures(self) -> List[Any]:  # noqa: N802
        return list(self._textures)

    def GetActiveOcioColorSpacesNames(self) -> Tuple[str, str, str]:  # noqa: N802
        return self._color_spaces

    def GetTime(self) -> BaseTime:  # noqa: N802
        return self._time

    def GetMinTime(self) -> BaseTime:  # noqa: N802
        return self._min_time

    def GetMaxTime(self) -> BaseTime:  # noqa: N802
        return self._max_time

    def GetActiveRenderData(self) -> RenderData:  # noqa: N802
        return self._render_data

    def GetActiveObject(self) -> Optional[BaseObject]:  # noqa: N802
        return self._active_object

    def GetFps(self) -> int:  # noqa: N802
        return self._fps

    def GetMode(self) -> int:  # noqa: N802
        return self._mode


# Now the submodules. Doing it at the end of this file so the BaseDocument /
# RenderData / BaseObject classes are defined when the subpackages import.
from . import documents  # noqa: E402,F401
from . import plugins  # noqa: E402,F401


# Initialize with sensible defaults on first import so the plugin's
# module-level setup doesn't crash.
reset_state()
