"""
NukePresence is a Discord Rich Presence client plugin for The Foundry's Nuke,
NukeX, and NukeStudio. NukePresence has been tested on Nuke[s] 17.0.1.
For more info, see https://github.com/MarlArini/dcc-rpc.
"""

import atexit
from dataclasses import dataclass, field
import os
from pathlib import Path
import sys
import threading
import time
from typing import Tuple, ClassVar, List, Dict, Any
from PySide6 import QtWidgets as QtW
from pypresence.presence import Presence

import nuke  # pyright: ignore[reportMissingImports] pylint: disable=import-error

from common import (
    SharedSettings,
    RenderSettings,
    SessionInfo,
    RPCUpdateDetails,
    JSONSharedSettings,
    QtSettingsGUIMenu,
    on_render_start,
    on_render_end,
    on_frame_render_end,
    get_file_size_str,
    force_clear_on_exit,
    plural as nk_plural,
    push_rpc_update,
    update_buttons,
    connect_rpc,
    advance_cycle,
    update_slot,
    format_render_details,
    DISCORD_SHORT_TERM_RATE_LIMIT,
)

# Bootstrap: ensure this plugin's directory is on sys.path so the sibling
# common.py and pypresence/ resolve when loaded by the host application.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

###########
# Globals #
###########


@dataclass
class NKSettings(SharedSettings, JSONSharedSettings):
    # pylint: disable=invalid-name
    _PREFIX: ClassVar[str] = "nukePresence_"
    INFO_CHOICES: ClassVar[List[Tuple[str, str]]] = [
        ("Memory usage", "memory_usage"),
        ("Node count", "num_nodes"),
        ("Active node (commercial)", "active_node"),
        ("Read/write node count (commercial)", "io_nodes"),
        ("Layer count", "num_layers"),
        ("Frame info", "frame"),
        ("Viewer info (commercial)", "viewer_info"),
        ("Color management", "color_management"),
        ("Comp name", "comp_name"),
        ("Format", "format"),
        ("Proxy info", "scaling"),
    ]
    _INITIAL_DEFAULTS: ClassVar[Dict[str, Any]] = {
        "detailsType": "comp_name",
        "stateType": "num_nodes",
    }
    displayRenderStats: bool = field(
        default=True,
        metadata={"group": "Details", "label": "Display render stats in details"},
    )
    displayFileName: bool = field(
        default=True,
        metadata={"group": "General", "label": "Display file name when rendering"},
    )
    displayFrames: bool = field(
        default=True,
        metadata={"group": "Details", "label": "Display frames rendered in details"},
    )


# This plugin was originally written based on a misreading of the Non-commercial and
# Indie Python API restrictions, in which I believed it was possible to repeatedly
# query nodes but that only the first 10 results to any query would be returned. Thus
# there are methods throughout the file to find the selected node and display its icon
# or to query the node being viewed in a Viewer. However, a Non-commercial or Indie user
# can only query 10 nodes throughout the entire lifetime of a Nuke session. Thus all of
# the node-related code has been temporarily turned into string statements until/unless
# the API is updated such that it allows more than 10 node queries.


