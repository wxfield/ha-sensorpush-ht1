# SensorPush HT1: Local Bluetooth Integration for Home Assistant

A fully local, cloud-free Home Assistant integration for the **SensorPush HT1** temperature and humidity sensor. No SensorPush account. No subscription. No internet required.

---

## Why This Exists

SensorPush makes excellent hardware. Their HT1 sensor broadcasts temperature and humidity continuously over Bluetooth, every second, to anyone listening, with no pairing required. The data is right there in the air.

This integration receives that data directly, locally, without leaving your network. It is intended for Home Assistant users who prefer local control and do not use the SensorPush cloud platform. If you use the SensorPush app and cloud service, this integration is independent of it; both can coexist.

It also exposes something not available through any other HA path: the HT1 stores weeks of readings in onboard flash memory. This integration connects via Bluetooth every 30 minutes, downloads the complete history, and injects it into Home Assistant's long-term statistics, giving you a continuous record of temperature and humidity stretching back to when the battery was last replaced.

---

## Features

- **Fully local:** no SensorPush account, no cloud, no internet required
- **Real-time** temperature and humidity from passive BLE advertisements (~1 Hz)
- **Battery level** and battery voltage
- **Signal strength** (RSSI)
- **Onboard history download:** retrieves weeks of per-minute readings from the sensor's flash memory and injects them into HA long-term statistics
- **Unit system aware:** statistics stored in °F or °C based on your HA configuration

---

## How It Works

The HT1 uses two distinct Bluetooth mechanisms:

**Passive advertisements (~1 Hz)**
The sensor continuously broadcasts a 4-byte manufacturer payload containing temperature and humidity, encoded using the Silicon Labs Si7021 bit-packing format. No connection needed. Home Assistant's Bluetooth stack receives these advertisements and updates the temperature and humidity entities in real time.

**GATT connection (every 30 minutes)**
The integration briefly connects to the sensor to read battery voltage and download onboard history. The HT1 stores one reading per minute in a circular flash buffer. The integration retrieves all records newer than the last known timestamp and injects them into HA's long-term statistics as hourly buckets, respecting your unit system (°F or °C).

---

## The Protocol

The HT1's live advertisement protocol was straightforward to document; the 4-byte payload and Si7021 encoding are visible to any Bluetooth scanner. The history download protocol was another matter.

SensorPush publishes a BLE API reference for their sensors. In it, characteristics `ef090009` and `ef09000a` are listed as **RESERVED** with no further documentation. No public implementation of the history download existed anywhere as of early 2026.

