"""Start the Qt application entry point."""

import runpy


def main():
    runpy.run_module("dxf2gcode.presentation.qt.application",
                     run_name="__main__")
    return 0
