#!/usr/bin/env python3
"""Update translation catalogs and compile them using Qt Linguist tools."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dxf2gcode.presentation.qt.qt_compat import PYQT_VERSION


def find_tool(names):
    """Prefer tools belonging to the selected interpreter, then search PATH."""
    for name in names:
        for directory in (Path(sys.executable).parent,
                          Path(sys.prefix) / "Scripts"):
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
        candidate = shutil.which(name)
        if candidate:
            return candidate
    raise RuntimeError("Required Qt tool not found: " + ", ".join(names))


def remove_linenumbers(path):
    text = path.read_text(encoding="utf-8")
    path.write_text("".join(line for line in text.splitlines(keepends=True)
                            if "<location " not in line), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-U", "--no-pylupdate", action="store_true",
                        help="compile existing catalogs without updating TS files")
    parser.add_argument("-k", "--keep-ln", action="store_true",
                        help="keep source locations and skip QM compilation")
    args = parser.parse_args(argv)
    catalogs = sorted((ROOT / "i18n").glob("*.ts"))
    if not catalogs:
        parser.error("No translation catalogs found under " + str(ROOT / "i18n"))
    try:
        if not args.no_pylupdate:
            name = "pylupdate%d" % PYQT_VERSION
            updater = find_tool((name + ".exe", name) if sys.platform == "win32"
                                else (name,))
            if PYQT_VERSION == 5:
                subprocess.check_call([updater, str(ROOT / "dxf2gcode.pro")],
                                      cwd=ROOT)
            else:
                sources = sorted(str(p) for p in (ROOT / "dxf2gcode").rglob("*.py"))
                for catalog in catalogs:
                    subprocess.check_call([updater, "--ts", str(catalog)] + sources,
                                          cwd=ROOT)
            if not args.keep_ln:
                for catalog in catalogs:
                    remove_linenumbers(catalog)
        if not args.keep_ln:
            compiler = find_tool((
                "lrelease-qt%d" % PYQT_VERSION, "lrelease%d" % PYQT_VERSION,
                "lrelease.exe", "lrelease",
                "/usr/lib/qt%d/bin/lrelease" % PYQT_VERSION,
                "/usr/lib64/qt%d/bin/lrelease" % PYQT_VERSION,
                "/usr/lib/qt%d/libexec/lrelease" % PYQT_VERSION))
            subprocess.check_call([compiler] + [str(p) for p in catalogs], cwd=ROOT)
    except RuntimeError as error:
        parser.exit(1, str(error) + "\n")
    print("Translation catalogs prepared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
