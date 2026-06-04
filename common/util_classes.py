"""Classes (settings, session, details) used in all or most plugins"""

from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List
import time


@dataclass
class SharedSettings:
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
    """Simple convenience mixin class for applications with colored icons, providing
    settings fields for whether to enable the icons and what color names to use."""

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


@dataclass
class RenderSettings:
    """Convenience mixin class for applications with displayable rendering state, providing
    settings fields for whether to display the engine, override the details field, display
    the file name, and display the frames rendered."""

    # pylint: disable=invalid-name
    displayEngine: bool = field(
        default=True,
        metadata={"group": "Details", "label": "Display active render engine on hover"},
    )
    displayRenderStats: bool = field(
        default=True,
        metadata={"group": "Details", "label": "Display render stats in details"},
    )
    displayFileName: bool = field(
        default=False,
        metadata={"group": "Details", "label": "Display file name when rendering"},
    )
    displayFrames: bool = field(
        default=True,
        metadata={"group": "Details", "label": "Display frames rendered in details"},
    )


class RPCUpdateDetails:
    """Class to hold data for each parameter of the RPC update"""

    def __init__(self, app_icon_name):
        self.start_time: float = time.time()
        self.state_text: str = "  "
        self.details_text: str = "  "
        self.small_icon: str | None = None
        self.small_icon_text: str = ""
        self.large_icon: str = app_icon_name
        self.large_icon_text: str = ""
        self.buttons: List[Dict] = []


class SessionInfo:
    """Class to hold information about a RPC session with the
    application"""

    start_time: float = time.time()
    last_update: float = 0.0
    connected: bool = False
    is_rendering: bool = False
    rendered_frames: int = 0
    cycle_iter: int = 0
