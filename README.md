# DXF2GCODE source package

This directory contains the Python application, its packaging and translation
tools, and the Qt resources. The repository root also contains the test suite,
architecture notes, sample DXF files, and project-level tooling.

Build helpers are grouped under `tools/build/`:

```text
source/
├── pyproject.toml               Python package definition
├── MANIFEST.in                  Source archive contents
├── Makefile                     Common developer commands
├── dxf2gcode.pro                Qt Creator and Linguist project
├── tools/build/
│   ├── windows.py               Windows EXE/MSI builder (cx_Freeze)
│   ├── qt_assets.py             Qt UI and resource generation
│   ├── translations.py          Translation updates and QM compilation
│   └── setuptools_commands.py   Prepared asset packaging
└── dxf2gcode/                   Application package
```

`tools/` is included in the source archive for building, and is excluded from
the installed application wheel. `build/` and `dist/` are generated output.
There are no forwarding scripts at the former helper locations.

## Package structure

```text
dxf2gcode/
├── bootstrap/          Application startup and runtime wiring
├── domain/             Geometry, project data, and toolpath concepts
├── application/        Import, project, export, preview, and optimization flows
├── adapters/           DXF, project/configuration, toolpath, and postprocessor code
└── presentation/qt/    Qt windows, controllers, views, and resources
```

### `bootstrap/`

`dxf2gcode.py` is the source-tree entry point. It delegates to
`bootstrap/launcher.py`, which starts `presentation.qt.application`. The
composition function in `bootstrap/composition.py` creates the shared
`ApplicationContext` and supplies the project repository. Logging setup and
runtime state are kept in `bootstrap/logging.py` and `bootstrap/runtime_state.py`.

### `domain/`

The domain package holds the main data and geometry used by the application:

- `geometry/` contains points, lines, arcs, holes, bounding boxes, and related
  geometry operations.
- `project/` contains the project, entity, layer, and shape models.
- `toolpath/` contains movement geometry, depth passes, leads, pocketing,
  offsets, and the semantic `ToolpathPlan` data model. `planner.py` selects
  pure strategies in `strategies/` for basic milling, contours and drag
  knives. They consume immutable geometry/settings/capability snapshots and
  return ordered semantic actions without calling a postprocessor.

### `application/`

Application services coordinate work without owning file formats or Qt
widgets. Examples include `ImportDrawing`, `BuildDrawingModel`, project load
and save operations, shape actions, `ExportShape`, toolpath planning and
projection, and route optimization. The GUI calls these services for shared
workflows; the CLI export flow uses the same application layer where
available.

### `adapters/`

Adapters connect application and domain code to external formats or existing
implementations:

- `dxf/` wraps the existing DXF parser and its entity handlers. `reader.py`
  exposes the import contract and returns parser diagnostics.
- `project/` reads and writes the existing `.d2g` project format. The
  `legacy_*.py` modules preserve compatibility with its stored structure.
- `config/` loads application settings and profiles through ConfigObj.
- `postprocessor/` loads machine-specific postprocessor profiles and formats
  output commands as G-Code or another configured output format.
- `toolpath/planning.py` freezes existing Shape, StMove and profile data for
  the planner and adapts the established lead/overcut geometry algorithms.
  `gcode_exporter.py` serializes the resulting semantic actions. There is no
  Shape command recorder or fallback that runs a postprocessor during planning.

The machine mode selected in the UI (`milling`, `lathe`, or `drag_knife`) is an
application configuration setting. It is separate from the selected
postprocessor profile, which controls the target controller's output dialect.

### `presentation/qt/`

`application.py` owns the Qt application and main window coordination.
`treehandling.py` coordinates tree edits and UI actions; `canvas2d.py` and
`canvas3d.py` render the drawing and toolpath views. Dialogs, configuration
widgets, Qt compatibility wrappers, generated UI/resource modules, and image
assets live alongside them. The editable `.ui` form and `.qrc` resource file
are in `resources/`.

## Main application flow

```text
dxf2gcode.py
  -> bootstrap launcher and runtime wiring
  -> Qt application and main window
  -> DxfReaderAdapter -> DXF parser -> imported entities and diagnostics
  -> BuildDrawingModel -> project, layers, shapes, and geometry
  -> 2D/3D views and tree interaction
  -> toolpath planning -> postprocessor serialization -> output file
```

Project load/save uses the project adapter and retains the existing `.d2g`
format. Import warnings are returned as diagnostics so the caller can log or
display them. During export, the application asks for a toolpath plan and the
postprocessor serializes its operations. The semantic plan and preview
projections are being introduced incrementally; many existing machining cases
still use the established shape-based toolpath builder.

## Current architecture boundaries

The package layout separates responsibilities, but some older coupling remains
inside the implementation. In particular, `bootstrap/runtime_state.py` still
provides shared global configuration and window state, parts of the GUI and
processing code read it directly, and `domain/constants.py` imports Qt
compatibility code. The toolpath migration also continues to reuse existing
shape algorithms. Treat the package boundaries as the current organization,
not as a guarantee that every dependency is fully isolated yet.

## Running and preparing the source tree

Run from this directory after installing the runtime dependencies and
generating the Qt UI/resource modules:

```text
python tools/build/qt_assets.py
python tools/build/translations.py
python dxf2gcode.py
```

UI and resource modules are generated under
`dxf2gcode/presentation/qt/generated/`. Translations are maintained in
`i18n/*.ts` and compiled to `.qm` files. `Makefile` provides `prepare`,
`clean`, `trs`, and `trf` targets when GNU Make is available.

