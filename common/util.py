"""Utility functions not directly related to RPC updates"""

import re

from .util_classes import RenderSettings, SessionInfo


def plural(count: int, prefix: str, postfix: str = "s") -> str:
    """Take a count of something and its word prefix and postfix, and
    return the singular or plural form depending on the count - e.g., '1',
    'mesh', 'es' -> '1 mesh'; '2', 'mesh', 'es' -> '2 meshes'."""
    if count == 1:
        return f"{count} {prefix}"
    return f"{count} {prefix}{postfix}"


def is_url(s: str) -> bool:
    """Evaluate a string and return True if it is a valid URL (may miss some edge cases)"""
    regex = re.compile(
        r"^https?://"  # http:// or https://
        r"(?:[a-zA-Z0-9-]+\.)+"  # subdomain(s)
        r"[a-zA-Z]{2,}"  # top-level domain
        r"(?:\:\d{1,5})?"  # optional port
        r"(?:/[^\s]*)?$",  # optional path
        re.IGNORECASE,
    )
    return regex.match(s) is not None


def pad_text(s: str) -> str:
    """
    If the user string is more than one character, return it. Else,
    return a length-2 empty string to satisfy Discord's requirement.
    """
    s = str(s)
    return s if len(s) > 1 else "  "


def shorten_number(n: int) -> str:
    """Take a number between 0 and 1,000,000,000 and shorten it
    by adding an appropriate postfix (k, m, b) for more compact
    display in the rich presence fields (useful for poly counts)
    """
    if n < 1_000:
        return str(n)
    elif n < 1_000_000:
        return f"{n // 1_000}k"
    elif n < 1_000_000_000:
        return f"{n // 1_000_000}m"
    else:
        return f"{n // 1_000_000_000}b"


def get_file_size_str(b: float) -> str:
    """
    Convert bytes to a readable string. Snippet taken
    directly from https://github.com/abrasic/blendpresence.
    """
    for u in [" bytes", " KB", " MB", " GB", " TB"]:
        if b < 1024.0 or u == " PB":
            break
        b /= 1024.0
    return f"{b:.2f} {u}"


def on_render_start(info: SessionInfo):
    info.is_rendering = True


def on_render_end(info: SessionInfo):
    info.is_rendering = False
    info.rendered_frames = 0


def on_frame_render_end(info: SessionInfo):
    info.rendered_frames += 1


def format_render_details(
    file_name: str | None = None,
    res: tuple[int, int] | None = None,
    rendered_frames: int | None = None,
    total_frames: int | None = None,
    fps: float | int | None = None,
    prefs: RenderSettings = RenderSettings(),
) -> str:
    """Format rendering details string using a concat-join approach."""
    parts = ["Rendering"]

    if file_name and prefs.displayFileName:
        parts.append(file_name)

    stats = []
    if res is not None and prefs.displayRenderStats:
        stats.append(f"{res[0]}x{res[1]}")

    frame_fps = []
    if prefs.displayFrames and total_frames:
        if rendered_frames is not None:
            frame_fps.append(f"Frame {rendered_frames} of {total_frames}")
        else:
            frame_fps.append(f"{total_frames} frames")

    if fps is not None:
        frame_fps.append(f"@{fps}fps")

    if frame_fps:
        stats.append(" ".join(frame_fps))

    if stats:
        return " ".join(parts) + ": " + ", ".join(stats)
    return " ".join(parts)
