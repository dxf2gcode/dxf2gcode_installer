#!/usr/bin/env python3
"""Build the Windows installer with cx_Freeze.

Run ``python tools/build/windows.py bdist_msi`` from source/.
Inputs and output paths are anchored to source/, independent of the working directory.
"""

import os
import sys
from importlib.util import find_spec
from pathlib import Path

from cx_Freeze import Executable, setup


PROJECT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_DIR))
# Keep cx_Freeze's distribution metadata separate from the Python wheel
# project. Otherwise setuptools replaces the dotted MSI version with the
# date-based Python package version from pyproject.toml.
WINDOWS_BUILD_DIR = PROJECT_DIR / "build" / "windows-config"
WINDOWS_BUILD_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(WINDOWS_BUILD_DIR)

from dxf2gcode import __version__
from dxf2gcode.bootstrap.version_metadata import METADATA_FILE, write_build_metadata

VERSION = __version__
VERSION_DOTTED = "%s.%s.%s" % (
    VERSION[:4], VERSION[4:6], VERSION[6:8])


def include_opengl():
    """Include OpenGL modules from the active interpreter environment."""
    spec = find_spec("OpenGL")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError(
            "PyOpenGL is not installed in the Python environment used to "
            "run tools/build/windows.py.")

    package_dir = Path(next(iter(spec.submodule_search_locations))).resolve()
    site_packages = package_dir.parent
    return [
        (str(path), path.relative_to(site_packages).as_posix())
        for path in package_dir.rglob("*") if path.is_file()
    ]


translation_files = sorted((PROJECT_DIR / "i18n").glob("*.qm"))
if not translation_files:
    raise RuntimeError(
        "No compiled translations were found. Run "
        "'python tools/build/translations.py --no-pylupdate' first.")

include_files = [
    (str(PROJECT_DIR / "COPYING"), "COPYING"),
    (str(PROJECT_DIR / "README.txt"), "README.txt"),
]
metadata_path = WINDOWS_BUILD_DIR / METADATA_FILE
write_build_metadata(metadata_path, PROJECT_DIR / "dxf2gcode")
include_files.append((str(metadata_path), "lib/dxf2gcode/" + METADATA_FILE))
include_files.extend(
    (str(path), "i18n/%s" % path.name) for path in translation_files)

icon_path = (PROJECT_DIR / "dxf2gcode" / "presentation" / "qt" /
             "resources" / "images" / "DXF2GCODE-001.ico")
base = "gui" if sys.platform == "win32" else "console"

setup(
    name="dxf2gcode",
    version=VERSION_DOTTED,
    description="2D drawings to CNC machine compatible G-Code converter.",
    options={
        "build": {"build_base": str(PROJECT_DIR / "build")},
        "bdist_msi": {"dist_dir": str(PROJECT_DIR / "dist")},
        "build_exe": {
            # The launcher enters the GUI through runpy, so these imports are
            # not visible to cx_Freeze's static module scanner.
            "packages": ["dxf2gcode", "PyQt5", "OpenGL", "configobj"],
            "include_files": include_files,
            "zip_includes": include_opengl(),
        }
    },
    executables=[
        Executable(
            script=str(PROJECT_DIR / "dxf2gcode.py"),
            base=base,
            icon=str(icon_path),
            target_name="dxf2gcode.exe",
            shortcut_name="DXF to G-Code Converter",
            shortcut_dir="ProgramMenuFolder",
        )
    ],
)