# pylint: disable=line-too-long
# fmt:off
NK_ICONS = [
    '2D', '2DMasked', '3D', 'Add', 'Add32', 'AddMix', 'AdjBBox', 'Anaglyph', 'AppendClip', 'Assert', 'Axis', 
    'Backdrop', 'Bezier', 'Bilateral', 'BlackOutside', 'Blend', 'Blur', 'BumpBoss', 'Camera', 'CameraShake', 
    'Card', 'ChannelMerge', 'CheckerBoard', 'Clamp', 'CMSTestPattern', 'Color', 'Color3D', 'ColorBars', 
    'ColorCorrect', 'ColorLookup', 'ColorMath', 'ColorSpace', 'ColorTransfer', 'ColorWheel', 'Constant', 
    'ContactSheet', 'Convolve', 'Copy', 'CopyBBox', 'CopyRectangle', 'CornerPin', 'Crop', 'Crosstalk', 'Cube',
    'CurveTool', 'Cylinder', 'Defocus', 'DegrainBlue', 'DegrainSimple', 'Difference', 'DirBlur', 'DirectLight', 
    'Dissolve', 'Dither', 'Dot', 'DustBust', 'EdgeBlur', 'EdgeDetect', 'Emboss', 'EnvironMaps', 'Environment', 
    'ErodeBlur', 'ErodeFast', 'Exposure', 'filter', 'FilterErode', 'Flare', 'FloodFill', 'Fog', 'FrameBlend', 
    'FrameHold', 'FrameRange', 'GenerateLUT', 'Geometry', 'Glint', 'Glow', 'GodRays', 'Grade', 'Grain', 'Grid', 
    'GridWarp', 'Group', 'HistEQ', 'Histogram', 'HSVTool', 'HueCorrect', 'HueKeyer', 'HueShift', 'IBKColour', 
    'IBKGizmo', 'IDistort', 'Input', 'Invert', 'JoinViews', 'Keyer', 'KeyerLuminance', 'Keylight', 'Keymix', 
    'Laplacian', 'LayerChannel', 'LayerContactSheet', 'LensDistort', 'LevelSet', 'Light', 'LightWrap', 'Log2Lin', 
    'MarkerRemoval', 'Matrix', 'Median', 'Merge', 'MergeExpression', 'MinColor', 'Mirror', 'Modify', 'MotionBlur2D',
    'MotionBlur3D', 'Noise', 'NoOp', 'NoTimeBlur', 'Oflow', 'OneView', 'Output', 'Paint', 'PointLight', 'PointsTo3D', 
    'PointTo3D', 'Position', 'PostageStamp', 'Posterize', 'Premult', 'Primatte', 'Radial', 'Ramp', 'Read', 'ReadGeo', 
    'Reconcile3D', 'Rectangle', 'Reformat', 'Remove', 'Remove32', 'Render', 'Retime', 'RolloffContrast', 'Sampler', 
    'Saturation', 'ScannedGrain', 'Scene', 'Shader', 'Sharpen', 'Shuffle', 'ShuffleCopy', 'ShuffleViews', 'SideBySide',
    'SoftClip', 'Soften', 'Spark', 'Sparkles', 'Sphere', 'SplineWarp', 'SplitAndJoin', 'SpotLight', 'Stabilize', 
    'StickyNote', 'STMap', 'Switch', 'TemporalMedian', 'Text', 'Time', 'TimeBlur', 'TimeDissolve', 'TimeEcho', 
    'TimeOffset', 'TimeWarp', 'Tracker', 'Transform', 'Truelight', 'TVIScale', 'Unpremult', 'VectorBlur', 
    'Vectorfield', 'Viewer', 'VolumeRays', 'Write', 'WriteGeo', 'ZBlur', 'ZMerge', 'ZSlice'
]

# fmt:on
# pylint: enable=line-too-long
NK_PREFS = NKSettings()
NK_IS_COMMERCIAL = not (nuke.env.get("indie") or nuke.env.get("nc"))
NK_RPC_CLIENT = Presence("1503841982743707718")
NK_UPDATE_DETAILS = RPCUpdateDetails("nuke")
NK_SESSION = SessionInfo()
NK_SETTINGS_WINDOW: QtSettingsGUIMenu | None = None

####################
# Property Getters #
####################