The runtime dependencies are Python 3.9 or newer, ConfigObj, PyOpenGL, and either PyQt5 or
PyQt6. PDF and PostScript import also needs the external `pdftops` and
`pstoedit` programs. Application settings and postprocessor profiles are kept
under `~/.config/dxf2gcode` on the current configuration path; named
application profiles use sibling folders such as `~/.config/dxf2gcode.laser`.

## Python packages and Linux installation

`pyproject.toml` defines the Python package, dependencies and the
`dxf2gcode` command. Build releases as wheels and source archives using
`python -m build`. The old `st-setup.py` and `setup.py` scripts have been
removed. The Windows MSI builder is separate in `tools/build/windows.py`.

To install a downloaded release on Linux:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install ./dxf2gcode-20261030.post2-py3-none-any.whl
dxf2gcode
```

A release source archive (`.tar.gz`) can be supplied to the same pip command.
Alternatively, `pipx install ./dxf2gcode-20261030.post2-py3-none-any.whl` exposes the
command through an isolated application environment. Runtime dependencies are
installed by pip; the `qt6` extra adds PyQt6. The default installation retains
PyQt5 support and uses PyQt6 when available, as selected by the existing
`DXF2GCODE_QT` setting. The package also supports `python -m dxf2gcode`.

Prepared releases contain both Qt UI/resource variants and all compiled
translations. Translations are installed inside the Python package, so
launching from another directory or from a virtual environment works.
Desktop, icon and AppStream files are installed under the environment's
`share/` directory. A desktop menu does not automatically scan a virtual
environment: distro packages can install these files into the normal system
locations, or a user can copy the desktop file/icon into their XDG data
directories and set its `Exec=` line to the environment's absolute executable
path. Installing into a virtual environment does not write into the system Python.

### Preparing and building a release

From a repository checkout, prepare the generated assets before building.
The developer environment needs `build`, PyQt5 and PyQt6 plus Qt 6 `rcc`
and Qt Linguist `lrelease` on PATH:

```sh
python -m pip install build PyQt5 PyQt6 configobj PyOpenGL
DXF2GCODE_QT=5 python tools/build/qt_assets.py
DXF2GCODE_QT=6 python tools/build/qt_assets.py
DXF2GCODE_QT=5 python tools/build/translations.py --no-pylupdate
python -m build
```

With GNU Make, `make package PYTHON=python` runs the same preparation and
build. `make prepare` prepares the selected Qt binding; `make windows`
prepares release assets and builds the Windows MSI. Invoke these targets
from `source/`, or use `make -C source ...` from the repository root.
On PowerShell set `$env:DXF2GCODE_QT = "5"` or `"6"` before the
corresponding Python command. The generated release artifacts are:

- `dist/dxf2gcode-20261030.post2-py3-none-any.whl`
- `dist/dxf2gcode-20261030.post2.tar.gz`

For development, a prepared checkout can be installed using
`python -m pip install --editable .`. End users installing a prepared wheel
or source archive do not need Qt development tools. The build validates the
prepared assets and rejects incomplete releases.

`tools/build/setuptools_commands.py` bundles prepared assets; `MANIFEST.in` includes them in
the source archive. Setuptools may still generate a temporary `.egg-info`
metadata directory while building; the installed wheel uses `.dist-info`
and does not install an Egg or use EasyInstall.

`dxf2gcode.pro` supplies the Qt Creator/Linguist file lists.
`tools/build/qt_assets.py` generates Python modules from the `.ui` and `.qrc` files;
`tools/build/translations.py` updates and compiles translation catalogs. Generated files,
`build/` and `dist/` remain excluded from Git.

After generating the UI/resource and translation files, build the MSI on
Windows from this directory with:

```text
python -m pip install "cx-Freeze>=8"
python tools/build/windows.py bdist_msi
```

The Python helper paths above are relative to `source/`. From the repository
root, use `python source/tools/build/windows.py bdist_msi` instead. Each
helper resolves its input/output paths from its own location, so it also
works when called by absolute path from a different working directory.

After installing the built wheel into a test environment, the repository's
acceptance check verifies its contents, installed resources/translations,
desktop files, command entry points and a headless DXF export:

```text
python tests/verify_wheel.py source/dist/dxf2gcode-20261030.post2-py3-none-any.whl --python PATH_TO_TEST_ENV_PYTHON --qt 5
```

Run this command from the repository root. Repeat with `--qt 6` in an
environment containing the `qt6` extra. The check starts the application from
a temporary directory with isolated configuration paths.

## Version and build provenance

The About dialog displays the package version, source revision and branch,
commit date, build date, local-change status and Python/Qt runtime versions.
When running the source checkout, these values are read from that checkout;
a normal commit or branch switch needs no hook or manual metadata update.
The release version in `dxf2gcode/_version.py` is still updated deliberately.

Wheels, release source archives and Windows builds carry
`dxf2gcode/_build_metadata.json`. Installed applications read this resource
without Git. The displayed branch is the build's source branch, not a branch
on the end user's computer. Missing provenance is reported as unavailable.
Source distributions preserve provenance when rebuilt as wheels. Set
`SOURCE_DATE_EPOCH` to control the build timestamp for reproducible builds.
Generated metadata stays out of the source checkout and Git. The former
keyword filters and their setup instructions have been removed.

## Tests

The test runner is in the repository-level `tests/` directory. From the
repository root, run the full suite with:

```text
python tests/run_tests.py full
```
