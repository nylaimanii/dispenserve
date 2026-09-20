#!/bin/bash
# Start the whole demo: camera loop, kiosk + dashboard server, and every integration
# that has a key in .env. Prints the URL to open on the iPad.
#
#   ./start.sh                  the usual demo
#   ./start.sh --no-camera      fake scans, no webcam
#   ./start.sh --liveness       add any other main.py flag; they're passed through
set -u
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
PYTHON=".venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo "No .venv here. Run:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

# The kiosk and the app both want port 8000 (ui/mockserver.py is the usual culprit).
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use:"
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN | tail -n +2 | awk '{print "  " $1 " (pid " $2 ")"}'
  echo "Stop it first (e.g. pkill -f mockserver.py), or run with PORT=8001 ./start.sh"
  exit 1
fi

# This Mac's address on the network the iPad is on: the interface with the default
# route first (usually Wi-Fi), then the Wi-Fi device, then anything with an address.
IP=""
DEFAULT_IF=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
WIFI_IF=$(networksetup -listallhardwareports 2>/dev/null | awk '/Hardware Port: Wi-Fi/{getline; print $2}')
for iface in $DEFAULT_IF $WIFI_IF $(networksetup -listallhardwareports 2>/dev/null | awk '/Device:/{print $2}'); do
  ADDR=$(ipconfig getifaddr "$iface" 2>/dev/null)
  if [ -n "$ADDR" ]; then IP="$ADDR"; break; fi
done
[ -z "$IP" ] && IP="localhost"

CAMERA_INDEX=$(grep -E '^CAMERA_INDEX=[0-9]' .env 2>/dev/null | tail -1 | cut -d= -f2)

echo
echo "  Dispenserve"
echo "  ────────────────────────────────────────────────"
echo "  Kiosk (open this on the iPad):"
echo "      http://$IP:$PORT/kiosk.html"
echo "  Operator dashboard:"
echo "      http://$IP:$PORT/dashboard.html"
echo "      (add ?fleet=<fleet-api-url> for the fleet + donor ledger)"
echo "  Camera index: ${CAMERA_INDEX:-auto}    Sensor: off (--no-sensor)"
echo "  Keys: f dispense   c clear memory   r restock   q quit"
echo "  ────────────────────────────────────────────────"
echo

exec "$PYTHON" -u vision/main.py --no-sensor --port "$PORT" "$@"
