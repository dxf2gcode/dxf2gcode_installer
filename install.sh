#!/bin/bash

echo ""
echo "#################################"
echo "# dxf2gcode Install Script V6.6 #"
echo "#   for Debian & Arch based OS  #"
echo "#      by Daniel Luginbuehl     #"
echo "#   webmaster@ltspiceusers.ch   #"
echo "#          (c) 2026             #"
echo "#################################"
echo ""
echo "Support: https://www.ltspiceusers.ch/#dxf2gcode.68"
echo ""
echo ""

## URLs
#STABLE_SOURCE_URL="https://sourceforge.net/projects/dxf2gcode/files/dxf2gcode-20220226_RC1.zip/download"

SOURCEFORGE_DEV_URL="https://sourceforge.net/code-snapshots/git/d/dx/dxf2gcode/sourcecode.git/dxf2gcode-sourcecode-6772cd770273130fee1e636fb1a0a164182ab3c4.zip"
#SOURCEFORGE_DEV_URL="https://sourceforge.net/projects/dxf2gcode/files/Development/dxf2gcode.zip/download"

GITHUB_DEV_URL="https://github.com/dxf2gcode/dxf2gcode/archive/master.zip"

ICON_URL="https://raw.github.com/dxf2gcode/dxf2gcode_installer/main/dxf2gcode_symbol.png"
#ICON_URL="https://sourceforge.net/projects/dxf2gcode/files/Development/DXF2GCODE.ico/download"

ICON_FILE="$HOME/dxf2gcode/DXF2GCODE.png"
#ICON_FILE="$HOME/dxf2gcode/DXF2GCODE.ico"

sourceforge=false       # Download from github: false | Download from sourceforge: true
pipversion="pip3"       # pip command syntax
pyversion="python3"     # If python-is-python3 is installed, change to "python"
aptversion="apt-get"    # Old style = apt-get | New style = apt

STARTER_FILE="$HOME/dxf2gcode.sh"

#### Do not make any changes from here!

## Farben Konsole
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
LIGHTCYAN=$'\033[1;36m'
NC=$'\033[0m'

BACKUP_TMPDIR=$(mktemp -d)

## Exit mit Restore
exit_restore() {
    rm -rf "$HOME/dxf2gcode"
    set -e
    if [ -d "$BACKUP_TMPDIR/dxf2gcode" ]; then
        echo "${GREEN}Restoring $BACKUP_TMPDIR/dxf2gcode...${NC}"
        mv "$BACKUP_TMPDIR/dxf2gcode" "$HOME/dxf2gcode"
    else
        echo "${GREEN}No backup found. Nothing to restore.${NC}"
    fi
    rm -rf "$BACKUP_TMPDIR"
    exit 1
}

## Nicht als root Überprüfung
if [ "$(id -u)" -eq 0 ]; then
    echo "${RED}This script must NOT be executed as root or via sudo!${NC}"
    echo
    exit 1
fi

if ! hash "$pyversion"; then
    echo "${RED}$pyversion is not installed"
    echo "Script ends in 8 seconds${NC}"
    sleep 8
    exit 1
fi

echo "${GREEN}Installed Python version:"
"$pyversion" -V
echo "${NC}"

