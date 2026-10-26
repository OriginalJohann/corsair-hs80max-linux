#!/usr/bin/env bash
# E2E test: HS80 D-Bus service against a private test bus.
set -u
cd /Data/ai/corsair-hs80max-linux

cat > /tmp/dbus-test.conf <<'CONF'
<busconfig>
  <listen>unix:path=/tmp/hs80.sock</listen>
  <policy user="fne">
    <allow own="*"/>
    <allow send_destination="*"/>
    <allow receive_sender="*"/>
  </policy>
</busconfig>
CONF

rm -f /tmp/hs80.sock
DBUS_SESSION_BUS_ADDRESS= dbus-daemon --config-file=/tmp/dbus-test.conf --fork
sleep 1

export DBUS_SESSION_BUS_ADDRESS="unix:path=/tmp/hs80.sock"

# Start service in background (no timeout – we kill it later)
DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
  nix-shell shells/dev.nix --command \
  "cd service && python3 -m hs80max_service.main" > /tmp/hs80-test.log 2>&1 &
SPID=$!

# Wait for service to register on the bus
sleep 10

echo "=== GetStatus ==="
timeout 5 dbus-send --print-reply --dest=com.corsair.hs80max /com/corsair/hs80max com.corsair.hs80max.GetStatus 2>&1 || echo "(timeout or error)"
echo "=== GetBattery ==="
timeout 5 dbus-send --print-reply --dest=com.corsair.hs80max /com/corsair/hs80max com.corsair.hs80max.GetBattery 2>&1 || echo "(timeout or error)"
echo "=== GetMicMuted ==="
timeout 5 dbus-send --print-reply --dest=com.corsair.hs80max /com/corsair/hs80max com.corsair.hs80max.GetMicMuted 2>&1 || echo "(timeout or error)"
echo "=== Property Mode ==="
timeout 5 gdbus call --session --dest com.corsair.hs80max --object-path /com/corsair/hs80max \
  --method org.freedesktop.DBus.Properties.Get com.corsair.hs80max Mode 2>&1 || echo "(timeout or error)"

# Cleanup: kill service and remove socket
pkill -f "hs80max_service.main" 2>/dev/null || true
sleep 1
rm -f /tmp/hs80.sock

echo "--- SERVICE LOG ---"
cat /tmp/hs80-test.log
