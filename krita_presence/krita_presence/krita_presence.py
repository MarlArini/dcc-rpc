"""
KritaPresence is a Discord Rich Presence client plugin for Krita, tested on
Krita 5.3.1 (git 9069dbc). For more info, see https://github.com/MarlArini/dcc-rpc.
"""

from dataclasses import dataclass, fields
from pathlib import Path
import re
import time
from typing import cast, ClassVar, List, Tuple, Dict, Callable, Any, get_type_hints
import xml.etree.ElementTree as ET

# pylint: disable=import-error
import PyQt5.QtGui as qg  # pyright: ignore[reportMissingImports]
import PyQt5.QtWidgets as qw  # pyright: ignore[reportMissingImports]
import PyQt5.QtCore as qc  # pyright: ignore[reportMissingImports]
import krita as kr  # pyright: ignore[reportMissingImports]
# pylint: enable=import-error

from common import (
    SharedSettings,
    RPCBasePlugin,
    ColoredIconSettings,
    plural as kp_plural,
)
from colors import find_closest as kp_find_closest_color

# Identifier for the one Krita tool we have per-color icon variants for.
# Other brush-family tools (Multibrush, Dynamic, etc.) fall back to their
# normal monochrome icon, since Discord only allows 300 total icons.
_KP_COLORIZED_TOOL = "KritaShape/KisToolBrush"


############
# Settings #
############
@dataclass
class KPSettings(SharedSettings, ColoredIconSettings):
    _PREFIX: ClassVar[str] = "kritaPresence_"
    INFO_CHOICES: ClassVar[List[Tuple[str, str]]] = [
        ("Active document name", "doc_name"),
        ("Number of documents", "doc_count"),
        ("Active layer", "layer_info"),
        ("Layers in active document", "layer_count"),
        ("Tool info", "tool_info"),
        ("Brush preset", "brush_preset"),
        ("Color profile", "color_info"),
        ("Document dimensions", "dimensions"),
        ("Layer blend mode", "layer_blend"),
        ("Total time on document", "document_time"),
    ]
    _INITIAL_DEFAULTS: ClassVar[Dict[str, Any]] = {
        "detailsType": "doc_name",
        "stateType": "layer_info",
    }

    def __init__(self):
        self._loaded = False
        super().__init__()
        self._load()
        self._loaded = True

    def _load(self):
        instance = kr.Krita.instance()
        if instance is None:
            qc.qWarning("[KritaPresence] Unable to load user settings (using defaults)")
            return
        field_types = get_type_hints(KPSettings)
        for f in fields(self):
            if v := instance.readSetting(self._PREFIX, f.name, ""):
                f_type = field_types[f.name]
                if f_type is bool:
                    v = v == "True"
                elif f_type is int:
                    v = int(v)
                object.__setattr__(self, f.name, v)
            elif f.name in self._INITIAL_DEFAULTS:
                object.__setattr__(self, f.name, self._INITIAL_DEFAULTS[f.name])

    def __setattr__(self, name: str, value: Any):
        object.__setattr__(self, name, value)
        if name.startswith("_") or not self._loaded:
            return
        declared = {f.name: f.type for f in fields(self)}
        if name not in declared:
            return
        instance = kr.Krita.instance()
        if instance is None:
            qc.qWarning(f"[KritaPresence] Unable to write user setting {name}")
            return
        instance.writeSetting(self._PREFIX, name, str(value))

    def reset(self):
        for f in fields(self):
            default = self._INITIAL_DEFAULTS.get(f.name, f.default)
            setattr(self, f.name, default)


