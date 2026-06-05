import re
from typing import Callable, List, Tuple

import maya.cmds as cmds  # pyright: ignore[reportMissingImports] pylint: disable=import-error

from common import on_render_start, on_render_end, on_frame_render_end
from .shared_state import mp_print, MP_PREFS, MP_SESSION
from .rpc import mp_update_presence

MP_HOOK_START = "/* MayaPresence:Hook:Begin */"
MP_HOOK_END = " /* MayaPresence:Hook:End */"


def mp_wrap_mel(
    py_call: Callable[[], None], surface_except: bool = False, wrap: bool = True
) -> str:
    """Return a MEL fragment that calls the Python function `py_call`.

    The fragment imports the function's own module (via py_call.__module__)
    rather than going through the top-level `maya_presence` module — that
    matters because Maya's plug-in loader doesn't register maya_presence.py
    in sys.modules, so `import maya_presence` from MEL creates a fresh
    duplicate module whose namespace wouldn't have these functions unless
    we explicitly re-exported them. Submodules under mayapresence_util/
    DO go through normal import machinery and ARE cached, so importing
    them by their dotted name lands on the canonical instance.
    """
    mp = "_mp"
    start = f"{MP_HOOK_START} " if wrap else ""  # fmt: skip
    end = f"{MP_HOOK_END}" if wrap else ""  # fmt:skip
    exc = ' as e:","\tprint(e)")' if surface_except else ':","\tpass")'
    exc = f'"except Exception{exc}'
    module_path = py_call.__module__
    return (
        f"{start}"
        f'python("try:","\timport {module_path} as {mp}",'
        f'"\t{mp}.{py_call.__name__}()",'
        f"{exc}"
        f"{end}"
    )


def mp_on_render_start():
    on_render_start(MP_SESSION)
    mp_update_presence()


def mp_on_render_end():
    on_render_end(MP_SESSION)
    mp_update_presence()


def mp_on_frame_render_end():
    on_frame_render_end(MP_SESSION)
    mp_update_presence()


# Render-hook install sites: (node, attr, py_call).
#
#   defaultRenderGlobals  — Maya's stock node, used by Maya Software,
#                           Maya Hardware, Arnold, V-Ray, RenderMan, etc.
#                           Per empirical observation, preMel/postMel
#                           fire per-frame and postRenderMel fires once
#                           at the end of a sequence.
#
#   redshiftOptions       — Redshift's own options node, only exists when
#                           the Redshift plug-in is loaded. Redshift's
#                           semantics are cleaner: preRenderMel and
#                           postRenderMel bracket the entire render;
#                           postRenderFrameMel fires per frame.
#
_RENDER_HOOK_SITES: List[Tuple[str, str, Callable[[], None]]] = [
    ("defaultRenderGlobals", "preMel", mp_on_render_start),
    ("defaultRenderGlobals", "postMel", mp_on_render_end),
    ("defaultRenderGlobals", "postRenderMel", mp_on_frame_render_end),
    ("redshiftOptions", "preRenderMel", mp_on_render_start),
    ("redshiftOptions", "postRenderMel", mp_on_render_end),
    ("redshiftOptions", "postRenderFrameMel", mp_on_frame_render_end),
]


def _hook_state(node: str, attr: str) -> bool:
    """Returns True if a hook is currently installed at <node>.<attr> or
    the attribute doesn't exist (e.g., an engine that isn't loaded), and
    False if the attr exists but our fragment isn't there."""
    try:
        existing = cmds.getAttr(f"{node}.{attr}")
    except (RuntimeError, ValueError):  # fmt: skip
        return True
    if existing is None:
        return False
    return MP_HOOK_START in existing


def mp_check_render_handlers_installed() -> bool:
    """Return True if all hooks are installed."""
    for node, attr, _py in _RENDER_HOOK_SITES:
        if not _hook_state(node, attr):
            return False
    return True


def mp_install_render_handlers():  # pylint: disable=unused-argument
    """Append our hook fragment to each render-hook site that exists and
    doesn't already have our fragment."""
    if not MP_PREFS.useRenderHooks:
        return
    for node, attr, py_call in _RENDER_HOOK_SITES:
        state = _hook_state(node, attr)
        if state:
            continue  # already installed or does not exist
        plug = f"{node}.{attr}"
        try:
            existing = cmds.getAttr(plug) or ""
            cmds.setAttr(plug, existing + mp_wrap_mel(py_call), type="string")
        except (RuntimeError, ValueError) as e:
            mp_print(f"could not install handler {plug}: {e}")


def mp_uninstall_render_handlers(*args):  # pylint: disable=unused-argument
    """Strip hooks from every applicable site."""
    pattern = re.compile(
        re.escape(MP_HOOK_START) + r".*?" + re.escape(MP_HOOK_END), re.DOTALL
    )
    for node, attr, _py in _RENDER_HOOK_SITES:
        plug = f"{node}.{attr}"
        try:
            existing = cmds.getAttr(plug)
        except RuntimeError:
            continue  # node not present
        if not existing:
            continue
        stripped = pattern.sub("", existing)
        if stripped == existing:
            continue
        try:
            cmds.setAttr(plug, stripped, type="string")
        except (RuntimeError, ValueError) as e:
            mp_print(f"could not restore handler {plug}: {e}")