class NKContext:
    @classmethod
    def capture(cls) -> "NKContext":
        return cls()

    def get_app_str(self, include_version: bool = False) -> str:
        version = nuke.env.get("NukeVersionString")
        studio = nuke.env.get("studio")
        x = nuke.env.get("nukex")
        appname = "NukeX" if x else "NukeStudio" if studio else "Nuke"
        nc_str = " Non-Commercial" if not NK_IS_COMMERCIAL else ""
        if include_version:
            return f"{appname} {version}{nc_str}"
        else:
            return f"{appname}{nc_str}"

    def get_memory_usage(self) -> str:
        mem_bytes = nuke.memory2.usage()
        return f"Using {get_file_size_str(mem_bytes)} of memory"

    def get_frame_range(self) -> Tuple[int, int]:
        frame_range = nuke.root().frameRange()
        return (frame_range.first(), frame_range.last())

    def get_active_node(self) -> Tuple[str, str] | None:
        if not NK_IS_COMMERCIAL:
            return None
        try:
            active_node = nuke.selectedNode()
        except ValueError:
            return None
        if active_node is None:
            return None
        node_name = active_node.name()
        node_class = active_node.Class()
        return (node_name, node_class)

    def get_num_nodes(self) -> str:
        if (
            not NK_IS_COMMERCIAL
        ):  # This doesn't count nodes in groups; use it for only NC users
            nodes = nuke.root().numNodes()
        else:
            nodes = len(nuke.allNodes(recurseGroups=True))
        return nk_plural(nodes, "node")

    def get_io_nodes(self) -> str | None:
        if not NK_IS_COMMERCIAL:
            return None
        read_nodes = nuke.allNodes("Read")
        write_nodes = nuke.allNodes("Write")
        if read_nodes is not None and write_nodes is not None:
            if read_nodes and write_nodes:
                return (
                    f"{nk_plural(len(read_nodes), 'read node')}; "
                    f"{nk_plural(len(write_nodes), 'write node')}"
                )
            elif read_nodes:
                return nk_plural(len(read_nodes), "read node")
            elif write_nodes:
                return nk_plural(len(write_nodes), "write node")
        elif read_nodes is not None and read_nodes:
            return nk_plural(len(read_nodes), "read node")
        elif write_nodes is not None and write_nodes:
            return nk_plural(len(write_nodes), "write node")
        else:
            return None

    def get_num_layers(self) -> str:
        return nk_plural(len(nuke.layers()), "layer")

    def get_viewer_str(self) -> str | None:
        """Construct a string representing the viewing context: the node
        being viewed through the viewer, the channel being viewed, and the
        viewer process (if not sRGB)"""
        if not NK_IS_COMMERCIAL:
            return None
        viewer = nuke.activeViewer()
        if viewer is None:
            return None
        node = viewer.node()
        idx = viewer.activeInput()
        upstream = node.input(idx) if idx is not None else None
        if upstream is None:
            return None
        channels = node["channels"].value()
        vp = node["viewerProcess"].value()
        parts = [f"Viewing {upstream.name()}"]
        if channels:
            parts.append(f"({channels})")
        if vp and vp != "sRGB":
            parts.append(f"in {vp}")
        return " ".join(parts)

    def get_color_management(self) -> str:
        cm = nuke.root()["colorManagement"].value()
        return f"Color management: {cm}"

    def get_comp_name(self) -> str:
        try:
            return Path(nuke.scriptName()).name
        except RuntimeError:
            return "Unsaved Script"

    def get_fps(self) -> float:
        return nuke.root().realFps()

    def get_format_str(self) -> str:
        fmt = nuke.root().format()
        fmt_name = fmt.name().replace("_", " ").strip()
        return f"{fmt_name} ({fmt.width()}x{fmt.height()})"

    def get_scaling_info(self) -> str | None:
        root = nuke.root()
        viewer = nuke.activeViewer()
        if root["proxy"].value():
            proxy = root["proxy_scale"].value()
        else:
            proxy = 1
        if not NK_IS_COMMERCIAL and proxy != 1:
            return f"Proxy {proxy}x"
        elif NK_IS_COMMERCIAL:
            if viewer is not None:
                downrez = viewer.node()["downrez"].value()
            else:
                downrez = 1
            if proxy != 1 and downrez != 1:
                return f"Proxy {proxy}x | Downrez 1/{downrez}"
            elif proxy != 1:
                return f"Proxy {proxy}x"
            elif downrez != 1:
                return f"Downrez 1/{downrez}"
        return None

    def get_frame_info(self) -> str:
        frame = nuke.frame()
        fps = self.get_fps()
        return f"Frame {frame} ({fps}fps)"

#######
# RPC #
#######


def nk_update_large_icon(ctx: NKContext):
    NK_UPDATE_DETAILS.large_icon = "nuke"
    NK_UPDATE_DETAILS.large_icon_text = ctx.get_app_str(NK_PREFS.displayVersion)


