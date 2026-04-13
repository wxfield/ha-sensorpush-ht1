"""Data models for the SensorPush HT1 integration."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HT1AdvertisementData:
    """Decoded data from a passive BLE advertisement."""
    temp_c:   float
    temp_f:   float
    humidity: float
    rssi:     int | None = None
    raw_hex:  str = ""


@dataclass
class HT1GattData:
    """Data read via GATT connection (battery, device info)."""
    device_id:    int | None = None
    tx_power_dbm: int | None = None
    battery_v:    float | None = None
    battery_pct:  int | None = None
    raw_adc:      int | None = None


@dataclass
class HT1HistoryRecord:
    """A single timestamped record from the HT1 onboard history log."""
    timestamp: int    # Unix timestamp (UTC)
    temp_c:    float
    temp_f:    float
    humidity:  float


@dataclass
class HT1SensorData:
    """Combined advertisement + GATT data for a single HT1 device."""
    advertisement: HT1AdvertisementData | None = None
    gatt:          HT1GattData = field(default_factory=HT1GattData)
