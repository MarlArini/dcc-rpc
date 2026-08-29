"""
PainterPresence is a Discord Rich Presence client plugin for Adobe Substance 3D Painter.
PainterPresence has been tested on Substance Painter 12.0.3 (Windows 11).
For more info, see https://github.com/MarlArini/dcc-rpc.
"""

import atexit
from dataclasses import dataclass, field
from enum import Enum
import os
import time
from typing import Any, Callable, ClassVar, Dict, List, Tuple
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

# Store plugin preferences in this directory
_SP_PREF_LOCATION = os.path.dirname(os.path.abspath(__file__))

############
# Settings #
############


@dataclass
class SPSettings(ColoredIconSettings, SharedSettings, JSONSharedSettings):
    # pylint: disable=invalid-name
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


class UIMode(Enum):
    BAKING = 1
    PAINTING = 2
    RENDERING = 3


_UI_MODE_STATE = {
    UIMode.BAKING: "Adjusting baking settings",
    UIMode.RENDERING: "Previewing in IRay",
}

_UI_MODE_ICONS = {
    UIMode.BAKING: ("baking", "Baking settings"),
    UIMode.RENDERING: ("rendering", "Previewing in IRay"),
}


def current_ui(window: QtW.QMainWindow) -> UIMode:
    """Query the Qt QMainWindow to determine the UI mode (painting, baking, or
    rendering). Fall back to painting if the mode cannot be determined since
    Qt object names might change and painting is the most likely state for
    a user to be in."""
    try:
        ui_mode_container = window.findChild(
            QtW.QWidget, "paint_editor_toolbar_ui_mode"
        )
        if not ui_mode_container:
            return UIMode.PAINTING
        selected_items = [
            i for i in ui_mode_container.findChildren(QtW.QToolButton) if i.isChecked()
        ]
        if not selected_items:
            return UIMode.PAINTING
        action = selected_items[0].defaultAction()
        if action is None:
            return UIMode.PAINTING
        ui_name = action.objectName()
    except RuntimeError:
        return UIMode.PAINTING
    if ui_name == "bakingAction":
        return UIMode.BAKING
    elif ui_name == "rendering_mode":
        return UIMode.RENDERING
    return UIMode.PAINTING


def get_project_name() -> str | None:
    try:
        p_name = sp.project.name()
    except sp.exception.ProjectError:  # pyright: ignore[reportGeneralTypeIssues]
        return None
    if p_name is None:
        return "Unsaved Project"
    return f"Project: {p_name}"


