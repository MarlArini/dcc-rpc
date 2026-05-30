"""AI-generated (Claude Opus 4.7): fake `gi` namespace.

The real `gi` package lazy-loads GTK/Gimp via GObject Introspection; we only
need `gi.require_version` to be a no-op so the plugin's import succeeds.
"""
from __future__ import annotations


def require_version(name: str, version: str) -> None:  # noqa: D401
    """No-op. Real gi.require_version verifies the typelib version; tests
    don't need that since we substitute the modules directly."""
    return None


# Submodule autoload
from . import repository  # noqa: F401,E402
