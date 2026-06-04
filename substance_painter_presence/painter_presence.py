"""
PainterPresence is a Discord Rich Presence client plugin for Adobe Substance 3D Painter.
PainterPresence has been tested on Substance Painter 12.0.3 (Windows 11).
For more info, see https://github.com/MarlArini/dcc-rpc.
"""

import atexit
from dataclasses import dataclass, field
import os
import time
from typing import Any, Callable, ClassVar, Dict, List, Tuple
import PySide6.QtGui as QtG
import PySide6.QtWidgets as QtW
import substance_painter as sp  # pylint: disable=import-error

from common import (
    SharedSettings,
    JSONSharedSettings,
    ColoredIconSettings,
    RPCBasePlugin,
    force_clear_on_exit,
    plural as sp_plural,
)
from colors import (
    find_closest,
    SUBSTANCEPAINTER_PAINT_SUBSET,
    SUBSTANCEPAINTER_PHYSPAINT_SUBSET,
)

# Paint / Physical paint action objectName() values (always English) for
# checking if the current tool's icon should be colored
_SP_PAINT_NAME = "Paint"
_SP_PHYSPAINT_NAME = "Paint_Physics"

# Map Painter tool -> (icon-key prefix, palette subset for closest-color icon
# lookup). The subset partitions the 250-entry palette into 125 evens (Paint)
# + 125 odds (Physical paint) so each brush gets a
# distinct icon set without exceeding Discord's 300 assets-per-app limit.
_SP_BRUSH_TOOL_CONFIG = {
    "paint": SUBSTANCEPAINTER_PAINT_SUBSET,
    "pphys": SUBSTANCEPAINTER_PHYSPAINT_SUBSET,
}

# Store plugin preferences in this directory
_SP_PREF_LOCATION = os.path.dirname(os.path.abspath(__file__))

############
# Settings #
############


@dataclass
class SPSettings(ColoredIconSettings, SharedSettings, JSONSharedSettings):
    # pylint: disable=invalid-name
    _PREFIX: ClassVar[str] = "painterPresence_"
    INFO_CHOICES: ClassVar[List[Tuple[str, str]]] = [
        ("Project name", "project"),
        ("Project mesh count", "num_meshes"),
        ("Project resource count", "num_resources"),
        ("Project layer count", "num_layers"),
        ("Active material channel count", "channel_count"),
        ("Active texture set info", "active_texset_info"),
        ("Project texture set info", "texset_info"),
        ("Active layer info", "layer_info"),
        ("Active brush alpha", "brush_alpha"),
    ]
    _INITIAL_DEFAULTS: ClassVar[Dict[str, Any]] = {
        "detailsType": "project",
        "stateType": "texset_info",
    }
    countActiveStack: bool = field(
        default=False,
        metadata={
            "group": "General",
            "label": "Count layers and UV tiles in the active stack only",
        },
    )
    bakingDetails: bool = field(
        default=True,
        metadata={
            "group": "General",
            "label": "Override details with baking information when baking",
        },
    )


###########
# Context #
###########


