"""
Common functionality for all application plugins related to rich presence updates,
render callbacks, and GUI construction.

This module is split into two sections:

  1. Host-agnostic utilities + dataclasses — always available; no Qt binding 
  requirements

  2. Qt-bound classes: `QtSettingsGUIMenu`, `JSONSharedSettings`, `RPCTimer`, 
  and `RPCBasePlugin`. Hosts with no Qt binding get `None` for these names.

`QT_BINDING` exposes the string name of the detected binding ("PySide6", "PyQt5",
"PySide2", or None).
"""

from __future__ import annotations
import json
import os
import re
import time
from typing import List, Dict, Any, ClassVar, Callable, get_type_hints
from dataclasses import dataclass, field, fields, Field
from abc import abstractmethod, ABC
from pypresence.presence import Presence
from pypresence import exceptions

# Qt binding detection
QtCore: Any = None
QtWidgets: Any = None
QT_BINDING: str | None = None
for _binding in ("PySide6", "PyQt5", "PySide2"):
    try:
        _qt_core = __import__(f"{_binding}.QtCore", fromlist=["QtCore"])
        _qt_widgets = __import__(f"{_binding}.QtWidgets", fromlist=["QtWidgets"])
    except ImportError:
        continue
    QtCore = _qt_core
    QtWidgets = _qt_widgets
    QT_BINDING = _binding
    break


# ===========================================================================
# Host-agnostic utilities
# ===========================================================================


def plural(count: int, prefix: str, postfix: str = "s") -> str:
    if count == 1:
        return f"{count} {prefix}"
    return f"{count} {prefix}{postfix}"


def is_url(s: str) -> bool:
    """Evaluate a string and return True if it is a valid URL (may miss some edge cases)"""
    regex = re.compile(
        r"^https?://"  # http:// or https://
        r"(?:[a-zA-Z0-9-]+\.)+"  # subdomain(s)
        r"[a-zA-Z]{2,}"  # top-level domain
        r"(?:\:\d{1,5})?"  # optional port
        r"(?:/[^\s]*)?$",  # optional path
        re.IGNORECASE,
    )
    return regex.match(s) is not None


def pad_text(s: str) -> str:
    """
    If the user string is more than one character, return it. Else,
    return a length-2 empty string to satisfy Discord's requirement.
    """
    s = str(s)
    return s if len(s) > 1 else "  "


def shorten_number(n: int) -> str:
    if n < 1_000:
        return str(n)
    elif n < 1_000_000:
        return f"{n // 1_000}k"
    elif n < 1_000_000_000:
        return f"{n // 1_000_000}m"
    else:
        return f"{n // 1_000_000_000}b"


def get_file_size_str(b: float) -> str:
    """
    Convert bytes to a readable string. Taken directly from
    https://github.com/abrasic/blendpresence
    """
    for u in [" bytes", " KB", " MB", " GB", " TB"]:
        if b < 1024.0 or u == " PB":
            break
        b /= 1024.0
    return f"{b:.2f} {u}"


class RPCUpdateDetails:
    """Class to hold data for each parameter of the RPC update"""

    def __init__(self, app_icon_name):
        self.start_time: float = time.time()
        self.state_text: str = ""
        self.details_text: str = ""
        self.small_icon: str | None = None
        self.small_icon_text: str = ""
        self.large_icon: str = app_icon_name
        self.large_icon_text: str = ""
        self.buttons: List[Dict] = []


class SessionInfo:
    start_time: float = time.time()
    connected: bool = False
    is_rendering: bool = False
    rendered_frames: int = 0
    cycle_iter: int = 0


def rpc_update(details, client, enable_time):
    """Send an update to the RPC client. May raise exceptions which must be handled."""
    client.update(
        start=details.start_time if enable_time else None,
        state=details.state_text,
        details=details.details_text if details.details_text else "  ",
        small_image=details.small_icon,
        small_text=details.small_icon_text if details.small_icon_text else None,
        large_image=details.large_icon,
        large_text=details.large_icon_text if details.large_icon_text else None,
        buttons=details.buttons if details.buttons else None,
    )