def nk_update_small_icon(ctx: NKContext):
    NK_UPDATE_DETAILS.small_icon = None
    NK_UPDATE_DETAILS.small_icon_text = ""
    if not NK_IS_COMMERCIAL:
        return
    if NK_PREFS.displaySmallIcon:
        res = ctx.get_active_node()
        if res is not None:
            if res[1] not in NK_ICONS:
                return
            NK_UPDATE_DETAILS.small_icon = res[1].lower()
            NK_UPDATE_DETAILS.small_icon_text = f"{res[0]} ({res[1]})"


def nk_handle_active_node(ctx: NKContext) -> str | None:
    node = ctx.get_active_node()
    if node is None:  # get_active_node returns None on non-commercial/indie
        return
    if (
        (  # User has set details or state to a fixed 'active node' display
            not NK_PREFS.detailsCycle
            and NK_PREFS.detailsType == "active_node"
            or not NK_PREFS.stateCycle
            and NK_PREFS.stateType == "active_node"
        )
        or (  # Icons disabled
            not NK_PREFS.displaySmallIcon
        )
        or (  # Node has no valid icon
            node is not None and node[1] not in NK_ICONS
        )
    ):
        if node is None:
            return "No nodes selected"
        else:
            return f"{node[0]} ({node[1]})"
    else:  # Node has a small icon which will be displayed AND we're in a cycle: skip
        return None


NK_DISPLAY_TYPES = {
    "memory_usage": lambda ctx: ctx.get_memory_usage(),
    "num_nodes": lambda ctx: ctx.get_num_nodes(),
    "active_node": nk_handle_active_node,
    "io_nodes": lambda ctx: ctx.get_io_nodes(),
    "num_layers": lambda ctx: ctx.get_num_layers(),
    "frame": lambda ctx: ctx.get_frame_info(),
    "viewer_info": lambda ctx: ctx.get_viewer_str(),
    "color_management": lambda ctx: ctx.get_color_management(),
    "comp_name": lambda ctx: ctx.get_comp_name(),
    "format": lambda ctx: ctx.get_format_str(),
    "scaling": lambda ctx: ctx.get_scaling_info(),
}


# Nuke does not provide a way to get the frame range of what's actually rendering
# since it happens through an execute dialog/function which doesn't get hooked
# This is just an approximation.
def nk_update_presence_details(ctx):
    NK_UPDATE_DETAILS.details_text = ""
    # Rendering Details
    if NK_PREFS.enableDetails and NK_SESSION.is_rendering:
        fname = ctx.get_comp_name()
        NK_UPDATE_DETAILS.details_text = format_render_details(
            file_name=fname,
            rendered_frames=NK_SESSION.rendered_frames,
            prefs=RenderSettings(
                displayRenderStats=NK_PREFS.displayRenderStats,
                displayFileName=NK_PREFS.displayFileName,
                displayFrames=NK_PREFS.displayFrames,
            ),
        )
    elif NK_PREFS.enableDetails:
        update_slot(
            ctx, "details", NK_PREFS, NK_UPDATE_DETAILS, NK_DISPLAY_TYPES, NK_SESSION
        )


def nk_update_presence():
    if NK_PREFS.generalEnable:
        ctx = NKContext.capture()
        if ctx is None:
            return
        if NK_PREFS.detailsCycle or NK_PREFS.stateCycle:
            advance_cycle(NK_SESSION, NK_DISPLAY_TYPES)
        nk_update_large_icon(ctx)
        nk_update_small_icon(ctx)
        nk_update_presence_details(ctx)
        update_slot(
            ctx, "state", NK_PREFS, NK_UPDATE_DETAILS, NK_DISPLAY_TYPES, NK_SESSION
        )
        update_buttons(NK_UPDATE_DETAILS, NK_PREFS)
        push_rpc_update(
            NK_SESSION, NK_UPDATE_DETAILS, NK_PREFS, NK_RPC_CLIENT, "nuke", nuke.error
        )
    elif NK_SESSION.connected:
        try:
            NK_RPC_CLIENT.clear()
        except Exception as e:  # noqa: BLE001
            nuke.warning(f"[NukePresence] clear failed: {e}")
            NK_SESSION.connected = False


