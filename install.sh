#!/bin/sh
set -eu

INSTALL_DIR="$HOME/.local/share/steam-frame-passthrough-toggle"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_NAME="steam-frame-passthrough-toggle.service"
ACTION=${1:-install}
SF_TOGGLE_BASE_URL=${SF_TOGGLE_BASE_URL:-https://raw.githubusercontent.com/toorux/steam-frame-passthrough-toggle/main}

uninstall_plugin() {
    systemctl --user disable --now "$UNIT_NAME" 2>/dev/null || true
    rm -f "$UNIT_DIR/$UNIT_NAME"
    rm -rf "$INSTALL_DIR"
    systemctl --user daemon-reload
    echo "Steam Frame Passthrough Toggle removed."
}

case "$ACTION" in
    uninstall)
        uninstall_plugin
        exit 0
        ;;
    install) ;;
    *) echo "Usage: install.sh [install|uninstall]" >&2; exit 2 ;;
esac

command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }
command -v systemctl >/dev/null 2>&1 || { echo "systemd is required" >&2; exit 1; }

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || true)
if [ ! -f "$SOURCE_DIR/src/steam_frame_passthrough_toggle.py" ]; then
    command -v curl >/dev/null 2>&1 || { echo "curl is required for remote installation" >&2; exit 1; }
    command -v unzip >/dev/null 2>&1 || { echo "unzip is required for remote installation" >&2; exit 1; }
    command -v sha256sum >/dev/null 2>&1 || { echo "sha256sum is required for remote installation" >&2; exit 1; }
    TEMP_DIR=$(mktemp -d)
    trap 'rm -rf "$TEMP_DIR"' EXIT INT TERM
    SOURCE_DIR="$TEMP_DIR/package"
    mkdir -p "$SOURCE_DIR/src" "$SOURCE_DIR/vendor/frame-passthrough-shortcuts"
    curl -fsSL "$SF_TOGGLE_BASE_URL/src/steam_frame_passthrough_toggle.py" -o "$SOURCE_DIR/src/steam_frame_passthrough_toggle.py"
    curl -fsSL "$SF_TOGGLE_BASE_URL/steam-frame-passthrough-toggle.service" -o "$SOURCE_DIR/steam-frame-passthrough-toggle.service"
    HELPER_ZIP="$TEMP_DIR/helper.zip"
    curl -fsSL "https://github.com/KominoVR/frame-passthrough-shortcuts/releases/download/v0.1.0/frame-passthrough-shortcuts-0.1.0-linux-arm64.zip" -o "$HELPER_ZIP"
    echo "68f742051318a56dbb04f089f9d5e8546cf82ee101131390be3fbcb13767a66d  $HELPER_ZIP" | sha256sum -c - >/dev/null
    unzip -q "$HELPER_ZIP" -d "$SOURCE_DIR/vendor/frame-passthrough-shortcuts"
fi

mkdir -p "$INSTALL_DIR/src" "$INSTALL_DIR/vendor/frame-passthrough-shortcuts" "$UNIT_DIR"
install -m 755 "$SOURCE_DIR/src/steam_frame_passthrough_toggle.py" "$INSTALL_DIR/src/steam_frame_passthrough_toggle.py"
install -m 755 "$SOURCE_DIR/vendor/frame-passthrough-shortcuts/frame-passthrough-shortcuts" "$INSTALL_DIR/vendor/frame-passthrough-shortcuts/frame-passthrough-shortcuts"
install -m 644 "$SOURCE_DIR/vendor/frame-passthrough-shortcuts/actions.json" "$SOURCE_DIR/vendor/frame-passthrough-shortcuts/config.json" "$SOURCE_DIR/vendor/frame-passthrough-shortcuts/LICENSE" "$SOURCE_DIR/vendor/frame-passthrough-shortcuts/THIRD_PARTY_NOTICES.md" "$INSTALL_DIR/vendor/frame-passthrough-shortcuts/"

sed "s|@INSTALL_DIR@|$INSTALL_DIR|g" "$SOURCE_DIR/steam-frame-passthrough-toggle.service" > "$UNIT_DIR/$UNIT_NAME"
systemctl --user daemon-reload
systemctl --user enable --now "$UNIT_NAME"
systemctl --user is-active --quiet "$UNIT_NAME"
echo "Installed. Logs: journalctl --user -u steam-frame-passthrough-toggle -f"