The protocol was determined through direct BLE probing using Python and [bleak](https://github.com/hbldh/bleak) from a standard laptop. The HT1 is an open GATT server with no pairing, bonding, or authentication requirement. Any Bluetooth central can connect freely.

The trigger: write `0x01000000` (uint32, little-endian) to characteristic `ef090009`. The device responds with a flood of 20-byte notifications on `ef09000a`, delivering up to 4 sensor records per packet, newest first, until an `0xFFFFFFFF` sentinel marks the end of stored history. The per-record encoding is identical to the advertisement format: the same Si7021 bit-packing used for live readings applies directly to every history record.

**Complete GATT characteristic map** (first full public documentation of the HT1 protocol):

| UUID | Properties | Description |
|------|-----------|-------------|
| `ef090001` | read | Device ID (uint24, little-endian) |
| `ef090003` | read | TX power (int8, dBm) |
| `ef090004` | read/write | Measurement interval in seconds (uint16 LE, default 60) |
| `ef090005` | read/write | BLE advertising interval (uint16 LE, 0.625ms slot units, default 0x0505 = 803ms) |
| `ef090006` | read/write | Low alarm thresholds: [temp_raw uint16 LE, hum_raw uint16 LE] in Si7021 raw format |
| `ef090007` | read | Battery: [ADC_raw uint16 LE, die_temp_raw uint16 LE] |
| `ef090008` | read | Last-seen Unix timestamp (uint32 LE) |
| `ef090009` | write | History command: write `0x01000000` to begin download |
| `ef09000a` | notify/read | History data: 20-byte notifications, 4 records per packet |
| `ef09000b` | read/write | Humidity alarms: [low_%RH uint16 LE, high_%RH uint16 LE] (default [5, 55]) |

**History notification format:**
```
Bytes  0– 3:  uint32 LE  Unix timestamp of oldest record in this packet
Bytes  4– 7:  Sensor record 1  (timestamp + 0s)
Bytes  8–11:  Sensor record 2  (timestamp + 60s)
Bytes 12–15:  Sensor record 3  (timestamp + 120s)
Bytes 16–19:  Sensor record 4  (timestamp + 180s)
```

**Per-record encoding (4 bytes, Si7021 format):**
```
humidity_raw = byte0 + ((byte1 & 0x0F) << 8)
temp_raw     = (byte1 >> 4) + (byte2 << 4) + ((byte3 & 0x03) << 12)
humidity_pct = max(0, min(100, -6.0 + 125.0 * humidity_raw / 4096.0))
temp_celsius = -46.85 + 175.72 * temp_raw / 16384.0
```

**Battery voltage:**
```
voltage = (adc_raw & 0x7FFF) * 3.6 / 1024
```
Based on the nRF52 SAADC configuration (gain=1/6, Vref=0.6V). Percentage is calculated against CR2 lithium cell characteristics (3.1V full, 2.1V empty).

---

## Requirements

- Home Assistant 2024.1.0 or later
- A Bluetooth adapter accessible to HA (built-in or USB dongle)
- SensorPush HT1 sensor in Bluetooth range

---

## Installation

### Option 1: Manual

1. Download the [latest release](https://github.com/wxfield/ha-sensorpush-ht1/releases/latest) and unzip it
2. Copy the `custom_components/sensorpush_ht1/` folder into your Home Assistant configuration directory so the path reads `config/custom_components/sensorpush_ht1/`
3. Restart Home Assistant

Not sure where your configuration directory is? In Home Assistant go to **Settings → System → Storage** and look for the configuration path.

### Option 2: HACS

If you use [HACS](https://hacs.xyz), this integration can be added as a custom repository using the URL `https://github.com/wxfield/ha-sensorpush-ht1` with category **Integration**. See the [HACS custom repository documentation](https://hacs.xyz/docs/faq/custom_repositories/) for the steps specific to your HACS version.

---

## Setup

The integration uses Bluetooth discovery. No manual configuration needed.

1. Make sure your HT1 sensor has a battery and is in range
2. Go to **Settings → Devices & Services**
3. You should see a **SensorPush HT1 (xx:xx)** card in the Discovered section. Click **Add** and confirm.
4. The device will be added. Assign it to a room when prompted.

You may also see a second discovery card labeled **HT1 xxxx / SensorPush** -- that is Home Assistant's built-in SensorPush cloud integration detecting the same device. Click **Ignore** on that card. Only add the one labeled **SensorPush HT1**.

If discovery doesn't appear automatically, check that your Bluetooth adapter is working in HA and that no other device is currently connected to the sensor via GATT (for example, the SensorPush app actively syncing). Passive temperature and humidity advertisements are always available to any receiver simultaneously, but only one device can hold a GATT connection at a time. If the SensorPush app is connected when HA attempts its scheduled poll, that poll will be skipped and retried at the next interval -- no data is lost.

If you have been using the SensorPush app and want to preserve your cloud history before switching to this integration, export or archive it from the app first. The HT1 requires no pairing -- there is nothing to unpair from the app.

---

## Configuration

After setup, the integration has one configurable option. To access it, go to **Settings → Devices & Services → SensorPush HT1** and click **Configure**.

| Option | Default | Description |
|--------|---------|-------------|
| GATT poll interval | 30 minutes | How often to connect via Bluetooth to read battery level and download history. Minimum 5 minutes, maximum 1440 minutes (24 hours). |

Most users will not need to change this. The default of 30 minutes balances timely history updates against unnecessary Bluetooth connections.

---

## Entities

| Entity | Type | Default | Description |
|--------|------|---------|-------------|
| Temperature | Sensor | Enabled | Live reading from BLE advertisement |
| Humidity | Sensor | Enabled | Live reading from BLE advertisement |
| Battery | Sensor | Enabled | Battery percentage (0-100%) |
| Battery Voltage | Sensor | Disabled | Raw battery voltage in volts |
| Signal Strength | Sensor | Disabled | RSSI in dBm |

Battery Voltage and Signal Strength are disabled by default. To enable them, go to **Settings → Devices & Services → SensorPush HT1 → [device] → entities** and toggle them on.

---

## Long-Term Statistics

Temperature and humidity history is visible in a **Statistics Graph** card, not the standard entity History view. To add one:

1. Edit your dashboard → **Add Card** → **Statistics Graph**
2. Switch to YAML and use:

```yaml
type: statistics-graph
title: Kitchen Temperature
chart_type: line
period: hour
days_to_show: 14
entities:
  - entity: sensorpush_ht1:aabbccddeeff_temperature
    name: Kitchen
stat_types:
  - mean
```

Replace `aabbccddeeff` with your device's Bluetooth MAC address (`AA:BB:CC:DD:EE:FF`) with the colons removed and letters lowercased. The full statistic ID for your device is shown in **Developer Tools → Statistics**.

History is downloaded and injected every 30 minutes. On first setup, the full contents of the device's onboard flash (typically 1-2 weeks of per-minute readings) will be backfilled automatically.

---

## Limitations

- Requires Bluetooth LE on the Home Assistant host. Docker users need the D-Bus socket mounted: `-v /var/run/dbus:/var/run/dbus`
- The HT1's onboard flash holds approximately 1-2 weeks of history at the default 60-second measurement interval. Older records are overwritten as new ones are written.
- History is stored in hourly buckets in HA long-term statistics (HA's external statistics format requires hourly resolution). The value stored for each hour is the reading closest to the top of the hour, not an average.
- If your HA unit system is changed after history has been injected, existing statistics records will have the wrong unit label. Clear the affected statistic via **Developer Tools → Statistics** and the next poll will reinject in the correct unit.

---

## License

MIT License. See [LICENSE](LICENSE).

---

## Acknowledgements

Temperature and humidity formulas from the [Silicon Labs Si7021 datasheet](https://www.silabs.com/documents/public/data-sheets/Si7021-A20.pdf).
Battery voltage formula from the [Nordic Semiconductor nRF52 Product Specification](https://infocenter.nordicsemi.com/pdf/nRF52832_PS_v1.8.pdf).
Built with [bleak](https://github.com/hbldh/bleak) and [bleak-retry-connector](https://github.com/Bluetooth-Devices/bleak-retry-connector).