def force_clear_on_exit(client):
    try:
        client.clear()
        client.close()
    except BaseException:
        pass


def update_buttons(details, prefs):
    """Check validity of user buttons, if enabled, and update the RPC details."""
    details.buttons = []
    if is_url(prefs.button1Url) and prefs.button1Label and prefs.enableButton1:
        details.buttons.append({"label": prefs.button1Label, "url": prefs.button1Url})
    if is_url(prefs.button2Url) and prefs.button2Label and prefs.enableButton2:
        details.buttons.append({"label": prefs.button2Label, "url": prefs.button2Url})


def on_render_start(info: SessionInfo, prefs):
    info.is_rendering = True
    if prefs.resetTimer:
        info.start_time = time.time()


def on_render_end(info: SessionInfo, prefs):
    info.is_rendering = False
    info.rendered_frames = 0
    if prefs.resetTimer:
        info.start_time = time.time()


def on_frame_render_end(info: SessionInfo):
    info.rendered_frames += 1


def connect_rpc(client: Presence, app_name: str, error: Callable = print):
    try:
        client.connect()
        return True
    except Exception as e:
        error(f"[{app_name.capitalize()}Presence] Connection Error: {e}")
        return False


def push_rpc_update(
    session: SessionInfo,
    details: RPCUpdateDetails,
    prefs: SharedSettings,
    client: Presence,
    app_name: str,
    error: Callable = print,
):
    if session.connected:
        try:
            rpc_update(details, client, prefs.enableTime)
        except (
            exceptions.InvalidID,
            AssertionError,
            exceptions.PipeClosed,
            exceptions.DiscordNotFound,
        ) as e:
            session.connected = False
            error(f"[{app_name.capitalize()}Presence] RPC Connection Lost: {e}")
            session.connected = connect_rpc(client, app_name, error)
        except exceptions.ServerError as e:
            error(f"[{app_name.capitalize()}Presence] ServerError: {e}")
    else:
        error(f"[{app_name.capitalize()}Presence] Retrying...")
        session.connected = connect_rpc(client, app_name, error)


def advance_cycle(session: SessionInfo, display_types: Dict):
    session.cycle_iter += 1
    session.cycle_iter = session.cycle_iter % len(display_types)


_SLOT_PEER = {"state": "details", "details": "state"}
_SLOT_OFFSET = {"state": 0, "details": 1}


def update_slot(
    ctx,
    slot: str,
    prefs: SharedSettings,
    details: RPCUpdateDetails,
    display_types: Dict[str, Callable],
    session: SessionInfo,
) -> None:
    peer = _SLOT_PEER[slot]
    text_attr = f"{slot}_text"
    setattr(details, text_attr, "")

    if not getattr(prefs, f"enable{slot.capitalize()}"):
        return
    custom = getattr(prefs, f"custom{slot.capitalize()}")
    if custom:
        setattr(details, text_attr, pad_text(custom))
        return

    cycling = getattr(prefs, f"{slot}Cycle")
    peer_cycling = getattr(prefs, f"{peer}Cycle")
    peer_fixed = getattr(prefs, f"{peer}Type")
    fixed = getattr(prefs, f"{slot}Type")

    if cycling:
        text = pick_cycling(
            ctx, peer_cycling, peer_fixed, _SLOT_OFFSET[slot], display_types, session
        )
    else:
        text = pick_fixed(ctx, fixed, display_types)

    text = pad_text(text)
    setattr(details, text_attr, text)


def pick_fixed(ctx, kind: str, display_types: Dict[str, Callable]) -> str:
    fn = display_types.get(kind)
    if fn is None:
        return ""
    value = fn(ctx)
    return str(value) if value not in (None, "") else ""


