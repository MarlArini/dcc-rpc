"""AI-generated (Claude Opus 4.7): fake `maya` package root."""
from __future__ import annotations

# Submodules autoload here so `import maya.cmds` and `import maya.api.OpenMaya`
# both succeed via the natural package mechanism.
from . import api  # noqa: F401
from . import app  # noqa: F401
from . import cmds  # noqa: F401