KP_TOOL_MAPPING = {
    "KisToolTransform": "Transform Tool",
    "KisToolEncloseAndFill": "Enclose and Fill Tool",
    "KritaShape/KisToolRectangle": "Rectangle Tool",
    "KisToolSelectOutline": "Freehand Selection Tool",
    "KisToolSelectContiguous": "Contiguous Selection Tool",
    "KritaFill/KisToolGradient": "Draw Gradient Tool",
    "KisToolPolygon": "Polygon Tool",
    "KritaShape/KisToolMultiBrush": "Multibrush Tool",
    "KritaShape/KisToolEllipse": "Ellipse Tool",
    "PathTool": "Edit Shapes Tool",
    "KarbonCalligraphyTool": "Calligraphy Tool",
    "KritaShape/KisToolKnife": "Comic Panel Editing Tool",
    "KisToolSelectPath": "Bezier Curve Selection Tool",
    "KritaFill/KisToolFill": "Fill Tool",
    "KisToolSelectMagnetic": "Magnetic Curve Selection Tool",
    "PanTool": "Pan Tool",
    "KritaShape/KisToolBrush": "Freehand Brush Tool",
    "ZoomTool": "Zoom Tool",
    "KritaShape/KisToolLazyBrush": "Colorize Mask Tool",
    "KritaShape/KisToolDyna": "Dynamic Brush Tool",
    "KisToolPath": "Bezier Curve Tool",
    "KritaShape/KisToolSmartPatch": "Smart Patch Tool",
    "KritaTransform/KisToolMove": "Move Tool",
    "KisToolSelectRectangular": "Rectangular Selection Tool",
    "KisToolPolyline": "Polyline Tool",
    "KisToolCrop": "Crop Tool",
    "KisAssistantTool": "Assistant Tool",
    "KritaShape/KisToolLine": "Line Tool",
    "KisToolPencil": "Freehand Path Tool",
    "KritaShape/KisToolMeasure": "Measure Tool",
    "InteractionTool": "Select Shapes Tool",
    "KisToolSelectSimilar": "Similar Color Selection Tool",
    "KritaSelected/KisToolColorSampler": "Color Sampler Tool",
    "ToolReferenceImages": "Reference Images Tool",
    "KisToolSelectElliptical": "Elliptical Selection Tool",
    "SvgTextTool": "Text Tool",
    "KisToolSelectPolygonal": "Polygonal Selection Tool",
}


class IdleDetector(qc.QObject):
    """KritaPresence can display an approximation of total time on the active document
    using the time recorded in the file metadata by Krita as a starting point and then
    incrementing a count when the file is open during an RPC tick. We monitor ourselves
    to see if a user becomes idle so the count can stop incrementing, capturing input
    events and updating a timer."""

    def __init__(self, threshold_seconds=180):
        super().__init__()
        self._last_input = time.time()
        self._threshold = threshold_seconds

    def eventFilter(self, obj, event):  # pylint: disable=invalid-name,unused-argument
        if event.type() in (
            qc.QEvent.Type.MouseButtonPress,
            qc.QEvent.Type.KeyPress,
            qc.QEvent.Type.Wheel,
            qc.QEvent.Type.TabletPress,
        ):
            self._last_input = time.time()
        return False

    def is_idle(self) -> bool:
        return (time.time() - self._last_input) > self._threshold


