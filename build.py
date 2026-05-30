"""
Bundle each plugin into a deployable form under ./dist/.
"""
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
DIST = REPO / "dist"
COMMON_SRC = REPO / "common" / "common.py"
COLOR_SRC = REPO / "colors"  # package dir (color_find.py + palette.csv + iscc-nbs.csv + Attribution.txt)

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "build")


def _find_pypresence() -> Path:
    try:
        import pypresence
    except ImportError:
        sys.exit(
            "[build] pypresence is not installed in this Python environment.\n"
            "        Install with: python -m pip install pypresence"
        )
    return Path(pypresence.__file__).resolve().parent


def _drop_runtime(target: Path, pypresence_src: Path, colors: bool = False) -> None:
    """
    Copy common.py, pypresence/, and optionally the color-name package into a
    target directory. The target directory must already exist.
    """
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(COMMON_SRC, target / "common.py")
    if colors:
        shutil.copytree(COLOR_SRC, target / "colors", ignore=IGNORE)
    shutil.copytree(pypresence_src, target / "pypresence", ignore=IGNORE)


def _bundle_maya(pypresence_src: Path) -> None:
    """Produces:
        dist/maya_presence/                  (drop into MAYA_MODULE_PATH)
          maya_presence.mod
          shared/plug-ins/
            maya_presence.py
            common.py
            pypresence/
    """
    src = REPO / "maya_presence"
    dst = DIST / "maya_presence"
    shutil.copytree(src, dst, ignore=IGNORE)
    _drop_runtime(dst / "shared" / "plug-ins", pypresence_src)
    print(f"[build] maya_presence/  (Maya module: {dst.name})")


def _bundle_designer(pypresence_src: Path) -> None:
    """Produces:
        dist/designer_presence/
          designerpresence.sdplugin           (zip produced by makepackage.py)
          designerpresence/                   (sources retained next to the .sdplugin)
            pluginInfo.json
            makepackage.py
            designerpresence/                 (inner Python package)
              __init__.py
              common.py
              pypresence/
    """
    src = REPO / "substance_designer_presence" / "designerpresence"
    dst = DIST / "designer_presence" / "designerpresence"
    shutil.copytree(src, dst, ignore=IGNORE)
    inner = dst / "designerpresence"
    _drop_runtime(inner, pypresence_src)

    result = subprocess.run(
        [sys.executable, "makepackage.py"],
        cwd=dst, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        print("[build] makepackage.py failed:")
        print(result.stdout)
        print(result.stderr)
        sys.exit(1)

    # Surface the .sdplugin one level up for visibility.
    sdplugin = dst / "build" / "designerpresence.sdplugin"
    if sdplugin.exists():
        final = DIST / "designer_presence" / "designerpresence.sdplugin"
        shutil.move(str(sdplugin), str(final))
        print("[build] designer_presence/designerpresence.sdplugin")
    else:
        print("[build] makepackage.py ran but no .sdplugin was produced")


def _bundle_nuke(pypresence_src: Path) -> None:
    """Produces:
        dist/nuke_presence/                  (drop into ~/.nuke/)
          menu.py
          common.py
          pypresence/
    """
    src = REPO / "nuke_presence" / "menu.py"
    if not src.exists():
        print(f"[build] skip nuke_presence: {src.name} not found")
        return
    dst = DIST / "nuke_presence"
    dst.mkdir(parents=True)
    shutil.copy2(src, dst / "menu.py")
    _drop_runtime(dst, pypresence_src)
    print("[build] nuke_presence/")


def _bundle_painter(pypresence_src: Path) -> None:
    """Produces:
        dist/substance_painter_presence/     (drop into Painter user_plugins/startup/)
          __init__.py
          painter_presence.py
          common.py
          colors/
            __init__.py
            color_find.py
            palette.csv
            iscc-nbs.csv
            Attribution.txt
          pypresence/

    NOTE: Painter adds the plugin's own directory to sys.path on load, which is
    why `from common import ...` and `from colors import ...` inside
    painter_presence.py resolve to the siblings in this folder rather than
    needing to be `from .common` / `from .colors`.
    """
    src = REPO / "substance_painter_presence"
    if not (src / "painter_presence.py").exists():
        print("[build] skip substance_painter_presence: painter_presence.py not found")
        return
    dst = DIST / "substance_painter_presence"
    dst.mkdir(parents=True)
    shutil.copy2(src / "painter_presence.py", dst / "painter_presence.py")
    shutil.copy2(src / "__init__.py", dst / "__init__.py")
    _drop_runtime(dst, pypresence_src, colors=True)
    print("[build] substance_painter_presence/")


def _bundle_krita(pypresence_src: Path) -> None:
    """Produces:
        dist/krita_presence/                 (drop into pykrita/)
          krita_presence.desktop
          krita_presence/
            __init__.py
            krita_presence.py
            common.py
            colors/
              __init__.py
              color_find.py
              palette.csv
              iscc-nbs.csv
              Attribution.txt
            pypresence/
    """
    src_root = REPO / "krita_presence"
    desktop = src_root / "krita_presence.desktop"
    package_src = src_root / "krita_presence"
    if not desktop.exists() or not package_src.exists():
        print("[build] skip krita_presence: missing krita_presence.desktop or package dir")
        return
    dst_root = DIST / "krita_presence"
    dst_root.mkdir(parents=True)
    shutil.copy2(desktop, dst_root / "krita_presence.desktop")
    shutil.copytree(package_src, dst_root / "krita_presence", ignore=IGNORE)
    _drop_runtime(dst_root / "krita_presence", pypresence_src, colors=True)
    print("[build] krita_presence/")


def _bundle_gimp(pypresence_src: Path) -> None:
    """Produces:
        dist/gimp_presence/                  (drop into GIMP plug-ins/)
          gimp_presence.py
          common.py
          colors/
            __init__.py
            color_find.py
            palette.csv
            iscc-nbs.csv
            Attribution.txt
          pypresence/

    GIMP 3 discovers plug-ins as either a single file OR a directory containing
    a script with the same name. The directory form (used here) is required to
    bundle dependencies alongside the script.
    """
    src = REPO / "gimp_presence" / "gimp_presence.py"
    if not src.exists():
        print("[build] skip gimp_presence: gimp_presence.py not found")
        return
    dst = DIST / "gimp_presence"
    dst.mkdir(parents=True)
    shutil.copy2(src, dst / "gimp_presence.py")
    _drop_runtime(dst, pypresence_src, colors=True)
    print("[build] gimp_presence/")


def build() -> None:
    if not COMMON_SRC.exists():
        sys.exit(f"[build] missing {COMMON_SRC}")
    if not COLOR_SRC.exists():
        sys.exit(f"[build] missing {COLOR_SRC}")
    pypresence_src = _find_pypresence()

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    _bundle_maya(pypresence_src)
    _bundle_designer(pypresence_src)
    _bundle_nuke(pypresence_src)
    _bundle_painter(pypresence_src)
    _bundle_krita(pypresence_src)
    _bundle_gimp(pypresence_src)

    print(f"[build] done -> {DIST}")


if __name__ == "__main__":
    build()
