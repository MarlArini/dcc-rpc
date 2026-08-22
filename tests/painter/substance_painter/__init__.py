"""
AI-generated (Claude Opus 4.7): fake `substance_painter` module for tests.

This stand-in covers the API surface that painter_presence.py imports and
that SPContext methods touch. It's intentionally minimal — Qt-introspection
methods (get_active_tool, get_paint_color, get_brush_material, get_brush_alpha)
are *not* covered here because they walk a real QMainWindow widget tree;
those would need pytest-qt or a much more elaborate fake.

Pattern for tests:

    def test_something(sp):
        sp.set_state(
            project_name="MyProject",
            texture_sets=[sp.make_texture_set(name="ts1", ...)],
            active_stack=...,
        )
        ctx = SPContext(...)
        assert ctx.get_project_name() == "Project: MyProject"

State is reset between tests by the autouse fixture in conftest.py.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable, List, Optional


# ---------------------------------------------------------------------------
# Exception types (sp.exception.*)
# ---------------------------------------------------------------------------

class ProjectError(Exception):
    pass


class ServiceNotFoundError(Exception):
    pass


exception = SimpleNamespace(
    ProjectError=ProjectError,
    ServiceNotFoundError=ServiceNotFoundError,
)


# ---------------------------------------------------------------------------
# Domain types — Material, Stack, TextureSet, Layer, GroupLayerNode
# ---------------------------------------------------------------------------

@dataclass
class _Material:
    name: str = "material_01"
    res_w: int = 2048
    res_h: int = 2048
    # `None` => no UV tiles; otherwise a list of opaque tile objects.
    uv_tiles: Optional[List[Any]] = None

    def get_resolution(self):
        return SimpleNamespace(width=self.res_w, height=self.res_h)

    def has_uv_tiles(self) -> bool:
        return self.uv_tiles is not None

    def all_uv_tiles(self):
        return self.uv_tiles or []


@dataclass
class _Stack:
    material_obj: _Material = field(default_factory=_Material)
    root_nodes: List[Any] = field(default_factory=list)
    selected_nodes: List[Any] = field(default_factory=list)
    channels: List[Any] = field(default_factory=list)

    def material(self):
        return self.material_obj

    def all_channels(self):
        return self.channels


@dataclass
class _TextureSet:
    name: str = "texture_set_01"
    mesh_names: List[str] = field(default_factory=list)
    stacks: List[_Stack] = field(default_factory=list)

    def all_mesh_names(self):
        return self.mesh_names

    def all_stacks(self):
        return self.stacks


@dataclass
class _Layer:
    name: str = "Layer 1"
    blend_mode: str = "Normal"
    is_mask: bool = False
    children: Optional[List[Any]] = None  # None on non-group leaves

    def get_name(self) -> str:
        return self.name

    def is_in_mask_stack(self) -> bool:
        return self.is_mask

    def get_blending_mode(self, _arg):
        return SimpleNamespace(name=self.blend_mode)

    def sub_layers(self):
        return self.children or []


class GroupLayerNode(_Layer):
    """Marker subclass — the plugin's isinstance check distinguishes group
    layers (which recurse into children) from regular layers."""

    def __init__(
        self,
        name: str = "Group 1",
        children: Optional[List[Any]] = None,
        blend_mode: str = "Normal",
        is_mask: bool = False,
    ):
        super().__init__(
            name=name, blend_mode=blend_mode, is_mask=is_mask, children=children or []
        )


# ---------------------------------------------------------------------------
# Submodule namespaces (sp.project, sp.textureset, sp.layerstack, ...)
# ---------------------------------------------------------------------------

@dataclass
class _State:
    project_name: Optional[str] = None
    active_stack: Optional[_Stack] = None
    texture_sets: Optional[List[_TextureSet]] = None
    resources: List[Any] = field(default_factory=list)
    application_version: str = "12.0.3"
    capture_raises: Optional[BaseException] = None
    # Optional fake Qt main window tree. None -> _get_main_window() returns a
    # bare empty QMainWindow (no children); tests that exercise Qt introspection
    # build a populated tree via make_qt_main_window(...) and install it here.
    main_window: Optional[Any] = None


_state = _State()


def reset_state() -> None:
    global _state
    _state = _State()


def set_state(**kwargs) -> None:
    """Configure fake module state for the current test."""
    for k, v in kwargs.items():
        if not hasattr(_state, k):
            raise AttributeError(f"unknown state field: {k}")
        setattr(_state, k, v)


# sp.project
project = SimpleNamespace(name=lambda: _state.project_name)


# sp.textureset
def _get_active_stack():
    if _state.capture_raises is not None:
        raise _state.capture_raises
    return _state.active_stack


textureset = SimpleNamespace(
    get_active_stack=_get_active_stack,
    all_texture_sets=lambda: _state.texture_sets,
    TextureSet=_TextureSet,
    Stack=_Stack,
)


# sp.layerstack
layerstack = SimpleNamespace(
    get_root_layer_nodes=lambda stack: stack.root_nodes,
    get_selected_nodes=lambda stack: stack.selected_nodes,
    GroupLayerNode=GroupLayerNode,
)


# sp.application
application = SimpleNamespace(version=lambda: _state.application_version)


# sp.resource
class _ResourceType:
    """Stand-in for sp.resource.Type — opaque enum-like."""
    def __init__(self, name="any"):
        self.name = name


resource = SimpleNamespace(
    list_project_resources=lambda: _state.resources,
    Resource=SimpleNamespace(retrieve=lambda r: None),
    Type=_ResourceType,
)


# sp.ui — fake Qt widget tree
#
# Painter's SPContext does Qt introspection via findChild/findChildren on
# a QMainWindow. Our fake `_FakeQWidget` walks an in-memory tree of nodes
# tagged with a class-name string and an object_name, returning matches
# the same way Qt's recursive search does. It covers everything
# SPContext.get_active_tool / get_paint_color / get_brush_material /
# get_brush_alpha need:
#
#   - findChild(cls, name) returns the first matching descendant
#   - findChildren(cls, name=None) returns all matching descendants
#   - isChecked / defaultAction / text on tool buttons and labels
#   - grab().toImage().pixelColor(x, y) for the color-zone pixel sampler
#
# Tests build a tree with make_qt_tree(...) and install it via
# sp.set_state(main_window=tree); SPContext.capture() picks it up through
# ui.get_main_window().

class _FakeQAction:
    def __init__(self, text: str = "", object_name: str = ""):
        self._text = text
        self._object_name = object_name
        # `menu()` returns a sub-menu when this action represents a menubar
        # submenu; tests that exercise menubar walks set this via
        # _menubar_with_discord_menu(...).
        self._submenu: Optional[Any] = None

    def text(self) -> str:
        return self._text

    def objectName(self) -> str:  # noqa: N802
        return self._object_name

    def menu(self):
        return self._submenu


class _FakeQColor:
    def __init__(self, r: int = 0, g: int = 0, b: int = 0):
        self._r, self._g, self._b = r, g, b

    def red(self) -> int:
        return self._r

    def green(self) -> int:
        return self._g

    def blue(self) -> int:
        return self._b


class _FakeQImage:
    def __init__(self, color: tuple):
        self._color = color

    def pixelColor(self, x: int, y: int) -> _FakeQColor:  # noqa: N802
        return _FakeQColor(*self._color)


class _FakeQSize:
    def __init__(self, w: int, h: int):
        self._w, self._h = w, h

    def width(self) -> int:
        return self._w

    def height(self) -> int:
        return self._h


class _FakeQPixmap:
    def __init__(self, color: tuple, size: tuple = (10, 10)):
        self._color = color
        self._size = size

    def size(self) -> _FakeQSize:
        return _FakeQSize(*self._size)

    def toImage(self) -> _FakeQImage:  # noqa: N802
        return _FakeQImage(self._color)


class _FakeQWidget:
    """In-memory stand-in for Qt's findChild/findChildren protocol.

    Each node carries a `widget_class` (string like 'QToolBar') matched
    against `cls.__name__` of the requested type, and an optional
    `object_name`. findChild/findChildren walk all descendants depth-first
    and filter on both. Pass `raise_on_find=True` to simulate a torn-down
    widget that raises RuntimeError from Qt — useful for testing the
    exception branches in painter_presence._find_named / get_active_tool.
    """

    def __init__(
        self,
        widget_class: str,
        object_name: str = "",
        children: Optional[List["_FakeQWidget"]] = None,
        text: str = "",
        checked: bool = False,
        default_action: Optional[_FakeQAction] = None,
        paint_color: Optional[tuple] = None,
        raise_on_find: bool = False,
    ):
        self._widget_class = widget_class
        self._object_name = object_name
        self._children: List["_FakeQWidget"] = list(children) if children else []
        self._text = text
        self._checked = checked
        self._default_action = default_action
        self._paint_color = paint_color
        self._raise_on_find = raise_on_find

    # --- tree traversal ------------------------------------------------

    def _iter_descendants(self):
        for c in self._children:
            yield c
            yield from c._iter_descendants()

    def findChild(self, cls, name=None):  # noqa: N802
        if self._raise_on_find:
            raise RuntimeError("widget has been destroyed")
        for child in self._iter_descendants():
            if child._widget_class != cls.__name__:
                continue
            if name is not None and child._object_name != name:
                continue
            return child
        return None

    def findChildren(self, cls, name=None):  # noqa: N802
        if self._raise_on_find:
            raise RuntimeError("widget has been destroyed")
        return [
            c for c in self._iter_descendants()
            if c._widget_class == cls.__name__
            and (name is None or c._object_name == name)
        ]

    # --- per-widget surface --------------------------------------------

    def objectName(self) -> str:  # noqa: N802
        return self._object_name

    def text(self) -> str:
        return self._text

    def isChecked(self) -> bool:  # noqa: N802
        return self._checked

    def defaultAction(self) -> Optional[_FakeQAction]:  # noqa: N802
        return self._default_action

    def grab(self) -> _FakeQPixmap:
        return _FakeQPixmap(self._paint_color or (0, 0, 0))


# Public constructors used in tests.
def make_qt_widget(widget_class: str, object_name: str = "", **kwargs) -> _FakeQWidget:
    return _FakeQWidget(widget_class=widget_class, object_name=object_name, **kwargs)


def make_qt_action(text: str = "", object_name: str = "") -> _FakeQAction:
    return _FakeQAction(text=text, object_name=object_name)


def make_qt_main_window(children: Optional[List[_FakeQWidget]] = None) -> _FakeQWidget:
    return _FakeQWidget(widget_class="QMainWindow", children=children)


def make_toolbar(name: str = "tools_toolbar", buttons: Optional[List[_FakeQWidget]] = None) -> _FakeQWidget:
    return _FakeQWidget(widget_class="QToolBar", object_name=name, children=buttons)


def make_tool_button(
    action_text: str = "",
    checked: bool = False,
    object_name: str = "",
    action_object_name: str = "",
) -> _FakeQWidget:
    """Build a checked-or-unchecked QToolButton whose `defaultAction()` returns
    a QAction with the given `text` (localized hover label) and `objectName`
    (English-stable identifier the plugin maps to icon keys).

    Pass `action_object_name` (or `action_text` for legacy callers) — when
    `action_object_name` is empty, the action's objectName defaults to the
    text so single-arg callers stay working.
    """
    if action_text or action_object_name:
        action = _FakeQAction(
            text=action_text,
            object_name=action_object_name or action_text,
        )
    else:
        action = None
    return _FakeQWidget(
        widget_class="QToolButton",
        object_name=object_name,
        checked=checked,
        default_action=action,
    )


def make_source_parameters_view(base_color_label: bool = True) -> _FakeQWidget:
    """A QFrame named 'SourceParametersView' containing the 'Base color' label
    + a 'colorZone' QToolButton — the minimum shape get_paint_color expects."""
    labels = []
    if base_color_label:
        labels.append(_FakeQWidget(
            widget_class="QLabel",
            object_name="dropzone_title",
            text="Base color",
        ))
    color_zone = _FakeQWidget(
        widget_class="QToolButton",
        object_name="colorZone",
        paint_color=(255, 0, 0),
    )
    return _FakeQWidget(
        widget_class="QFrame",
        object_name="SourceParametersView",
        children=[*labels, color_zone],
    )


def _make_dropzone_view(
    widget_class: str, object_name: str, dropzone_text: str,
) -> _FakeQWidget:
    """Shared shape: an outer container with a single 'dropzone_text' QLabel
    child. Used by both the brush-alpha (MaskParametersView) and brush-material
    (materialModeParams) factories below."""
    return _FakeQWidget(
        widget_class=widget_class,
        object_name=object_name,
        children=[_FakeQWidget(
            widget_class="QLabel",
            object_name="dropzone_text",
            text=dropzone_text,
        )],
    )


def make_mask_parameters_view(dropzone_text: str = "Soft Brush") -> _FakeQWidget:
    """A QFrame named 'MaskParametersView' containing a 'dropzone_text' QLabel.
    Used to test get_brush_alpha (the mask drop-zone holds the alpha)."""
    return _make_dropzone_view("QFrame", "MaskParametersView", dropzone_text)


def make_material_mode_params(
    dropzone_text: str = "Worn Leather", has_clear_button: bool = True,
) -> _FakeQWidget:
    """A QWidget named 'materialModeParams' containing a 'dropzone_text' QLabel.
    Used to test get_brush_material (the brush-tip material drop-zone).

    get_brush_material treats the presence of the 'clear' QToolButton as the
    signal that a material is actually selected, so the factory includes one
    by default; pass has_clear_button=False to model the unselected state."""
    view = _make_dropzone_view("QWidget", "materialModeParams", dropzone_text)
    if has_clear_button:
        view._children.append(
            _FakeQWidget(widget_class="QToolButton", object_name="clear")
        )
    return view


def _get_main_window():
    # If a test set sp._state.main_window via set_state, return it; otherwise
    # default to an empty QMainWindow so capture() succeeds.
    if _state.main_window is not None:
        return _state.main_window
    return _FakeQWidget(widget_class="QMainWindow")


ui = SimpleNamespace(get_main_window=_get_main_window)


# sp.logging
logging = SimpleNamespace(
    warning=lambda *a, **kw: None,
    error=lambda *a, **kw: None,
    info=lambda *a, **kw: None,
)


# sp.event
class _Dispatcher:
    """Tracks (event, callback) connections so tests can assert that
    close() disconnects everything start() connected."""

    def __init__(self):
        self.connections = []

    def connect(self, event, callback):
        self.connections.append((event, callback))

    def disconnect(self, event, callback):
        self.connections.remove((event, callback))


event = SimpleNamespace(
    DISPATCHER=_Dispatcher(),
    ProjectOpened=object(),
    ProjectCreated=object(),
    BakingProcessAboutToStart=object(),
    BakingProcessProgress=object(),
    BakingProcessEnded=object(),
)


# ---------------------------------------------------------------------------
# Convenience factories used by tests
# ---------------------------------------------------------------------------

def make_material(name="material_01", res_w=2048, res_h=2048, uv_tiles=None) -> _Material:
    return _Material(name=name, res_w=res_w, res_h=res_h, uv_tiles=uv_tiles)


def make_stack(
    material: Optional[_Material] = None,
    root_nodes: Optional[List[Any]] = None,
    selected_nodes: Optional[List[Any]] = None,
    channels: Optional[List[Any]] = None,
) -> _Stack:
    return _Stack(
        material_obj=material or make_material(),
        root_nodes=root_nodes or [],
        selected_nodes=selected_nodes or [],
        channels=channels or [],
    )


def make_texture_set(
    name: str = "texture_set_01",
    mesh_names: Optional[List[str]] = None,
    stacks: Optional[List[_Stack]] = None,
) -> _TextureSet:
    return _TextureSet(
        name=name,
        mesh_names=mesh_names or [],
        stacks=stacks or [],
    )


def make_layer(name="Layer 1", blend_mode="Normal", is_mask=False) -> _Layer:
    return _Layer(name=name, blend_mode=blend_mode, is_mask=is_mask, children=None)


def make_group(
    name="Group 1",
    children: Optional[List[Any]] = None,
    blend_mode: str = "Normal",
    is_mask: bool = False,
) -> GroupLayerNode:
    return GroupLayerNode(
        name=name, children=children or [], blend_mode=blend_mode, is_mask=is_mask
    )