@dataclass
class KPContext:
    instance: kr.Krita
    doc: kr.Document
    window: kr.Window
    view: kr.View

    @classmethod
    def capture(cls) -> "KPContext | None":
        if (instance := kr.Krita.instance()) is None:
            return None
        if (doc := instance.activeDocument()) is None:
            return None
        if (window := instance.activeWindow()) is None:
            return None
        if not (view := window.activeView()):
            return None
        return cls(instance=instance, doc=doc, window=window, view=view)

    def version(self) -> str:
        return cast(kr.Krita, self.instance).version()

    def active_document_name(self) -> str | None:
        name = cast(kr.Document, self.doc).name()
        if name is None:  # name comes from document metadata: only exists on .kra files
            name = cast(kr.Document, self.doc).fileName()  # try file name instead
            if not name:
                return None
            return Path(name).name
        if name == "Unnamed":
            return "Unsaved document"
        return f"{name}.kra"  # Document.name() does not include the .kra extension

    def num_documents(self) -> str:
        num_docs = len(cast(kr.Krita, self.instance).documents())
        return kp_plural(num_docs, "document")

    def _active_layer_name(self) -> str:
        active_node = cast(kr.Document, self.doc).activeNode()
        return active_node.name()

    def _recurse_count(self, node: kr.Node) -> int:
        children = node.childNodes()
        if len(children) == 0:
            return 1
        return 1 + sum([self._recurse_count(n) for n in children])

    def num_layers(self) -> str:
        top_level_nodes = cast(kr.Document, self.doc).topLevelNodes()
        num = sum([self._recurse_count(n) for n in top_level_nodes])
        return kp_plural(num, "layer")

    def _num_active_layer_descendants(self) -> int:
        active_node = cast(kr.Document, self.doc).activeNode()
        return self._recurse_count(active_node) - 1

    def layer_info(self) -> str:
        al_name = self._active_layer_name()
        al_descendants = self._num_active_layer_descendants()
        if al_descendants == 0:
            if "layer" in al_name.lower():
                return al_name
            return f"Layer: {al_name}"
        return f"{al_name} ({kp_plural(al_descendants, 'sublayer')})"

    # From KnowZero on the Krita Forums: https://krita-artists.org/t/active-tool-request/78904
    def active_tool_name(self) -> str | None:
        qdock = next(
            (
                w
                for w in cast(kr.Krita, self.instance).dockers()
                if w.objectName() == "ToolBox"
            ),
            None,
        )
        if qdock is None:
            return None
        wobj = cast(qw.QDockWidget, qdock).findChild(qw.QButtonGroup)
        if wobj is None:
            return None
        btn = wobj.checkedButton()
        if btn is None:
            return None
        return btn.objectName()

    def active_brush_preset(self) -> str | None:
        preset = cast(kr.View, self.view).currentBrushPreset()
        if preset is None:
            return None
        tool = self.active_tool_name()
        if tool not in [
            "KritaShape/KisToolMultiBrush",
            "KritaShape/KisToolBrush",
            "KritaShape/KisToolDyna",
        ]:
            return None
        preset = preset.name().strip()
        default_pattern = re.compile(r"^[a-z]\)")
        if default_pattern.match(preset) is not None:
            preset = preset[2:]
        preset = preset.replace("(mypaint)_prev", "")
        preset = preset.replace("(mypaint)", " ").strip()
        return f"Preset: {preset}"

    def _color_model(self) -> str:
        return cast(kr.Document, self.doc).colorModel()

    def _color_profile(self) -> str:
        return cast(kr.Document, self.doc).colorProfile()

    def color_info(self) -> str:
        return f"{self._color_model()} ({self._color_profile()})"

    def _active_document_dimensions(self) -> Tuple[int, int]:
        w = cast(kr.Document, self.doc).width()
        h = cast(kr.Document, self.doc).height()
        return (w, h)

    def _active_document_resolution(self) -> int:
        return cast(kr.Document, self.doc).resolution()

    def active_document_dimensions(self) -> str:
        dims = self._active_document_dimensions()
        res = self._active_document_resolution()
        return f"{dims[0]}x{dims[1]} @ {res}dpi"

    def foreground_color(self) -> Tuple[int, int, int] | None:
        color = cast(kr.View, self.view).foregroundColor()
        canvas = cast(kr.View, self.view).canvas()
        if canvas is None:
            return None
        if color is None:
            return None
        color_canv = cast(qg.QColor, color.colorForCanvas(canvas))
        return (color_canv.red(), color_canv.green(), color_canv.blue())

    def view_blend_mode(self) -> str:
        return cast(kr.View, self.view).currentBlendingMode()

    def tool_info(self) -> str | None:
        name = self.active_tool_name()
        if name is None:
            return None
        tool_name = KP_TOOL_MAPPING.get(name, None)
        tool_blend_mode = self.view_blend_mode()
        if tool_blend_mode.lower() != "normal":
            return f"{tool_name} ({tool_blend_mode})"
        return tool_name

    def layer_blend_mode(self) -> str | None:
        active_node = cast(kr.Document, self.doc).activeNode()
        mode = active_node.blendingMode()
        if mode.lower() == "normal":
            return None
        return f"Layer blend mode: {mode}"


