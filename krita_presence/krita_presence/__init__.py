"""KritaPresence package entry point.

Krita imports this package and expects the extension to register itself as an
import side effect, which `krita_presence.krita_presence` does at module scope.
The re-export list is explicit so the public surface is greppable and static
analysis can follow it.
"""

from .krita_presence import (  # noqa: F401
    IdleDetector,
    KPContext,
    KPExtension,
    KPPlugin,
    KPSettings,
    KP_TOOL_MAPPING,
)

__all__ = [
    "IdleDetector",
    "KPContext",
    "KPExtension",
    "KPPlugin",
    "KPSettings",
    "KP_TOOL_MAPPING",
]
