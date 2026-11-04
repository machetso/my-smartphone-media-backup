#!/bin/sh
# Linux: put a start icon for Fast Smartphone Media Backup on the desktop and in the app menu.
# Run again after moving the project folder.   Remove:  ./install-linux-desktop.sh --remove
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
ID="fast-smartphone-media-backup"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
DESKTOP="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"

if [ "$1" = "--remove" ]; then
    rm -f "$DATA/applications/$ID.desktop" "$DESKTOP/$ID.desktop"
    find "$DATA/icons/hicolor" -name "$ID.png" -delete 2>/dev/null || true
    echo "Removed."
    exit 0
fi

# icons in all sizes
for d in "$DIR"/assets/hicolor/*/apps; do
    size="$(basename "$(dirname "$d")")"
    mkdir -p "$DATA/icons/hicolor/$size/apps"
    cp "$d/$ID.png" "$DATA/icons/hicolor/$size/apps/$ID.png"
done
gtk-update-icon-cache -q -t "$DATA/icons/hicolor" 2>/dev/null || true

# launcher
mkdir -p "$DATA/applications"
cat > "$DATA/applications/$ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.5
Name=Fast Smartphone Media Backup
GenericName=Phone photo backup
Comment=Verified backup of photos and videos from an Android phone to external drives
Exec="$DIR/start-linux.sh"
Path=$DIR
Icon=$ID
Terminal=false
Categories=Utility;Archiving;
StartupWMClass=$ID
Keywords=backup;phone;photos;videos;android;adb;
EOF
chmod +x "$DATA/applications/$ID.desktop"
update-desktop-database -q "$DATA/applications" 2>/dev/null || true

# desktop icon
if [ -d "$DESKTOP" ]; then
    cp "$DATA/applications/$ID.desktop" "$DESKTOP/$ID.desktop"
    chmod +x "$DESKTOP/$ID.desktop"
    gio set "$DESKTOP/$ID.desktop" metadata::trusted true 2>/dev/null || true
    echo "Desktop icon: $DESKTOP/$ID.desktop"
fi
echo "App menu entry: $DATA/applications/$ID.desktop"
