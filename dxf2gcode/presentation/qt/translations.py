"""Locate translation catalogs in source, installed and frozen applications."""

import os
import sys
from pathlib import Path


def translation_search_paths():
    qt_dir = Path(__file__).resolve().parent
    paths = [
        Path.cwd() / "i18n",
        qt_dir / "resources" / "i18n",
        qt_dir.parents[2] / "i18n",
        Path(sys.executable).parent / "i18n",
        Path(sys.prefix) / "share" / "dxf2gcode" / "i18n",
        Path("/usr/share/dxf2gcode/i18n"),
    ]
    return tuple(dict.fromkeys(os.fspath(path) for path in paths))