def nk_on_setting_change():
    if time.time() - NK_SESSION.last_update > DISCORD_SHORT_TERM_RATE_LIMIT:
        nk_update_presence()


#############
# Threading #
#############


class NKBackgroundWorker:
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
        )

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=5)

    def _run(self):
        while not self._stop_event.wait(NK_PREFS.generalUpdate):
            try:
                nuke.executeInMainThreadWithResult(nk_update_presence)
            except Exception as e:
                nuke.executeInMainThreadWithResult(
                    lambda e=e: nuke.warning(f"[NukePresence] Update Error: {e}")
                )


#############
# Callbacks #
#############


def nk_install_render_callbacks():
    nuke.addBeforeRender(on_render_start, args=(NK_SESSION,))
    nuke.addAfterFrameRender(on_frame_render_end, args=(NK_SESSION,))
    nuke.addAfterRender(on_render_end, args=(NK_SESSION,))


def nk_uninstall_render_callbacks():
    nuke.removeBeforeRender(on_render_start, args=(NK_SESSION,))
    nuke.removeAfterFrameRender(on_frame_render_end, args=(NK_SESSION,))
    nuke.removeAfterRender(on_render_end, args=(NK_SESSION,))


#####################
# GUI Settings Menu #
#####################


class NukeSettingsWindow(QtSettingsGUIMenu):
    def __init__(self, parent=None):
        super().__init__(NK_PREFS, nk_on_setting_change, "Nuke", parent)


def nk_open_settings():
    global NK_SETTINGS_WINDOW
    if NK_SETTINGS_WINDOW is not None and NK_SETTINGS_WINDOW.isVisible():
        NK_SETTINGS_WINDOW.raise_()
        NK_SETTINGS_WINDOW.activateWindow()
        return

    nuke_main_window = QtW.QApplication.activeWindow()

    NK_SETTINGS_WINDOW = NukeSettingsWindow(parent=nuke_main_window)

    if NK_SETTINGS_WINDOW is None:
        nuke.warning("[NukePresence] could not register settings menu")
        return
    NK_SETTINGS_WINDOW.show()


###################
# Plugin Lifetime #
###################


class NKMenu:
    def __init__(self, prefs, worker):
        menubar = nuke.menu("Nuke")
        discord_menu = menubar.addMenu("Discord")
        self.enable_item = discord_menu.addCommand(
            "Enable Rich Presence", command=self.start
        )
        self.disable_item = discord_menu.addCommand(
            "Disable Rich Presence", command=self.stop
        )
        discord_menu.addCommand("Settings", command=nk_open_settings)
        self.prefs = prefs
        self.worker = worker
        if self.prefs.generalEnable and not NK_SESSION.connected:
            NK_SESSION.connected = connect_rpc(NK_RPC_CLIENT, "Nuke", nuke.warning)
        self._sync_menu_state()

    def _sync_menu_state(self):
        """Match the enable/disable menu items' enabled state to generalEnable."""
        self.enable_item.setEnabled(not self.prefs.generalEnable)
        self.disable_item.setEnabled(self.prefs.generalEnable)

    def start(self):
        if not NK_SESSION.connected:
            NK_SESSION.connected = connect_rpc(NK_RPC_CLIENT, "Nuke", nuke.warning)
        self.prefs.generalEnable = True
        self.prefs.flush()
        self._sync_menu_state()

    def stop(self):
        self.prefs.generalEnable = False
        self.prefs.flush()
        self._sync_menu_state()


NK_WORKER = NKBackgroundWorker()
NK_PREFS.setup_persistence(
    path=os.path.join(os.path.expanduser("~/.nuke"), "nuke_presence_preferences.json"),
    app_name="nuke",
    warn=nuke.warning,
)
NK_MENU = NKMenu(NK_PREFS, NK_WORKER)
NK_WORKER.start()
nk_install_render_callbacks()
atexit.register(force_clear_on_exit, NK_RPC_CLIENT)
