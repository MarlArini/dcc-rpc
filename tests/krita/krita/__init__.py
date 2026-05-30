"""
AI-generated (Claude Opus 4.7): fake `krita` module for tests.

Covers the API surface krita_presence.py imports and that KPContext methods
touch. Qt-introspection methods (active_tool_name) are not exercised here —
they walk the real Krita docker tree.

Pattern:
    def test_X(kr):
        kr.set_state(
            documents=[kr.make_document(name="A.kra")],
            active_document=...,
            active_view=...,
        )
        ctx = KPContext.capture()
        assert ctx.num_documents() == "1 document"
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass
class _Node:
    _name: str = "Layer 1"
    _blend: str = "Normal"
    _children: List["_Node"] = field(default_factory=list)
    _visible: bool = True

    def name(self) -> str:
        return self._name

    def blendingMode(self) -> str:  # noqa: N802 (Krita API casing)
        return self._blend

    def childNodes(self) -> List["_Node"]:  # noqa: N802
        return list(self._children)

    def get_visible(self) -> bool:
        return self._visible


@dataclass
class _Document:
    _name: str = "Unnamed"
    _top_level_nodes: List[_Node] = field(default_factory=list)
    _active_node: Optional[_Node] = None
    _color_model: str = "RGBA"
    _color_profile: str = "sRGB-elle-V2-srgbtrc.icc"
    _width: int = 1920
    _height: int = 1080
    _resolution: int = 72
    _document_info_xml: str = (
        '<?xml version="1.0"?>'
        '<document-info xmlns="http://www.calligra.org/DTD/document-info">'
        '<about><editing-time>0</editing-time></about>'
        '</document-info>'
    )

    def name(self) -> str:
        return self._name

    def topLevelNodes(self) -> List[_Node]:  # noqa: N802
        return list(self._top_level_nodes)

    def activeNode(self) -> Optional[_Node]:  # noqa: N802
        return self._active_node

    def colorModel(self) -> str:  # noqa: N802
        return self._color_model

    def colorProfile(self) -> str:  # noqa: N802
        return self._color_profile

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height

    def resolution(self) -> int:
        return self._resolution

    def documentInfo(self) -> str:  # noqa: N802
        return self._document_info_xml


@dataclass
class _ManagedColor:
    _rgba: Tuple[int, int, int, int] = (0, 0, 0, 255)

    def colorForCanvas(self, canvas):  # noqa: N802
        # Stand in for QColor with red/green/blue ints.
        from PySide6.QtGui import QColor
        r, g, b, a = self._rgba
        return QColor(r, g, b, a)


@dataclass
class _Preset:
    _name: str = "default preset"

    def name(self) -> str:
        return self._name


@dataclass
class _View:
    _brush_preset: Optional[_Preset] = None
    _foreground_color: Optional[_ManagedColor] = None
    _canvas: Any = None
    _blending_mode: str = "Normal"

    def currentBrushPreset(self) -> Optional[_Preset]:  # noqa: N802
        return self._brush_preset

    def foregroundColor(self) -> Optional[_ManagedColor]:  # noqa: N802
        return self._foreground_color

    def canvas(self):
        return self._canvas

    def currentBlendingMode(self) -> str:  # noqa: N802
        return self._blending_mode


@dataclass
class _Window:
    _active_view: Optional[_View] = None

    def activeView(self) -> Optional[_View]:  # noqa: N802
        return self._active_view

    def qwindow(self):
        return None

    def createAction(self, name, label, location):  # noqa: N802
        # Returns a fake action with a triggered.connect method.
        from PySide6.QtCore import QObject, Signal

        class _Action(QObject):
            triggered = Signal()

        return _Action()


# Convenience types used in type hints
Node = _Node
Document = _Document
Window = _Window
View = _View
Krita = None  # placeholder; set after class definition below


# ---------------------------------------------------------------------------
# Notifier (signals + setActive)
# ---------------------------------------------------------------------------

class _Signal:
    """Lightweight stand-in for Qt signals: stores connected callbacks."""

    def __init__(self):
        self._connections: List[Callable] = []

    def connect(self, fn):
        self._connections.append(fn)

    def emit(self, *args, **kwargs):
        for fn in self._connections:
            fn(*args, **kwargs)


@dataclass
class _Notifier:
    imageCreated: _Signal = field(default_factory=_Signal)
    imageOpened: _Signal = field(default_factory=_Signal)
    applicationClosing: _Signal = field(default_factory=_Signal)
    _active: bool = False

    def setActive(self, on: bool):  # noqa: N802
        self._active = on


# ---------------------------------------------------------------------------
# Krita class (singleton)
# ---------------------------------------------------------------------------

@dataclass
class _State:
    documents: List[_Document] = field(default_factory=list)
    active_document: Optional[_Document] = None
    active_window: Optional[_Window] = None
    settings_storage: Dict[Tuple[str, str], str] = field(default_factory=dict)
    version: str = "5.3.1"
    dockers: List[Any] = field(default_factory=list)
    notifier: _Notifier = field(default_factory=_Notifier)
    extensions: List[Any] = field(default_factory=list)
    instance_is_none: bool = False  # toggle to simulate Krita.instance() == None


_state = _State()


class _Krita:
    @classmethod
    def instance(cls) -> Optional["_Krita"]:
        if _state.instance_is_none:
            return None
        return _SINGLETON

    def documents(self) -> List[_Document]:
        return list(_state.documents)

    def activeDocument(self) -> Optional[_Document]:  # noqa: N802
        return _state.active_document

    def activeWindow(self) -> Optional[_Window]:  # noqa: N802
        return _state.active_window

    def notifier(self) -> _Notifier:
        return _state.notifier

    def version(self) -> str:
        return _state.version

    def dockers(self):
        return list(_state.dockers)

    def addExtension(self, ext):  # noqa: N802
        _state.extensions.append(ext)

    def readSetting(self, prefix: str, name: str, default: str = "") -> str:  # noqa: N802
        return _state.settings_storage.get((prefix, name), default)

    def writeSetting(self, prefix: str, name: str, value: str) -> None:  # noqa: N802
        _state.settings_storage[(prefix, name)] = value


_SINGLETON = _Krita()
Krita = _Krita


# ---------------------------------------------------------------------------
# Extension base class — krita_presence.MyExtension subclasses this
# ---------------------------------------------------------------------------

class Extension:
    def __init__(self, parent):
        self._parent = parent


# ---------------------------------------------------------------------------
# State configuration helpers
# ---------------------------------------------------------------------------

def reset_state() -> None:
    global _state
    _state = _State()


def set_state(**kwargs) -> None:
    for k, v in kwargs.items():
        if not hasattr(_state, k):
            raise AttributeError(f"unknown state field: {k}")
        setattr(_state, k, v)


def get_settings_storage() -> Dict[Tuple[str, str], str]:
    """Expose the in-memory settings dict for assertions."""
    return _state.settings_storage


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def make_node(name: str = "Layer 1", blend: str = "Normal",
              children: Optional[List[_Node]] = None, visible: bool = True) -> _Node:
    return _Node(_name=name, _blend=blend, _children=children or [], _visible=visible)


def make_document(name: str = "Unnamed",
                  top_level_nodes: Optional[List[_Node]] = None,
                  active_node: Optional[_Node] = None,
                  color_model: str = "RGBA",
                  color_profile: str = "sRGB-elle-V2-srgbtrc.icc",
                  width: int = 1920, height: int = 1080,
                  resolution: int = 72,
                  document_info_xml: Optional[str] = None) -> _Document:
    kwargs = dict(
        _name=name,
        _top_level_nodes=top_level_nodes or [],
        _active_node=active_node,
        _color_model=color_model,
        _color_profile=color_profile,
        _width=width, _height=height, _resolution=resolution,
    )
    if document_info_xml is not None:
        kwargs["_document_info_xml"] = document_info_xml
    return _Document(**kwargs)


def make_view(brush_preset: Optional[_Preset] = None,
              foreground_color: Optional[_ManagedColor] = None,
              canvas: Any = None,
              blending_mode: str = "Normal") -> _View:
    return _View(
        _brush_preset=brush_preset,
        _foreground_color=foreground_color,
        _canvas=canvas,
        _blending_mode=blending_mode,
    )


def make_window(active_view: Optional[_View] = None) -> _Window:
    return _Window(_active_view=active_view)


def make_managed_color(r: int = 0, g: int = 0, b: int = 0, a: int = 255) -> _ManagedColor:
    return _ManagedColor(_rgba=(r, g, b, a))


def make_preset(name: str = "default preset") -> _Preset:
    return _Preset(_name=name)


# ---------------------------------------------------------------------------
# ToolBox docker fake (for active_tool_name)
#
# Krita's active_tool_name walks `instance.dockers()` for a widget whose
# objectName() is "ToolBox", then finds its child QButtonGroup, then reads
# the checkedButton's objectName. The plugin uses real PyQt5 types
# (QDockWidget, QButtonGroup, QToolButton); we just need objects that
# respond to objectName / findChild / checkedButton / behave like the
# matched types when isinstance(QButtonGroup) is checked.
# ---------------------------------------------------------------------------

class _FakeBtn:
    """Stand-in for a QToolButton — just needs objectName()."""
    def __init__(self, object_name: str):
        self._object_name = object_name

    def objectName(self) -> str:  # noqa: N802
        return self._object_name


def _make_toolbox_docker(active_tool_object_name: Optional[str]):
    """Build a ToolBox docker whose QButtonGroup child reports
    `active_tool_object_name` as the checked button's objectName.

    If `active_tool_object_name` is None, the docker still exists and the
    QButtonGroup is present, but checkedButton() returns None — exercising
    the "no checked button" branch.

    Uses PySide6 QObject parent chain so the plugin's
    `findChild(qw.QButtonGroup)` resolves through the alias installed by
    tests/krita/conftest.py.
    """
    from PySide6.QtWidgets import QDockWidget, QButtonGroup

    docker = QDockWidget()
    docker.setObjectName("ToolBox")
    bg = QButtonGroup(docker)
    if active_tool_object_name is not None:
        # QButtonGroup needs actual QAbstractButtons to track 'checked'. Patch
        # checkedButton on this specific instance to return our lightweight
        # stand-in; avoids needing to wire up real Qt widgets for this test.
        btn = _FakeBtn(active_tool_object_name)
        bg.checkedButton = lambda b=btn: b  # type: ignore[method-assign]
    else:
        bg.checkedButton = lambda: None  # type: ignore[method-assign]
    return docker


def make_toolbox_with_active_tool(tool_object_name: Optional[str]):
    """Public helper used in test_krita.py.

    Returns a docker suitable for installing as `kr.set_state(dockers=[...])`."""
    return _make_toolbox_docker(tool_object_name)
