from pathlib import Path
import os
import pytest

from colors import color_find
from colors.color_find import (
    _check_csv,
    _load_iscc,
    _load_palette,
    _closest
)


file_path = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture(autouse=True)
def _reset_palette_cache():
    """Clear the module-level _PALETTE / _ISCC caches before and after each
    test so cache state from test_color_find.py (which runs first
    alphabetically and primes both globals via find_closest) doesn't make
    these exception/branch tests short-circuit through the cached path."""
    snap_p = color_find._PALETTE
    snap_i = color_find._ISCC
    color_find._PALETTE = None
    color_find._ISCC = None
    yield
    color_find._PALETTE = snap_p
    color_find._ISCC = snap_i


# Exceptions / branches
def test_find_csv_raises():
    with pytest.raises(FileNotFoundError):
        _check_csv(Path("/invalid path"), "no name")

def test_load_palette_raises():
    with pytest.raises(RuntimeError):
        _load_palette(path=Path(os.path.join(file_path, 'empty.csv')))

def test_load_iscc_raises():
    with pytest.raises(RuntimeError):
        _load_iscc(path=Path(os.path.join(file_path, 'empty.csv')))

def test_closest_raises():
    with pytest.raises(RuntimeError):
        _closest([], (0.1, 0.1, 0.1))

def test_iscc_skips_malformed():
    colors = _load_iscc(path=Path(os.path.join(file_path, 'malformed_iscc.csv')))
    assert len(colors) == 2
    assert colors[0].name == "Vivid Pink"
    assert colors[1].name == "Deep Pink"