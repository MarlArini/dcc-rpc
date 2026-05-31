"""
AI-generated (Claude Opus 4.7): fake `gi.repository.Gimp` module.

Covers the API surface that gimp_presence.py and settings_dialog.py touch.
Pattern mirrors the other plugin fakes: a module-level `_state` dataclass
configures returns; tests use `Gimp.set_state(...)` to seed values; an
autouse `reset_state()` fixture in conftest cleans up between tests.
"""
from __future__ import annotations
import enum
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Enums (use Python Enum so the plugin's _gp_get_enum_name walks ._member_map_)
# ---------------------------------------------------------------------------

class ImageBaseType(enum.Enum):
    RGB = 0
    GRAY = 1
    INDEXED = 2


class LayerMode(enum.Enum):
    Normal = 0
    Multiply = 1
    Screen = 2
    Overlay = 3
    Darken = 4
    Lighten = 5
    Dodge = 6


class PaintMode(enum.Enum):
    Normal = 0
    Multiply = 1
    Screen = 2
    Burn = 3


class PDBProcType(enum.Enum):
    INTERNAL = 0
    PLUGIN = 1
    TEMPORARY = 2
    PERSISTENT = 3


class PDBStatusType(enum.Enum):
    SUCCESS = 0
    EXECUTION_ERROR = 1
    CALLING_ERROR = 2
    PASS_THROUGH = 3
    CANCEL = 4


class MessageHandlerType(enum.Enum):
    """Subset of Gimp.MessageHandlerType used by settings_dialog._gp_warn."""
    MESSAGE_BOX = 0
    CONSOLE = 1
    ERROR_CONSOLE = 2


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass
class _ColorProfile:
    _label: str = "sRGB built-in"

    def get_label(self) -> str:
        return self._label


@dataclass
class _Layer:
    _name: str = "Layer 1"
    _mode: LayerMode = LayerMode.Normal
    _visible: bool = True

    def get_name(self) -> str:
        return self._name

    def get_mode(self) -> LayerMode:
        return self._mode

    def get_visible(self) -> bool:
        return self._visible


@dataclass
class Image:  # exposed as Gimp.Image
    _id: int = 0
    _name: str = "Untitled"
    _layers: List[_Layer] = field(default_factory=list)
    _selected_layers: List[_Layer] = field(default_factory=list)
    _base_type: ImageBaseType = ImageBaseType.RGB
    _color_profile: _ColorProfile = field(default_factory=_ColorProfile)
    _width: int = 1920
    _height: int = 1080
    _resolution: Tuple[bool, float, float] = (True, 72.0, 72.0)

    def get_id(self) -> int:
        return self._id

    def get_name(self) -> str:
        return self._name

    def get_layers(self) -> List[_Layer]:
        return list(self._layers)

    def get_selected_layers(self) -> Optional[List[_Layer]]:
        # GIMP returns an empty list when nothing is selected — None is
        # exceptional. Plugin code handles both; tests can configure either.
        return list(self._selected_layers)

    def get_base_type(self) -> ImageBaseType:
        return self._base_type

    def get_effective_color_profile(self) -> _ColorProfile:
        return self._color_profile

    def get_width(self) -> int:
        return self._width

    def get_height(self) -> int:
        return self._height

    def get_resolution(self) -> Tuple[bool, float, float]:
        # GIMP's get_resolution returns (success, xres, yres).
        return self._resolution

    @staticmethod
    def id_is_valid(image_id: int) -> bool:
        """Real GIMP: returns True iff `image_id` belongs to an open image.
        Fake: walks _state.images for a matching id."""
        return any(img._id == image_id for img in _state.images)


@dataclass
class _Brush:
    _name: str = "Default Brush"

    def get_name(self) -> str:
        return self._name


# ---------------------------------------------------------------------------
# Procedure types
# ---------------------------------------------------------------------------

class _BaseProcedure:
    """In-memory stand-in for Gimp.Procedure / Gimp.ImageProcedure. Tests
    inspect attributes set by the plugin (menu label, doc strings,
    argument list, etc.); the actual run function is callable via .run_fn."""

    def __init__(self, plug_in, name: str, proc_type: PDBProcType,
                 run_fn: Callable, run_data: Any):
        self.plug_in = plug_in
        self.name = name
        self.proc_type = proc_type
        self.run_fn = run_fn
        self.run_data = run_data
        self.menu_label: Optional[str] = None
        self.attribution: Optional[Tuple[str, str, str]] = None
        self.documentation: Optional[Tuple] = None
        self.menu_paths: List[str] = []
        # ImageProcedure-specific: image color modes accepted for invocation.
        # None = not set (plain Procedure); "*" = any mode.
        self.image_types: Optional[str] = None
        self.arguments: List[Tuple] = []  # (kind, name, label, blurb, default, extras)
        self.choice_arguments: Dict[str, Any] = {}
        self.persistent_ready_called = False

    def set_menu_label(self, label: str) -> None:
        self.menu_label = label

    def set_attribution(self, *args) -> None:
        self.attribution = tuple(args)

    def set_documentation(self, *args) -> None:
        self.documentation = tuple(args)

    def add_menu_path(self, path: str) -> None:
        self.menu_paths.append(path)

    def set_image_types(self, types: str) -> None:
        """ImageProcedure-only in real GIMP; we accept it on the shared
        fake class so tests can verify it was called."""
        self.image_types = types

    def add_boolean_argument(self, name, label, blurb, default, flags):
        self.arguments.append(("boolean", name, label, blurb, default, flags))

    def add_int_argument(self, name, label, blurb, lo, hi, default, flags):
        self.arguments.append(("int", name, label, blurb, default, (lo, hi, flags)))

    def add_string_argument(self, name, label, blurb, default, flags):
        self.arguments.append(("string", name, label, blurb, default, flags))

    def add_choice_argument(self, name, label, blurb, choice, default_id, flags):
        self.arguments.append(("choice", name, label, blurb, default_id, flags))
        self.choice_arguments[name] = choice

    def persistent_ready(self) -> None:
        self.persistent_ready_called = True

    def new_return_values(self, status: PDBStatusType, error_or_args=None):
        return (status, error_or_args)

    def get_plug_in(self):
        return self.plug_in


class _ProcedureFactory:
    """Stand-in for the Gimp.Procedure / Gimp.ImageProcedure classes whose
    `.new(plugin, name, type, run_fn, run_data=None)` is a constructor.
    `run_data` is optional in real GIMP and the plug-in calls without it."""

    @staticmethod
    def new(plug_in, name, proc_type, run_fn, run_data=None):
        return _BaseProcedure(plug_in, name, proc_type, run_fn, run_data)


Procedure = _ProcedureFactory
ImageProcedure = _ProcedureFactory


# ---------------------------------------------------------------------------
# Choice (used by add_choice_argument)
# ---------------------------------------------------------------------------

class _Choice:
    def __init__(self):
        self._entries: List[Tuple[str, int, str, str]] = []

    def add(self, nick: str, weight: int, label: str, blurb: str) -> None:
        self._entries.append((nick, weight, label, blurb))


class Choice:
    @staticmethod
    def new() -> _Choice:
        return _Choice()


# ---------------------------------------------------------------------------
# PlugIn base class (GPPlugin subclasses this)
# ---------------------------------------------------------------------------

class PlugIn:
    """Bare-minimum base. Tests don't construct a real one; the plugin's
    `do_query_procedures`/`do_create_procedure` callbacks are invoked
    manually when needed."""

    __gtype__ = "PlugIn"

    def add_temp_procedure(self, procedure: _BaseProcedure) -> None:
        _state.temp_procedures[procedure.name] = procedure

    def remove_temp_procedure(self, name: str) -> None:
        _state.temp_procedures.pop(name, None)

    def persistent_enable(self) -> None:
        _state.persistent_enable_called = True


# ---------------------------------------------------------------------------
# State (module-level returns + side effects)
# ---------------------------------------------------------------------------

@dataclass
class _State:
    images: List[Image] = field(default_factory=list)
    version_str: str = "3.2.4"
    directory_path: str = ""  # populated in reset_state with a fresh tempdir
    warnings: List[str] = field(default_factory=list)
    # context
    brush: _Brush = field(default_factory=_Brush)
    brush_hardness: float = 0.5
    foreground_color: Tuple[float, float, float] = (1.0, 0.0, 0.0)
    paint_mode: PaintMode = PaintMode.Normal
    # bookkeeping
    temp_procedures: Dict[str, _BaseProcedure] = field(default_factory=dict)
    persistent_enable_called: bool = False
    main_called_with: Optional[Tuple[Any, list]] = None
    # _gp_warn machinery: tracks the current handler and every message sent.
    message_handler: MessageHandlerType = MessageHandlerType.ERROR_CONSOLE
    messages: List[str] = field(default_factory=list)
    # When True, message_set_handler returns False (simulates a host
    # rejecting the handler change so _gp_warn falls through to its
    # MESSAGE_BOX guard).
    message_set_handler_fails: bool = False


_state = _State()


def reset_state() -> None:
    global _state
    _state = _State()
    # Use a fresh per-test tempdir so the plugin's
    # _GP_PREFS_PATH = Path(Gimp.directory()) / ... never trips over stale files.
    _state.directory_path = tempfile.mkdtemp(prefix="gimp_fake_")


reset_state()  # initialize at import time


def set_state(**kwargs) -> None:
    for k, v in kwargs.items():
        if not hasattr(_state, k):
            raise AttributeError(f"unknown state field: {k}")
        setattr(_state, k, v)


def get_state() -> _State:
    return _state


# ---------------------------------------------------------------------------
# Module-level functions (Gimp.* surface)
# ---------------------------------------------------------------------------

def directory() -> str:
    return _state.directory_path


def version() -> str:
    return _state.version_str


def get_images() -> List[Image]:
    return list(_state.images)


def warning(msg: str, *args) -> None:
    # Real Gimp.warning takes a single str. The plugin sometimes passes
    # additional args (printf-style mistake) — preserve them for tests but
    # don't attempt to interpolate.
    _state.warnings.append(msg if not args else f"{msg} | extra args: {args!r}")


def message(msg: str) -> None:
    """Record a message routed through the current handler."""
    _state.messages.append(msg)


def message_get_handler() -> MessageHandlerType:
    return _state.message_handler


def message_set_handler(handler: MessageHandlerType) -> bool:
    """Set the handler. Returns True on success; tests can flip
    _state.message_set_handler_fails to exercise the failure branch."""
    if _state.message_set_handler_fails:
        return False
    _state.message_handler = handler
    return True


def context_get_brush() -> _Brush:
    return _state.brush


def context_get_brush_hardness() -> float:
    return _state.brush_hardness


def context_get_foreground():
    """Returns an object whose .get_rgba() yields a 3- or 4-element sequence
    of unit floats. Tests can override _state.foreground_color with either
    a (r,g,b) or (r,g,b,a) tuple."""
    class _Color:
        def __init__(self, rgba):
            self._rgba = rgba

        def get_rgba(self):
            return self._rgba

    return _Color(_state.foreground_color)


def context_get_paint_mode() -> PaintMode:
    return _state.paint_mode


def main(gtype, argv) -> None:
    """No-op so module import doesn't try to start the GIMP event loop."""
    _state.main_called_with = (gtype, list(argv))


# ---------------------------------------------------------------------------
# Factories used by tests
# ---------------------------------------------------------------------------

def make_layer(name: str = "Layer 1", mode: LayerMode = LayerMode.Normal,
               visible: bool = True) -> _Layer:
    return _Layer(_name=name, _mode=mode, _visible=visible)


def make_image(
    id: int = 1,  # noqa: A002 (matches GIMP API)
    name: str = "Untitled",
    layers: Optional[List[_Layer]] = None,
    selected_layers: Optional[List[_Layer]] = None,
    base_type: ImageBaseType = ImageBaseType.RGB,
    color_profile: Optional[_ColorProfile] = None,
    width: int = 1920,
    height: int = 1080,
    resolution: Tuple[bool, float, float] = (True, 72.0, 72.0),
) -> Image:
    return Image(
        _id=id,
        _name=name,
        _layers=layers or [],
        _selected_layers=selected_layers or [],
        _base_type=base_type,
        _color_profile=color_profile or _ColorProfile(),
        _width=width,
        _height=height,
        _resolution=resolution,
    )


def make_color_profile(label: str = "sRGB built-in") -> _ColorProfile:
    return _ColorProfile(_label=label)


def make_brush(name: str = "Default Brush") -> _Brush:
    return _Brush(_name=name)