def pick_cycling(
    ctx,
    peer_cycling: bool,
    peer_fixed: str,
    offset: int,
    display_types: Dict[str, Callable],
    session: SessionInfo,
) -> str:
    display_cycle = list(display_types)
    n = len(display_cycle)
    start = (session.cycle_iter + offset) % n
    # Skip the slot occupied by a fixed peer.
    if not peer_cycling:
        skip = peer_fixed
    else:
        skip = None
    for i in range(n):
        idx = (start + i) % n
        kind = display_cycle[idx]
        if kind == skip:
            continue
        value = display_types[kind](ctx)
        if value not in (None, ""):
            return str(value)
    return ""  # nothing meaningful in the entire cycle


@dataclass
class SharedSettings(ABC):
    """
    Base class for user settings for all plugins. Fields with metadata allow dynamic
    construction of the settings GUI for each application. Specific applications should
    inherit from this to implement settings persistence across sessions and to add
    additional fields.
    """

    # pylint: disable=invalid-name
    generalEnable: bool = field(
        default=True, metadata={"group": "General", "label": "Enable RPC Updates"}
    )
    generalUpdate: int = field(
        default=12,
        metadata={
            "group": "General",
            "label": "Update interval",
            "min": 12,
            "max": 60,
            "suffix": "s",
        },
    )
    enableTime: bool = field(
        default=True, metadata={"group": "General", "label": "Show elapsed time"}
    )
    resetTimer: bool = field(
        default=True,
        metadata={"group": "General", "label": "Reset timer when a new file is opened"},
    )
    displayVersion: bool = field(
        default=True,
        metadata={
            "group": "Icons",
            "label": "Display application version on large icon hover",
        },
    )
    displaySmallIcon: bool = field(
        default=True,
        metadata={
            "group": "Icons",
            "label": "Display a small icon for specific contexts",
        },
    )
    enableDetails: bool = field(
        default=True,
        metadata={
            "group": "Details",
            "label": "Enable details field",
            "group_master": True,
        },
    )
    detailsType: str = field(
        default="scene",
        metadata={
            "group": "Details",
            "label": "Detail type to display",
            "widget": "combobox",
            "choices_attr": "INFO_CHOICES",
        },
    )
    customDetails: str = field(
        default="",
        metadata={"group": "Details", "label": "Custom text for details field"},
    )
    detailsCycle: bool = field(
        default=False, metadata={"group": "Details", "label": "Cycle displayed details"}
    )
    enableState: bool = field(
        default=True,
        metadata={
            "group": "State",
            "label": "Enable state field",
            "group_master": True,
        },
    )
    stateType: str = field(
        default="scene",
        metadata={
            "group": "State",
            "label": "State type to display",
            "widget": "combobox",
            "choices_attr": "INFO_CHOICES",
        },
    )
    customState: str = field(
        default="", metadata={"group": "State", "label": "Custom text for state field"}
    )
    stateCycle: bool = field(
        default=False, metadata={"group": "State", "label": "Cycle displayed state"}
    )
    enableButton1: bool = field(
        default=False,
        metadata={
            "group": "Buttons",
            "label": "Enable Button 1",
            "controls": ["button1Label", "button1Url"],
        },
    )
    button1Label: str = field(
        default="", metadata={"group": "Buttons", "label": "Custom label for button 1"}
    )
    button1Url: str = field(
        default="", metadata={"group": "Buttons", "label": "URL for button 1"}
    )
    enableButton2: bool = field(
        default=False,
        metadata={
            "group": "Buttons",
            "label": "Enable Button 2",
            "controls": ["button2Label", "button2Url"],
        },
    )
    button2Label: str = field(
        default="", metadata={"group": "Buttons", "label": "Custom label for button 2"}
    )
    button2Url: str = field(
        default="", metadata={"group": "Buttons", "label": "URL for button 2"}
    )
    _INITIAL_DEFAULTS: ClassVar[Dict[str, Any]] = {}

    def __post_init__(self):
        for k, v in self._INITIAL_DEFAULTS.items():
            self.__setattr__(k, v)


