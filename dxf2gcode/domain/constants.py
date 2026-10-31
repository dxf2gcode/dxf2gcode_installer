# -*- coding: utf-8 -*-

############################################################################
#
#   Copyright (C) 2010-2015
#    Christian Kohlöffel
#    Jean-Paul Schouwstra
#
#   This file is part of DXF2GCODE.
#
#   DXF2GCODE is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   DXF2GCODE is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with DXF2GCODE.  If not, see <http://www.gnu.org/licenses/>.
#
############################################################################

"""
All global constants are initialized in this module.
They are used in the other modules.

see http://code.activestate.com/recipes/65207/ for module const

@purpose:  initialization of the global constants used within the other modules.
"""

import logging
import os
import platform

from dxf2gcode.presentation.qt.qt_compat import QtCore

# Global Variables
APPNAME = "DXF2GCODE"
RUNTIME_VERSION = "Py%s PyQt%s" % (platform.python_version(), QtCore.PYQT_VERSION_STR)

CONFIG_EXTENSION = '.cfg'
PY_EXTENSION = '.py'
PROJECT_EXTENSION = '.d2g'

# Rename unreadable config/varspace files to .bad
BAD_CONFIG_EXTENSION = '.bad'
DEFAULT_CONFIG_DIR = 'config'
DEFAULT_POSTPRO_DIR = 'postpro_config'

# Configuration profiles: the default profile is stored directly in
# DEFAULT_CONFIG_FOLDER, an alternative profile appends
# CONFIG_PROFILE_SEPARATOR + <suffix> to that folder name. On Linux this gives
# for example ~/.config/dxf2gcode (default) and ~/.config/dxf2gcode.laser
# (profile "laser"). All platform specific path resolution stays in
# DEFAULT_CONFIG_FOLDER below, so profiles work the same on every platform.
BASE_CONFIG_NAME = 'dxf2gcode'
CONFIG_PROFILE_SEPARATOR = '.'
DEFAULT_CONFIG_FOLDER = os.path.join(os.path.expanduser("~"), ".config",
                                     BASE_CONFIG_NAME).replace("\\", "/")

# log related
DEFAULT_LOGFILE = 'dxf2gcode.log'
STARTUP_LOGLEVEL = logging.DEBUG
# PRT = logging.INFO
