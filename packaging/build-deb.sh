#!/usr/bin/env bash
# Builds a Debian/Ubuntu package that uses the distribution's PySide6. Output: dist/solardeck_<version>_all.deb
#
#   packaging/build-deb.sh            # needs: bash, dpkg-deb, python3
#   sudo apt install ./dist/solardeck_<version>_all.deb
#   sudo apt remove solardeck
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="$(python3 -c 'import re;print(re.search(r"\"([^\"]+)\"", open("solardeck/__init__.py").read()).group(1))')"
PKG="solardeck_${VERSION}_all"
STAGE="$ROOT/build/deb/$PKG"
MAINT="Stefano Ciurleo <105057757+stefanolmo@users.noreply.github.com>"

rm -rf "$STAGE"
install -d "$STAGE/DEBIAN" "$STAGE/usr/bin" "$STAGE/usr/lib/python3/dist-packages" "$STAGE/usr/share/applications" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps" "$STAGE/usr/share/doc/solardeck" "$STAGE/usr/share/man/man1"
cp -r solardeck "$STAGE/usr/lib/python3/dist-packages/solardeck"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +

cat > "$STAGE/usr/bin/solardeck" <<'PY'
#!/usr/bin/python3
import sys

from solardeck.__main__ import main

sys.exit(main())
PY
chmod 755 "$STAGE/usr/bin/solardeck"
sed -e 's|^Exec=.*|Exec=solardeck|' -e 's|^Icon=.*|Icon=solardeck|' packaging/solardeck.desktop > "$STAGE/usr/share/applications/solardeck.desktop"
cp packaging/solardeck.svg "$STAGE/usr/share/icons/hicolor/scalable/apps/solardeck.svg"
cp README.md "$STAGE/usr/share/doc/solardeck/README.md"
gzip -9n -c packaging/solardeck.1 > "$STAGE/usr/share/man/man1/solardeck.1.gz"

cat > "$STAGE/usr/share/doc/solardeck/copyright" <<TXT
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: solardeck
Files: *
Copyright: 2026 Stefano Ciurleo
License: MIT
TXT
{
  echo "solardeck ($VERSION) stable; urgency=medium"
  echo
  echo "  * Debian/Ubuntu package of SolarDeck $VERSION."
  echo
  echo " -- $MAINT  $(date -R)"
} | gzip -9n > "$STAGE/usr/share/doc/solardeck/changelog.gz"

cat > "$STAGE/DEBIAN/control" <<TXT
Package: solardeck
Version: $VERSION
Section: electronics
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-pyside6.qtcore, python3-pyside6.qtgui, python3-pyside6.qtwidgets
Recommends: libxcb-cursor0, libxkbcommon-x11-0
Maintainer: $MAINT
Installed-Size: $(du -sk "$STAGE" | cut -f1)
Description: SolarEdge HD-Wave monitor over Modbus TCP
 SolarDeck reads production, consumption and grid import/export from a
 SolarEdge inverter (SunSpec over Modbus TCP) and shows them as a live
 energy-flow diagram with a production/consumption chart.
TXT

cat > "$STAGE/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
if command -v py3compile >/dev/null 2>&1; then py3compile -p solardeck || true; fi
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q /usr/share/applications || true; fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true; fi
exit 0
SH
cat > "$STAGE/DEBIAN/prerm" <<'SH'
#!/bin/sh
set -e
if command -v py3clean >/dev/null 2>&1; then py3clean -p solardeck || true; fi
exit 0
SH
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm"
find "$STAGE" -type d -exec chmod 755 {} +
find "$STAGE" -type f ! -perm -111 -exec chmod 644 {} +
chmod 755 "$STAGE/usr/bin/solardeck"

mkdir -p dist
dpkg-deb --root-owner-group --build "$STAGE" "dist/$PKG.deb" >/dev/null
echo "Created dist/$PKG.deb ($(du -h "dist/$PKG.deb" | cut -f1))"