class KPPlugin(RPCBasePlugin):
    display_types: ClassVar[Dict[str, Callable]] = {
        "doc_name": lambda ctx: ctx.active_document_name(),
        "doc_count": lambda ctx: ctx.num_documents(),
        "layer_info": lambda ctx: ctx.layer_info(),
        "layer_count": lambda ctx: ctx.num_layers(),
        "tool_info": lambda ctx: ctx.tool_info(),
        "brush_preset": lambda ctx: ctx.active_brush_preset(),
        "color_info": lambda ctx: ctx.color_info(),
        "dimensions": lambda ctx: ctx.active_document_dimensions(),
        "layer_blend": lambda ctx: ctx.layer_blend_mode(),
        "document_time": lambda ctx: KPPlugin.doc_time(ctx),  # pylint: disable=unnecessary-lambda
    }
    display_cycle: ClassVar[List[str]] = list(display_types.keys())
    doc_times: ClassVar[Dict[int, int]] = {}
    idle_monitor = IdleDetector()

    @staticmethod
    def doc_time(ctx: KPContext):
        """Check the internal document-time map for how long a document was open
        and for whether the user is idle."""
        t = KPPlugin.doc_times.get(id(ctx.doc), None)
        if t is None:
            return None
        t_conv = (t // 3600, (t % 3600) // 60)
        t_formatted = f"{t_conv[0]}h {t_conv[1]}m" if t_conv[0] else (f"{t_conv[1]}m")
        if KPPlugin.idle_monitor.is_idle():
            return f"Document time: {t_formatted} (Idle)"
        return f"Document time: {t_formatted}"

    def __init__(self):
        super().__init__(
            app_id="1507476862740336650",
            app_name="krita",
            prefs_class=KPSettings,
            warn=qc.qWarning,
            error=qc.qCritical,
        )

    def start(self):
        self.session.connected = self._connect_rpc()
        self.session.start_time = time.time()
        if (instance := kr.Krita.instance()) is not None:
            if (notifier := instance.notifier()) is not None:
                notifier.imageCreated.connect(self._on_file_open)
        if (app := qw.QApplication.instance()) is not None:
            app.installEventFilter(self.idle_monitor)
        self.timer.start()

    def close(self):
        self.timer.stop()
        if (app := qw.QApplication.instance()) is not None:
            app.removeEventFilter(self.idle_monitor)
        try:
            self.rpc_client.clear()
            self.rpc_client.close()
        except Exception as e:
            qc.qCritical(f"[KritaPresence] failed to clear and close client: {e}")

    def _capture(self):
        return KPContext.capture()

    def _on_file_open(self, doc):  # pylint:disable=unused-argument
        if self.prefs.resetTimer:
            self.session.start_time = time.time()
        doc_xml = cast(kr.Document, doc).documentInfo()
        doc_time = ET.fromstring(doc_xml)[0].find(
            "{http://www.calligra.org/DTD/document-info}editing-time"
        )
        if doc_time is None or doc_time.text is None:
            self.doc_times[id(doc)] = 0
        else:
            try:
                self.doc_times[id(doc)] = int(doc_time.text)
            except ValueError, TypeError:
                self.doc_times[id(doc)] = 0

    def update_small_icon(self, ctx: KPContext):  # pylint: disable=unused-argument
        self.details.small_icon = None
        self.details.small_icon_text = ""
        if not self.prefs.displaySmallIcon:
            return
        tool = ctx.active_tool_name()
        if tool is None or tool not in KP_TOOL_MAPPING:
            return
        # Default: monochrome tool icon + tool-name hover.
        self.details.small_icon = tool.lower().replace("/", "_")
        self.details.small_icon_text = KP_TOOL_MAPPING[tool]
        # If enabled, color the paint brush
        if tool == _KP_COLORIZED_TOOL and self.prefs.enableColoredIcons:
            rgb = ctx.foreground_color()
            if rgb is not None:
                match = kp_find_closest_color(rgb, self.prefs.useEvocativeNames)
                self.details.small_icon = f"kbrush_{match.icon_key_suffix}"
                self.details.small_icon_text = (
                    f"Painting in {match.display_name} ({match.user_hex})"
                )

    def update_large_icon(self, ctx: KPContext):
        if self.prefs.displayVersion:
            self.details.large_icon_text = f"Krita {ctx.version()}"
        else:
            self.details.large_icon_text = "Krita"

    def update_presence(self):
        instance = kr.Krita.instance()
        if instance is not None:
            doc = instance.activeDocument()
            if doc is not None and not self.idle_monitor.is_idle():
                if id(doc) in self.doc_times:
                    self.doc_times[id(doc)] += self.prefs.generalUpdate
                else:
                    self.doc_times[id(doc)] = self.prefs.generalUpdate
        return super().update_presence()


class KPExtension(kr.Extension):
    def __init__(self, parent):
        super().__init__(parent)
        self._plugin = KPPlugin()

    def setup(self):
        self._plugin.start()
        instance = kr.Krita.instance()
        if instance is None:
            return
        notifier = instance.notifier()
        if notifier is None:
            return
        notifier.applicationClosing.connect(self._plugin.close)
        notifier.setActive(True)

    def close_settings_menu(self):
        if (window := self._plugin.settings_window) is not None:
            try:
                window.close()
                window.deleteLater()
            except Exception:
                pass

    def open_settings_menu(self):
        self.close_settings_menu()
        instance = kr.Krita.instance()
        if instance is None:
            return
        window = instance.activeWindow()
        if window is None:
            return
        qwindow = window.qwindow()
        self._plugin.make_qt_window("Krita", qwindow)
        if self._plugin.settings_window:
            self._plugin.settings_window.show()
            self._plugin.settings_window.raise_()
            self._plugin.settings_window.activateWindow()

    def createActions(self, window):  # pylint: disable=invalid-name
        if window is None:
            return
        action = window.createAction(
            "krpresence_open_settings", "KritaPresence Settings", "tools/scripts"
        )
        if action is None:
            return
        action.triggered.connect(self.open_settings_menu)


_instance = kr.Krita.instance()
if _instance is not None:
    _instance.addExtension(KPExtension(_instance))
