#!/bin/sh
# Install pd200x-linux for the current user.
#
#   ./install.sh              copy the tool to ~/.local, install the udev rule (asks for sudo)
#   ./install.sh --service    also start the web UI at login (systemd user service)
#   ./install.sh --uninstall  remove all of the above
#
# PREFIX (default ~/.local) can be overridden from the environment.
set -eu

PREFIX=${PREFIX:-$HOME/.local}
SHARE=$PREFIX/share/pd200x
BIN=$PREFIX/bin
UNIT_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
UNIT=$UNIT_DIR/pd200x-web.service
RULE=/etc/udev/rules.d/70-pd200x.rules
SRC=$(cd "$(dirname "$0")" && pwd)

service=0
case "${1:-}" in
  --service) service=1 ;;
  --uninstall)
    if [ -f "$UNIT" ]; then
      systemctl --user disable --now pd200x-web.service 2>/dev/null || true
      rm -f "$UNIT"
      systemctl --user daemon-reload
    fi
    rm -f "$BIN/pd200xctl" "$BIN/pd200x-web"
    rm -rf "$SHARE"
    if [ -f "$RULE" ]; then
      echo "removing $RULE (needs sudo)"
      sudo rm -f "$RULE" && sudo udevadm control --reload-rules
    fi
    echo "uninstalled"
    exit 0 ;;
  "") ;;
  *) echo "usage: $0 [--service|--uninstall]" >&2; exit 2 ;;
esac

command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 1; }

mkdir -p "$SHARE" "$BIN"
install -m 0644 "$SRC/pd200x.py" "$SHARE/pd200x.py"
install -m 0755 "$SRC/pd200xctl" "$SHARE/pd200xctl"
install -m 0755 "$SRC/pd200x-web" "$SHARE/pd200x-web"
ln -sf "$SHARE/pd200xctl" "$BIN/pd200xctl"
ln -sf "$SHARE/pd200x-web" "$BIN/pd200x-web"
echo "installed pd200xctl and pd200x-web to $BIN"

if cmp -s "$SRC/udev/70-pd200x.rules" "$RULE"; then
  echo "udev rule already up to date"
else
  echo "installing $RULE (needs sudo)"
  sudo install -m 0644 "$SRC/udev/70-pd200x.rules" "$RULE"
  sudo udevadm control --reload-rules
  sudo udevadm trigger --action=change --subsystem-match=hidraw
fi

if [ "$service" = 1 ]; then
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT" <<EOF
[Unit]
Description=Maono PD200X web UI (http://127.0.0.1:8200/)

[Service]
ExecStart=$BIN/pd200x-web --port 8200
Restart=on-failure

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now pd200x-web.service
  echo "web UI running at http://127.0.0.1:8200/ and will start at login"
fi

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "note: $BIN is not on your PATH" ;;
esac
