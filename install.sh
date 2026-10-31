#!/bin/bash

echo ""
echo "#################################"
echo "# dxf2gcode Install Script V6.0 #"
echo "#   for Debian & Arch based OS  #"
echo "#      by Daniel Luginbuehl     #"
echo "#   webmaster@ltspiceusers.ch   #"
echo "#          (c) 2026             #"
echo "#################################"
echo ""
echo "Support: https://www.ltspiceusers.ch/#dxf2gcode.68"
echo ""
echo ""

STABLE_SOURCE_URL="https://sourceforge.net/projects/dxf2gcode/files/dxf2gcode-20220226_RC1.zip/download"

DEV_URL="https://sourceforge.net/code-snapshots/git/d/dx/dxf2gcode/sourcecode.git/dxf2gcode-sourcecode-11a14d4443919a4755d0f37686bd9d1a3c967951.zip"
#DEV_URL="https://sourceforge.net/projects/dxf2gcode/files/Development/dxf2gcode.zip/download"

GITHUB_URL="https://github.com/ltspicer/dxf2gcode_dev/archive/master.zip"
#GITHUB_URL="https://github.com/ltspicer/dxf2gcode/archive/master.zip"

ICON_URL="https://sourceforge.net/projects/dxf2gcode/files/Development/DXF2GCODE.ico/download"

sourceforge=false       # Download from github: false | Download from sourceforge: true
pipversion="pip3"       # pip command syntax
pyversion="python3"     # If python-is-python3 is installed, change to "python"
aptversion="apt-get"    # Old style = apt-get | New style = apt

#### Do not make any changes from here!

PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
PYDIR="/usr/lib/python${MAJOR}.${MINOR}"

TMPDIR=$(mktemp -d)

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
LIGHTCYAN=$'\033[1;36m'
NC=$'\033[0m'

devinst=0

# Für künftige git clone Funktion
#download_via_git_clone() {
#    local url="$1"
#    local unused_outfile="$2"
#
#    local target_dir="$TMPDIR/dxf2gcode-sourcecode"
#
#    echo -e "${GREEN}Cloning via Git: $url${NC}"
#    # Klonen direkt in den Unterordner 'source'
#    git clone "$url" "$target_dir/source"
#}

download_zip() {
    local url="$1"
    local outfile="$2"

    echo "${GREEN}Downloading: $url${NC}"
    wget -O "$outfile" "$url"
    unzip "$outfile" -d "$TMPDIR"
    rm "$outfile"
}

download_source() {
    if $sourceforge ; then
        echo "${GREEN}Download from SOURCEFORGE${NC}"
        download_zip "$DEV_URL" "$TMPDIR/dev.zip"
    else
        echo "${GREEN}Download from GITHUB${NC}"
        download_zip "$GITHUB_URL" "$TMPDIR/master.zip"
        echo "${GREEN}Downloading icon…${NC}"
        wget -O ${HOME}/DXF2GCODE.ico https://raw.githubusercontent.com/ltspicer/dxf2gcode.linux.installer/main/DXF2GCODE.ico
    fi

    pfad=$(find_deepest_dxf2gcode_dir "$TMPDIR")
    cd "$pfad" || { echo "${RED}Error: Could not change to directory $pfad ${NC}"; exit 1; }

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
    echo "If you want install your own version press n${NC}"

    while true; do
        read answer

        # --- Automatic developer download ---
        if echo "$answer" | grep -iq "^y" ; then
            download_source
            devinst=0
            return
        fi

        # --- Manual path selection ---
        if echo "$answer" | grep -iq "^n" ; then
            echo
            echo "${RED}Ok. First download the desired version of dxf2gcode into your home directory${NC}"
            echo "Download links:"
            echo
            echo "${GREEN}https://sourceforge.net/p/dxf2gcode/sourcecode/ci/develop/tree${NC} (source directory)"
            echo "or"
            echo "${GREEN}https://github.com/ltspicer/dxf2gcode${NC}"
            echo

            while true; do
                echo "${LIGHTCYAN}Enter path to the dxf2gcode source in your home directory e.g. ${GREEN}Downloads/source ${RED}(without / at the beginning and end!) ${NC}"
                read SRC

                [ -z "$SRC" ] && SRC="_"
                if echo "$SRC" | grep -iq "^q" ; then
                    exit
                fi

                pfad="${HOME}/$SRC"

                echo "${GREEN}I will work in the directory $pfad"
                echo "${LIGHTCYAN}Is that correct (y/n/q)? (q = Quit installer)${NC}"
                read answer

                if echo "$answer" | grep -iq "^q" ; then
                    exit
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
                            exit 1
                        fi

                        cd "$pfad"
                        devinst=1
                        return
                    fi
                fi
            done
        fi
    done
}

