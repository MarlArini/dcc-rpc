"""Plugin settings class for the Maya plugin, with render-specific functionality
and optionVar-based persistence."""

from dataclasses import dataclass, field, fields
from typing import Any, ClassVar, Dict, List, Tuple, get_type_hints

import maya.cmds as cmds  # pyright: ignore[reportMissingImports] pylint: disable=import-error

from common import SharedSettings, RenderSettings


@dataclass
class MPSettings(SharedSettings, RenderSettings):
    """Store user preferences and persist across sessions with OptionVars"""

    # pylint: disable=invalid-name
    _PREFIX: ClassVar[str] = "mayaPresence_"
    INFO_CHOICES: ClassVar[List[Tuple[str, str]]] = [
        ("Scene name", "scene"),
        ("Mesh count", "mesh"),
        ("Poly count", "poly"),
        ("Joint count", "joint"),
        ("Light count", "light"),
        ("Camera count", "cam"),
        ("Blendshape count", "blendshape"),
        ("Material count", "mat"),
        ("Texture count", "tex"),
        ("File size", "size"),
        ("Current frame", "frame"),
        ("Active object", "active"),
        ("Current tool context", "context"),
    ]
    _INITIAL_DEFAULTS: ClassVar[Dict[str, Any]] = {
        "detailsType": "scene",
        "stateType": "poly",
    }
    countExtensions: bool = field(
        default=True,
        metadata={
            "group": "General",
            "label": (
                "Count lights, materials, and textures from third-party renderers"
            ),
        },
    )
    useRenderHooks: bool = field(
        default=True,
        metadata={
            "group": "Rendering",
            "label": "Add MEL hook to scene pre/post render events for render detection",
        },
    )
    displayGPU: bool = field(
        default=False,
        metadata={
            "group": "Rendering",
            "label": "Display GPU name in details when rendering",
        },
    )

    def __post_init__(self):
        for f in fields(self):
            ov = self._PREFIX + f.name
            if cmds.optionVar(exists=ov):
                v = cmds.optionVar(query=ov)
                f_type = _FIELD_TYPES[f.name]
                if f_type is bool:
                    v = bool(v)
                object.__setattr__(self, f.name, v)
            elif f.name in self._INITIAL_DEFAULTS:
                object.__setattr__(self, f.name, self._INITIAL_DEFAULTS[f.name])
        # From here on, attribute writes persist to optionVars.
        object.__setattr__(self, "_loaded", True)

    def __setattr__(self, name: str, value: Any):
        object.__setattr__(self, name, value)
        # Skip persistence for private attrs and for the bootstrap phase (the
        # dataclass-generated __init__ runs field assignments BEFORE __post_init__)
        if name.startswith("_") or not getattr(self, "_loaded", False):
            return
        if name not in _FIELD_TYPES:
            return
        ov = self._PREFIX + name
        kind = _FIELD_TYPES[name]
        if kind is bool or kind is int:
            cmds.optionVar(intValue=(ov, int(value)))
        elif kind is float:
            cmds.optionVar(floatValue=(ov, float(value)))
        else:
            cmds.optionVar(stringValue=(ov, str(value)))

    def reset(self):
        """Restore all fields to default values (Maya-specific defaults take precedence)."""
        for f in fields(self):
            default = self._INITIAL_DEFAULTS.get(f.name, f.default)
            setattr(self, f.name, default)


# {field name -> resolved type} for MPSettings' dataclass fields
_TYPE_HINTS = get_type_hints(MPSettings)
_FIELD_TYPES: Dict[str, Any] = {f.name: _TYPE_HINTS[f.name] for f in fields(MPSettings)}
