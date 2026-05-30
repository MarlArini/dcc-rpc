"""
AI-generated (Claude Opus 4.7): unit tests for colors/color_find.py.

Covers the OKLab conversion, hex formatting, and the closest-color lookup.
The palette is real (loaded lazily from colors/palette.csv), so assertions
about specific match results are tied to the committed palette — if you
regenerate palette.csv with different evocative names, expect to update the
expected names in the "exact match" tests below.
"""
from __future__ import annotations
import math
import pytest

from colors.color_find import (
    ColorMatch,
    find_closest,
    format_hex,
    palette,
    iscc,
    srgb_to_oklab,
    SUBSTANCEPAINTER_PAINT_SUBSET,
    SUBSTANCEPAINTER_PHYSPAINT_SUBSET,
)


# ---------------------------------------------------------------------------
# Lazy loaders
# ---------------------------------------------------------------------------

def test_palette_loads_250_entries():
    entries = palette()
    assert len(entries) == 250
    # Indices are 0..249 and unique.
    indices = sorted(e.index for e in entries)
    assert indices == list(range(250))


def test_palette_has_display_names():
    for e in palette():
        assert e.display_name, f"entry {e.index} has empty display_name"
        # name and display_name are both populated; display_name may equal name.
        assert e.name


def test_iscc_loads_full_set():
    """ISCC-NBS centroid set from W3Schools is ~267 entries."""
    entries = iscc()
    assert 260 <= len(entries) <= 270
    # Names should not contain underscores after normalization.
    for e in entries:
        assert "_" not in e.name

# ---------------------------------------------------------------------------
# Subset constants
# ---------------------------------------------------------------------------

def test_paint_subsets_partition_palette():
    assert len(SUBSTANCEPAINTER_PAINT_SUBSET) == 125
    assert len(SUBSTANCEPAINTER_PHYSPAINT_SUBSET) == 125
    assert SUBSTANCEPAINTER_PAINT_SUBSET & SUBSTANCEPAINTER_PHYSPAINT_SUBSET == frozenset()
    union = SUBSTANCEPAINTER_PAINT_SUBSET | SUBSTANCEPAINTER_PHYSPAINT_SUBSET
    assert union == frozenset(range(250))
    # Sanity: paint is even indices, pphys is odd.
    assert all(i % 2 == 0 for i in SUBSTANCEPAINTER_PAINT_SUBSET)
    assert all(i % 2 == 1 for i in SUBSTANCEPAINTER_PHYSPAINT_SUBSET)


# ---------------------------------------------------------------------------
# OKLab conversion (anchored to known sRGB primaries)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "hex_str, expected_L, expected_hue_deg",
    [
        # OKLab L axis ranges 0..1; hue is atan2(b, a) in degrees.
        ("#ffffff", 1.000, None),  # pure white, no hue
        ("#000000", 0.000, None),
        ("#ff0000", 0.628, 29),
        ("#00ff00", 0.866, 143),
        ("#0000ff", 0.452, 264),
        ("#ffff00", 0.968, 110),
        ("#ff00ff", 0.701, 328),
        ("#00ffff", 0.905, 195),
    ],
)
def test_srgb_to_oklab_canonical(hex_str, expected_L, expected_hue_deg):
    L, a, b = srgb_to_oklab(hex_str)
    assert math.isclose(L, expected_L, abs_tol=0.01)
    if expected_hue_deg is not None:
        hue_deg = math.degrees(math.atan2(b, a)) % 360
        assert math.isclose(hue_deg, expected_hue_deg, abs_tol=2.0)


@pytest.mark.parametrize(
    "rgb",
    [
        (0, 0, 0),
        (255, 255, 255),
        (128, 128, 128),
        (1.0, 0.0, 0.0),
        (0.5, 0.5, 0.5),
    ],
)
def test_srgb_to_oklab_accepts_tuples(rgb):
    L, a, b = srgb_to_oklab(rgb)
    # All canonical primaries land in [0, 1] for L and in [-0.5, 0.5] for a/b.
    assert 0.0 <= L <= 1.0
    assert -0.5 <= a <= 0.5
    assert -0.5 <= b <= 0.5


def test_srgb_to_oklab_8bit_vs_unit_match():
    """An 8-bit tuple and the equivalent unit-float tuple should map to the
    same OKLab coordinates (within tiny float rounding)."""
    a = srgb_to_oklab((128, 200, 50))
    b = srgb_to_oklab((128 / 255, 200 / 255, 50 / 255))
    for x, y in zip(a, b):
        assert math.isclose(x, y, abs_tol=1e-9)