## Python betreffendes
PYVER=$("$pyversion" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
MAJOR=$("$pyversion" -c "import sys; print(sys.version_info.major)")
MINOR=$("$pyversion" -c "import sys; print(sys.version_info.minor)")
PYDIR="/usr/lib/python${MAJOR}.${MINOR}"

REQUIRED_MAJOR=3
REQUIRED_MINOR=9

if [ "$MAJOR" -lt "$REQUIRED_MAJOR" ] || { [ "$MAJOR" -eq "$REQUIRED_MAJOR" ] && [ "$MINOR" -lt "$REQUIRED_MINOR" ]; }; then
    echo "${RED}Error: Python ${REQUIRED_MAJOR}.${REQUIRED_MINOR} or higher is required (found $PYVER)."
    echo "Please install a modern Python version.${NC}"
    sleep 8
    exit 1
fi

## Aktion bei existierender Installation
if [ -d "$HOME/dxf2gcode" ]; then
    echo "${LIGHTCYAN}$HOME/dxf2gcode directory exists."
    
    while true; do
        echo "o = Overwrite, r = Rename, q = Quit installer${NC}"

        read -n 1 -r choice
        echo

        case "$choice" in
            [Oo])
                echo "Overwrite selected. Existing directory will be deleted..."
                mv "$HOME/dxf2gcode" "$BACKUP_TMPDIR"
                echo "${GREEN}Backup in $BACKUP_TMPDIR ${NC}"
                break
                ;;
            [Rr])
                while true; do
                    cp -a "$HOME/dxf2gcode" "$BACKUP_TMPDIR/"

                    echo "Rename selected. Please enter a new name for the old installation (instead of dxf2gcode. Eg. dxf2gcode.bak):"
                    read -r new_name
                    echo

                    if [ -e "$HOME/$new_name" ]; then
                        echo "${RED}Error: That name already exists!${NC}"
                    elif [ -z "$new_name" ] || [ "$new_name" = "dxf2gcode" ]; then
                        echo "${RED}Error: The name cannot be empty or identical!${NC}"
                    else
                        mv "$HOME/dxf2gcode" "$HOME/$new_name"
                        break 2
                    fi
                done
                ;;

            [Qq])
                echo "Abort."
                exit 0
                ;;
            *)
                echo "Invalid input. Please press o, r, or q."
                ;;
        esac
    done
fi

## Installations Routine

mkdir "$HOME/dxf2gcode"

install_own_source=0

# Für künftige git clone Funktion
#download_via_git_clone() {
#    local url="$1"
#    local unused_outfile="$2"
#
#    local target_dir="$HOME/dxf2gcode/dxf2gcode-sourcecode"
#
#    echo -e "${GREEN}Cloning via Git: $url${NC}"
#    # Klonen direkt in den Unterordner 'source'
#    git clone "$url" "$target_dir/source"
#}

download_zip() {
    TMPDIR=$(mktemp -d)
    local url="$1"
    local outdir="$2"

    echo "${GREEN}Downloading: $url${NC}"

    if ! wget -O "$TMPDIR/dev.zip" "$url"; then
        echo
        echo "${RED}Error: Download failed (e.g., 404 Not Found or no connection).${NC}"
        # Temporäres Verzeichnis löschen
        rm -rf "$TMPDIR"
        exit_restore
    fi

    # Überprüfung, ob die Datei existiert und nicht leer ist
    if [ ! -s "$TMPDIR/dev.zip" ]; then
        echo "${RED}Error: The downloaded file is empty or does not exist.${NC}"
        rm -rf "$TMPDIR"
        exit_restore
    fi

    # Entpacken
    echo "${GREEN}Unpack file to $outdir...${NC}"
    if ! unzip "$TMPDIR/dev.zip" -d "$outdir"; then
        echo "${RED}Error: Could not extract file. Not a valid ZIP file.${NC}"
        rm -rf "$TMPDIR"
        exit_restore
    fi

    echo
    echo "Output directory: $outdir, Content:"
    ls "$outdir"
    echo

    rm -rf "$TMPDIR"
}

download_source() {
    if $sourceforge ; then
        echo "${GREEN}Download from SOURCEFORGE${NC}"
        download_zip "$SOURCEFORGE_DEV_URL" "$HOME/dxf2gcode"
    else
        echo "${GREEN}Download from GITHUB${NC}"
        download_zip "$GITHUB_DEV_URL" "$HOME/dxf2gcode"
        #echo "${GREEN}Downloading icon…${NC}"
        #wget -O "$ICON_FILE" "$ICON_URL"
    fi

    pfad=$(find_deepest_dxf2gcode_dir "$HOME/dxf2gcode")
    cd "$pfad" || { echo "${RED}Error: Could not change to directory $pfad ${NC}"; exit_restore; }

    echo "${GREEN}Current folder: $(pwd)${NC}"
}

find_deepest_dxf2gcode_dir() {
    local current_dir="$1"
    while true; do
        if find "$current_dir" -mindepth 1 -maxdepth 1 -type f | grep -q .; then
            break
        fi
        local next_dir=$(find "$current_dir" -mindepth 1 -maxdepth 1 -type d -name "dxf2gcode*" | head -n 1)
        [ -z "$next_dir" ] && break
        current_dir="$next_dir"
    done
    echo "$current_dir"
}

