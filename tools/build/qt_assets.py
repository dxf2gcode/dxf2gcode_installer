#!/usr/bin/env python3
"""Generate UI and resource modules using the selected interpreter's PyQt."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dxf2gcode.presentation.qt.qt_compat import PYQT_VERSION
RESOURCES = ROOT / "dxf2gcode" / "presentation" / "qt" / "resources"
GENERATED = RESOURCES.parent / "generated"


def main():
    version = PYQT_VERSION
    GENERATED.mkdir(parents=True, exist_ok=True)
    resource_module = "dxf2gcode_images%d_rc" % version
    source = (RESOURCES / "dxf2gcode.ui").read_text(encoding="utf-8")
    source = source.replace("dxf2gcode_images.qrc",
                            "dxf2gcode_images%d.qrc" % version)
    ui_output = GENERATED / ("dxf2gcode_ui%d.py" % version)
    resource_output = GENERATED / (resource_module + ".py")
    descriptor, temporary_ui = tempfile.mkstemp(suffix=".ui")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(source)
        subprocess.check_call([
            sys.executable, "-m", "PyQt%d.uic.pyuic" % version,
            temporary_ui, "-o", str(ui_output)])
        generated = ui_output.read_text(encoding="utf-8")
        generated = generated.replace(
            "import " + resource_module, "from . import " + resource_module)
        resource_import = "from . import " + resource_module
        if resource_import not in generated:
            generated += "\n" + resource_import + "\n"
        ui_output.write_text(generated, encoding="utf-8")
        if version == 5:
            command = [sys.executable, "-m", "PyQt5.pyrcc_main"]
        else:
            candidates = ("rcc", "rcc6", "/usr/lib/qt6/libexec/rcc",
                          "/usr/lib64/qt6/libexec/rcc")
            rcc = next((shutil.which(name) for name in candidates
                        if shutil.which(name)), None)
            if rcc is None:
                raise RuntimeError(
                    "Qt 6 rcc was not found. Install Qt 6 development tools "
                    "and put rcc on PATH before generating Qt 6 resources.")
            command = [rcc, "-g", "python"]
        subprocess.check_call(command + [
            "-o", str(resource_output),
            str(RESOURCES / "dxf2gcode_images.qrc")])
        if version == 6:
            generated = resource_output.read_text(encoding="utf-8")
            resource_output.write_text(generated.replace(
                "from PySide6 import QtCore", "from PyQt6 import QtCore"),
                encoding="utf-8")
    finally:
        Path(temporary_ui).unlink(missing_ok=True)
    print("Prepared Qt %d UI and resources; do not commit generated files." % version)


if __name__ == "__main__":
    main()
