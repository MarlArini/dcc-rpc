"""
Cached frozensets of render-engine-contributed node types.
`cmds.listNodeTypes("light" | "shader" | "texture")` returns
the union of types registered by every loaded render-engine
plug-in. We just rebuild the sets when a plug-in load/unload
could have changed the contents.

"""
from typing import FrozenSet

import maya.cmds as cmds  # pyright: ignore[reportMissingImports] pylint: disable=import-error


# All extension-contributed light/material/texture node type names.
# Default to empty until rebuild() is called for the first time.
MP_EXT_LIGHTS: FrozenSet[str] = frozenset()
MP_EXT_MATERIALS: FrozenSet[str] = frozenset()
MP_EXT_TEXTURES: FrozenSet[str] = frozenset()


def rebuild() -> None:
    """Refresh the cached type sets from cmds.listNodeTypes.

    Called at plug-in startup and on every kAfterPluginLoad /
    kAfterPluginUnload. Wrapped in try/except in case of
    listNodeTypes returning None or raising."""
    global MP_EXT_LIGHTS, MP_EXT_MATERIALS, MP_EXT_TEXTURES
    try:
        MP_EXT_LIGHTS = frozenset(cmds.listNodeTypes("light") or [])
    except RuntimeError:
        MP_EXT_LIGHTS = frozenset()
    try:
        MP_EXT_MATERIALS = frozenset(cmds.listNodeTypes("shader") or [])
    except RuntimeError:
        MP_EXT_MATERIALS = frozenset()
    try:
        MP_EXT_TEXTURES = frozenset(cmds.listNodeTypes("texture") or [])
    except RuntimeError:
        MP_EXT_TEXTURES = frozenset()
