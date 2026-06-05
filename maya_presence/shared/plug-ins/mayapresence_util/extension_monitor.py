"""Class for monitoring the render engine plugins loaded in Maya, to help with
counting lights, materials, and textures for specific engines."""
from enum import Enum

import maya.cmds as cmds # pyright: ignore[reportMissingImports] pylint: disable=import-error

class MPExtensionMonitor:
    """
    Watch known render engine plugins (Redshift, Arnold, V-Ray, RenderMan, Octane).
    We maintain whether the engine is loaded and a list of its custom types, so
    if the user enables counting lights, materials, or textures from the engine
    we can iterate the types and count them with `cmds.ls`.
    """

    class Engine:
        def __init__(
            self, pn: str, rn: str, light_path=None, mat_path=None, tex_path=None
        ):
            self.plugin_name = pn
            self.registry_name = rn
            self.light_path = light_path or f"rendernode/{rn}/light"
            self.material_path = mat_path or f"rendernode/{rn}/shader"
            self.texture_path = tex_path or f"rendernode/{rn}/texture"
            self.loaded = False
            self.types: dict | None = None

    class TypeCategory(Enum):
        LIGHT = 0
        MATERIAL = 1
        TEXTURE = 2

    def __init__(self):
        self.monitored_engines = {
            "Redshift": self.Engine("redshift4maya", "redshift"),
            "Arnold": self.Engine("mtoa", "arnold"),
            "V-Ray": self.Engine("vrayformaya", "vray"),
            "RenderMan": self.Engine(
                "RenderMan_For_Maya",
                "renderman",
                mat_path="rendernode/renderman/bxdf",
                tex_path="rendernode/renderman/pattern",
            ),
            "Octane": self.Engine(
                "octaneplugin",
                "octane",
                mat_path="rendernode/octane/material",
                light_path="rendernode/octane/node",  # some non-light stuff in here - refactor?
            ),
        }

    def init_engine(self, e: str):
        engine = self.monitored_engines[e]
        engine.loaded = True
        light_types = cmds.listNodeTypes(engine.light_path) or []
        mat_types = cmds.listNodeTypes(engine.material_path) or []
        tex_types = cmds.listNodeTypes(engine.texture_path) or []
        self.monitored_engines[e].types = {
            "light": light_types,
            "material": mat_types,
            "texture": tex_types,
        }

    def count(self, category: TypeCategory) -> int:
        types = []
        for engine in self.monitored_engines.values():
            if engine.loaded and engine.types is not None:
                types += engine.types.get(category.name.lower(), [])
        return len(cmds.ls(type=types)) if types else 0
