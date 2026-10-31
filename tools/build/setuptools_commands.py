"""Bundle prepared Qt assets in wheels and source distributions.

Release preparation uses the project's Qt tools. Installing an already built
wheel or source distribution needs no UI or translation compiler.
"""

from pathlib import Path
from shutil import copy2
import sys
import tarfile

from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

# Setuptools can load this command by filename while an older application is
# installed in the build environment. Resolve our provider from this source.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dxf2gcode.bootstrap.version_metadata import (
    METADATA_FILE, capture_build_info, write_build_metadata)


GENERATED = ROOT / "dxf2gcode" / "presentation" / "qt" / "generated"
CATALOGS = ROOT / "i18n"


def validate_assets():
    missing = []
    for version in (5, 6):
        for name in ("dxf2gcode_ui%d.py" % version,
                     "dxf2gcode_images%d_rc.py" % version):
            path = GENERATED / name
            if not path.is_file():
                missing.append(str(path.relative_to(ROOT)))
            elif "from PySide6" in path.read_text(encoding="utf-8"):
                raise RuntimeError(
                    "%s must be generated for PyQt6; run tools/build/qt_assets.py with "
                    "DXF2GCODE_QT=6 before building." % path.name)
    sources = sorted(CATALOGS.glob("dxf2gcode_*.ts"))
    if not sources:
        missing.append("i18n/dxf2gcode_*.ts")
    for source in sources:
        if not source.with_suffix(".qm").is_file():
            missing.append(str(source.with_suffix(".qm").relative_to(ROOT)))
    if missing:
        raise RuntimeError(
            "Qt release assets are missing: %s. Prepare both Qt variants with "
            "tools/build/qt_assets.py and compile translations with "
            "tools/build/translations.py "
            "--no-pylupdate before building a release. See README.md."
            % ", ".join(missing))


class BuildPy(build_py):
    def find_package_modules(self, package, package_dir):
        # Qt Designer may emit an editor-only PySide resource module next to
        # the QRC source. Only versioned modules under generated/ are runtime
        # assets; never ship this untracked editor output in a Python package.
        return [
            item for item in super().find_package_modules(package, package_dir)
            if not (item[0] == "dxf2gcode.presentation.qt.resources" and
                    item[1] == "dxf2gcode_images_rc")]

    def run(self):
        validate_assets()
        info = capture_build_info(ROOT / "dxf2gcode")
        super().run()
        obsolete = (Path(self.build_lib) / "dxf2gcode" / "presentation" /
                    "qt" / "resources" / "dxf2gcode_images_rc.py")
        obsolete.unlink(missing_ok=True)
        destination = (Path(self.build_lib) / "dxf2gcode" / "presentation" /
                       "qt" / "resources" / "i18n")
        destination.mkdir(parents=True, exist_ok=True)
        for catalog in sorted(CATALOGS.glob("dxf2gcode_*.qm")):
            copy2(catalog, destination / catalog.name)
        write_build_metadata(Path(self.build_lib) / "dxf2gcode" / METADATA_FILE,
                             info=info)


class SourceDistribution(sdist):
    def make_release_tree(self, base_dir, files):
        info = capture_build_info(ROOT / "dxf2gcode")
        super().make_release_tree(base_dir, files)
        write_build_metadata(Path(base_dir) / "dxf2gcode" / METADATA_FILE,
                             info=info)

    def make_archive(self, base_name, format, root_dir=None, base_dir=None,
                     owner=None, group=None):
        if format != "gztar":
            return super().make_archive(base_name, format, root_dir, base_dir,
                                        owner, group)
        # Apply the exclusion at the archive boundary as well: interrupted
        # builds can leave files in the release tree outside the manifest.
        def release_member(member):
            if member.name.endswith(
                    "/presentation/qt/resources/dxf2gcode_images_rc.py"):
                return None
            return member

        archive_path = str(base_name) + ".tar.gz"
        Path(archive_path).parent.mkdir(parents=True, exist_ok=True)
        source = Path(root_dir or ".") / base_dir
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(source, arcname=base_dir, filter=release_member)
        return archive_path

    def run(self):
        validate_assets()
        super().run()
