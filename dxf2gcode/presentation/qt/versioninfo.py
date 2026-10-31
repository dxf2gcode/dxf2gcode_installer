"""Localized, escaped presentation of package and source provenance."""

from html import escape

from dxf2gcode.bootstrap.version_metadata import get_version_info
from dxf2gcode.domain.constants import RUNTIME_VERSION
from dxf2gcode.presentation.qt.qt_compat import QtCore


def version_details_html(info=None):
    info = get_version_info() if info is None else info
    unavailable = QtCore.QCoreApplication.translate("VersionInfo", "Not available")
    detached = QtCore.QCoreApplication.translate("VersionInfo", "No active branch")
    if info.dirty is True:
        state = QtCore.QCoreApplication.translate("VersionInfo", "Local changes")
    elif info.dirty is False:
        state = QtCore.QCoreApplication.translate("VersionInfo", "Clean source tree")
    else:
        state = unavailable
    if info.origin == "checkout":
        origin = QtCore.QCoreApplication.translate("VersionInfo", "Source checkout")
    elif info.origin == "build":
        origin = QtCore.QCoreApplication.translate("VersionInfo", "Package build")
    else:
        origin = unavailable
    rows = (
        (QtCore.QCoreApplication.translate("VersionInfo", "Package version:"), info.version),
        (QtCore.QCoreApplication.translate("VersionInfo", "Source revision:"),
         info.revision[:12] if info.revision else unavailable),
        (QtCore.QCoreApplication.translate("VersionInfo", "Source branch:"),
         info.branch or (detached if info.revision else unavailable)),
        (QtCore.QCoreApplication.translate("VersionInfo", "Commit date:"),
         info.commit_date or unavailable),
        (QtCore.QCoreApplication.translate("VersionInfo", "Build date:"),
         info.build_date or unavailable),
        (QtCore.QCoreApplication.translate("VersionInfo", "Source status:"), state),
        (QtCore.QCoreApplication.translate("VersionInfo", "Provenance:"), origin),
        (QtCore.QCoreApplication.translate("VersionInfo", "Runtime:"), RUNTIME_VERSION),
    )
    return "<br>".join("<b>%s</b> %s" % (escape(str(label)), escape(str(value)))
                       for label, value in rows) + "<br>"
