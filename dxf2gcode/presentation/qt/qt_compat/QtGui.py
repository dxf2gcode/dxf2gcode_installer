# -*- coding: utf-8 -*-

############################################################################
#
#   Copyright (C) 2026
#    Richard Kenney
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

from . import PYQT_VERSION

if PYQT_VERSION == 6:
    from PyQt6.QtGui import *
else:
    from PyQt5.QtGui import *
    from PyQt5.QtGui import QRegExpValidator as QRegularExpressionValidator
    from PyQt5.QtWidgets import QAction, QActionGroup