select_source_dir() {
    echo "${LIGHTCYAN}If you want automatically download the developer version press y"
    echo "If you want install your own version press n"
    echo "q = Quit installer${NC}"

    while true; do
        read -n 1 -r answer
        echo

        # Quit installer
        if echo "$answer" | grep -iq "^q" ; then
            exit_restore
        fi

        # Automatic developer download
        if echo "$answer" | grep -iq "^y" ; then
            download_source
            install_own_source=0
            return
        fi

        # Manual path selection
        if echo "$answer" | grep -iq "^n" ; then
            echo
            echo "${RED}Ok. First download the desired version of dxf2gcode into your home directory${NC}"
            echo "Download links:"
            echo
            echo "${GREEN}https://sourceforge.net/p/dxf2gcode/sourcecode/ci/develop/tree${NC} (source directory)"
            echo "or"
            echo "${GREEN}https://github.com/dxf2gcode/dxf2gcode${NC}"
            echo

            while true; do
                echo "${LIGHTCYAN}Enter path to the dxf2gcode source in your home directory e.g. ${GREEN}Downloads/source ${RED}(without / at the beginning and end!) ${NC}"
                read SRC
                echo

                [ -z "$SRC" ] && SRC="_"
                if echo "$SRC" | grep -iq "^q" ; then
                    exit_restore
                fi

                pfad="${HOME}/$SRC"

                echo "${GREEN}I will work in the directory $pfad"
                echo "${LIGHTCYAN}Is that correct (y/n/q)? (q = Quit installer)${NC}"
                read -n 1 -r answer
                echo

                if echo "$answer" | grep -iq "^q" ; then
                    exit_restore
                fi

                if echo "$answer" | grep -iq "^y" ; then
                    if [ ! -d "$pfad" ]; then
                        echo "${RED}This directory does not exist!${NC}"
                    else
                        # Check for native install.sh inside the source directory
                        if [ -f "$pfad/install.sh" ]; then
                            echo
                            echo "${RED}This source contains the install.sh script. Please use this one!${NC}"
                            echo
                            sleep 8
                            exit_restore
                        fi

                        own_path="$HOME/dxf2gcode"
                        rm -rf "$own_path"
                        mkdir -p "$own_path"
                        cp -r "$pfad/." "$own_path"
                        pfad="$own_path"
                        cd "$pfad" || {
                            echo "${RED}Error: Could not change to directory $pfad.${NC}"
                            exit_restore
                        }

                        install_own_source=1
                        return
                    fi
                fi
            done
        fi
    done
}

arch_package_set_available() {
    local package

    for package in "$@"; do
        if pacman -Q "$package" >/dev/null 2>&1 ||
           pacman -Si "$package" >/dev/null 2>&1; then
            continue
        fi
        return 1
    done

    return 0
}

patch_qt_validator() {
    local validator="$1"

    "$pyversion" - "$validator" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text(encoding="utf-8")

if "import os\n" not in source:
    source = source.replace("import sys\n", "import os\nimport sys\n", 1)

start = source.index("def validate_assets():")
end = source.index("\n\nclass BuildPy", start)

replacement = '''def validate_assets():
    version = os.environ.get("DXF2GCODE_QT", "5")
    if version not in ("5", "6"):
        raise RuntimeError("DXF2GCODE_QT must be 5 or 6.")

    missing = []
    names = (
        "dxf2gcode_ui%s.py" % version,
        "dxf2gcode_images%s_rc.py" % version,
    )

    for name in names:
        path = GENERATED / name
        if not path.is_file():
            missing.append(str(path.relative_to(ROOT)))
        elif "from PySide6" in path.read_text(encoding="utf-8"):
            raise RuntimeError(
                "%s must be generated for PyQt%s; run "
                "tools/build/qt_assets.py with DXF2GCODE_QT=%s before building."
                % (path.name, version, version)
            )

    sources = sorted(CATALOGS.glob("dxf2gcode_*.ts"))
    if not sources:
        missing.append("i18n/dxf2gcode_*.ts")

    for source in sources:
        if not source.with_suffix(".qm").is_file():
            missing.append(str(source.with_suffix(".qm").relative_to(ROOT)))

    if missing:
        raise RuntimeError(
            "Qt release assets are missing: %s. Prepare Qt %s assets with "
            "tools/build/qt_assets.py and compile translations with "
            "tools/build/translations.py --no-pylupdate before building."
            % (", ".join(missing), version)
        )
'''

source = source[:start] + replacement + source[end:]
path.write_text(source, encoding="utf-8")
PY
}

