#!/usr/bin/env bash
# Installs SolarDeck for the current user on Ubuntu/Debian (venv in ~/.local/share/solardeck).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PREFIX="$HOME/.local/share/solardeck"

echo "==> System dependencies (needs sudo)"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip \
    libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libdbus-1-3 libfontconfig1

echo "==> Virtual environment and package"
python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --upgrade pip
"$PREFIX/venv/bin/pip" install "$HERE"

echo "==> Launcher and icon"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/scalable/apps"
ln -sf "$PREFIX/venv/bin/solardeck" "$HOME/.local/bin/solardeck"
cp "$HERE/packaging/solardeck.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/solardeck.svg"
sed -e "s|@EXEC@|$PREFIX/venv/bin/solardeck|" -e "s|@ICON@|solardeck|" "$HERE/packaging/solardeck.desktop" \
    > "$HOME/.local/share/applications/solardeck.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -q -t -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo "Done. Start 'solardeck' from the applications menu or from a terminal (try: solardeck --sim)."