@dataclass
class SPContext:
    texture_sets: List[sp.textureset.TextureSet]
    stack: sp.textureset.Stack | None
    main_window: QtW.QMainWindow
    active_only: bool
    ui_mode: UIMode = UIMode.PAINTING

    @classmethod
    def capture(cls, active_only: bool) -> "SPContext | None":
        # fmt: off
        if get_project_name() is None:
            return None
        # Window
        try:
            window = sp.ui.get_main_window()
        except sp.exception.ServiceNotFoundError:  # pyright: ignore[reportGeneralTypeIssues]
            return None
        # Texture sets
        try:
            sets = sp.textureset.all_texture_sets() or []
        except (  # 12.0.3 Stubs are wrong and label exceptions as enum.Enum; suppress Pylance
            RuntimeError,
            sp.exception.ProjectError,
            sp.exception.ServiceNotFoundError,
        ):  # pyright: ignore[reportGeneralTypeIssues]
            return None
        # Active stack
        try:
            stack = sp.textureset.get_active_stack()
        except (
            sp.exception.ProjectError,
            sp.exception.ServiceNotFoundError
        ):  # pyright: ignore[reportGeneralTypeIssues]
            return None
        except RuntimeError:
            stack = None
        # UI mode
        ui_mode = current_ui(window)
        if stack is None and ui_mode not in _UI_MODE_STATE:
            return None
        # fmt: on
        return cls(
            texture_sets=sets,
            stack=stack,
            main_window=window,
            active_only=active_only,
            ui_mode=ui_mode,
        )

    def get_project_name(self) -> str:
        return get_project_name() or "No project open"

    def get_num_meshes(self) -> str:
        count = sum([len(texset.all_mesh_names()) for texset in self.texture_sets])
        return sp_plural(count, "mesh", "es")

    def get_num_texsets(self) -> int:
        return len(self.texture_sets)

    def get_active_texset_name(self) -> str | None:
        if self.stack is None:
            return None
        return self.stack.material().name

    def get_material_resolution_str(self) -> str | None:
        if self.stack is None:
            return None
        material_resolution = self.stack.material().get_resolution()
        return f"{material_resolution.width}x{material_resolution.height}"

    def get_active_texset_info(self) -> str | None:
        """Return a formatted string containing the name and resolution
        of the active texture set"""
        tn = self.get_active_texset_name()
        tmr = self.get_material_resolution_str()
        if tn is None or tmr is None:
            return None
        return f"Texture set: {tn} ({tmr})"

    def _recurse_count_nodes(self, root_node) -> int:
        """Count the number of non-group nodes descending from this one,
        including the root node itself (if the root is not a GroupLayerNode)"""
        count = 0
        if isinstance(root_node, sp.layerstack.GroupLayerNode):
            for child_node in root_node.sub_layers():
                count += self._recurse_count_nodes(child_node)
            return count
        else:
            return 1

    def get_num_layers(self) -> str | None:
        if self.active_only:
            if self.stack is None:
                return None
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
        if self.stack is None:
            return 0
        selected_nodes = sp.layerstack.get_selected_nodes(self.stack)
        count = len(selected_nodes)
        if count != 1:
            return count
        else:
            return selected_nodes[0].get_name()

    def get_num_uv_tiles(self) -> int | None:
        if self.active_only:
            if self.stack is None:
                return None
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
        if self.stack is None:
            return None
        selected_nodes = sp.layerstack.get_selected_nodes(self.stack)
        # Note: get_blending_mode on a node requires specifying a channel if the
        # node is not in a mask stack
        if selected_nodes and selected_nodes[0].is_in_mask_stack():
            return selected_nodes[0].get_blending_mode(None).name
        return None

    def get_layer_num_channels(self) -> str | None:
        if self.stack is None:
            return None
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

    def _find_named_visible(self, parent, cls, name):
        """Helper to find a child of the parent QtWidget matching
        the provided class and name, catching the exception if
        the parent widget has been destroyed and returning None"""
        try:
            if parent is None:
                return None
            return next(
                filter(lambda x: x.isVisible(), parent.findChildren(cls, name)), None
            )
        except RuntimeError:
            return None

    def get_active_tool(self) -> Tuple[str, str] | None:
        """Query the Qt UI for active tool. Return a tuple with the object name of the tool
        (always English, used for mapping to icon names) and the name of the tool (localized,
        used as the small icon text)"""
        try:
            toolbar = self._find_named_visible(
                self.main_window, QtW.QToolBar, "tools_toolbar"
            )
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
                    if x.isVisible()
                    and any(
                        "Base color" in y.text()
                        for y in x.findChildren(QtW.QLabel, "dropzone_title")
                    )
                ),
                None,
            )
            if color_frame is None:
                return None
            color_zone = self._find_named_visible(
                color_frame, QtW.QToolButton, "colorZone"
            )
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
        and reading its dropzone_text. Checks if a material is selected by seeing if the
        clear material button is visible."""
        mat_params = self._find_named_visible(
            self.main_window, QtW.QWidget, "materialModeParams"
        )
        if mat_params is None:
            return None
        mat_label = self._find_named_visible(mat_params, QtW.QLabel, "dropzone_text")
        button = self._find_named_visible(mat_params, QtW.QToolButton, "clear")
        if not mat_label or not button:
            return None
        label = mat_label.text()
        return label if label else None

    def sample_brush_material_color(self) -> Tuple[int, int, int] | None:
        """Sample three points on the preview material sphere for a selected material
        and return their average color so that later we can try to choose a brush icon
        color that loosely matches it."""
        mat_params = self._find_named_visible(
            self.main_window, QtW.QWidget, "materialModeParams"
        )
        if mat_params is None:
            return None
        mat_preview = self._find_named_visible(mat_params, QtW.QLabel, "dropzone_icon")
        if not mat_preview:
            return None
        preview_image = mat_preview.grab().toImage()
        top_sample = preview_image.pixelColor(21, 5).getRgb()
        left_sample = preview_image.pixelColor(5, 21).getRgb()
        middle_sample = preview_image.pixelColor(21, 21).getRgb()
        combined = tuple(
            map(
                sum,
                zip(top_sample, left_sample, middle_sample),
            )
        )
        return (combined[0] // 3, combined[1] // 3, combined[2] // 3)

    def get_brush_alpha(self) -> str | None:
        """Query the UI for brush alpha by looking for the MaskParametersView widget
        and reading its dropzone_text."""
        alpha_widget = self._find_named_visible(
            self.main_window, QtW.QFrame, "MaskParametersView"
        )
        if alpha_widget is None:
            return None
        alpha_label = self._find_named_visible(
            alpha_widget, QtW.QLabel, "dropzone_text"
        )
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

    def __init__(self):
        super().__init__(
            app_id="1506547790937981008",
            app_name="painter",
            prefs_class=SPSettings,
            warn=sp.logging.warning,
            error=sp.logging.error,
            path=_SP_PREF_LOCATION,
        )
        self._event_connections = []

    def start(self):
        self.session.connected = self._connect_rpc()
        self.session.start_time = time.time()
        self._event_connections = [
            (sp.event.ProjectOpened, self._on_file_open),
            (sp.event.ProjectCreated, self._on_file_open),
            (sp.event.BakingProcessAboutToStart, self._on_bake_start),
            (sp.event.BakingProcessProgress, self._on_bake_update),
            (sp.event.BakingProcessEnded, self._on_bake_end),
        ]
        for event, handler in self._event_connections:
            sp.event.DISPATCHER.connect(event, handler)
        self.timer.start()

    def close(self):
        self.timer.stop()
        for event, handler in self._event_connections:
            try:
                sp.event.DISPATCHER.disconnect(event, handler)
            except Exception:  # noqa: BLE001
                pass
        self._event_connections = []
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
        # Baking / rendering UI panes: there is no active stack and no active
        # tool, so surface an icon that reflects what phase of work the user
        # is in rather than falling through to a stale/empty tool query.
        if ctx.ui_mode in _UI_MODE_ICONS:
            icon_key, icon_text = _UI_MODE_ICONS[ctx.ui_mode]
            self.details.small_icon = icon_key
            self.details.small_icon_text = icon_text
            return
        tool = ctx.get_active_tool()
        if tool is None:
            return
        tool_objname, tool_text = tool
        # Paint and Physical Paint tools
        if tool_objname in [_SP_PAINT_NAME, _SP_PHYSPAINT_NAME]:
            if tool_objname == _SP_PAINT_NAME:
                prefix, subset = "paint", SUBSTANCEPAINTER_PAINT_SUBSET
            else:
                prefix, subset = "pphys", SUBSTANCEPAINTER_PHYSPAINT_SUBSET
            if (mat := ctx.get_brush_material()) is not None:
                rgb = ctx.sample_brush_material_color()
            else:
                rgb = ctx.get_paint_color()
            if rgb:
                match = find_closest(
                    rgb, self.prefs.useEvocativeNames, icon_subset=subset
                )
                if self.prefs.enableColoredIcons:
                    self.details.small_icon = f"{prefix}_{match.icon_key_suffix}"
                else:
                    self.details.small_icon = tool_objname.lower()
                if mat:
                    self.details.small_icon_text = f"Painting in {mat}"
                else:
                    self.details.small_icon_text = (
                        f"Painting in {match.display_name} ({match.user_hex})"
                    )
                return
        # No colored icons, or not Paint/Physical Paint tools
        self.details.small_icon = tool_objname.lower()
        self.details.small_icon_text = tool_text.title()

    def update_large_icon(self, ctx):  # pylint: disable=unused-argument
        if self.prefs.displayVersion:
            self.details.large_icon_text = (
                f"Adobe Substance 3D Painter {sp.application.version()}"
            )
        else:
            self.details.large_icon_text = "Adobe Substance 3D Painter"

    def update_details(self, ctx):
        # Baking / rendering UI panes: the user's configured detailsType may
        # depend on the active stack, which is None here. Force the details slot
        # to the project name so the display stays informative.
        if self.prefs.enableDetails and (
            (self.prefs.bakingDetails and self.session.is_rendering)
            or ctx.ui_mode in _UI_MODE_STATE
        ):
            self.details.details_text = ctx.get_project_name()
            return
        super().update_details(ctx)

    def update_state(self, ctx):
        # Baking / rendering UI panes: the state slot describes what phase of
        # work the user is in ("Adjusting baking settings", "Previewing in
        # IRay"). During an actual bake we display bake progress.
        if (
            self.prefs.enableState
            and self.prefs.bakingDetails
            and self.session.is_rendering
        ):
            self.details.state_text = (
                f"Baking: {self.session.rendered_frames}% complete"
            )
            return
        if (
            self.prefs.enableState
            and not self.session.is_rendering
            and ctx.ui_mode in _UI_MODE_STATE
        ):
            self.details.state_text = _UI_MODE_STATE[ctx.ui_mode]
            return
        super().update_state(ctx)


SP_PLUGIN = SPPlugin()


#####################
# GUI Settings Menu #
#####################

_MENU_OBJNAME = "substancepainterpresence.menu"


def sp_close_settings_menu():
    if SP_PLUGIN.settings_window is not None:
        try:
            SP_PLUGIN.settings_window.close()
            SP_PLUGIN.settings_window.deleteLater()
        except Exception:
            pass


def get_menu_action():
    try:
        window = sp.ui.get_main_window()
        menu_bar = window.menuBar()
        actions = {action.objectName(): action for action in menu_bar.actions()}
        discord_action = actions.get(_MENU_OBJNAME)
        return discord_action
    except (sp.exception.ServiceNotFoundError, RuntimeError):  # type: ignore #fmt: skip
        return None


def _sp_remove_discord_menu(menu_bar: QtW.QMenuBar):
    """Remove the Discord submenu from `menu_bar` if present. Safe to call
    when no such submenu exists."""
    action = get_menu_action()
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
    except sp.exception.ServiceNotFoundError:  # pyright: ignore[reportGeneralTypeIssues]
        pass


def sp_install_settings_menu():
    try:
        main_window = sp.ui.get_main_window()
        menu_bar = main_window.menuBar()
        # If a previous load left a Discord menu, strip it before
        # adding a new one so reloads don't stack duplicates.
        _sp_remove_discord_menu(menu_bar)
        plugin_menu = menu_bar.addMenu("Discord")
        # The menu bar exposes each submenu as its menuAction(); get_menu_action
        # looks these up by objectName. Setting it on the QMenu itself is not
        # enough — the menuAction is a distinct QObject with its own (empty)
        # objectName, so the dedup lookup would silently miss and reloads would
        # stack duplicate "Discord" menus.
        plugin_menu.menuAction().setObjectName(_MENU_OBJNAME)
        settings_action = plugin_menu.addAction("Settings")
        settings_action.triggered.connect(sp_open_settings_menu)
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