@dataclass
class ColoredIconSettings:
    # pylint: disable=invalid-name
    enableColoredIcons: bool = field(
        default=True,
        metadata={"group": "Icons", "label": "Use colored icons (when supported)"},
    )
    useEvocativeNames: bool = field(
        default=True,
        metadata={
            "group": "Icons",
            "label": ("Use vibrant color names in small icon text"),
        },
    )


# ===========================================================================
# Qt-bound classes
# ===========================================================================

if QtCore is not None:

    class QtSettingsGUIMenu(QtWidgets.QDialog):
        def __init__(self, prefs, refresh_func, app_name, parent=None):
            super(QtSettingsGUIMenu, self).__init__(parent=parent)
            self.setObjectName(f"{app_name}PresenceSettingsDialog")
            self.setWindowTitle(f"{app_name} Presence — Settings")
            self.setWindowFlags(
                self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint
            )
            self.resize(400, 640)
            self.setMinimumWidth(400)
            self._boxes = []
            self._gui_widgets = {}
            self._prefs = prefs
            self._app_name = app_name
            self._refresh = refresh_func
            self._timer = QtCore.QTimer(singleShot=True, interval=1000)
            self._timer.timeout.connect(self._refresh)
            self._groups = self._build_groups()
            self._build()
            self._controllers = self._build_controller_dict()
            self._refresh_enabled_states()
            self._building = False
            self._assemble()

        _default_widgets = {bool: "checkbox", int: "spinbox", str: "lineedit"}

        def _widget_kind(self, f: Field):
            resolved = get_type_hints(type(self._prefs))[f.name]
            return f.metadata.get("widget") or self._default_widgets[resolved]

        def _build_groups(self):
            groups = {}
            for f in fields(self._prefs):
                group = f.metadata.get("group")
                if group is None:
                    continue
                groups.setdefault(group, []).append(f)
            return groups

        def _build(self):
            builders = {
                "checkbox": self._build_checkbox,
                "spinbox": self._build_spinbox,
                "lineedit": self._build_lineedit,
                "combobox": self._build_combobox,
            }
            for group_name, group_fields in self._groups.items():
                box = QtWidgets.QGroupBox(group_name)
                form = QtWidgets.QFormLayout(box)
                for f in group_fields:
                    qt_item = builders[self._widget_kind(f)](f, form)
                    self._gui_widgets[f.name] = qt_item
                self._boxes.append(box)

        def _build_checkbox(self, f: Field, form: QtWidgets.QFormLayout):
            qt_item = QtWidgets.QCheckBox(f.metadata["label"])
            qt_item.setChecked(getattr(self._prefs, f.name))
            qt_item.toggled.connect(lambda v, name=f.name: self._set(name, v))
            form.addRow(qt_item)
            return qt_item

        def _build_spinbox(self, f: Field, form: QtWidgets.QFormLayout):
            qt_item = QtWidgets.QSpinBox()
            qt_item.setRange(f.metadata["min"], f.metadata["max"])
            qt_item.setSuffix(f.metadata["suffix"])
            qt_item.setValue(getattr(self._prefs, f.name))
            qt_item.valueChanged.connect(lambda v, name=f.name: self._set(name, v))
            form.addRow(f.metadata["label"], qt_item)
            qt_item.setMaximumWidth(80)
            qt_item.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Preferred,
                QtWidgets.QSizePolicy.Policy.Preferred,
            )
            return qt_item

        def _build_lineedit(self, f: Field, form: QtWidgets.QFormLayout):
            qt_item = QtWidgets.QLineEdit()
            qt_item.setText(getattr(self._prefs, f.name))
            qt_item.editingFinished.connect(
                lambda w=qt_item, name=f.name: self._set(name, w.text())
            )
            form.addRow(f.metadata["label"], qt_item)
            return qt_item

        def _build_combobox(self, f: Field, form: QtWidgets.QFormLayout):  # pylint: disable=unused-argument
            qt_item = QtWidgets.QComboBox()
            choices = getattr(self._prefs, f.metadata["choices_attr"])
            for label, key in choices:
                qt_item.addItem(label, key)
            current = getattr(self._prefs, f.name)
            idx = qt_item.findData(current)
            qt_item.setCurrentIndex(idx if idx >= 0 else 0)
            # currentIndexChanged emits an int; absorb it explicitly so the default-bound
            # `w` keeps pointing at the widget rather than getting shadowed by the int.
            qt_item.currentIndexChanged.connect(
                lambda _i, w=qt_item, name=f.name: self._set(name, w.currentData())
            )
            form.addRow(f.metadata["label"], qt_item)
            return qt_item

        def _build_controller_dict(self):
            controllers = {}
            for f in fields(self._prefs):
                if "group_master" in f.metadata:
                    f_group_name = f.metadata["group"]
                    subitems = [
                        f_.name for f_ in self._groups[f_group_name] if f_.name != f.name
                    ]
                    controllers[f.name] = subitems
                elif "controls" in f.metadata:
                    controllers[f.name] = f.metadata["controls"]
            return controllers

        def _assemble(self):
            root = QtWidgets.QVBoxLayout(self)
            root.setContentsMargins(10, 10, 10, 10)
            root.setSpacing(8)

            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            root.addWidget(scroll, 1)

            container = QtWidgets.QWidget()
            scroll.setWidget(container)
            col = QtWidgets.QVBoxLayout(container)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(10)

            for box in self._boxes:
                col.addWidget(box)
            col.addStretch(1)

            # Bottom bar
            bottom_bar = QtWidgets.QHBoxLayout()
            bottom_bar.addStretch(1)
            reset_btn = QtWidgets.QPushButton("Reset to defaults")
            reset_btn.clicked.connect(self._on_reset_clicked)
            close_btn = QtWidgets.QPushButton("Close")
            close_btn.clicked.connect(self.accept)
            bottom_bar.addWidget(reset_btn)
            bottom_bar.addWidget(close_btn)
            root.addLayout(bottom_bar)

        def _set(self, key, value):
            if self._building:
                return
            setattr(self._prefs, key, value)
            # Gray out / un-gray children immediately; debounce the RPC refresh so a flurry
            # of edits (e.g., spinbox keystrokes) doesn't push a presence update per keypress.
            self._refresh_enabled_states()
            self._timer.start()

        def _on_reset_clicked(self):
            confirm = QtWidgets.QMessageBox.question(
                self,
                "Reset settings",
                f"Reset all {self._app_name} Presence settings to their defaults?",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
                return
            if hasattr(self._prefs, "reset"):
                self._prefs.reset()
            self._building = True
            self._load_from_prefs()
            self._building = False
            self._refresh()

        def _load_from_prefs(self):
            for f in fields(self._prefs):
                if f.metadata.get("group") is None:
                    continue
                attr = getattr(self._prefs, f.name)
                widget_type = self._widget_kind(f)
                if widget_type == "checkbox":
                    self._gui_widgets[f.name].setChecked(attr)
                elif widget_type == "spinbox":
                    self._gui_widgets[f.name].setValue(attr)
                elif widget_type == "lineedit":
                    self._gui_widgets[f.name].setText(attr)
                elif widget_type == "combobox":
                    widget = self._gui_widgets[f.name]
                    idx = widget.findData(attr)
                    widget.setCurrentIndex(idx if idx >= 0 else 0)
            self._refresh_enabled_states()

        def _refresh_enabled_states(self):
            for controller_name, controlled_items in self._controllers.items():
                enabled = getattr(self._prefs, controller_name)
                for controlled_item_name in controlled_items:
                    self._gui_widgets[controlled_item_name].setEnabled(enabled)


    @dataclass
    class JSONSharedSettings:
        """JSON-backed settings with debounced writes via a QTimer.

        Qt-bound: the debounce uses `QtCore.QTimer`. Hosts without a Qt binding
        should not use this class — they need to wire persistence to their own
        host scheduler (GIMP: GLib.timeout_add; C4D: BaseContainer + custom
        write hook). The GIMP plug-in does its own JSON I/O via the settings
        dialog procedure and intentionally does NOT inherit from this class.
        """
        __dataclass_fields__: ClassVar[dict[str, Any]]
        _INITIAL_DEFAULTS: ClassVar[Dict[str, Any]]
        _path: str = ""
        _warn: Callable[[str], None] = print
        _timer: QtCore.QTimer | None = None
        _loaded: bool = False
        _app_name: str = ""
        _refresh_func: Callable | None = None
        _prev_interval: int | None = None

        def setup_persistence(self, path, app_name, warn=print, refresh_func = None):
            self._path = path
            self._app_name = app_name
            self._warn = warn
            self._timer = QtCore.QTimer(singleShot=True, interval=2000)
            self._timer.timeout.connect(self._write)
            self._load()
            self._loaded = True
            self._prev_interval = getattr(self, 'generalUpdate', None)
            self._refresh_func = refresh_func

        def _load_warn(self, key="", default: Any = None):
            if not key:
                self._warn(
                    f"[{self._app_name.capitalize()}Presence] Error loading preferences: "
                    "falling back to default settings"
                )
            else:
                self._warn(
                    f"[{self._app_name.capitalize()}Presence] Unable to find key {key} in"
                    f" preferences (using default value of {str(default)})"
                )

        def _get_default(self, f: Field[Any]):
            if f.name in self._INITIAL_DEFAULTS:
                return self._INITIAL_DEFAULTS[f.name]
            else:
                return f.default

        def _load(self):
            if not self._path:
                self._load_warn()
                return
            try:
                with open(self._path, "r", encoding="utf-8") as prefs_fp:
                    prefs_json = json.load(prefs_fp)
            except (OSError, json.JSONDecodeError):
                self._load_warn()
                return
            for f in fields(self):
                if f.name.startswith("_"):
                    continue
                try:
                    v = prefs_json[f.name]
                    object.__setattr__(self, f.name, v)
                except KeyError:
                    self._load_warn(f.name, self._get_default(f))

        def _write(self, *_):
            if ( # Debounce interval changes to not spam Discord with rpc updates
                update := getattr(self, 'generalUpdate', None)
            ) != self._prev_interval and self._refresh_func is not None:
                self._prev_interval = update
                self._refresh_func()
            try:
                with open(self._path, "w", encoding="utf-8") as prefs_fp:
                    json.dump(
                        {
                            f.name: getattr(self, f.name)
                            for f in fields(self)
                            if not f.name.startswith("_")
                        },
                        prefs_fp,
                        indent=2,
                    )
            except (OSError, TypeError) as e:
                self._warn(
                    f"[{self._app_name.capitalize()}Presence] Error writing"
                    f"new plugin preference: {e}"
                )

        def __setattr__(self, name: str, value: Any) -> None:
            object.__setattr__(self, name, value)
            if name.startswith("_") or not self._loaded:
                return
            if self._timer is not None:
                self._timer.start()

        def flush(self):
            """Write any pending change to disk synchronously, bypassing the
            debounce. Call after a user-explicit action (menu toggle, etc.)
            that should persist immediately rather than risk being lost to
            a fast app close."""
            if self._timer is not None:
                self._timer.stop()
            self._write()

        def reset(self):
            """Restore all fields to default values"""
            for f in fields(self):
                if not f.name.startswith("_"):
                    setattr(self, f.name, self._get_default(f))


    class RPCTimer(QtCore.QObject):
        def __init__(self, prefs, update_presence_func):
            super().__init__()
            self._timer = QtCore.QTimer()
            self._prefs = prefs
            self._timer.timeout.connect(update_presence_func)

        def start(self):
            self._timer.start(self._prefs.generalUpdate * 1000)  # ms

        def stop(self):
            self._timer.stop()

        def refresh(self):
            if self._timer.isActive():
                self._timer.setInterval(self._prefs.generalUpdate * 1000)


    class RPCBasePlugin(ABC):
        display_types: ClassVar[Dict[str, Callable]] = {}

        def __init__(self, app_id, app_name, prefs_class, warn, error, path=""):
            self.rpc_client = Presence(app_id)
            self.session = SessionInfo()
            self.details = RPCUpdateDetails(app_name)
            self.active = False
            self.settings_window: QtSettingsGUIMenu | None = None
            self.prefs = prefs_class()
            self.timer = RPCTimer(self.prefs, self.update_presence)
            if isinstance(self.prefs, JSONSharedSettings):
                if not path:
                    raise ValueError("RPCBasePlugin with JSONSharedSettings needs a path")
                self.prefs.setup_persistence(
                    path=os.path.join(path, f"{app_name}_presence_settings.json"),
                    app_name=app_name,
                    warn=warn,
                    refresh_func=self.update_presence
                )
            self.menubar_item: QtWidgets.QMenu | None = None
            self.reset_callback: int | None = None
            self._app_name = app_name
            self._warn = warn
            self._error = error

        def _connect_rpc(self):
            return connect_rpc(self.rpc_client, self._app_name, self._error)

        def push_rpc_update(self, *args):  # pylint: disable=unused-argument
            push_rpc_update(
                self.session,
                self.details,
                self.prefs,
                self.rpc_client,
                self._app_name,
                self._error,
            )

        def _advance_cycle(self):
            advance_cycle(self.session, self.display_types)

        @abstractmethod
        def _capture(self) -> Any | None:
            ... # pragma: no cover

        @abstractmethod
        def start(self):
            ... # pragma: no cover

        @abstractmethod
        def close(self):
            ... # pragma: no cover

        @abstractmethod
        def update_small_icon(self, ctx):
            ... # pragma: no cover

        @abstractmethod
        def update_large_icon(self, ctx):
            ... # pragma: no cover

        def update_details(self, ctx):
            update_slot(
                ctx, "details", self.prefs, self.details, self.display_types, self.session
            )

        def update_state(self, ctx):
            update_slot(
                ctx, "state", self.prefs, self.details, self.display_types, self.session
            )

        def update_presence(self):
            if not self.prefs.generalEnable:
                if self.session.connected:
                    try:
                        self.rpc_client.clear()
                    except Exception as e:  # noqa: BLE001
                        self._error(
                            f"[{self._app_name.capitalize()}Presence] "
                            f"clear failed: {e}"
                        )
                        self.session.connected = False
                return

            ctx = self._capture()
            if ctx is None:
                self._warn(
                    f"[{self._app_name.capitalize()}Presence] Unable to get application context"
                )
                # No project open; show idle state.
                self.details.state_text = "No project open"
                self.details.details_text = ""
                self.details.small_icon = None
                self.push_rpc_update()
                return
            if self.prefs.detailsCycle or self.prefs.stateCycle:
                self._advance_cycle()
            self.update_small_icon(ctx)
            self.update_large_icon(ctx)
            self.update_state(ctx)
            self.update_details(ctx)
            update_buttons(self.details, self.prefs)
            self.push_rpc_update()

else:
    # Stub assignments so `from common import RPCBasePlugin` still resolves on
    # hosts without a Qt binding.
    QtSettingsGUIMenu = None  # type: ignore[assignment]
    JSONSharedSettings = None  # type: ignore[assignment]
    RPCTimer = None  # type: ignore[assignment]
    RPCBasePlugin = None  # type: ignore[assignment]
