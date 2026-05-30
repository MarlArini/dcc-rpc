"""
DesignerPresence is a Discord Rich Presence client plugin for Adobe Substance 3D Designer.
DesignerPresence has been tested on Substance Designer 16.0.1 (Windows 11).
For more info, see https://github.com/MarlArini/dcc-rpc.
"""

from __future__ import annotations
import time
import logging
import atexit
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, List, Tuple, cast, Dict, Callable
import PySide6.QtGui as QtG

# pylint: disable=import-error
import sd
import sd.api
import sd.api.qtforpythonuimgrwrapper
import sd.api.sbs.sdsbscompgraph
import sd.api.sdbasetypes

# pylint: enable=import-error
from common import SharedSettings as SPSharedSettings, force_clear_on_exit
from common import QtSettingsGUIMenu, JSONSharedSettings, RPCBasePlugin
from common import plural as sp_plural

############
# Settings #
############


@dataclass
class SPSettings(SPSharedSettings, JSONSharedSettings):
    _PREFIX: ClassVar[str] = "designerPresence_"
    INFO_CHOICES: ClassVar[List[Tuple[str, str]]] = [
        ("Project name", "project"),
        ("Active node", "active_node"),
        ("Node count", "node_count"),
        ("Output node count", "out_node_count"),
        ("Export resolution", "resolution"),
        ("Material model", "material_model"),
        ("Resource count", "resource_count"),
        ("Color space", "color_space"),
    ]
    _INITIAL_DEFAULTS = {"detailsType": "project", "stateType": "node_count"}


###########
# Globals #
###########


class SPPlugin(RPCBasePlugin):
    # fmt: off
    atomic_nodes: ClassVar[frozenset] = frozenset(
        ["bitmap", "blend", "blur", "channels_shuffle",
        "curve", "directional_blur", "directional_warp", "distance",
        "emboss", "fx_map", "gradient_dynamic", "gradient_map",
        "grayscale_conversion", "hsl", "input_color", "input_grayscale",
        "levels", "normal", "output", "pixel_processor", "sharpen", "svg",
        "text", "transformation_2d", "uniform_color", "value_processor", "warp"]
    )
    # fmt: on
    display_types: ClassVar[Dict[str, Callable]] = {
        "project": lambda ctx: ctx.project_name(),
        "active_node": lambda ctx: ctx.node_name(),
        "node_count": lambda ctx: ctx.num_nodes(),
        "out_node_count": lambda ctx: ctx.num_output_nodes(),
        "resolution": lambda ctx: ctx.output_resolution(),
        "material_model": lambda ctx: ctx.material_model(),
        "resource_count": lambda ctx: ctx.resource_count(),
        "color_space": lambda ctx: ctx.color_space(),
    }
    display_cycle: ClassVar[List[str]] = list(display_types.keys())

    def __init__(self):
        self.ctx = sd.getContext()
        self.app = self.ctx.getSDApplication()
        self.uimgr = self.app.getQtForPythonUIMgr()
        self.logger = logging.getLogger("DesignerPresenceLogger")
        if not self.logger.handlers:
            self.logger.addHandler(self.ctx.createRuntimeLogHandler())
            self.logger.propagate = False
            self.logger.setLevel(logging.INFO)
        super().__init__(
            app_id="1503302572822499439",
            app_name="designer",
            prefs_class=SPSettings,
            warn=self.logger.warning,
            error=self.logger.error,
            path=self.app.getPluginMgr().getUserPluginsDir()
        )

    def start(self):
        self.session.connected = self._connect_rpc()
        self.session.start_time = time.time()
        self.reset_callback = self.app.registerAfterFileLoadedCallback(
            self.on_file_open
        )
        self.timer.start()

    def close(self):
        if self.reset_callback is not None:
            self.app.unregisterCallback(self.reset_callback)
        self.timer.stop()
        try:
            self.rpc_client.clear()
            self.rpc_client.close()
        except Exception:
            self.logger.exception(
                "[DesignerPresence] failed to clear and close client"
            )

    def _capture(self):
        return SPContext.capture()

    def on_file_open(self, *args):  # pylint: disable=unused-argument
        if self.prefs.resetTimer:
            self.session.start_time = time.time()

    def update_small_icon(self, ctx: SPContext):
        self.details.small_icon = None
        self.details.small_icon_text = ""
        if self.prefs.displaySmallIcon:
            selected_node = ctx.node_name()
            if selected_node is None:
                return
            s = selected_node.lower().replace("-", "_").replace(" ", "_")
            s = s.replace("(", "").replace(")", "")
            if s in self.atomic_nodes:
                self.details.small_icon_text = selected_node
                self.details.small_icon = s

    def update_large_icon(self, ctx):
        if self.prefs.displayVersion:
            self.details.large_icon_text = (
                f"Adobe Substance Designer {self.app.getVersion()}"
            )
        else:
            self.details.large_icon_text = "Adobe Substance Designer"


SP_PLUGIN = SPPlugin()


