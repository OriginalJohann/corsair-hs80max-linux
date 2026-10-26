# HS80 Max Wireless (1b1c:0a97) – HID Battery & Control Protocol

Source: `Sapd/HeadsetControl` – `lib/devices/corsair_void_v2w.hpp`
Verified against: HS80 MAX Wireless receiver (USB `1b1c:0a97`), HID interface 4.

## USB Device

| Property | Value |
|---|---|
| Vendor ID | `0x1b1c` (Corsair) |
| Product ID | `0x0a97` (HS80 MAX Wireless receiver) |
| Control interface | **Interface 4** (OUT EP `0x02`, IN EP `0x83`, descriptor 54 B) |
| Telemetry interface | Interface 3 (IN EP `0x84`, descriptor 147 B) |
| hidraw node | `/dev/hidraw1` (control), `/dev/hidraw0` (telemetry) |

> **No USB Battery SUD** – `/sys/class/power_supply/` is empty.
> All battery data must be read via the proprietary HID protocol.

## Message Format

All messages are **64-byte payloads**. Writes are prefixed with report ID
`0x00` (total **65 bytes** on the hidraw device node).

```
WRITE: [0x00] + 64-byte payload   (65 bytes total)
READ:  64-byte IN report
```

## Wake / Handshake Sequence

Before querying battery or mic state, the receiver must be "woken up":

| Step | Bytes (first 5 of 64) | Endpoint | Purpose |
|---|---|---|---|
| 1 | `00 02 08 02 13` | Receiver (`0x08`) | Firmware query |
| 2 | `00 02 08 02 12` | Receiver (`0x08`) | Receiver heartbeat |
| 3 | `00 02 09 02 12` | Headset (`0x09`) | Headset heartbeat |

After step 3, read one IN report. If a response arrives within the timeout
(1 s), the headset is connected to the receiver. If not, it is offline.

> **Note:** The full `initializeDevice` in HeadsetControl also sends a
> "software mode" command (`00 02 08 01 03 00 02`) before the heartbeat.
> For read-only battery/mic queries this step is **not required**.

## Battery Query

**Request:** write `00 02 09 02 0F` (headset endpoint, command `0x0F`)

**Response:** 64-byte IN report

| Byte | Meaning |
|---|---|
| `[4]` | Low byte of battery value (1–1000, 0.1 % resolution) |
| `[5]` | High byte of battery value |

```
battery_percent = (resp[4] | resp[5] << 8) // 10
```

- Valid range: **1 … 1000** → **0.1 % … 100.0 %**
- The receiver may reply with a paired-headset ID instead of the battery
  level (multi-headset pairing). Retry up to **3 times** until a plausible
  reading (1–1000) is received.
- If no response or no plausible value after 3 attempts → battery unavailable.

## Microphone Mute Query

**Request:** write `00 02 09 02 A6` (headset endpoint, command `0xA6`)

**Response:** 64-byte IN report

| Byte | Meaning |
|---|---|
| `[4]` | `0x01` = mic muted (boom mic flipped up), `0x00` = not muted |

## Endpoint Constants

| Constant | Value | Description |
|---|---|---|
| `RECEIVER_ENDPOINT` | `0x08` | Wireless receiver |
| `HEADSET_ENDPOINT` | `0x09` | Headset (via receiver) |

## Permissions

The hidraw nodes are `root:root 0600` by default. A udev rule is required:

```
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1b1c", ATTRS{idProduct}=="0a97", MODE="0660", GROUP="users"
```

## Known Limitations

- Battery accuracy is approximately **±10 %** (per HeadsetControl docs).
- The receiver may report a headset ID instead of battery level when
  multiple headsets are paired (mitigated by retry loop).
- No charging state is exposed via this protocol (unlike the older
  5-byte `0xC9 0x64` protocol used by some other Corsair devices).
