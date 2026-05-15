#!/usr/bin/env bash
#
# ESP-IDF Installation Script — ESP32 YS Video Player
# Run once: sets up ESP-IDF 5.x in ~/esp/esp-idf
#

set -e

ESPIDF_VERSION="v5.4"
ESPIDF_DIR="$HOME/esp/esp-idf"
INSTALL_URL="https://dl.espressif.com/dl/esp-idf/esp-idf-${ESPIDF_VERSION}.tar.gz"

echo "==================================================="
echo "  ESP-IDF Installer — ESP32 YS Video Player"
echo "==================================================="
echo ""
echo "Installing ESP-IDF $ESPIDF_VERSION to:"
echo "  $ESPIDF_DIR"
echo ""

# Check if already installed
if [ -d "$ESPIDF_DIR" ]; then
    echo "[INFO] ESP-IDF already found at $ESPIDF_DIR"
    read -p "Reinstall? (y/N): " confirm
    if [ "$confirm" != "y" ]; then
        echo "Skipping installation."
        echo ""
        echo "To use ESP-IDF, run:"
        echo "  source $ESPIDF_DIR/export.sh"
        exit 0
    fi
    rm -rf "$ESPIDF_DIR"
fi

# Detect OS
OS="$(uname -s)"
echo "[INFO] Detected OS: $OS"

if [ "$OS" = "Darwin" ]; then
    echo "[INFO] Installing ESP-IDF for macOS..."
    brew install cmake ninja IDF_VER=$ESPIDF_VERSION 2>/dev/null || true
elif [ "$OS" = "Linux" ]; then
    echo "[INFO] Installing ESP-IDF for Linux..."
    sudo apt update && sudo apt install -y git wget flex bison gperf \
        python3 python3-pip python3-venv cmake ninja-build ccache \
        libffi-dev libssl-dev dfu-util libusb-1.0-0 dfu-programmer 2>/dev/null || true
else
    echo "[WARN] Unsupported OS: $OS"
fi

# Create directory and clone
echo "[INFO] Downloading ESP-IDF..."
mkdir -p ~/esp
cd ~/esp

if command -v curl &> /dev/null; then
    curl -L -o esp-idf.tar.gz "$INSTALL_URL"
    tar -xzf esp-idf.tar.gz
    rm esp-idf.tar.gz
    mv esp-idf* esp-idf 2>/dev/null || true
else
    git clone --recursive -b ${ESPIDF_VERSION} --depth 1 \
        https://github.com/espressif/esp-idf.git "$ESPIDF_DIR"
fi

echo "[INFO] Installing ESP-IDF Python dependencies..."
python3 -m venv "$ESPIDF_DIR/.venv"
source "$ESPIDF_DIR/.venv/bin/activate"
pip install --upgrade pip
pip install pyelftools

echo ""
echo "==================================================="
echo "  INSTALLATION COMPLETE"
echo "==================================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Activate ESP-IDF environment:"
echo "   source $ESPIDF_DIR/export.sh"
echo ""
echo "2. Build the project:"
echo "   cd /path/to/esp32-ys-video-player"
echo "   idf.py build"
echo ""
echo "3. Flash to ESP32:"
echo "   idf.py flash"
echo ""
echo "4. Monitor output:"
echo "   idf.py monitor"
echo ""