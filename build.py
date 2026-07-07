"""
AI-Generated (Opus 4.7)
Bundle each plugin into a deployable form under ./dist/.
"""
import ast
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
DIST = REPO / "dist"
COMMON_SRC = REPO / "common"
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


def _to_relative_imports(text: str, modules: list[str], prefix: str = ".") -> str:
    """Prepend a prefix (defaults to a leading dot) to every `from <mod>` import line in `text` for
    each name in `modules`.

    Handles both bare-form (`from common import X`) and submodule-form
    (`from pypresence.presence import Presence`). Does not touch lines that
    are already relative (`from .common`) or imports of unrelated names that
    happen to start with the same prefix.
    """
    result = text
    for mod in modules:
        # The trailing space / dot match prevents accidentally rewriting an
        # unrelated module that happens to start with the same prefix.
        result = result.replace(f"from {mod} ", f"from {prefix}{mod} ")
        result = result.replace(f"from {mod}.", f"from {prefix}{mod}.")
    return result


def _validate_python(path: Path) -> None:
    """ast.parse the file so a broken rewrite is caught at build time, not at
    plugin-load time inside the host application."""
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as e:
        sys.exit(f"[build] rewritten file {path} has a syntax error: {e}")


def _write_rewritten(src: Path, dst: Path, modules: list[str], prefix: str = ".") -> None:
    """Read `src`, apply _to_relative_imports for `modules`, write to `dst`,
    and ast.parse the result to catch breakage at build time."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    rewritten = _to_relative_imports(src.read_text(encoding="utf-8"), modules, prefix)
    dst.write_text(rewritten, encoding="utf-8")
    _validate_python(dst)


def _write_common_subpackage(parent: Path, pypresence_src: Path) -> None:
    """Build a `common/` subpackage under `parent`:
        common/
          __init__.py
          ...
          pypresence/     (third-party, nested as a subpackage)
    """
    common_dir = parent / "common"
    shutil.copytree(COMMON_SRC, common_dir, ignore=IGNORE)
    for py_file in common_dir.glob("*.py"):
        _write_rewritten(py_file, py_file, modules=["pypresence"])
    shutil.copytree(pypresence_src, common_dir / "pypresence", ignore=IGNORE)


def _drop_runtime(target: Path, pypresence_src: Path, colors: bool = False) -> None:
    """
    Copy common/, pypresence/, and optionally the color-name package into a
    target directory. The target directory must already exist.
    """
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(COMMON_SRC, target / "common", ignore=IGNORE)
    if colors:
        shutil.copytree(COLOR_SRC, target / "colors", ignore=IGNORE)
    shutil.copytree(pypresence_src, target / "pypresence", ignore=IGNORE)


def _bundle_maya(pypresence_src: Path) -> None:
    """Produces:
        dist/maya_presence/                  (drop into MAYA_MODULE_PATH)
          maya_presence.mod
          plug-ins/
            maya_presence.py
            common/
            pypresence/
    """
    src = REPO / "maya_presence"
    dst = DIST / "maya_presence"
    shutil.copytree(src, dst, ignore=IGNORE)
    _drop_runtime(dst / "plug-ins", pypresence_src)
    print(f"[build] maya_presence/  (Maya module: {dst.name})")


def _bundle_designer(pypresence_src: Path) -> None:
    """Produces:
        dist/designer_presence/
          designerpresence.sdplugin           (zip produced by makepackage.py)
          designerpresence/                   (sources retained next to the .sdplugin)
            pluginInfo.json
            makepackage.py
            designerpresence/                 (inner Python package)
              __init__.py                     (rewritten: `from common` -> `from .common`)
              common/                          (subpackage; was a single common.py)
                __init__.py                    (was common.py, with `from .pypresence`)
                pypresence/                    (moved inside common/ so common.py's
                                                 sibling-import resolves under the package)

    Why the restructure: Designer doesn't put the loaded plugin's directory
    on sys.path before running module-level imports, so the older layout's
    `from common import ...` would ModuleNotFoundError at plugin load. We
    convert sibling imports to relative form and nest pypresence under common/
    because common.py is the only file that imports pypresence; keeping them
    co-located makes the relative-import surface trivial.
    """
    src = REPO / "substance_designer_presence" / "designerpresence"
    dst = DIST / "designer_presence" / "designerpresence"
    shutil.copytree(src, dst, ignore=IGNORE)
    inner = dst / "designerpresence"

    # Rewrite designerpresence/__init__.py: `from common ...` -> `from .common ...`.
    init_path = inner / "__init__.py"
    _write_rewritten(init_path, init_path, modules=["common"])

    # Build the common/ subpackage with pypresence/ nested inside it.
    # common.py auto-detects PySide6 (which Designer's plugin Python ships).
    _write_common_subpackage(inner, pypresence_src)

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
          painter_presence.py                (rewritten: from .common / .colors / .pypresence)
          common.py                           (rewritten: from .pypresence)
          colors/
            __init__.py
            color_find.py
            palette.csv
            iscc-nbs.csv
            Attribution.txt
          pypresence/

    Why we rewrite: in practice Painter does NOT have the loaded plugin's
    directory on sys.path by the time the module-level `from common import ...`
    runs (the bootstrap inside painter_presence.py that prepends sys.path
    runs AFTER those imports, so the bundled plugin used to fail to load).
    Converting sibling imports to relative form makes the bundle resolve
    purely against its own package structure.
    """
    src = REPO / "substance_painter_presence"
    if not (src / "painter_presence.py").exists():
        print("[build] skip substance_painter_presence: painter_presence.py not found")
        return
    dst = DIST / "substance_painter_presence"
    dst.mkdir(parents=True)
    # __init__.py is just `from .painter_presence import *` — already relative.
    shutil.copy2(src / "__init__.py", dst / "__init__.py")
    # painter_presence.py: rewrite three sibling-module names.
    _write_rewritten(
        src=src / "painter_presence.py",
        dst=dst / "painter_presence.py",
        modules=["common", "colors", "pypresence"],
    )
    # common package: rewrite the pypresence imports to use prefix ".."
    common_dir = dst / "common"
    shutil.copytree(COMMON_SRC, common_dir, ignore=IGNORE)
    for py_file in common_dir.glob("*.py"):
        _write_rewritten(
            src=py_file,
            dst=py_file,
            modules=["pypresence"],
            prefix="..",
        )
    # colors/ uses internal relative imports already — copy as-is.
    shutil.copytree(COLOR_SRC, dst / "colors", ignore=IGNORE)
    # pypresence/ is third-party — keep as-is.
    shutil.copytree(pypresence_src, dst / "pypresence", ignore=IGNORE)
    print("[build] substance_painter_presence/")


