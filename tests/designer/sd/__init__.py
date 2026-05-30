"""
AI-generated (Claude Opus 4.7): fake `sd` (Substance Designer) module for tests.

This module is the entry point. Submodules (`sd.api`, `sd.api.sbs`, etc.)
live in their own files so `import sd.api.qtforpythonuimgrwrapper` works.

Pattern:
    def test_X(sd):
        sd.set_state(
            current_graph=sd.make_graph(...),
            current_package=sd.make_package(...),
        )
        ctx = SPContext.capture()
        assert ctx.project_name() == ...
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple

from . import api  # noqa: F401 — re-exported for `sd.api.*` access in code


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass
class _Int2:
    x: int = 0
    y: int = 0


@dataclass
class _SDValueString:
    _value: str = ""

    def get(self) -> str:
        return self._value


@dataclass
class _NodeDefinition:
    _label: str = "Uniform color"

    def getLabel(self) -> str:  # noqa: N802
        return self._label


@dataclass
class _Node:
    _definition: Optional[_NodeDefinition] = field(default_factory=_NodeDefinition)

    def getDefinition(self) -> Optional[_NodeDefinition]:  # noqa: N802
        return self._definition


@dataclass
class _SDArray:
    """Stand-in for the SDArray collection. Designer's API returns these for
    node and selection sets; they support getSize() and getItem(idx)."""
    items: List[Any] = field(default_factory=list)

    def getSize(self) -> int:  # noqa: N802
        return len(self.items)

    def getItem(self, idx: int) -> Any:  # noqa: N802
        return self.items[idx]


@dataclass
class _Resource:
    _class_name: str = "SDResource"

    def getClassName(self) -> str:  # noqa: N802
        return self._class_name


@dataclass
class _Package:
    _file_path: str = ""
    _resources: List[_Resource] = field(default_factory=list)

    def getFilePath(self) -> str:  # noqa: N802
        return self._file_path

    def getChildrenResources(self, recursive: bool = True) -> List[_Resource]:  # noqa: N802,N803
        return list(self._resources)


@dataclass
class _Graph:
    """Base graph. Annotation/property lookups are dict-based for ergonomics."""
    _package: Optional[_Package] = None
    _nodes: _SDArray = field(default_factory=_SDArray)
    _output_nodes: _SDArray = field(default_factory=_SDArray)
    _annotations: dict = field(default_factory=dict)
    _input_properties: dict = field(default_factory=dict)
    _default_parent_size: Optional[_Int2] = None
    _is_comp_graph: bool = False

    def getPackage(self) -> Optional[_Package]:  # noqa: N802
        return self._package

    def getNodes(self) -> _SDArray:  # noqa: N802
        return self._nodes

    def getOutputNodes(self) -> _SDArray:  # noqa: N802
        return self._output_nodes

    def getAnnotationPropertyValueFromId(self, identifier: str):  # noqa: N802
        return self._annotations.get(identifier)

    def getInputPropertyValueFromId(self, identifier: str):  # noqa: N802
        return self._input_properties.get(identifier)

    def getDefaultParentSize(self) -> _Int2:  # noqa: N802
        return self._default_parent_size or _Int2(2048, 2048)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class _State:
    current_graph: Optional[_Graph] = None
    main_window: Any = None
    selected_nodes: Optional[_SDArray] = None
    color_management_engine_name: Optional[str] = "sRGB"
    color_management_engine_is_none: bool = False
    application_version: str = "16.0.1"
    user_plugins_dir: str = ""  # filled by reset() to a tempdir
    registered_callback_id: int = 0
    unregistered_callbacks: List[int] = field(default_factory=list)


_state = _State()


def reset_state() -> None:
    global _state
    import tempfile
    _state = _State()
    # JSONSharedSettings tries to read/write a settings JSON in this dir;
    # use a tempdir so tests don't pollute the repo.
    _state.user_plugins_dir = tempfile.mkdtemp(prefix="sdfake_")


def set_state(**kwargs) -> None:
    for k, v in kwargs.items():
        if not hasattr(_state, k):
            raise AttributeError(f"unknown state field: {k}")
        setattr(_state, k, v)


reset_state()  # initialize at import


# ---------------------------------------------------------------------------
# Color management
# ---------------------------------------------------------------------------

class _ColorManagementEngine:
    def getWorkingColorSpaceName(self) -> str:  # noqa: N802
        return _state.color_management_engine_name or ""


# ---------------------------------------------------------------------------
# UI manager + main window
# ---------------------------------------------------------------------------

class _MenuBar:
    def __init__(self):
        self.menus: List[Any] = []

    def addMenu(self, name: str):  # noqa: N802
        menu = _Menu(name)
        self.menus.append(menu)
        return menu

    def removeAction(self, action):  # noqa: N802
        pass


class _Menu:
    def __init__(self, name: str):
        self.name = name
        self.actions: List[Any] = []

    def addAction(self, label: str):  # noqa: N802
        action = _Action(label)
        self.actions.append(action)
        return action

    def menuAction(self):  # noqa: N802
        return self


class _Action:
    def __init__(self, label: str):
        self.label = label
        self.enabled = True
        self.callbacks: List[Callable] = []
        self.triggered = self  # so `.triggered.connect(fn)` works

    def connect(self, fn: Callable):
        self.callbacks.append(fn)

    def setEnabled(self, on: bool):  # noqa: N802
        self.enabled = on


class _MainWindow:
    def menuBar(self) -> _MenuBar:  # noqa: N802
        return _MenuBar()


class _QtForPythonUIMgr:
    def getCurrentGraph(self) -> Optional[_Graph]:  # noqa: N802
        return _state.current_graph

    def getMainWindow(self):  # noqa: N802
        return _state.main_window or _MainWindow()

    def getCurrentGraphSelectedNodes(self) -> Optional[_SDArray]:  # noqa: N802
        return _state.selected_nodes


# ---------------------------------------------------------------------------
# Application + Context
# ---------------------------------------------------------------------------

class _PluginMgr:
    def getUserPluginsDir(self) -> str:  # noqa: N802
        return _state.user_plugins_dir


class _Application:
    def getQtForPythonUIMgr(self) -> _QtForPythonUIMgr:  # noqa: N802
        return _QtForPythonUIMgr()

    def getVersion(self) -> str:  # noqa: N802
        return _state.application_version

    def getColorManagementEngine(self) -> Optional[_ColorManagementEngine]:  # noqa: N802
        if _state.color_management_engine_is_none:
            return None
        return _ColorManagementEngine()

    def getPluginMgr(self) -> _PluginMgr:  # noqa: N802
        return _PluginMgr()

    def registerAfterFileLoadedCallback(self, fn: Callable) -> int:  # noqa: N802
        _state.registered_callback_id += 1
        return _state.registered_callback_id

    def unregisterCallback(self, callback_id: int) -> None:  # noqa: N802
        _state.unregistered_callbacks.append(callback_id)


import logging as _py_logging


class _Context:
    def getSDApplication(self) -> _Application:  # noqa: N802
        return _Application()

    def createRuntimeLogHandler(self) -> _py_logging.Handler:  # noqa: N802
        return _py_logging.NullHandler()


def getContext() -> _Context:  # noqa: N802
    return _Context()


# ---------------------------------------------------------------------------
# Factories used by tests
# ---------------------------------------------------------------------------

def make_int2(x: int = 0, y: int = 0) -> _Int2:
    return _Int2(x=x, y=y)


def make_value_string(value: str) -> _SDValueString:
    return _SDValueString(_value=value)


def make_node_definition(label: str = "Uniform color") -> _NodeDefinition:
    return _NodeDefinition(_label=label)


def make_node(label: str = "Uniform color") -> _Node:
    return _Node(_definition=make_node_definition(label))


def make_array(items: Optional[List[Any]] = None) -> _SDArray:
    return _SDArray(items=items or [])


def make_resource(class_name: str = "SDResource") -> _Resource:
    return _Resource(_class_name=class_name)


def make_package(file_path: str = "", resources: Optional[List[_Resource]] = None) -> _Package:
    return _Package(_file_path=file_path, _resources=resources or [])


def make_graph(
    package: Optional[_Package] = None,
    nodes: Optional[List[Any]] = None,
    output_nodes: Optional[List[Any]] = None,
    annotations: Optional[dict] = None,
    input_properties: Optional[dict] = None,
    default_parent_size: Optional[_Int2] = None,
    is_comp_graph: bool = False,
) -> _Graph:
    """Returns a graph. is_comp_graph=True makes it pass isinstance(...,
    sd.api.sbs.sdsbscompgraph.SDSBSCompGraph)."""
    cls = api.sbs.sdsbscompgraph.SDSBSCompGraph if is_comp_graph else _Graph
    g = cls()  # type: ignore[abstract]
    g._package = package
    g._nodes = make_array(nodes or [])
    g._output_nodes = make_array(output_nodes or [])
    g._annotations = annotations or {}
    g._input_properties = input_properties or {}
    g._default_parent_size = default_parent_size
    g._is_comp_graph = is_comp_graph
    return g


# Expose private types so the plugin can `isinstance(...)` against them
# through `sd.api.*` paths. Done after api submodule is initialized below.
api._Graph = _Graph
api._Int2 = _Int2
api._SDValueString = _SDValueString
api._SDArray = _SDArray
api._Package = _Package
api._Resource = _Resource
