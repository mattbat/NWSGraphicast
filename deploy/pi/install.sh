#!/usr/bin/env bash
# Install NWSGraphicast on a Raspberry Pi (Raspberry Pi OS / Debian). Run as the normal user:
#   bash deploy/pi/install.sh
# Safe to re-run: it updates the install and leaves your config in place.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOME_DIR="$HOME/graphicast"
CONF="$HOME_DIR/graphicast.env"

command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }
python3 - <<'PY' || { echo "Python 3.11 or newer is required"; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY

mkdir -p "$HOME_DIR"
python3 -m venv "$HOME_DIR/venv"
"$HOME_DIR/venv/bin/pip" install --quiet --upgrade pip
"$HOME_DIR/venv/bin/pip" install --quiet "$SRC"

if [ ! -f "$CONF" ]; then
  cp "$SRC/deploy/pi/graphicast.env.example" "$CONF"
  chmod 600 "$CONF"
  echo "Created $CONF -- edit it and fill in the SMTP settings."
fi

# run.sh starts in the clone: the widget icons are read from ./assets/icons (they are not
# installed into the venv), and cron would otherwise start in $HOME.
cat > "$HOME_DIR/run.sh" <<RUN
#!/usr/bin/env bash
cd "$SRC"
set -a; . "$CONF"; set +a
exec "$HOME_DIR/venv/bin/python" -m graphicast "\$@"
RUN
chmod +x "$HOME_DIR/run.sh"

# Every 15 minutes; the program itself decides whether a run sends (6am/12pm/6pm Central slots).
LINE="*/15 * * * * $HOME_DIR/run.sh >> $HOME_DIR/graphicast.log 2>&1"
( crontab -l 2>/dev/null | grep -v "$HOME_DIR/run.sh" || true; echo "$LINE" ) | crontab -

echo
echo "Installed. Next:"
echo "  1. nano $CONF            (set SMTP_USER, SMTP_PASSWORD, EMAIL_TO)"
echo "  2. $HOME_DIR/run.sh --dry-run --ignore-schedule --out /tmp/preview   (no email, no state)"
echo "  3. $HOME_DIR/run.sh --force                                          (sends a real test email)"
echo "  Logs: $HOME_DIR/graphicast.log"
