"""
Runtime closest-color lookup for the dcc-rpc plugins.
Mostly Claude Opus with some personal review/changes.
"""
from __future__ import annotations
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, NamedTuple, Tuple, List, cast, Sequence

_HERE = Path(__file__).resolve().parent
_PALETTE_PATH = _HERE / "palette.csv"
_ISCC_PATH = _HERE / "iscc-nbs.csv"

class ColorMatch(NamedTuple):
    icon_index: int
    icon_key_suffix: str
    display_name: str
    user_hex: str

SUBSTANCEPAINTER_PAINT_SUBSET: frozenset[int] = frozenset(range(0, 250, 2))    # 125 entries, evens
SUBSTANCEPAINTER_PHYSPAINT_SUBSET: frozenset[int] = frozenset(range(1, 250, 2))  # 125 entries, odds

# ----------------------------------------------------------------------------
# sRGB -> OKLab (Björn Ottosson's transform; mirrors select_palette.py)
# ----------------------------------------------------------------------------

def _srgb_decode(c: float) -> float:
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4

def _linear_srgb_to_oklab(r: float, g: float, b: float) -> Tuple[float, float, float]:
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b  # noqa: E741 (ambiguous name 'l')
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_ = l ** (1.0 / 3.0) if l >= 0 else -((-l) ** (1.0 / 3.0))
    m_ = m ** (1.0 / 3.0) if m >= 0 else -((-m) ** (1.0 / 3.0))
    s_ = s ** (1.0 / 3.0) if s >= 0 else -((-s) ** (1.0 / 3.0))
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )

def _hex_to_unit_srgb(hex_str: str) -> Tuple[float, float, float]:
    h = hex_str.lstrip("#")
    return (
        int(h[0:2], 16) / 255.0,
        int(h[2:4], 16) / 255.0,
        int(h[4:6], 16) / 255.0,
    )

def clamp(a, i, j):
    return i if a < i else j if a > j else a

def _normalize_rgb(rgb:
        str |
        Tuple[float, float, float] |
        Tuple[int, int, int]
        ) -> Tuple[float, float, float]:
    if isinstance(rgb, str):
        r, g, b = _hex_to_unit_srgb(rgb)
    else:
        r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
        if isinstance(rgb[0], int):
            r, g, b = r / 255.0, g / 255.0, b / 255.0
    return clamp(r, 0, 1), clamp(g, 0, 1), clamp(b, 0, 1)

def srgb_to_oklab(rgb) -> Tuple[float, float, float]:
    """Convert sRGB input (hex string or 3-tuple) to OKLab.
    Accepts:
      - "#RRGGBB" / "RRGGBB" hex string
      - (r, g, b) tuple of ints in [0, 255]
      - (r, g, b) tuple of floats in [0.0, 1.0]
    """
    r, g, b = _normalize_rgb(rgb)
    return _linear_srgb_to_oklab(_srgb_decode(r), _srgb_decode(g), _srgb_decode(b))

def format_hex(rgb) -> str:
    """Return "#RRGGBB" uppercase for the given input (hex string or tuple)."""
    r, g, b = _normalize_rgb(rgb)
    return "#{:02X}{:02X}{:02X}".format( #pylint: disable=consider-using-f-string
        round(r * 255), round(g * 255), round(b * 255),
    )

# ----------------------------------------------------------------------------
# Loaded data
# ----------------------------------------------------------------------------

@dataclass
class OKLABColor:
    name: str
    hex: str
    L: float #pylint: disable=invalid-name
    a: float
    b: float

@dataclass
class _PaletteEntry(OKLABColor):
    index: int
    key_suffix: str
    display_name: str

_PALETTE: List[_PaletteEntry] | None = None
_ISCC: List[OKLABColor] | None = None

def _check_csv(path, name):
    if not path.exists():
        raise FileNotFoundError(
            f"{name}.csv not found at {path}. "
            f"This plugin's installation is incomplete. "
            f"Reinstall from https://github.com/MarlArini/dcc-rpc "
            f"or report the issue."
        )

