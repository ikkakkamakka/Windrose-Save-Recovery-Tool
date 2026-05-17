#!/usr/bin/env bash
set -e

echo ""
echo " Windrose Save Recovery Tool - Build Script"
echo " -------------------------------------------"
echo ""

echo " [1/3] Installing dependencies..."
pip install -r requirements.txt -q
pip install pyinstaller -q
echo "       Done."
echo ""

echo " [2/3] Building executable..."
pyinstaller windrose_tool.spec --clean --noconfirm
echo ""

if [ -f "dist/WindroseSaveRecovery" ]; then
    echo " [3/3] Success!"
    echo ""
    echo " Output: dist/WindroseSaveRecovery"
else
    echo " [3/3] Build failed."
    exit 1
fi