@dataclass
class SPContext:
    texture_sets: List[sp.textureset.TextureSet]
    stack: sp.textureset.Stack
    main_window: QtW.QMainWindow
    active_only: bool

    @classmethod
    def capture(cls, active_only: bool) -> "SPContext | None":
        try:
            stack = sp.textureset.get_active_stack()
            sets = sp.textureset.all_texture_sets()
            window = sp.ui.get_main_window()
            return cls(
                texture_sets=sets,
                stack=stack,
                main_window=window,
                active_only=active_only,
            )
        except (  # 12.0.3 Stubs are wrong and label exceptions as enum.Enum; suppress Pylance
            RuntimeError,
            sp.exception.ProjectError,
            sp.exception.ServiceNotFoundError,
        ):  # pyright: ignore[reportGeneralTypeIssues]
            return None

    def get_project_name(self) -> str:
        p_name = sp.project.name()
        if p_name is None:
            return "Unsaved Project"
        return f"Project: {p_name}"

    def get_num_meshes(self) -> str:
        count = sum([len(texset.all_mesh_names()) for texset in self.texture_sets])
        return sp_plural(count, "mesh", "es")

    def get_num_texsets(self) -> int:
        return len(self.texture_sets)

    def get_active_texset_name(self) -> str:
        return self.stack.material().name

    def get_material_resolution_str(self) -> str:
        material_resolution = self.stack.material().get_resolution()
        return f"{material_resolution.width}x{material_resolution.height}"

    def get_active_texset_info(self) -> str:
        """Return a formatted string containing the name and resolution
        of the active texture set"""
        tn = self.get_active_texset_name()
        tmr = self.get_material_resolution_str()
        return f"Texture set: {tn} ({tmr})"

    def _recurse_count_nodes(self, root_node) -> int:
        """Count the number of nodes descending from this one,
        including the root node itself"""
        count = 0
        if isinstance(root_node, sp.layerstack.GroupLayerNode):
            for child_node in root_node.sub_layers():
                count += self._recurse_count_nodes(child_node)
            return count
        else:
            return 1

    def get_num_layers(self) -> str:
        if self.active_only:
            count = sum(
                [
                    self._recurse_count_nodes(node)
                    for node in sp.layerstack.get_root_layer_nodes(self.stack)
                ]
            )
            return sp_plural(count, "active layer")
        else:
            count = 0
            for texset in self.texture_sets:
                for stack in texset.all_stacks():
                    count += sum(
                        [
                            self._recurse_count_nodes(node)
                            for node in sp.layerstack.get_root_layer_nodes(stack)
                        ]
                    )
            return sp_plural(count, "layer")

    def _get_active_layer_raw(self) -> str | int:
        """Return a string (the active layer name) if only one layer is
        selected, and an int (the number of selected layers) otherwise.
        """
        selected_nodes = sp.layerstack.get_selected_nodes(self.stack)
        count = len(selected_nodes)
        if count != 1:
            return count
        else:
            return selected_nodes[0].get_name()

    def get_num_uv_tiles(self) -> int | None:
        if self.active_only:
            active_stack_set = self.stack.material()
            if not active_stack_set.has_uv_tiles():
                return None
            return len(active_stack_set.all_uv_tiles())
        else:
            count = 0
            for texset in self.texture_sets:
                for stack in texset.all_stacks():
                    mat = stack.material()
                    if mat.has_uv_tiles():
                        count += len(mat.all_uv_tiles())
            return count if count else None

    def get_project_texset_info(self) -> str:
        num_texsets = self.get_num_texsets()
        num_uv_tiles = self.get_num_uv_tiles()
        if not num_texsets:
            return "No texture sets"
        if num_uv_tiles is None:
            return sp_plural(num_texsets, "texture set")
        return (
            f"{sp_plural(num_texsets, 'texture set')} "
            f"({sp_plural(num_uv_tiles, 'UV tile')})"
        )

    def get_active_layer_blend_mode(self) -> str | None:
        selected_nodes = sp.layerstack.get_selected_nodes(self.stack)
        if selected_nodes and selected_nodes[0].is_in_mask_stack():
            return selected_nodes[0].get_blending_mode(None).name
        return None

    def get_layer_num_channels(self) -> str:
        return sp_plural(len(self.stack.all_channels()), "channel")

    def get_active_layer_info(self) -> str | None:
        """Return:
        - A formatted string with information about the active layer (layer
        name and blend mode, if not 'normal') if a single layer is selected
        - None if no layers are selected
        - '_ layers selected' if more than one layer is selected
        """
        layer_raw = self._get_active_layer_raw()
        if isinstance(layer_raw, int):
            if layer_raw:
                return f"{layer_raw} layers selected"
            else:
                # Prefer returning None to skip this in favor of something
                # more informative which will draw from the whole project
                return None
        else:
            layer_blend_mode = self.get_active_layer_blend_mode()
            layer_str = "Layer: " if "layer" not in layer_raw.lower() else ""
            if layer_blend_mode is not None:
                return f"{layer_str}{layer_raw} ({layer_blend_mode})"
            return f"{layer_str}{layer_raw}"

    def get_num_resources(self) -> str:
        return sp_plural(len(sp.resource.list_project_resources()), "resource")

    ##################################################################
    # Below here, methods rely on querying the Qt UI (no API routes) #
    ##################################################################

    def _find_named(self, parent, cls, name):
        """Helper to find a child of the parent QtWidget matching
        the provided class and name, catching the exception if
        the parent widget has been destroyed and returning None"""
        try:
            if parent is None:
                return None
            return parent.findChild(cls, name)
        except RuntimeError:
            return None

    def get_active_tool(self) -> Tuple[str, str] | None:
        """Query the Qt UI for active tool. Return a tuple with the object name of the tool
        (always English, used for mapping to icon names) and the name of the tool (localized,
        used as the small icon text)"""
        try:
            toolbar = self._find_named(self.main_window, QtW.QToolBar, "tools_toolbar")
            if toolbar is None:
                return None
            checked_items = [
                i for i in toolbar.findChildren(QtW.QToolButton) if i.isChecked()
            ]
            if len(checked_items) < 1:
                return None
            # Use index = -1 since the material picker can be active at the same time
            # as other tools and will appear later in the list; if the material picker
            # is active we display that instead of the other selected tool
            tool_action = checked_items[-1].defaultAction()
            if tool_action is None:
                return None
            tool_object_name = tool_action.objectName()
            tool_text = tool_action.text()
            return (tool_object_name, tool_text)
        except RuntimeError:
            return None

    def get_paint_color(self) -> Tuple[int, int, int] | None:
        """Query the UI for paint color by attempting to find the SourceParametersView
        element with 'Base color' in the dropzone_title.text() of a child ('Base color'
        is not localized, so as of 12.0.3 this works on all languages. If there is no
        such SourceParametersView, return None."""
        try:
            mw = self.main_window
            source_parameter_views = mw.findChildren(QtW.QFrame, "SourceParametersView")
            color_frame = next(
                (
                    x
                    for x in source_parameter_views
                    if any(
                        "Base color" in y.text()
                        for y in x.findChildren(QtW.QLabel, "dropzone_title")
                    )
                ),
                None,
            )
            if color_frame is None:
                return None
            color_zone = self._find_named(color_frame, QtW.QToolButton, "colorZone")
            if color_zone is None:
                return None
            # I couldn't find a way to directly access the RGB values of the color zone,
            # thus this method samples the center pixel
            cz_grab = color_zone.grab()
            cz_w, cz_h = cz_grab.size().width(), cz_grab.size().height()
            pix = cz_grab.toImage().pixelColor(cz_w // 2, cz_h // 2)
            return (pix.red(), pix.green(), pix.blue())
        except RuntimeError:
            return None

    def get_brush_material(self) -> str | None:
        """Query the UI for brush material by looking for the materialModeParams widget
        and reading its dropzone_text"""
        mat_params = self._find_named(
            self.main_window, QtW.QWidget, "materialModeParams"
        )
        if mat_params is None:
            return None
        mat_label = self._find_named(mat_params, QtW.QLabel, "dropzone_text")
        if mat_label is None:
            return None
        return mat_label.text()

    def get_brush_alpha(self) -> str | None:
        """Query the UI for brush alpha by looking for the MaskParametersView widget
        and reading its dropzone_text."""
        alpha_widget = self._find_named(
            self.main_window, QtW.QFrame, "MaskParametersView"
        )
        if alpha_widget is None:
            return None
        alpha_label = self._find_named(alpha_widget, QtW.QLabel, "dropzone_text")
        # Potential future upgrade: do not skip uniform color and instead find the
        # alpha value if the alpha color selector can be easily located in the Qt layout
        if alpha_label is None or alpha_label.text() == "uniform color":
            return None
        return f"Brush Alpha: {alpha_label.text()}"


##########
# Plugin #
##########


class SPPlugin(RPCBasePlugin):
    display_types: ClassVar[Dict[str, Callable]] = {
        "project": lambda ctx: ctx.get_project_name(),
        "num_meshes": lambda ctx: ctx.get_num_meshes(),
        "num_resources": lambda ctx: ctx.get_num_resources(),
        "num_layers": lambda ctx: ctx.get_num_layers(),
        "channel_count": lambda ctx: ctx.get_layer_num_channels(),
        "active_texset_info": lambda ctx: ctx.get_active_texset_info(),
        "texset_info": lambda ctx: ctx.get_project_texset_info(),
        "layer_info": lambda ctx: ctx.get_active_layer_info(),
        "brush_alpha": lambda ctx: ctx.get_brush_alpha(),
    }
    display_cycle: ClassVar[List[str]] = list(display_types.keys())

    def __init__(self):
        super().__init__(
            app_id="1506547790937981008",
            app_name="painter",
            prefs_class=SPSettings,
            warn=sp.logging.warning,
            error=sp.logging.error,
            path=_SP_PREF_LOCATION,
        )

    def start(self):
        self.session.connected = self._connect_rpc()
        self.session.start_time = time.time()
        sp.event.DISPATCHER.connect(sp.event.ProjectOpened, self._on_file_open)
        sp.event.DISPATCHER.connect(sp.event.ProjectCreated, self._on_file_open)
        sp.event.DISPATCHER.connect(
            sp.event.BakingProcessAboutToStart, self._on_bake_start
        )
        sp.event.DISPATCHER.connect(
            sp.event.BakingProcessProgress, self._on_bake_update
        )
        sp.event.DISPATCHER.connect(sp.event.BakingProcessEnded, self._on_bake_end)
        self.timer.start()

    def close(self):
        self.timer.stop()
        try:
            self.rpc_client.clear()
            self.rpc_client.close()
        except Exception as e:
            sp.logging.error(f"[PainterPresence] failed to clear and close client: {e}")

    def _capture(self):
        return SPContext.capture(self.prefs.countActiveStack)

    def _on_file_open(self, *args):  # pylint: disable=unused-argument
        if self.prefs.resetTimer:
            self.session.start_time = time.time()

    def _on_bake_start(self, *args):  # pylint: disable=unused-argument
        self.session.is_rendering = True

    def _on_bake_end(self, *args):  # pylint: disable=unused-argument
        self.session.is_rendering = False

    def _on_bake_update(self, arg):
        self.session.rendered_frames = int(100 * arg.progress)

    def update_small_icon(self, ctx):
        self.details.small_icon = None
        self.details.small_icon_text = ""
        if not self.prefs.displaySmallIcon:
            return
        if self.session.is_rendering:
            self.details.small_icon = "baking"
            if not self.prefs.bakingDetails:
                self.details.small_icon_text = (
                    f"Baking: {self.session.rendered_frames}%"
                )
            else:
                self.details.small_icon_text = "Baking"
            return
        tool = ctx.get_active_tool()
        if tool is None:
            return
        tool_objname, tool_text = tool
        # Colored icons for Paint and Physical Paint tools
        if self.prefs.enableColoredIcons and (
            tool_objname in [_SP_PAINT_NAME, _SP_PHYSPAINT_NAME]
        ):
            if tool_objname == _SP_PAINT_NAME:
                prefix, subset = "paint", _SP_BRUSH_TOOL_CONFIG["paint"]
            else:
                prefix, subset = "pphys", _SP_BRUSH_TOOL_CONFIG["pphys"]
            rgb = ctx.get_paint_color()
            if rgb is not None:
                match = find_closest(
                    rgb, self.prefs.useEvocativeNames, icon_subset=subset
                )
                self.details.small_icon = f"{prefix}_{match.icon_key_suffix}"
                self.details.small_icon_text = (
                    f"Painting in {match.display_name} ({match.user_hex})"
                )
        # No colored icons, or not Paint/Physical Paint tools
        else:
            self.details.small_icon = tool_objname.lower()
            self.details.small_icon_text = tool_text.title()
            mat = ctx.get_brush_material()
            if mat is not None and (
                tool_objname in [_SP_PAINT_NAME, _SP_PHYSPAINT_NAME]
            ):
                self.details.small_icon_text = f"Painting in {mat}"

    def update_large_icon(self, ctx):  # pylint: disable=unused-argument
        if self.prefs.displayVersion:
            self.details.large_icon_text = (
                f"Adobe Substance 3D Painter {sp.application.version()}"
            )
        else:
            self.details.large_icon_text = "Adobe Substance 3D Painter"

    def update_details(self, ctx):
        if (
            self.prefs.enableDetails
            and self.prefs.bakingDetails
            and self.session.is_rendering
        ):
            proj_name = sp.project.name()
            if not proj_name:
                proj_name = "Unsaved Project"
            self.details.details_text = (
                f"Baking {proj_name}: {self.session.rendered_frames}%"
            )
        else:
            super().update_details(ctx)


SP_PLUGIN = SPPlugin()


#####################
# GUI Settings Menu #
#####################

SP_STOP_ACTION: QtG.QAction | None = None
SP_START_ACTION: QtG.QAction | None = None


def sp_close_settings_menu():
    if SP_PLUGIN.settings_window is not None:
        try:
            SP_PLUGIN.settings_window.close()
            SP_PLUGIN.settings_window.deleteLater()
        except Exception:
            pass


def sp_pause_presence():
    SP_PLUGIN.prefs.generalEnable = False
    SP_PLUGIN.prefs.flush()
    if SP_START_ACTION is not None:
        SP_START_ACTION.setEnabled(True)
    if SP_STOP_ACTION is not None:
        SP_STOP_ACTION.setEnabled(False)


def sp_restart_presence():
    SP_PLUGIN.prefs.generalEnable = True
    SP_PLUGIN.prefs.flush()
    if SP_START_ACTION is not None:
        SP_START_ACTION.setEnabled(False)
    if SP_STOP_ACTION is not None:
        SP_STOP_ACTION.setEnabled(True)


def _sp_find_discord_action(menu_bar):
    """Walk the menu bar's actions and return the one titled "Discord", or None.
    A stale wrapper on any action can raise RuntimeError ("Internal C++ object
    already deleted"); skip those and keep looking.
    """
    try:
        actions = menu_bar.actions()
    except RuntimeError:
        return None
    for action in actions:
        try:
            if action.text() == "Discord":
                return action
        except RuntimeError:
            continue
    return None


def _sp_remove_discord_menu(menu_bar):
    """Remove the Discord submenu from `menu_bar` if present. Safe to call
    when no such submenu exists."""
    action = _sp_find_discord_action(menu_bar)
    if action is None:
        return
    try:
        menu = action.menu()
    except RuntimeError:
        menu = None
    try:
        menu_bar.removeAction(action)
    except RuntimeError:
        pass
    if menu is not None:
        try:
            menu.deleteLater()
        except RuntimeError:
            pass


def sp_open_settings_menu():
    try:
        SP_PLUGIN.show_qt_window("Painter", sp.ui.get_main_window())
    except sp.exception.ServiceNotFoundError: # pyright: ignore[reportGeneralTypeIssues]
        pass


def sp_install_settings_menu():
    try:
        global SP_START_ACTION, SP_STOP_ACTION
        main_window = sp.ui.get_main_window()
        menu_bar = main_window.menuBar()
        # If a previous load left a Discord menu, strip it before
        # adding a new one so reloads don't stack duplicates.
        _sp_remove_discord_menu(menu_bar)
        plugin_menu = menu_bar.addMenu("Discord")
        settings_action = plugin_menu.addAction("Settings")
        settings_action.triggered.connect(sp_open_settings_menu)
        SP_STOP_ACTION = plugin_menu.addAction("Pause Presence")
        SP_START_ACTION = plugin_menu.addAction("Restart Presence")
        SP_START_ACTION.setEnabled(False)
        SP_START_ACTION.triggered.connect(sp_restart_presence)
        SP_STOP_ACTION.triggered.connect(sp_pause_presence)
        SP_PLUGIN.menubar_item = plugin_menu
    except Exception as e:
        sp.logging.warning(f"[PainterPresence] Unable to install settings menu: {e}")


def sp_uninstall_settings_menu():
    sp_close_settings_menu()
    try:
        main_window = sp.ui.get_main_window()
        menu_bar = main_window.menuBar()
        _sp_remove_discord_menu(menu_bar)
    except Exception as e:
        sp.logging.warning(f"[PainterPresence] Unable to uninstall settings menu: {e}")
    SP_PLUGIN.menubar_item = None


###################
# Plugin Lifetime #
###################


def start_plugin():
    SP_PLUGIN.start()
    sp_install_settings_menu()


def close_plugin():
    sp_uninstall_settings_menu()
    SP_PLUGIN.close()


if __name__ == "__main__":
    start_plugin()

atexit.register(force_clear_on_exit, SP_PLUGIN.rpc_client)
