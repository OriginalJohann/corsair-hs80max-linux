#!/usr/bin/env bash
# E2E test: HS80 D-Bus service against a private test bus.
#
# Run from anywhere: ./service/test_dbus.sh
#
# Requires a Python env with pydbus + python3-gi: the repo venv
# (service/.venv) when present, otherwise plain python3 (e.g. inside the
# dev nix-shell).
#
# NOTE: keep the dongle unplugged – with the receiver present the daemon's
# poll cycle can take up to ~30 s and the startup wait below may time out.
set -u
# Run from the repo root (the script lives in service/).
cd "$(dirname "$(readlink -f "$0")")/.."

# Prefer the repo venv; fall back to plain python3 (e.g. nix-shell).
if [ -x service/.venv/bin/python ]; then
  PY=service/.venv/bin/python
else
  PY=python3
fi

WORKDIR="$(mktemp -d /tmp/hs80max-e2e.XXXXXX)"
SOCK="$WORKDIR/bus.sock"
CONF="$WORKDIR/dbus.conf"
LOG="$WORKDIR/service.log"
cleanup() {
  pkill -f "hs80max_service.main" 2>/dev/null || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

cat > "$CONF" <<CONF
<busconfig>
  <listen>unix:path=$SOCK</listen>
  <policy user="*">
    <allow own="*"/>
    <allow send_destination="*"/>
    <allow receive_sender="*"/>
  </policy>
</busconfig>
CONF

# The default session policy already allows owning any name, so the policy
# block above only documents intent (private local test bus, single user).
dbus-daemon --config-file="$CONF" --fork

export DBUS_SESSION_BUS_ADDRESS="unix:path=$SOCK"

# Start service in background (no timeout – we kill it later)
DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
  "$PY" -m hs80max_service.main > "$LOG" 2>&1 &
SPID=$!

# Wait for the service to register on the bus (bounded retry, not a fixed
# sleep – startup time varies with the environment).
for _ in $(seq 1 30); do
  if timeout 3 dbus-send --print-reply --dest=com.corsair.hs80max \
       /com/corsair/hs80max com.corsair.hs80max.GetStatus > /dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$SPID" 2>/dev/null; then
    echo "--- SERVICE LOG (died during startup) ---"
    cat "$LOG"
    exit 1
  fi
  sleep 0.5
done

echo "=== GetStatus ==="
timeout 5 dbus-send --print-reply --dest=com.corsair.hs80max /com/corsair/hs80max com.corsair.hs80max.GetStatus 2>&1 || echo "(timeout or error)"
echo "=== Property Mode ==="
timeout 5 gdbus call --session --dest com.corsair.hs80max --object-path /com/corsair/hs80max \
  --method org.freedesktop.DBus.Properties.Get com.corsair.hs80max Mode 2>&1 || echo "(timeout or error)"

# Cleanup: kill service and bus, remove temp files
kill "$SPID" 2>/dev/null || true
sleep 1
dbus-daemon --config-file="$CONF" --fork --exit

echo "--- SERVICE LOG ---"
cat "$LOG"