def _bundle_krita(pypresence_src: Path) -> None:
    """Produces:
        dist/krita_presence/                 (drop into pykrita/)
          krita_presence.desktop
          krita_presence/
            __init__.py                     (unchanged: `from .krita_presence import *`)
            krita_presence.py               (rewritten: `from .common`, `from .colors`)
            colors/                          (sibling subpackage, copied as-is)
              __init__.py
              color_find.py
              palette.csv
              iscc-nbs.csv
              Attribution.txt
            common/                          (subpackage with pypresence nested inside)
              __init__.py                   (was common.py; PySide6 -> PyQt5,
                                              `from .pypresence`)
              pypresence/

    Host quirk this compensates for: Krita doesn't put the loaded plugin's
    directory on sys.path before running its module-level imports, so the
    source's `from common ...` and `from colors ...` would ModuleNotFoundError.
    The build rewrites them to relative imports. common.py's Qt-binding
    detection picks up PyQt5 automatically at plug-in load time.
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
    pkg_dst = dst_root / "krita_presence"
    shutil.copytree(package_src, pkg_dst, ignore=IGNORE)

    # krita_presence.py: convert sibling-module imports to relative.
    main_py = pkg_dst / "krita_presence.py"
    _write_rewritten(main_py, main_py, modules=["common", "colors"])

    # common/ subpackage with pypresence/ nested inside. common.py auto-detects
    # the host's Qt binding (PyQt5 in Krita's case).
    _write_common_subpackage(pkg_dst, pypresence_src)

    # colors/ uses internal relative imports already; copy as-is.
    shutil.copytree(COLOR_SRC, pkg_dst / "colors", ignore=IGNORE)
    print("[build] krita_presence/")


def _bundle_c4d(pypresence_src: Path) -> None:
    """Produces:
        dist/c4d_presence/                   (drop into a C4D plugins folder)
          c4d_presence.pyp
          res/
            c4d_symbols.h
            description/
            strings_us/
          common.py
          pypresence/

    C4D loads .pyp files directly; the bootstrap snippet at the top of
    c4d_presence.pyp inserts its own directory on sys.path, so absolute
    imports of the sibling common and pypresence modules resolve without
    any rewriting (same contract as Maya and Nuke).
    """
    src = REPO / "c4d_presence"
    if not (src / "c4d_presence.pyp").exists():
        print("[build] skip c4d_presence: c4d_presence.pyp not found")
        return
    dst = DIST / "c4d_presence"
    shutil.copytree(src, dst, ignore=IGNORE)
    _drop_runtime(dst, pypresence_src)
    print("[build] c4d_presence/")


def _bundle_gimp(pypresence_src: Path) -> None:
    """Produces:
        dist/gimp_presence/                  (drop into GIMP plug-ins/)
          gimp_presence.py
          settings_dialog.py
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
    src2 = REPO / "gimp_presence" / "settings_dialog.py"
    if not src.exists() or not src2.exists():
        print("[build] skip gimp_presence: gimp_presence.py not found")
        return
    dst = DIST / "gimp_presence"
    dst.mkdir(parents=True)
    shutil.copy2(src, dst / "gimp_presence.py")
    shutil.copy2(src2, dst / "settings_dialog.py")
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
    _bundle_c4d(pypresence_src)

    print(f"[build] done -> {DIST}")


if __name__ == "__main__":
    build()