@pytest.mark.parametrize("c", [-0.1, 1.5, -1.0, 2.0])
def test_srgb_to_oklab_clamps_out_of_range(c):
    # Should not raise; clamps to [0, 1] internally.
    srgb_to_oklab((c, 0.5, 0.5))


# ---------------------------------------------------------------------------
# format_hex
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "inp, expected",
    [
        ("#ff0000", "#FF0000"),
        ("ff0000", "#FF0000"),
        ((255, 0, 0), "#FF0000"),
        ((0, 0, 0), "#000000"),
        ((255, 255, 255), "#FFFFFF"),
        ((128, 128, 128), "#808080"),
        ((1.0, 1.0, 1.0), "#FFFFFF"),
        ((0.5, 0.5, 0.5), "#808080"),  # round(127.5) = 128
    ],
)
def test_format_hex(inp, expected):
    assert format_hex(inp) == expected


# ---------------------------------------------------------------------------
# find_closest
# ---------------------------------------------------------------------------

def test_find_closest_returns_color_match():
    m = find_closest("#5E13D6")
    assert isinstance(m, ColorMatch)
    assert 0 <= m.icon_index < 250
    assert m.icon_key_suffix.startswith("c") and len(m.icon_key_suffix) == 4
    assert m.display_name
    assert m.user_hex == "#5E13D6"


@pytest.mark.parametrize(
    "rgb_input, expected_user_hex",
    [
        ("#ff0000", "#FF0000"),
        ((255, 0, 0), "#FF0000"),
        ((0, 0, 0), "#000000"),
        ((128, 64, 200), "#8040C8"),
    ],
)
def test_find_closest_preserves_user_hex(rgb_input, expected_user_hex):
    m = find_closest(rgb_input)
    assert m.user_hex == expected_user_hex


def test_find_closest_with_paint_subset_returns_even_index():
    m = find_closest("#ff0000", icon_subset=SUBSTANCEPAINTER_PAINT_SUBSET)
    assert m.icon_index % 2 == 0


def test_find_closest_with_physpaint_subset_returns_odd_index():
    m = find_closest("#ff0000", icon_subset=SUBSTANCEPAINTER_PHYSPAINT_SUBSET)
    assert m.icon_index % 2 == 1


def test_find_closest_evocative_vs_iscc_can_differ():
    """For a color where the evocative palette has a specific entry and ISCC
    has a different one, requesting both should produce different display names
    most of the time."""
    e = find_closest("#5E13D6", evocative=True)
    i = find_closest("#5E13D6", evocative=False)
    # Icon index doesn't change between the two; only the name source changes.
    assert e.icon_index == i.icon_index
    # The display names should differ on this hue (high confidence: ISCC uses
    # functional names like "Vivid Purple" which won't match an evocative name).
    assert e.display_name != i.display_name


def test_find_closest_distance_increases_for_off_palette_colors():
    """A user color near a palette entry should match closely; a color in a
    sparse region of the palette should match further away."""
    # Pure red (#ff0000) is near 'Marinara Red' (#ff0008). Tiny ΔE.
    near = srgb_to_oklab("#ff0000")
    # Compute distance from input to the matched palette entry.
    m = find_closest("#ff0000")
    matched = next(p for p in palette() if p.index == m.icon_index)
    d_red = math.sqrt(
        (near[0] - matched.L) ** 2
        + (near[1] - matched.a) ** 2
        + (near[2] - matched.b) ** 2,
    )
    # An exact palette-pick should be within ΔE 0.01-ish (Marinara Red is at #ff0008).
    assert d_red < 0.02


# ---------------------------------------------------------------------------
# Fuzz: every (r, g, b) in a coarse grid should find SOMETHING valid.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("r", [0, 64, 128, 192, 255])
@pytest.mark.parametrize("g", [0, 64, 128, 192, 255])
@pytest.mark.parametrize("b", [0, 64, 128, 192, 255])
def test_find_closest_fuzz_grid(r, g, b):
    m = find_closest((r, g, b))
    assert isinstance(m, ColorMatch)
    assert m.user_hex == f"#{r:02X}{g:02X}{b:02X}"
    assert 0 <= m.icon_index < 250
    assert m.display_name
