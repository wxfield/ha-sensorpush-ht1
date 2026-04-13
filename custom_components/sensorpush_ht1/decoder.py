"""
SensorPush HT1 BLE advertisement and GATT decoder.

Protocol determined via:
- Passive BLE advertisement capture and analysis
- Behavioral testing of all GATT characteristics
- Si7021 datasheet formula validation
- Nordic nRF52 SAADC datasheet (battery voltage formula)

Validated against SensorPush iOS/Android app readings (delta < 0.5°F).
"""
from __future__ import annotations

import logging
import struct

from .const import (
    BATTERY_ADC_FULL_SCALE,
    BATTERY_ADC_MAX,
    BATTERY_VOLTAGE_EMPTY,
    BATTERY_VOLTAGE_FULL,
    HT1_DEVICE_TYPE,
)
from .models import HT1AdvertisementData, HT1GattData, HT1HistoryRecord

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Si7021 decode formulas (from Silicon Labs datasheet, not SensorPush IP)
# ---------------------------------------------------------------------------

def _humidity_from_raw(raw: int) -> float:
    """Convert 12-bit raw ADC to relative humidity % (Si7021 formula)."""
    v = -6.0 + (125.0 * (raw / 4096.0))
    return round(max(0.0, min(100.0, v)), 2)


def _temperature_c_from_raw(raw: int) -> float:
    """Convert 14-bit raw ADC to temperature in Celsius (Si7021 formula)."""
    return round(-46.85 + (175.72 * (raw / 16384.0)), 2)


# ---------------------------------------------------------------------------
# Advertisement decoder
# ---------------------------------------------------------------------------

def decode_advertisement(manufacturer_data: dict[int, bytes]) -> HT1AdvertisementData | None:
    """
    Decode HT1 manufacturer-specific advertisement data.

    The manufacturer_data dict maps company ID (int) → payload (bytes).
    We prepend the 2-byte company ID (little-endian) to reconstruct the
    full 4-byte packed sensor value.

    Byte layout:
        [0]   humidity bits [7:0]
        [1]   temp bits [3:0]  |  humidity bits [11:8]
        [2]   temp bits [11:4]
        [3]   0 | device_type[4:0] | temp bits [13:12] | 0

    device_type == 1 identifies the HT1 (vs other SensorPush models).
    """
    # HA accumulates manufacturer_data across packets. Because the HT1 encodes
    # temperature/humidity in the company ID field itself, the company ID changes
    # with every new reading. HA keeps all seen company IDs in the dict, ordered
    # by insertion (newest last). We must take the LAST valid entry, not the first.
    last: HT1AdvertisementData | None = None

    for cid, payload in manufacturer_data.items():
        mfg = cid.to_bytes(2, "little") + payload
        if len(mfg) < 4:
            continue

        device_type = (mfg[3] & 0x7C) >> 2
        if device_type != HT1_DEVICE_TYPE:
            continue

        hum_raw  = (mfg[0] & 0xFF) | ((mfg[1] & 0x0F) << 8)
        temp_raw = ((mfg[1] & 0xFF) >> 4) | ((mfg[2] & 0xFF) << 4) | ((mfg[3] & 0x03) << 12)

        temp_c = _temperature_c_from_raw(temp_raw)
        temp_f = round(temp_c * 9 / 5 + 32, 2)
        humidity = _humidity_from_raw(hum_raw)

        last = HT1AdvertisementData(
            temp_c=temp_c,
            temp_f=temp_f,
            humidity=humidity,
            raw_hex=mfg.hex(),
        )

    if last is not None:
        _LOGGER.debug(
            "HT1 advertisement decoded: temp=%.2f°C / %.2f°F  hum=%.2f%%  raw=%s",
            last.temp_c, last.temp_f, last.humidity, last.raw_hex,
        )

    return last


# ---------------------------------------------------------------------------
# GATT decoder
# ---------------------------------------------------------------------------

def _battery_pct(voltage: float) -> int:
    """Estimate battery % from voltage (linear approximation)."""
    pct = (voltage - BATTERY_VOLTAGE_EMPTY) / (BATTERY_VOLTAGE_FULL - BATTERY_VOLTAGE_EMPTY) * 100
    return max(0, min(100, round(pct)))


