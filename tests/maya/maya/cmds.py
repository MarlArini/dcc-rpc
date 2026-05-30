"""
AI-generated (Claude Opus 4.7): fake `maya.cmds` for tests.

Covers the cmds.* surface used by maya_presence.py — optionVar persistence,
scene/workspace queries, ls filters, polyEvaluate/headsUpDisplay, render
attrs, playback options, plugin info, current context, about(), and the
menu/UI shims used during install/uninstall.

Pattern:
    def test_X(cmds):
        cmds.set_state(
            scene_name="/path/to/scene.mb",
            ls_results={"mesh": ["pSphere1"], "light": []},
            ...
        )
        ctx = MPContext.capture()
        assert ctx.get_mesh_count() == "1 mesh"
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class _State:
    # File/workspace
    scene_name: str = ""
    project_short_name: str = "default"

    # ls(): keyed by the "type" or special-filter combination the plugin uses
    ls_results: Dict[Tuple[Any, ...], List[str]] = field(default_factory=dict)

    # optionVar storage — { name: value }
    option_vars: Dict[str, Any] = field(default_factory=dict)

    # Time/playback
    current_time: float = 1.0
    current_time_unit: str = "film"
    min_time: float = 1.0
    max_time: float = 100.0

    # Render globals (cmds.getAttr)
    attrs: Dict[str, Any] = field(default_factory=lambda: {
        "defaultRenderGlobals.currentRenderer": "arnold",
        "defaultResolution.width": 1920,
        "defaultResolution.height": 1080,
        "defaultRenderGlobals.preMel": "",
        "defaultRenderGlobals.postMel": "",
        "defaultRenderGlobals.postRenderMel": "",
    })
    # attrs that should raise RuntimeError on getAttr.
    attrs_raise: set = field(default_factory=set)

    # Misc
    gl_renderer: str = "NVIDIA GeForce RTX 4090/PCIe/SSE2"
    raise_gl_renderer: bool = False
    polyevaluate_result: Any = field(default_factory=lambda: {"vertex": 1000, "face": 800})
    hud_visible: bool = False
    hud_verts: int = 500
    hud_faces: int = 400

    # Workspace layout + current context (for small icon decisions)
    workspace_layout: str = "general"
    raise_workspace_layout: bool = False
    current_ctx: str = "selectSuperContext"

    # Plugins
    plugins: List[str] = field(default_factory=list)
    node_types_by_path: Dict[str, List[str]] = field(default_factory=dict)

    # about(): kwargs -> response value
    about_responses: Dict[str, Any] = field(default_factory=lambda: {
        "majorVersion": "2026",
        "minorVersion": "0",
        "patchVersion": "0",
        "version": "2026.0",
        "batch": False,
    })
    # cmds.about() will raise RuntimeError when called with any kwarg in this set.
    about_raises: set = field(default_factory=set)

    # cmds.setAttr() will raise RuntimeError when called with a plug in this set.
    setattr_raises: set = field(default_factory=set)

    # UI bookkeeping
    menu_items: Dict[str, dict] = field(default_factory=dict)


_state = _State()


def reset_state() -> None:
    global _state
    _state = _State()


def set_state(**kwargs) -> None:
    for k, v in kwargs.items():
        if not hasattr(_state, k):
            raise AttributeError(f"unknown state field: {k}")
        setattr(_state, k, v)


def get_state() -> _State:
    return _state


# ---------------------------------------------------------------------------
# Scene + workspace
# ---------------------------------------------------------------------------

def workspace(query: bool = False, shortName: bool = False, **_) -> str:  # noqa: N803
    return _state.project_short_name


def file(query: bool = False, sceneName: bool = False, **_) -> str:  # noqa: N803
    return _state.scene_name


# ---------------------------------------------------------------------------
# ls()
# ---------------------------------------------------------------------------

def _ls_key(kwargs: dict) -> Tuple[Any, ...]:
    """Canonicalize ls(...) kwargs to a state-lookup key.

    Tests configure cmds.set_state(ls_results={key: [...]}). Specific
    well-known filters map to short symbolic keys; everything else falls
    through to a sorted-kwargs tuple.
    """
    # Mesh geometry filter — must precede the generic ("type", ...) branch
    # because the plugin passes both geometry=True and type="mesh".
    if kwargs.get("geometry") and kwargs.get("type") == "mesh":
        return ("geometry_mesh",)
    # Simple single-flag selectors.
    for flag in ("cameras", "lights", "materials", "textures", "selection"):
        if kwargs.get(flag):
            return (flag,)
    # type=... selectors.
    if "type" in kwargs:
        t = kwargs["type"]
        if isinstance(t, list):
            return ("type_multi", tuple(t))
        return ("type", t)
    return tuple(sorted(kwargs.items(), key=lambda kv: kv[0]))


def ls(*args, **kwargs) -> List[str]:
    """Return the configured list, or [] if not configured. Accepts any args."""
    return list(_state.ls_results.get(_ls_key(kwargs), []))


# ---------------------------------------------------------------------------
# optionVar (Maya's user preference store)
# ---------------------------------------------------------------------------

def optionVar(**kwargs):  # noqa: N802
    if "exists" in kwargs:
        return kwargs["exists"] in _state.option_vars
    if "query" in kwargs:
        return _state.option_vars.get(kwargs["query"])
    # Writes: intValue/floatValue/stringValue are 2-tuples (name, value).
    for kind in ("intValue", "floatValue", "stringValue"):
        if kind in kwargs:
            name, value = kwargs[kind]
            _state.option_vars[name] = value
            return None
    return None


# ---------------------------------------------------------------------------
# headsUpDisplay + polyEvaluate
# ---------------------------------------------------------------------------

def headsUpDisplay(name: str, query: bool = False, visible: bool = False,  # noqa: N802,N803
                    scriptResult: bool = False, **_) -> Any:  # noqa: N803
    if visible:
        return 1 if _state.hud_visible else 0
    if scriptResult:
        if "Vert" in name:
            return [_state.hud_verts]
        if "Face" in name:
            return [_state.hud_faces]
    return None


def polyEvaluate(*args, vertex: bool = False, face: bool = False, **_):  # noqa: N802
    return _state.polyevaluate_result


# ---------------------------------------------------------------------------
# Time / playback
# ---------------------------------------------------------------------------

def currentTime(query: bool = False, **_) -> float:  # noqa: N802
    return _state.current_time


def currentUnit(query: bool = False, time: bool = False, **_) -> str:  # noqa: N802
    if _state.current_time_unit:
        return _state.current_time_unit
    raise RuntimeError("no current unit")


def playbackOptions(query: bool = False, minTime: bool = False,  # noqa: N802,N803
                    maxTime: bool = False, **_) -> float:  # noqa: N803
    if minTime:
        return _state.min_time
    if maxTime:
        return _state.max_time
    return 0.0


# ---------------------------------------------------------------------------
# getAttr / setAttr / listNodeTypes / pluginInfo / openGLExtension
# ---------------------------------------------------------------------------

def getAttr(plug: str, **_) -> Any:  # noqa: N802
    if plug in _state.attrs_raise:
        raise RuntimeError(f"attr {plug} raises")
    return _state.attrs.get(plug)


def setAttr(plug: str, value: Any, type: Optional[str] = None, **_) -> None:  # noqa: N802
    if plug in _state.setattr_raises:
        raise RuntimeError(f"setAttr({plug}) raises")
    _state.attrs[plug] = value


def listNodeTypes(path: str) -> List[str]:  # noqa: N802
    """As with cmds.ls, an explicit None in node_types_by_path is passed
    through so tests can exercise the None-vs-[] real-Maya gotcha."""
    result = _state.node_types_by_path.get(path, [])
    if result is None:
        return None
    return list(result)


def pluginInfo(query: bool = False, listPlugins: bool = False, **_) -> List[str]:  # noqa: N802,N803
    if listPlugins:
        return list(_state.plugins)
    return []


def openGLExtension(renderer: bool = False, **_) -> str:  # noqa: N802
    if _state.raise_gl_renderer:
        raise RuntimeError("no gl context")
    return _state.gl_renderer


# ---------------------------------------------------------------------------
# Current tool context + workspace layout
# ---------------------------------------------------------------------------

def currentCtx() -> str:  # noqa: N802
    return _state.current_ctx


def workspaceLayoutManager(query: bool = False, current: bool = False, **_) -> str:  # noqa: N802,N803
    if _state.raise_workspace_layout:
        raise RuntimeError("no workspace")
    return _state.workspace_layout


# ---------------------------------------------------------------------------
# about()
# ---------------------------------------------------------------------------

def about(**kwargs) -> Any:
    for k in kwargs:
        if k in _state.about_raises:
            raise RuntimeError(f"about({k}=True) raises")
    for k in kwargs:
        if k in _state.about_responses:
            return _state.about_responses[k]
    return None


# ---------------------------------------------------------------------------
# UI helpers (menuItem, deleteUI) — no-ops with bookkeeping
# ---------------------------------------------------------------------------

def menuItem(name: str = "", exists: bool = False, **kwargs):  # noqa: N802
    if exists:
        return name in _state.menu_items
    _state.menu_items[name] = dict(kwargs)
    return name


def deleteUI(name: str, menuItem: bool = False, **_) -> None:  # noqa: N802,N803
    _state.menu_items.pop(name, None)


# ---------------------------------------------------------------------------
# Factories for tests
# ---------------------------------------------------------------------------

def make_polyevaluate(verts: int, faces: int) -> dict:
    return {"vertex": verts, "face": faces}
