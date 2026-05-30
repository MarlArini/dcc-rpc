"""
AI-generated (Claude Opus 4.7): fake `nuke` module for tests.

Covers the API surface nuke_presence/menu.py imports and that NKContext
methods touch. The plugin does module-level instantiation (NK_PREFS,
NK_MENU, NK_WORKER background thread); this fake makes all of that work
import-time without real side effects.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# env (dict-like, accessed via env.get(...) and env["..."])
# ---------------------------------------------------------------------------

env: Dict[str, Any] = {
    "NukeVersionString": "17.0.1",
    "studio": False,
    "nukex": False,
    "indie": False,
    "nc": False,
}


# ---------------------------------------------------------------------------
# Knob (returned by node["name"]; has .value())
# ---------------------------------------------------------------------------

class _Knob:
    def __init__(self, value: Any = ""):
        self._value = value

    def value(self) -> Any:
        return self._value


# ---------------------------------------------------------------------------
# Node, Viewer, FrameRange, Format
# ---------------------------------------------------------------------------

class _Node:
    def __init__(
        self,
        name: str = "Node1",
        node_class: str = "Read",
        knobs: Optional[Dict[str, _Knob]] = None,
        inputs: Optional[Dict[int, "_Node"]] = None,
    ):
        self._name = name
        self._class = node_class
        self._knobs = knobs or {}
        self._inputs = inputs or {}

    def name(self) -> str:
        return self._name

    def Class(self) -> str:  # noqa: N802 (Nuke API casing)
        return self._class

    def __getitem__(self, knob_name: str) -> _Knob:
        return self._knobs.get(knob_name, _Knob(""))

    def input(self, idx: int) -> Optional["_Node"]:
        return self._inputs.get(idx)


class _FrameRange:
    def __init__(self, first: int = 1, last: int = 100):
        self._first, self._last = first, last

    def first(self) -> int:
        return self._first

    def last(self) -> int:
        return self._last


class _Format:
    def __init__(self, name: str = "HD", w: int = 1920, h: int = 1080):
        self._name, self._w, self._h = name, w, h

    def name(self) -> str:
        return self._name

    def width(self) -> int:
        return self._w

    def height(self) -> int:
        return self._h


class _Viewer:
    def __init__(self, node: Optional[_Node] = None, active_input: Optional[int] = 0):
        self._node = node
        self._active_input = active_input

    def node(self) -> Optional[_Node]:
        return self._node

    def activeInput(self) -> Optional[int]:  # noqa: N802
        return self._active_input


class _Root(_Node):
    def __init__(self):
        super().__init__(name="Root", node_class="Root")
        self._frame_range = _FrameRange(1, 100)
        self._num_nodes = 5
        self._real_fps = 24.0
        self._format = _Format("HD", 1920, 1080)
        self._knobs = {
            "proxy": _Knob(False),
            "proxy_scale": _Knob(1.0),
            "colorManagement": _Knob("OCIO"),
        }

    def frameRange(self) -> _FrameRange:  # noqa: N802
        return self._frame_range

    def numNodes(self) -> int:  # noqa: N802
        return self._num_nodes

    def realFps(self) -> float:  # noqa: N802
        return self._real_fps

    def fps(self) -> float:
        return self._real_fps

    def format(self) -> _Format:
        return self._format


# ---------------------------------------------------------------------------
# memory2
# ---------------------------------------------------------------------------

class _Memory2:
    @staticmethod
    def usage() -> int:
        return _state.memory_bytes


memory2 = _Memory2()


# ---------------------------------------------------------------------------
# Menu (returned by nuke.menu("Nuke"))
# ---------------------------------------------------------------------------

class _MenuItem:
    def __init__(self, label: str, command: Optional[Callable] = None):
        self.label = label
        self.command = command
        self.enabled = True

    def setEnabled(self, on: bool):  # noqa: N802
        self.enabled = on


class _Menu:
    def __init__(self, name: str = "Nuke"):
        self.name = name
        self.commands: List[_MenuItem] = []
        self.submenus: Dict[str, "_Menu"] = {}

    def addMenu(self, name: str) -> "_Menu":  # noqa: N802
        m = _Menu(name)
        self.submenus[name] = m
        return m

    def addCommand(self, label: str, command: Optional[Callable] = None) -> _MenuItem:  # noqa: N802
        item = _MenuItem(label, command)
        self.commands.append(item)
        return item


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

@dataclass
class _State:
    root: _Root = field(default_factory=_Root)
    # All-nodes results, keyed by `node_class` argument (None = no filter).
    all_nodes: Dict[Optional[str], List[_Node]] = field(default_factory=lambda: {None: []})
    layers_list: List[str] = field(default_factory=lambda: ["rgba", "depth"])
    script_name_str: Optional[str] = "comp.nk"
    raise_script_name: bool = False
    active_viewer: Optional[_Viewer] = None
    selected_node: Optional[_Node] = None
    memory_bytes: int = 1024 * 1024 * 100  # 100 MB
    frame_value: int = 1
    # Captured side effects (so tests can verify menu installation etc.).
    warn_messages: List[str] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)
    main_thread_calls: List[Callable] = field(default_factory=list)
    top_menu: _Menu = field(default_factory=lambda: _Menu("Nuke"))
    # Render callbacks: dicts mapping (fn, args) tuples to install/uninstall.
    before_render_callbacks: List[Tuple[Callable, tuple]] = field(default_factory=list)
    after_frame_callbacks: List[Tuple[Callable, tuple]] = field(default_factory=list)
    after_render_callbacks: List[Tuple[Callable, tuple]] = field(default_factory=list)


_state = _State()


def reset_state() -> None:
    global _state
    _state = _State()


def set_state(**kwargs) -> None:
    for k, v in kwargs.items():
        if not hasattr(_state, k):
            raise AttributeError(f"unknown state field: {k}")
        setattr(_state, k, v)


# ---------------------------------------------------------------------------
# Module-level functions (the `nuke.*` surface)
# ---------------------------------------------------------------------------

def root() -> _Root:
    return _state.root


def frame() -> int:
    return _state.frame_value


def layers() -> List[str]:
    return list(_state.layers_list)


def allNodes(node_class: Optional[str] = None, recurseGroups: bool = False):  # noqa: N802,N803
    """Returns a list of nodes, or None if the test explicitly stored None
    (some Nuke API calls return None rather than an empty list — used by
    get_io_nodes' fallback branches)."""
    if node_class in _state.all_nodes and _state.all_nodes[node_class] is None:
        return None
    return list(_state.all_nodes.get(node_class, []))


def scriptName() -> str:  # noqa: N802
    if _state.raise_script_name:
        raise RuntimeError("Script has not been saved")
    return _state.script_name_str or ""


def activeViewer() -> Optional[_Viewer]:  # noqa: N802
    return _state.active_viewer


def selectedNode() -> Optional[_Node]:  # noqa: N802
    return _state.selected_node


def warning(msg: str) -> None:
    _state.warn_messages.append(msg)


def error(msg: str) -> None:
    _state.error_messages.append(msg)


def executeInMainThreadWithResult(fn: Callable) -> Any:  # noqa: N802
    """Run synchronously and record the call so tests can assert on it."""
    _state.main_thread_calls.append(fn)
    return fn()


def menu(name: str) -> _Menu:
    # Always return the same top-level Nuke menu — the plugin only calls
    # nuke.menu("Nuke") once at import time.
    return _state.top_menu


def addBeforeRender(fn: Callable, args: tuple = ()) -> None:  # noqa: N802
    _state.before_render_callbacks.append((fn, args))


def removeBeforeRender(fn: Callable, args: tuple = ()) -> None:  # noqa: N802
    try:
        _state.before_render_callbacks.remove((fn, args))
    except ValueError:
        pass


def addAfterFrameRender(fn: Callable, args: tuple = ()) -> None:  # noqa: N802
    _state.after_frame_callbacks.append((fn, args))


def removeAfterFrameRender(fn: Callable, args: tuple = ()) -> None:  # noqa: N802
    try:
        _state.after_frame_callbacks.remove((fn, args))
    except ValueError:
        pass


def addAfterRender(fn: Callable, args: tuple = ()) -> None:  # noqa: N802
    _state.after_render_callbacks.append((fn, args))


def removeAfterRender(fn: Callable, args: tuple = ()) -> None:  # noqa: N802
    try:
        _state.after_render_callbacks.remove((fn, args))
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def make_knob(value: Any = "") -> _Knob:
    return _Knob(value)


def make_node(
    name: str = "Node1",
    node_class: str = "Read",
    knobs: Optional[Dict[str, Any]] = None,
    inputs: Optional[Dict[int, _Node]] = None,
) -> _Node:
    # Allow raw values as knob values; wrap them.
    wrapped = {k: (v if isinstance(v, _Knob) else _Knob(v)) for k, v in (knobs or {}).items()}
    return _Node(name=name, node_class=node_class, knobs=wrapped, inputs=inputs or {})


def make_viewer(node: Optional[_Node] = None, active_input: Optional[int] = 0) -> _Viewer:
    return _Viewer(node=node, active_input=active_input)


def make_format(name: str = "HD", w: int = 1920, h: int = 1080) -> _Format:
    return _Format(name=name, w=w, h=h)


def make_root(
    frame_range: Tuple[int, int] = (1, 100),
    num_nodes: int = 5,
    fps: float = 24.0,
    format_obj: Optional[_Format] = None,
    proxy: bool = False,
    proxy_scale: float = 1.0,
    color_mgmt: str = "OCIO",
) -> _Root:
    r = _Root()
    r._frame_range = _FrameRange(*frame_range)
    r._num_nodes = num_nodes
    r._real_fps = fps
    if format_obj is not None:
        r._format = format_obj
    r._knobs["proxy"] = _Knob(proxy)
    r._knobs["proxy_scale"] = _Knob(proxy_scale)
    r._knobs["colorManagement"] = _Knob(color_mgmt)
    return r