install_debian() {
    echo
    echo "${LIGHTCYAN}Ready to install? (y = Yes / q = Quit installer)?${NC}"
    while true; do
        read -n 1 -r answer
        echo
        if echo "$answer" | grep -iq "^y" ;then
            echo ""
            break
        fi
        if echo "$answer" | grep -iq "^q" ;then
            exit_restore
        fi
    done

    set -e

    echo "${GREEN}Update system...${NC}"
    sudo "$aptversion" update
    sudo "$aptversion" install -y git
    sudo "$aptversion" install -y wget
    sudo "$aptversion" install -y unzip
    echo

    #echo "${GREEN}Remove orphaned packages...${NC}"
    #sudo "$aptversion" autoremove -y
    #echo

    echo "${GREEN}Download the developer version...${NC}"
    select_source_dir

    echo
    echo "${GREEN}Install dependencies...${NC}"
    echo

    set -Ee
    trap 'exit_restore' ERR

    sudo "$aptversion" install -y python3-venv

    # Prüft: Paket ist installiert oder hat einen APT-Kandidaten.
    package_set_available() {
        local package candidate

        for package in "$@"; do
            if dpkg-query -W -f='${Status}' "$package" 2>/dev/null |
                grep -q 'install ok installed'; then
                continue
            fi

            candidate=$(LC_ALL=C apt-cache policy "$package" 2>/dev/null |
                awk '$1 == "Candidate:" { print $2; exit }')

            if [ -z "$candidate" ] || [ "$candidate" = "(none)" ]; then
                return 1
            fi
        done

        return 0
    }

    QT5_PACKAGES=(
        qtbase5-dev
        qtbase5-dev-tools
        qttools5-dev-tools
    )

    QT6_PACKAGES=(
        qt6-base-dev
        qt6-base-dev-tools
        qt6-l10n-tools
    )

    # Qt5 bevorzugen; Qt6 nur verwenden, wenn der Qt5-Werkzeugsatz fehlt.
    if package_set_available "${QT5_PACKAGES[@]}"; then
        QT_VERSION=5
        sudo "$aptversion" install -y \
            "${QT5_PACKAGES[@]}" \
            libxcb-cursor0
    elif package_set_available "${QT6_PACKAGES[@]}"; then
        QT_VERSION=6
        sudo "$aptversion" install -y \
            "${QT6_PACKAGES[@]}" \
            libxcb-cursor0
        export PATH="/usr/lib/qt6/bin:/usr/lib/qt6/libexec:/usr/lib64/qt6/libexec:$PATH"
    else
        echo "${RED}Error: Qt 5 and Qt 6 build tools are unavailable.${NC}"
        exit_restore
    fi

    echo "${GREEN}Qt ${QT_VERSION} selected.${NC}"

    # pyproject.toml finden
    PYPROJECT_FILE=$(find "$pfad" -type f -name "pyproject.toml" -print -quit)

    if [ -z "$PYPROJECT_FILE" ]; then
        echo "${RED}Error: pyproject.toml not found under $pfad.${NC}"
        exit_restore
    fi

    BUILD_DIR=$(dirname "$PYPROJECT_FILE")
    cd "$BUILD_DIR" || {
        echo "${RED}Error: Could not change to directory $BUILD_DIR.${NC}"
        exit_restore
    }

    echo
    echo "BUILD_DIR: $BUILD_DIR"
    echo

    # Virtuelle Umgebung erstellen und aktivieren
    echo "${GREEN}Create and activate virtual environment...${NC}"
    "$pyversion" -m venv .venv
    source .venv/bin/activate

    "$pipversion" install --upgrade pip
    "$pipversion" install setuptools wheel build

    if [ "$QT_VERSION" -eq 5 ]; then
        "$pipversion" install PyQt5
    else
        "$pipversion" install PyQt6
    fi

    # Die Variable steuert sowohl qt_compat als auch den Build-Validator.
    export DXF2GCODE_QT="$QT_VERSION"

    # Validator in dieser Quellkopie auf die ausgewählte Qt-Version begrenzen.
    python3 - "$BUILD_DIR/tools/build/setuptools_commands.py" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text(encoding="utf-8")

if "import os\n" not in source:
    source = source.replace("import sys\n", "import os\nimport sys\n", 1)

start = source.index("def validate_assets():")
end = source.index("\n\nclass BuildPy", start)

replacement = '''def validate_assets():
    version = os.environ.get("DXF2GCODE_QT", "5")
    if version not in ("5", "6"):
        raise RuntimeError("DXF2GCODE_QT must be 5 or 6.")

    missing = []
    names = (
        "dxf2gcode_ui%s.py" % version,
        "dxf2gcode_images%s_rc.py" % version,
    )

    for name in names:
        path = GENERATED / name
        if not path.is_file():
            missing.append(str(path.relative_to(ROOT)))
        elif "from PySide6" in path.read_text(encoding="utf-8"):
            raise RuntimeError(
                "%s must be generated for PyQt%s; run "
                "tools/build/qt_assets.py with DXF2GCODE_QT=%s before building."
                % (path.name, version, version)
            )

    sources = sorted(CATALOGS.glob("dxf2gcode_*.ts"))
    if not sources:
        missing.append("i18n/dxf2gcode_*.ts")

    for source in sources:
        if not source.with_suffix(".qm").is_file():
            missing.append(str(source.with_suffix(".qm").relative_to(ROOT)))

    if missing:
        raise RuntimeError(
            "Qt release assets are missing: %s. Prepare Qt %s assets with "
            "tools/build/qt_assets.py and compile translations with "
            "tools/build/translations.py --no-pylupdate before building."
            % (", ".join(missing), version)
        )
'''

source = source[:start] + replacement + source[end:]
path.write_text(source, encoding="utf-8")
PY

    mkdir -p dxf2gcode/presentation/qt/generated

    echo "${GREEN}Generate Qt ${QT_VERSION} assets...${NC}"
    "$pyversion" tools/build/qt_assets.py

    echo "${GREEN}Compile translation catalogs with Qt ${QT_VERSION}...${NC}"
    "$pyversion" tools/build/translations.py --no-pylupdate

    echo "${GREEN}Build and install wheel...${NC}"
    "$pipversion" wheel . --no-deps --no-build-isolation --wheel-dir dist
    "$pipversion" install dist/*.whl
}

install_arch() {
    sudo pacman -Syu

    set -Ee
    trap 'exit_restore' ERR

    local QT5_PACKAGES=(qt5-base qt5-tools)
    local QT6_PACKAGES=(qt6-base qt6-tools)

    if arch_package_set_available "${QT5_PACKAGES[@]}"; then
        QT_VERSION=5
        sudo pacman -S --needed --noconfirm \
            "${QT5_PACKAGES[@]}" libxcb unzip wget git
    elif arch_package_set_available "${QT6_PACKAGES[@]}"; then
        QT_VERSION=6
        sudo pacman -S --needed --noconfirm \
            "${QT6_PACKAGES[@]}" libxcb unzip wget git
        export PATH="/usr/lib/qt6/bin:/usr/lib/qt6/libexec:$PATH"
    else
        echo "${RED}Error: Qt 5 and Qt 6 tools are unavailable in pacman repositories.${NC}"
        exit_restore
    fi

    echo "${GREEN}Qt ${QT_VERSION} selected.${NC}"

    echo "${GREEN}Download the developer version...${NC}"
    select_source_dir

    if [ -z "$pfad" ] || [ ! -d "$pfad" ]; then
        echo "${RED}Error: Source folder not found!${NC}"
        exit_restore
    fi

    local PYPROJECT_FILE
    PYPROJECT_FILE=$(find "$pfad" -type f -name "pyproject.toml" -print -quit)

    if [ -z "$PYPROJECT_FILE" ]; then
        echo "${RED}Error: pyproject.toml not found under $pfad.${NC}"
        exit_restore
    fi

    local BUILD_DIR
    BUILD_DIR=$(dirname "$PYPROJECT_FILE")
    cd "$BUILD_DIR"

    echo
    echo "BUILD_DIR: $BUILD_DIR"
    echo

    echo "${GREEN}Create and activate virtual environment...${NC}"
    "$pyversion" -m venv .venv
    source .venv/bin/activate

    "$pipversion" install --upgrade pip
    "$pipversion" install setuptools wheel build

    if [ "$QT_VERSION" -eq 5 ]; then
        "$pipversion" install PyQt5
    else
        "$pipversion" install PyQt6
    fi

    export DXF2GCODE_QT="$QT_VERSION"

    patch_qt_validator "$BUILD_DIR/tools/build/setuptools_commands.py"

    mkdir -p dxf2gcode/presentation/qt/generated

    echo "${GREEN}Build Qt ${QT_VERSION} assets...${NC}"
    "$pyversion" tools/build/qt_assets.py

    echo "${GREEN}Compile translations with Qt ${QT_VERSION}...${NC}"
    "$pyversion" tools/build/translations.py --no-pylupdate

    echo "${GREEN}Build and install wheel...${NC}"
    "$pipversion" wheel . --no-deps --no-build-isolation --wheel-dir dist
    "$pipversion" install dist/*.whl
}

install_other() {
    echo "${RED}Unsupported OS. Manual installation required.${NC}"
    exit_restore
}

## OS detection
if [ -f /etc/debian_version ]; then
    OS="debian"
elif [ -f /etc/arch-release ]; then
    OS="arch"
else
    OS="other"
fi

case "$OS" in
    debian)
        install_debian
        ;;
    arch)
        install_arch
        ;;
    other)
        install_other
        ;;
esac

## Icon Download
if [ ! -f "$ICON_FILE" ]; then
    echo
    echo "${GREEN}Downloading icon…${NC}"
    if ! wget -O "$ICON_FILE" "$ICON_URL"; then
        echo
        echo "${RED}Error: Download failed (e.g., 404 Not Found or no connection).${NC}"
        exit_restore
    fi
fi

## Starter
# Absoluten Pfad zur ausführbaren dxf2gcode-Datei in der .venv ermitteln
REAL_EXEC_PATH=$(find "$HOME/dxf2gcode" -type f -path "*/.venv/bin/dxf2gcode" | head -n 1)

# Fallback
if [ -z "$REAL_EXEC_PATH" ]; then
    REAL_EXEC_PATH=$(find "$HOME/dxf2gcode" -type f -name "dxf2gcode" | head -n 1)
fi

echo "${GREEN}Determined binary path for starter: $REAL_EXEC_PATH${NC}"

# Alten Starter löschen
echo
echo "${GREEN}Build the $STARTER_FILE file...${NC}"
rm -f "$STARTER_FILE"

# Starter erstellen
cat << EOF > "$STARTER_FILE"
#!/bin/bash
# dxf2gcode.sh
# Starts dxf2gcode with the Qt version selected by the installer.

export DXF2GCODE_QT="$QT_VERSION"
exec "$REAL_EXEC_PATH" "\$@"
EOF

# Starter ausführbar machen
chmod +x "$STARTER_FILE"

# TMP Verzeichnis löschen
rm -rf "$BACKUP_TMPDIR"

echo
echo "${LIGHTCYAN}dxf2gcode was successfully installed.${NC}"
echo
echo "You can start it now with ${GREEN}~/dxf2gcode.sh${NC} in the console."
echo "If you want, you can create a starter on the desktop. Use command ${GREEN}$HOME/dxf2gcode.sh %f${NC} inside the starter."
echo "The icon for the starter is stored at: ${GREEN}$ICON_FILE${NC}"
echo
echo "${LIGHTCYAN}To uninstall, simply delete the ${GREEN}$HOME/dxf2gcode${LIGHTCYAN} directory.${NC}"
echo
exit 0
