"""Functionality for finding the colored icon to present to a user
if a plugin supports colored icons (GIMP, Krita, Substance 3D Painter)"""
from .color_find import ( # noqa: F401
    find_closest,
    SUBSTANCEPAINTER_PAINT_SUBSET,
    SUBSTANCEPAINTER_PHYSPAINT_SUBSET
)