def decode_gatt(
    id_bytes: bytes,
    tx_bytes: bytes,
    voltage_bytes: bytes,
) -> HT1GattData:
    """
    Decode raw GATT characteristic bytes into structured data.

    ef090001 (id_bytes):      3 bytes, uint24 little-endian device ID
    ef090003 (tx_bytes):      1 byte,  int8 signed TX power in dBm
    ef090007 (voltage_bytes): 4 bytes, uint16 LE ADC_raw + uint16 LE die_temp_raw

    Battery formula: nRF52 SAADC, gain=1/6, Vref=0.6V, 10-bit
    voltage = (raw & 0x7FFF) * 3.6 / 1024
    Confirmed via behavioral testing against known voltage references.
    """
    device_id = int.from_bytes(id_bytes[0:3], "little") if len(id_bytes) >= 3 else None

    tx_power_dbm = None
    if tx_bytes:
        raw = tx_bytes[0]
        tx_power_dbm = raw if raw < 128 else raw - 256  # int8 sign extend

    battery_v = None
    battery_pct = None
    raw_adc = None
    if len(voltage_bytes) >= 2:
        raw_adc   = int.from_bytes(voltage_bytes[0:2], "little") & 0x7FFF
        battery_v = round(raw_adc * BATTERY_ADC_FULL_SCALE / BATTERY_ADC_MAX, 2)
        battery_pct = _battery_pct(battery_v)

    _LOGGER.debug(
        "HT1 GATT decoded: device_id=%s  tx=%s dBm  battery=%.2fV (%d%%)",
        device_id, tx_power_dbm, battery_v or 0, battery_pct or 0,
    )

    return HT1GattData(
        device_id=device_id,
        tx_power_dbm=tx_power_dbm,
        battery_v=battery_v,
        battery_pct=battery_pct,
        raw_adc=raw_adc,
    )


# ---------------------------------------------------------------------------
# History decoder
# ---------------------------------------------------------------------------

_SENTINEL = b"\xff\xff\xff\xff"
_HISTORY_MEAS_INTERVAL = 60  # seconds between records (device default)


def _decode_history_record(data: bytes) -> tuple[float, float] | None:
    """
    Decode a 4-byte Si7021-packed history record.
    Returns (temp_c, humidity) or None if sentinel.
    Same packing as advertisement payload.
    """
    if len(data) < 4 or data == _SENTINEL:
        return None
    b0, b1, b2, b3 = data[0], data[1], data[2], data[3]
    hum_raw  = b0 + ((b1 & 0x0F) << 8)
    temp_raw = (b1 >> 4) + (b2 << 4) + ((b3 & 0x03) << 12)
    temp_c   = _temperature_c_from_raw(temp_raw)
    humidity = _humidity_from_raw(hum_raw)
    return (temp_c, humidity)


def decode_history_packet(data: bytes) -> list[HT1HistoryRecord]:
    """
    Decode a 20-byte GATT history notification into up to 4 records.

    Format (determined via protocol analysis 2026-03-12):
      Bytes  0- 3: uint32 LE Unix timestamp of the oldest record in this batch
      Bytes  4- 7: record 1 (Si7021 packed)
      Bytes  8-11: record 2
      Bytes 12-15: record 3
      Bytes 16-19: record 4

    Notifications arrive newest-first; records within each packet go
    forward in time (+60 s each from base_ts).
    0xFFFFFFFF in a record slot = end-of-history sentinel.
    """
    if len(data) < 20:
        return []

    base_ts = struct.unpack_from("<I", data, 0)[0]
    records: list[HT1HistoryRecord] = []

    for i in range(4):
        chunk = data[4 + i * 4 : 8 + i * 4]
        decoded = _decode_history_record(bytes(chunk))
        if decoded is None:
            break
        temp_c, humidity = decoded
        records.append(HT1HistoryRecord(
            timestamp=base_ts + i * _HISTORY_MEAS_INTERVAL,
            temp_c=temp_c,
            temp_f=round(temp_c * 9 / 5 + 32, 2),
            humidity=humidity,
        ))

    return records