check_python_version() {    # Python version >= 3.9 ?
    REQUIRED_MAJOR=3
    REQUIRED_MINOR=9

    if [ "$MAJOR" -lt "$REQUIRED_MAJOR" ] || { [ "$MAJOR" -eq "$REQUIRED_MAJOR" ] && [ "$MINOR" -lt "$REQUIRED_MINOR" ]; }; then
        echo "${RED}Error: Python ${REQUIRED_MAJOR}.${REQUIRED_MINOR} or higher is required (found $PYVER)."
        echo "Please install a modern Python version.${NC}"
        sleep 8
        exit 1
    fi
}

install_debian() {
    check_python_version

    if ! hash $pyversion; then
        echo "${RED}$pyversion is not installed"
        echo "Script ends in 8 seconds${NC}"
        sleep 8
        exit
    fi

    echo "${GREEN}Installed Python version:"
    $pyversion -V
    echo "${NC}"

    # Must be developer version if Python >= 3.10

    if [ "$MAJOR" -gt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 10 ]; }; then
        echo "${GREEN}Python $PYVER detected (>= 3.10)."
        echo "Developer version of dxf2gcode will be installed.${NC}"
        devinst=1
    fi

    set -e

    echo "${LIGHTCYAN}Do you want install..."
    if [ $devinst -eq 0 ] ;then
        echo "1   ...the latest stable version"
        echo "2   ...a developer version"
        echo "3   Quit installer${NC}"
        while true; do
            read answer
            if echo "$answer" | grep -iq "^3" ;then
                exit
            fi
            if echo "$answer" | grep -iq "^1" ;then
                break
            fi
            if echo "$answer" | grep -iq "^2" ;then
                break
            fi
        done
    else
        echo "${LIGHTCYAN}2   ...a developer version"
        echo "3   Quit installer${NC}"
        while true; do
            read answer
            if echo "$answer" | grep -iq "^3" ;then
                exit
            fi
            if echo "$answer" | grep -iq "^2" ;then
                break
            fi
        done
    fi

    echo
    echo "${LIGHTCYAN}I will now install. Are you ready (y/n)?${NC}"
    while true; do
        read answer
        if echo "$answer" | grep -iq "^y" ;then
            echo ""
            break
        fi
        if echo "$answer" | grep -iq "^n" ;then
            sudo rm -rf $TMPDIR
            exit
        fi
    done

    set +e

    echo "${GREEN}Update system...${NC}"
    sudo $aptversion update
    sudo $aptversion install -y git
    echo

    echo "${GREEN}Remove orphaned packages...${NC}"
    sudo $aptversion autoremove -y
    echo

    if echo "$answer" | grep -iq "^1" ; then
        echo "${GREEN}Download the latest stable...${NC}"
        download_zip "$STABLE_SOURCE_URL" "$TMPDIR/dxf.zip"
        pfad=$(find_deepest_dxf2gcode_dir "$TMPDIR")
        cd "$pfad"

    else
        echo "${GREEN}Download the developer version...${NC}"
        select_source_dir
    fi

    echo
    echo "${GREEN}Install dependencies...${NC}"
    echo

    sudo $aptversion install -y python3-venv
    sudo $aptversion install -y qt6-base-dev qt6-tools-dev pyqt5-dev-tools pyqt6-dev-tools libxcb-cursor0

    # Qt6-Tools in den Pfad aufnehmen (wichtig für Debian/Ubuntu)
    export PATH="/usr/lib/qt6/bin:/usr/lib/qt6/libexec:$PATH"

    # Virtuelle Umgebung aktivieren
    echo
    echo "${GREEN}Activate virtual environment...${NC}"
    $pyversion -m venv .venv
    source .venv/bin/activate

    cd "$pfad/source"

    echo
    echo "${GREEN}Install pip, setuptools, wheel, build, PyQt...${NC}"
    $pipversion install --upgrade pip
    $pipversion install setuptools wheel build
    if command -v rcc >/dev/null 2>&1 || command -v lrelease-qt6 >/dev/null 2>&1; then
        $pipversion install PyQt6
    else
        $pipversion install PyQt5
    fi

    echo
    echo "${GREEN}Build language files...${NC}"
    # Ordner für generierte Dateien erstellen
    mkdir -p dxf2gcode/presentation/qt/generated i18n

    # Asset-Generierung absichern (falls ein System-Tool fehlt)
    $pyversion tools/build/qt_assets.py || true
    $pyversion tools/build/translations.py --no-pylupdate || true

    # Sicherstellen, dass jede vom Validator verlangte Datei existiert.
    # Falls Qt5-Dateien fehlen, fülle sie mit Qt6
    [ -f dxf2gcode/presentation/qt/generated/dxf2gcode_ui6.py ] && [ ! -f dxf2gcode/presentation/qt/generated/dxf2gcode_ui5.py ] && cp dxf2gcode/presentation/qt/generated/dxf2gcode_ui6.py dxf2gcode/presentation/qt/generated/dxf2gcode_ui5.py
    [ -f dxf2gcode/presentation/qt/generated/dxf2gcode_images6_rc.py ] && [ ! -f dxf2gcode/presentation/qt/generated/dxf2gcode_images5_rc.py ] && cp dxf2gcode/presentation/qt/generated/dxf2gcode_images6_rc.py dxf2gcode/presentation/qt/generated/dxf2gcode_images5_rc.py

    # Falls Qt6-Dateien fehlen, fülle sie mit Qt5
    [ -f dxf2gcode/presentation/qt/generated/dxf2gcode_ui5.py ] && [ ! -f dxf2gcode/presentation/qt/generated/dxf2gcode_ui6.py ] && cp dxf2gcode/presentation/qt/generated/dxf2gcode_ui5.py dxf2gcode/presentation/qt/generated/dxf2gcode_ui6.py
    [ -f dxf2gcode/presentation/qt/generated/dxf2gcode_images5_rc.py ] && [ ! -f dxf2gcode/presentation/qt/generated/dxf2gcode_images6_rc.py ] && cp dxf2gcode/presentation/qt/generated/dxf2gcode_images5_rc.py dxf2gcode/presentation/qt/generated/dxf2gcode_images6_rc.py

    # Dummies für ev. fehlende Sprachdateien erzeugen, falls lrelease gestreikt hat
    for lang in de fr ru; do
        touch i18n/dxf2gcode_${lang}.qm
    done

    # Wheel bauen und installieren
    echo
    echo "${GREEN}Build wheel file...${NC}"
    $pipversion wheel . --no-deps --no-build-isolation --wheel-dir dist
    $pipversion install dist/*.whl
}

install_arch() {
    check_python_version

    echo
    echo "${GREEN}Install required system packages via pacman...${NC}"

    sudo pacman -S --needed --noconfirm \
        qt6-tools \
        qt5-tools \
        libxcb \
        unzip \
        wget \
        git

    download_source

    # Überprüfe das Quellverzeichnis
    if [ -z "$pfad" ] || [ ! -d "$pfad" ]; then
        echo "${RED}Error: Source folder not found!${NC}"
        exit 1
    fi

    # Virtuelle Umgebung im temporären Verzeichnis erstellen und aktivieren
    echo
    echo "${GREEN}Activate virtual environment...${NC}"
    $pyversion -m venv .venv
    source .venv/bin/activate

    # In den Quellordner wechseln
    cd "$pfad/source"

    # Python Build-Abhängigkeiten in der venv installieren
    echo
    echo "${GREEN}Install pip, setuptools, wheel, build, PyQt...${NC}"
    $pipversion install --upgrade pip
    $pipversion install PyQt5 PyQt6 setuptools wheel build

    # Falls die Qt-Tools systemspezifisch im Pfad fehlen, Arch-Standardpfade hinzufügen
    export PATH="/usr/lib/qt6/bin:/usr/lib/qt/bin:$PATH"

    export QT_SELECT=qt6

    # Assets und Übersetzungen generieren
    echo
    echo "${GREEN}Build language files...${NC}"
    $pyversion tools/build/qt_assets.py || true
    $pyversion tools/build/translations.py --no-pylupdate || true

    # Falls der Arch-rcc-Compiler stur PySide-Code erzeugt hat, 
    # Importzeile in der generierten Datei auf PyQt6 umpatchen:
    if [ -f dxf2gcode/presentation/qt/generated/dxf2gcode_images6_rc.py ]; then
        sed -i 's/from PySide2 import QtCore/from PyQt6 import QtCore/g' dxf2gcode/presentation/qt/generated/dxf2gcode_images6_rc.py
        sed -i 's/from PySide6 import QtCore/from PyQt6 import QtCore/g' dxf2gcode/presentation/qt/generated/dxf2gcode_images6_rc.py
    fi

    # Erstellt die von setuptools verlangten Dummies, falls eine Qt-Version übersprungen wurde
    mkdir -p dxf2gcode/presentation/qt/generated i18n
    
    [ -f dxf2gcode/presentation/qt/generated/dxf2gcode_ui6.py ] && [ ! -f dxf2gcode/presentation/qt/generated/dxf2gcode_ui5.py ] && cp dxf2gcode/presentation/qt/generated/dxf2gcode_ui6.py dxf2gcode/presentation/qt/generated/dxf2gcode_ui5.py
    [ -f dxf2gcode/presentation/qt/generated/dxf2gcode_images6_rc.py ] && [ ! -f dxf2gcode/presentation/qt/generated/dxf2gcode_images5_rc.py ] && cp dxf2gcode/presentation/qt/generated/dxf2gcode_images6_rc.py dxf2gcode/presentation/qt/generated/dxf2gcode_images5_rc.py
    [ -f dxf2gcode/presentation/qt/generated/dxf2gcode_ui5.py ] && [ ! -f dxf2gcode/presentation/qt/generated/dxf2gcode_ui6.py ] && cp dxf2gcode/presentation/qt/generated/dxf2gcode_ui5.py dxf2gcode/presentation/qt/generated/dxf2gcode_ui6.py
    [ -f dxf2gcode/presentation/qt/generated/dxf2gcode_images5_rc.py ] && [ ! -f dxf2gcode/presentation/qt/generated/dxf2gcode_images6_rc.py ] && cp dxf2gcode/presentation/qt/generated/dxf2gcode_images5_rc.py dxf2gcode/presentation/qt/generated/dxf2gcode_images6_rc.py

    for lang in de fr ru; do
        touch i18n/dxf2gcode_${lang}.qm
    done

    # 5. Wheel bauen und in der venv installieren
    echo
    echo "${GREEN}Build wheel file...${NC}"
    $pipversion wheel . --no-deps --no-build-isolation --wheel-dir dist
    $pipversion install dist/*.whl
}

install_other() {
    echo "${RED}Unsupported OS. Manual installation required.${NC}"
    exit 1
}

# --- OS detection ---
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

# venv verlassen und aus dem temporären Ordner herauswechseln
cd "$HOME"
if [ "$(type -t deactivate)" = "function" ]; then
    deactivate
fi

# Ordner ins Home-Verzeichnis verschieben
echo
echo "${GREEN}Move the dxf2gcode folder to the HOME directory...${NC}"
sudo rm -rf "$HOME/dxf2gcode"
mv "$pfad" "$HOME/dxf2gcode"

# Shebang anpassen
echo
echo "${GREEN}Adjust the shebang...${NC}"
sed -i "1s|.*|#!$HOME/dxf2gcode/.venv/bin/python|" "$HOME/dxf2gcode/.venv/bin/dxf2gcode"

ICON_FILE="$HOME/DXF2GCODE.ico"

if [ ! -f "$ICON_FILE" ]; then
    echo "${GREEN}Downloading icon…${NC}"
    wget -O "$ICON_FILE" "$ICON_URL"
fi

if [ $devinst -eq 1 ] ;then
    echo
    echo "${LIGHTCYAN}Should I delete the "$pfad" directory (y/N)?${NC}"
    read answer
    if echo "$answer" | grep -iq "^y" ;then
        sudo rm -rf $pfad
    fi
fi

# Alten Starter löschen
echo
echo "${GREEN}Build the dxf2gcode.sh starter script in HOME directory...${NC}"
rm -f $HOME/dxf2gcode.sh

# Starter im $HOME-Verzeichnis erstellen
cat << 'EOF' > "$HOME/dxf2gcode.sh"
#!/bin/bash
# dxf2gcode.sh
# Startet dxf2gcode direkt aus seiner virtuellen Umgebung

# Führt das Programm mit dem Python-Interpreter der venv aus
# und reicht alle übergebenen Argumente ("$@") weiter
exec "$HOME/dxf2gcode/.venv/bin/dxf2gcode" "$@"
EOF

# Starter ausführbar machen
chmod +x "$HOME/dxf2gcode.sh"

echo
echo "${LIGHTCYAN}dxf2gcode was successfully installed.${NC}"
echo
echo "You can start it now with ${GREEN}~/dxf2gcode.sh${NC} in the console."
echo "If you want, you can create a starter on the desktop. Use command ${GREEN}~/dxf2gcode.sh %f${NC} inside the starter."
echo "The icon for the starter is stored at: ${GREEN}"${HOME}/DXF2GCODE.ico"${NC}"
echo
echo "${LIGHTCYAN}To uninstall, simply delete the ${GREEN}$HOME/dxf2gcode${LIGHTCYAN} directory.${NC}"

exit 0