@dataclass
class SPContext:
    uimgr: sd.api.qtforpythonuimgrwrapper.QtForPythonUIMgrWrapper
    graph: sd.api.SDGraph
    package: sd.api.SDPackage

    @classmethod
    def capture(cls) -> "SPContext | None":
        if SP_PLUGIN.uimgr is None:
            return None
        graph = SP_PLUGIN.uimgr.getCurrentGraph()
        if graph is None:
            return None
        package = graph.getPackage()
        if package is None:
            return None
        return cls(uimgr=SP_PLUGIN.uimgr, graph=graph, package=package)

    def package_name(self) -> str:
        path = self.package.getFilePath()
        return Path(path).name if path else "Unsaved Package"

    def graph_name(self) -> str | None:
        v = self.graph.getAnnotationPropertyValueFromId("identifier")
        return (
            cast(sd.api.sdvaluestring.SDValueString, v).get() if v is not None else None
        )

    def project_name(self) -> str | None:
        package_name = self.package_name()
        graph_name = self.graph_name()
        if package_name is not None and graph_name is not None:
            return package_name + " | " + graph_name
        elif package_name is not None:
            return package_name
        elif graph_name is not None:
            return graph_name
        return None

    def node_name(self) -> str | None:
        nodes = self.uimgr.getCurrentGraphSelectedNodes()
        if nodes is None or nodes.getSize() != 1:
            return None
        definition = nodes.getItem(0).getDefinition()
        if definition is None:
            return None
        return definition.getLabel()

    def num_nodes(self) -> str:
        count = self.graph.getNodes().getSize()
        return sp_plural(count, "node")

    def num_output_nodes(self) -> str:
        count = self.graph.getOutputNodes().getSize()
        return sp_plural(count, "output node")

    def parent_size(self) -> Tuple[int, int] | None:
        if isinstance(self.graph, sd.api.sbs.sdsbscompgraph.SDSBSCompGraph):
            res = self.graph.getDefaultParentSize()
            return (res.x, res.y)
        else:
            return None

    def output_resolution(self) -> str | None:
        parent_size = self.parent_size()
        if parent_size is None:
            return None
        output_size = self.graph.getInputPropertyValueFromId("$outputsize")
        if output_size is None:
            return None
        output_size = cast(sd.api.sdbasetypes.int2, output_size)
        w = int(parent_size[0] * pow(2, output_size.x))
        h = int(parent_size[1] * pow(2, output_size.y))
        return f"{w}x{h}"

    def material_model(self) -> str | None:
        v = self.graph.getAnnotationPropertyValueFromId("material_model")
        if v is None:
            return None
        model = cast(sd.api.sdvaluestring.SDValueString, v).get()
        if model is None or model == "Undefined":
            return None
        return f"Material model: {model}"

    def resource_count(self) -> str:
        resources = self.package.getChildrenResources(True)
        count = sum(
            1
            for r in resources
            if r.getClassName() not in ("SDSBSCompGraph", "SDResourceFolder")
        )
        return sp_plural(count, "resource")

    def color_space(self) -> str | None:
        color_engine = SP_PLUGIN.app.getColorManagementEngine()
        if color_engine is None:
            return None
        return f"Color space: {color_engine.getWorkingColorSpaceName()}"


#####################
# GUI Settings Menu #
#####################

SP_STOP_ACTION: QtG.QAction | None = None
SP_START_ACTION: QtG.QAction | None = None


def sp_close_settings_menu():
    if (window := SP_PLUGIN.settings_window) is not None:
        try:
            window.close()
            window.deleteLater()
        except Exception:
            pass


def sp_open_settings_menu():
    sp_close_settings_menu()
    if (uimgr := SP_PLUGIN.uimgr) is None or (
        main_window := uimgr.getMainWindow()
    ) is None:
        return
    SP_PLUGIN.settings_window = QtSettingsGUIMenu(
        prefs=SP_PLUGIN.prefs,
        refresh_func=SP_PLUGIN.push_rpc_update,
        app_name="Designer",
        parent=main_window,
    )
    SP_PLUGIN.settings_window.show()
    SP_PLUGIN.settings_window.raise_()
    SP_PLUGIN.settings_window.activateWindow()


def sp_pause_presence():
    SP_PLUGIN.prefs.generalEnable = False
    if SP_START_ACTION is not None:
        SP_START_ACTION.setEnabled(True)
    if SP_STOP_ACTION is not None:
        SP_STOP_ACTION.setEnabled(False)


def sp_restart_presence():
    SP_PLUGIN.prefs.generalEnable = True
    if SP_START_ACTION is not None:
        SP_START_ACTION.setEnabled(False)
    if SP_STOP_ACTION is not None:
        SP_STOP_ACTION.setEnabled(True)


def sp_install_settings_menu():
    if (uimgr := SP_PLUGIN.uimgr) is None or (
        main_window := uimgr.getMainWindow()
    ) is None:
        SP_PLUGIN.logger.error("[DesignerPresence] Unable to install settings menu.")
        return
    menu_bar = main_window.menuBar()
    plugin_menu = menu_bar.addMenu("Discord")
    settings_action = plugin_menu.addAction("Settings")
    settings_action.triggered.connect(sp_open_settings_menu)
    global SP_START_ACTION, SP_STOP_ACTION
    SP_STOP_ACTION = plugin_menu.addAction("Pause Presence")
    SP_START_ACTION = plugin_menu.addAction("Restart Presence")
    SP_START_ACTION.setEnabled(False)
    SP_START_ACTION.triggered.connect(sp_restart_presence)
    SP_STOP_ACTION.triggered.connect(sp_pause_presence)
    SP_PLUGIN.menubar_item = plugin_menu


def sp_uninstall_settings_menu():
    if SP_PLUGIN.menubar_item is None:
        return
    if (uimgr := SP_PLUGIN.uimgr) is None or (
        main_window := uimgr.getMainWindow()
    ) is None:
        SP_PLUGIN.logger.error("[DesignerPresence] Unable to uninstall settings menu.")
        return
    menu_bar = main_window.menuBar()
    menu_bar.removeAction(SP_PLUGIN.menubar_item.menuAction())


###################
# Plugin Lifetime #
###################


def initializeSDPlugin():  # pylint: disable=invalid-name
    SP_PLUGIN.start()
    sp_install_settings_menu()


def uninitializeSDPlugin():  # pylint: disable=invalid-name
    sp_uninstall_settings_menu()
    SP_PLUGIN.close()


atexit.register(force_clear_on_exit, SP_PLUGIN.rpc_client)
