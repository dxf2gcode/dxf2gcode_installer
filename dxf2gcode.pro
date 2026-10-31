# Qt Creator / Linguist project metadata for DXF2GCODE.
TEMPLATE = app
TARGET = dxf2gcode

SOURCES += \
    dxf2gcode.py \
    tools/build/qt_assets.py \
    tools/build/translations.py \
    dxf2gcode/__main__.py \
    dxf2gcode/_version.py \
    dxf2gcode/bootstrap/version_metadata.py \
    dxf2gcode/presentation/qt/versioninfo.py \
    dxf2gcode/__init__.py \
    dxf2gcode/adapters/__init__.py \
    dxf2gcode/adapters/config/configobj_store.py \
    dxf2gcode/adapters/config/runtime_config.py \
    dxf2gcode/adapters/config/__init__.py \
    dxf2gcode/adapters/dxf/biarc.py \
    dxf2gcode/adapters/dxf/classes.py \
    dxf2gcode/adapters/dxf/geoent_arc.py \
    dxf2gcode/adapters/dxf/geoent_circle.py \
    dxf2gcode/adapters/dxf/geoent_ellipse.py \
    dxf2gcode/adapters/dxf/geoent_insert.py \
    dxf2gcode/adapters/dxf/geoent_line.py \
    dxf2gcode/adapters/dxf/geoent_lwpolyline.py \
    dxf2gcode/adapters/dxf/geoent_point.py \
    dxf2gcode/adapters/dxf/geoent_polyline.py \
    dxf2gcode/adapters/dxf/geoent_spline.py \
    dxf2gcode/adapters/dxf/parser.py \
    dxf2gcode/adapters/dxf/reader.py \
    dxf2gcode/adapters/dxf/spline_convert.py \
    dxf2gcode/adapters/dxf/__init__.py \
    dxf2gcode/adapters/postprocessor/breaks.py \
    dxf2gcode/adapters/postprocessor/postprocessor.py \
    dxf2gcode/adapters/postprocessor/postprocessorconfig.py \
    dxf2gcode/adapters/postprocessor/__init__.py \
    dxf2gcode/adapters/project/file_store.py \
    dxf2gcode/adapters/project/legacy_d2g.py \
    dxf2gcode/adapters/project/legacy_repository.py \
    dxf2gcode/adapters/project/__init__.py \
    dxf2gcode/adapters/toolpath/planning.py \
    dxf2gcode/adapters/toolpath/gcode_exporter.py \
    dxf2gcode/adapters/toolpath/__init__.py \
    dxf2gcode/application/cli_export.py \
    dxf2gcode/application/context.py \
    dxf2gcode/application/drawings.py \
    dxf2gcode/application/exceptions.py \
    dxf2gcode/application/exporting.py \
    dxf2gcode/application/importing.py \
    dxf2gcode/application/projects.py \
    dxf2gcode/application/shapes.py \
    dxf2gcode/application/text_helpers.py \
    dxf2gcode/application/__init__.py \
    dxf2gcode/application/optimization/routes.py \
    dxf2gcode/application/optimization/tsp.py \
    dxf2gcode/application/optimization/__init__.py \
    dxf2gcode/application/toolpath/exporting.py \
    dxf2gcode/application/toolpath/planning.py \
    dxf2gcode/application/toolpath/projections.py \
    dxf2gcode/application/toolpath/__init__.py \
    dxf2gcode/bootstrap/composition.py \
    dxf2gcode/bootstrap/launcher.py \
    dxf2gcode/bootstrap/logging.py \
    dxf2gcode/bootstrap/runtime_state.py \
    dxf2gcode/bootstrap/__init__.py \
    dxf2gcode/domain/constants.py \
    dxf2gcode/domain/__init__.py \
    dxf2gcode/domain/geometry/arcgeo.py \
    dxf2gcode/domain/geometry/boundingbox.py \
    dxf2gcode/domain/geometry/breakgeo.py \
    dxf2gcode/domain/geometry/holegeo.py \
    dxf2gcode/domain/geometry/linegeo.py \
    dxf2gcode/domain/geometry/point.py \
    dxf2gcode/domain/geometry/point3d.py \
    dxf2gcode/domain/geometry/__init__.py \
    dxf2gcode/domain/project/entitycontent.py \
    dxf2gcode/domain/project/layercontent.py \
    dxf2gcode/domain/project/project.py \
    dxf2gcode/domain/project/shape.py \
    dxf2gcode/domain/project/__init__.py \
    dxf2gcode/domain/toolpath/customgcode.py \
    dxf2gcode/domain/toolpath/depths.py \
    dxf2gcode/domain/toolpath/leadmove.py \
    dxf2gcode/domain/project/tool_settings.py \
    dxf2gcode/domain/toolpath/diagnostics.py \
    dxf2gcode/domain/toolpath/inputs.py \
    dxf2gcode/domain/toolpath/movements.py \
    dxf2gcode/domain/toolpath/planner.py \
    dxf2gcode/domain/toolpath/strategies/__init__.py \
    dxf2gcode/domain/toolpath/strategies/contour.py \
    dxf2gcode/domain/toolpath/strategies/drag_knife.py \
    dxf2gcode/domain/toolpath/strategies/simple_milling.py \
    dxf2gcode/domain/toolpath/plan.py \
    dxf2gcode/domain/toolpath/pocketmill.py \
    dxf2gcode/domain/toolpath/pocketmove.py \
    dxf2gcode/domain/toolpath/shapeoffset.py \
    dxf2gcode/domain/toolpath/stmove.py \
    dxf2gcode/domain/toolpath/__init__.py \
    dxf2gcode/presentation/__init__.py \
    dxf2gcode/presentation/qt/aboutdialog.py \
    dxf2gcode/presentation/qt/application.py \
    dxf2gcode/presentation/qt/arrow.py \
    dxf2gcode/presentation/qt/canvas.py \
    dxf2gcode/presentation/qt/canvas2d.py \
    dxf2gcode/presentation/qt/canvas3d.py \
    dxf2gcode/presentation/qt/configuration_widgets.py \
    dxf2gcode/presentation/qt/configwindow.py \
    dxf2gcode/presentation/qt/messagebox.py \
    dxf2gcode/presentation/qt/popupdialog.py \
    dxf2gcode/presentation/qt/routetext.py \
    dxf2gcode/presentation/qt/scalebar.py \
    dxf2gcode/presentation/qt/shapeparameterstate.py \
    dxf2gcode/presentation/qt/translations.py \
    dxf2gcode/presentation/qt/treehandling.py \
    dxf2gcode/presentation/qt/treeview.py \
    dxf2gcode/presentation/qt/wpzero.py \
    dxf2gcode/presentation/qt/__init__.py \
    dxf2gcode/presentation/qt/qt_compat/QtCore.py \
    dxf2gcode/presentation/qt/qt_compat/QtGui.py \
    dxf2gcode/presentation/qt/qt_compat/QtOpenGLWidgets.py \
    dxf2gcode/presentation/qt/qt_compat/QtWidgets.py \
    dxf2gcode/presentation/qt/qt_compat/__init__.py

DISTFILES += \
    README.txt \
    dxf2gcode.desktop \
    dxf2gcode.appdata.xml \
    MANIFEST.in \
    tools/build/windows.py \
    tools/build/setuptools_commands.py

RESOURCES += dxf2gcode/presentation/qt/resources/dxf2gcode_images.qrc
FORMS += dxf2gcode/presentation/qt/resources/dxf2gcode.ui

TRANSLATIONS += \
    i18n/dxf2gcode_de.ts \
    i18n/dxf2gcode_fr.ts \
    i18n/dxf2gcode_ru.ts

DISTFILES += pyproject.toml