def _load_palette(path: Path = _PALETTE_PATH) -> List[_PaletteEntry]:
    global _PALETTE
    if _PALETTE is not None:
        return _PALETTE
    _check_csv(path, 'palette')
    out: list[_PaletteEntry] = []
    with path.open("r", encoding="utf-8", newline="") as fp:
        for row in csv.DictReader(fp):
            out.append(_PaletteEntry(
                index=int(row["index"]),
                key_suffix=row["key_suffix"],
                name=row["name"],
                display_name=row["display_name"],
                hex=row["hex"],
                L=float(row["L"]),
                a=float(row["a"]),
                b=float(row["b"]),
            ))
    if not out:
        raise RuntimeError(f"palette.csv at {path} contained no entries")
    _PALETTE = out
    return out

def _load_iscc(path: Path = _ISCC_PATH) -> List[OKLABColor]:
    global _ISCC
    if _ISCC is not None:
        return _ISCC
    _check_csv(path, 'iscc-nbs')
    out: list[OKLABColor] = []
    with path.open("r", encoding="utf-8", newline="") as fp:
        for row in csv.DictReader(fp):
            hex_str = row["hex"].strip()
            # ISCC entries use underscores: "Vivid_Pink" -> "Vivid Pink".
            name = row["name"].strip().replace("_", " ")
            if not hex_str or not name:
                continue
            L, a, b = srgb_to_oklab(hex_str) #pylint: disable=invalid-name
            out.append(OKLABColor(name=name, hex=hex_str.lower(), L=L, a=a, b=b))
    if not out:
        raise RuntimeError(f"{path.name} at {path} contained no entries")
    _ISCC = out
    return out

def palette() -> List[_PaletteEntry]:
    """Return the loaded evocative palette (lazy-loaded)."""
    return _load_palette()

def iscc() -> List[OKLABColor]:
    """Return the loaded ISCC names (lazy-loaded)."""
    return _load_iscc()

# ----------------------------------------------------------------------------
# Lookup
# ----------------------------------------------------------------------------

def _closest(
    colors: Sequence[OKLABColor],
    target_oklab: Tuple[float, float, float],
    palette_subset: Iterable[int] | None = None) -> OKLABColor:
    L, a, b = target_oklab #pylint: disable=invalid-name
    subset = None if palette_subset is None else frozenset(palette_subset)
    best: OKLABColor | None = None
    best_d2 = float("inf")
    for entry in colors:
        if subset is not None and isinstance(entry, _PaletteEntry) and entry.index not in subset:
            continue
        dL = entry.L - L #pylint: disable=invalid-name
        da = entry.a - a
        db = entry.b - b
        d2 = (dL * dL) + (da * da) + (db * db)
        if d2 < best_d2:
            best_d2 = d2
            best = entry
    if best is None:
        raise RuntimeError("No entries in palette")
    return best

def find_closest(
    rgb,
    evocative: bool=True,
    icon_subset: Iterable[int] | None = None,
) -> ColorMatch:
    """Return the best icon + name for the given sRGB color.

    Icon is always drawn from the 250-entry palette, optionally restricted
    by icon_subset (e.g. PAINT_SUBSET to get only the 125 Paint-brush
    icons). 

    Result fields are described on the ColorMatch NamedTuple.
    """
    target = srgb_to_oklab(rgb)
    user_hex = format_hex(rgb)

    # Icon search (possibly subset-restricted).
    icon_entry = cast(_PaletteEntry, _closest(palette(), target, icon_subset))

    # Skip querying again if the icon entry is the closest (no subset filter)
    if evocative and icon_subset is None:
        display_name = icon_entry.display_name
    elif evocative:
        display_name = cast(_PaletteEntry, _closest(palette(), target)).display_name
    else:
        display_name = _closest(iscc(), target).name

    return ColorMatch(
        icon_index=icon_entry.index,
        icon_key_suffix=icon_entry.key_suffix,
        display_name=display_name,
        user_hex=user_hex,
    )
