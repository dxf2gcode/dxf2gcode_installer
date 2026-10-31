"""Read source provenance, or the immutable provenance shipped in a build.

This module deliberately has no Qt or build-tool dependencies. Git is used
only for a verified source checkout, never for an installed application.
"""

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from importlib import resources
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic
from typing import Optional

from dxf2gcode._version import __version__

METADATA_FILE = "_build_metadata.json"


@dataclass(frozen=True)
class VersionInfo:
    version: str
    revision: Optional[str] = None
    branch: Optional[str] = None
    commit_date: Optional[str] = None
    build_date: Optional[str] = None
    dirty: Optional[bool] = None
    origin: str = "unknown"


def _checkout_root(package_dir):
    package_dir = package_dir.resolve()
    source_dir = package_dir.parent
    repository = source_dir.parent
    # Do not walk up from site-packages or an extracted archive looking for
    # an unrelated enclosing repository. Worktrees may have a .git file.
    if (package_dir.name != "dxf2gcode" or source_dir.name != "source" or
            not (source_dir / "pyproject.toml").is_file() or
            not (repository / ".git").exists()):
        return None
    return repository


def _checkout_info(package_dir, version):
    repository = _checkout_root(package_dir)
    if repository is None:
        return None
    environment = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        environment.pop(key, None)
    deadline = monotonic() + 2.0

    def git(*arguments, detached_ok=False):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Git metadata lookup timed out")
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        process = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(repository), *arguments],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=environment, timeout=min(1.0, remaining), **options)
        if process.returncode == 1 and detached_ok:
            return None
        if process.returncode:
            raise ValueError("Git metadata unavailable")
        return process.stdout.strip()

    try:
        if Path(git("rev-parse", "--show-toplevel")).resolve() != repository:
            return None
        git("ls-files", "--error-unmatch", "--", "source/dxf2gcode/_version.py")
        revision, commit_date = git("show", "-s", "--format=%H%n%cI", "HEAD").splitlines()
        branch = git("symbolic-ref", "--quiet", "--short", "HEAD", detached_ok=True)
        dirty = bool(git("status", "--porcelain=v1", "--untracked-files=normal"))
        return VersionInfo(version, revision, branch, commit_date,
                           dirty=dirty, origin="checkout")
    except (OSError, ValueError, TimeoutError, subprocess.SubprocessError):
        return None


def _read_build_info(package_dir, version, use_resources):
    try:
        if use_resources:
            text = resources.files("dxf2gcode").joinpath(METADATA_FILE).read_text(encoding="utf-8")
        else:
            text = (package_dir / METADATA_FILE).read_text(encoding="utf-8")
        data = json.loads(text)
        if (not isinstance(data, dict) or data.get("schema") != 1 or
                data.get("version") != version):
            return None
        fields = ("revision", "branch", "commit_date", "build_date")
        if any(data.get(name) is not None and not isinstance(data[name], str)
               for name in fields):
            return None
        if data.get("dirty") is not None and type(data["dirty"]) is not bool:
            return None
        return VersionInfo(version, **{name: data.get(name) for name in fields},
                           dirty=data.get("dirty"), origin="build")
    except (OSError, ValueError, TypeError):
        return None


def get_version_info(package_dir=None, version=None):
    """Return current checkout data or saved build data, with honest fallbacks."""
    use_resources = package_dir is None
    package_dir = Path(package_dir) if package_dir is not None else Path(__file__).resolve().parents[1]
    version = __version__ if version is None else version
    if not getattr(sys, "frozen", False) and _checkout_root(package_dir) is not None:
        # A source checkout with unavailable Git must not inherit a stale
        # saved "clean" status from an earlier build.
        return _checkout_info(package_dir, version) or VersionInfo(version)
    return (_read_build_info(package_dir, version, use_resources) or
            VersionInfo(version))


def capture_build_info(package_dir, version=None):
    """Capture before generating build files; preserve inherited sdist data."""
    info = get_version_info(package_dir, version)
    if info.build_date is None:
        epoch = os.environ.get("SOURCE_DATE_EPOCH")
        timestamp = (datetime.fromtimestamp(int(epoch), timezone.utc) if epoch is not None
                     else datetime.now(timezone.utc))
        info = replace(info, build_date=timestamp.isoformat(timespec="seconds"))
    return replace(info, origin="build")


def write_build_metadata(destination, package_dir=None, version=None, *, info=None):
    """Serialize a snapshot without re-reading Git after build files appear."""
    if info is None:
        if package_dir is None:
            raise ValueError("A package directory or captured build info is required")
        info = capture_build_info(package_dir, version)
    data = asdict(info)
    data["schema"] = 1
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                      indent=2) + "\n", encoding="utf-8")
    return info
