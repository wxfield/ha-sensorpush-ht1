"""
SensorPush HT1 coordinators.

Two coordinators, both backed by DataUpdateCoordinator so entities share
a single well-understood HA pattern:

1. HT1PassiveCoordinator
   Registers a Bluetooth callback for passive advertisement data.
   Fires on every HT1 broadcast (~1 Hz) without connecting to the device.
   Updates temperature and humidity.

2. HT1GattCoordinator
   Connects via GATT on a 30-minute schedule (battery changes slowly).
   Reads battery voltage, TX power, and device ID.
   Also downloads onboard history and injects it into HA long-term statistics.
   Passive updates are unaffected while this runs.
"""
from __future__ import annotations

import asyncio
import logging
import struct
from datetime import datetime, timedelta, timezone

from bleak import BleakClient
from bleak_retry_connector import establish_connection

from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_register_callback,
)
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.util.unit_conversion import TemperatureConverter
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CHAR_BATTERY_VOLTAGE,
    CHAR_DEVICE_ID,
    CHAR_HISTORY_CMD,
    CHAR_HISTORY_DATA,
    CHAR_LAST_SEEN,
    CHAR_TX_POWER,
    CONF_GATT_POLL_INTERVAL,
    DOMAIN,
    GATT_POLL_INTERVAL_DEFAULT,
)
from .decoder import decode_advertisement, decode_gatt, decode_history_packet
from .models import HT1GattData, HT1HistoryRecord, HT1SensorData

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Passive coordinator — advertisement data (temperature / humidity)
# ---------------------------------------------------------------------------

class HT1PassiveCoordinator(DataUpdateCoordinator[HT1SensorData]):
    """
    Coordinator driven by passive Bluetooth advertisement callbacks.

    No polling interval — data arrives whenever the HT1 broadcasts.
    The coordinator holds the latest decoded advertisement and notifies
    all subscribed entities on each update.
    """

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_passive_{address}",
            # No update_interval — we push data via callback, not polling
        )
        self.address = address
        # Pre-populate with an empty container so entities never see None
        self.async_set_updated_data(HT1SensorData())

    @callback
    def _handle_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Called by HA on every matching advertisement."""
        adv = decode_advertisement(service_info.manufacturer_data)
        if adv is None:
            return
        adv.rssi = service_info.rssi
        sensor_data = HT1SensorData(advertisement=adv, gatt=self.data.gatt)
        self.async_set_updated_data(sensor_data)

    def async_start(self) -> None:
        """Register the Bluetooth callback. Call after entities are set up."""
        cancel = async_register_callback(
            self.hass,
            self._handle_bluetooth_event,
            BluetoothCallbackMatcher(address=self.address),
            BluetoothScanningMode.PASSIVE,
        )
        # Return the cancel callable so the config entry can unload it
        return cancel

    async def _async_update_data(self) -> HT1SensorData:
        # Not used for polling — data arrives via _handle_bluetooth_event.
        # Required by DataUpdateCoordinator; just return current data.
        return self.data


# ---------------------------------------------------------------------------
# GATT coordinator — battery, TX power, device ID
# ---------------------------------------------------------------------------

class HT1GattCoordinator(DataUpdateCoordinator[HT1GattData]):
    """
    Periodic GATT coordinator for battery voltage and device info.

    Polls every GATT_POLL_INTERVAL seconds (default 30 min).
    If the device is not connectable (out of range), logs a warning and
    returns the last known data rather than failing.
    """

    def __init__(self, hass: HomeAssistant, address: str, entry: ConfigEntry) -> None:
        poll_minutes = entry.options.get(CONF_GATT_POLL_INTERVAL, GATT_POLL_INTERVAL_DEFAULT)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_gatt_{address}",
            update_interval=timedelta(minutes=poll_minutes),
        )
        self.address = address
        self._entry = entry

    async def _async_update_data(self) -> HT1GattData:
        """Connect via GATT and read battery / device info, then sync history."""
        from homeassistant.components.bluetooth import async_ble_device_from_address

        ble_device = async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is None:
            if self.data is not None:
                _LOGGER.debug(
                    "HT1 %s not connectable right now; keeping last GATT data",
                    self.address,
                )
                return self.data
            raise UpdateFailed(
                f"HT1 {self.address} not connectable and no prior data available"
            )

        client: BleakClient | None = None
        try:
            client = await establish_connection(
                BleakClient,
                ble_device,
                self.address,
                max_attempts=3,
            )
            await asyncio.sleep(0.5)  # let the connection settle

            id_bytes      = await client.read_gatt_char(CHAR_DEVICE_ID)
            tx_bytes      = await client.read_gatt_char(CHAR_TX_POWER)
            voltage_bytes = await client.read_gatt_char(CHAR_BATTERY_VOLTAGE)
            last_seen_bytes = await client.read_gatt_char(CHAR_LAST_SEEN)

            gatt_data = decode_gatt(id_bytes, tx_bytes, voltage_bytes)

            # Download and inject history — non-fatal if BT stack can't do notifications
            try:
                await self._sync_history(client, last_seen_bytes)
            except Exception as history_err:
                _LOGGER.warning(
                    "HT1 %s history sync failed (battery data still valid): %s",
                    self.address, history_err,
                )

            return gatt_data

        except Exception as err:
            if self.data is not None:
                _LOGGER.warning(
                    "GATT read failed for %s (%s); keeping last data", self.address, err
                )
                return self.data
            raise UpdateFailed(f"GATT read failed: {err}") from err

        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def _sync_history(self, client: BleakClient, last_seen_bytes: bytes) -> None:
        """Download onboard history and inject new records into HA statistics."""
        # Determine the timestamp of the most recent record on the device
        device_last_ts = struct.unpack_from("<I", last_seen_bytes, 0)[0] if len(last_seen_bytes) >= 4 else 0

        # Find the newest timestamp we already have in HA statistics
        statistic_id_temp = f"{DOMAIN}:{self.address.replace(':', '').lower()}_temperature"
        last_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id_temp, True, {"mean"}
        )
        since_ts = 0
        if last_stats and statistic_id_temp in last_stats:
            # Use "start" of the last bucket (not "end") so the current partial
            # hour is always re-processed and new records within it are captured.
            since_dt = last_stats[statistic_id_temp][0].get("start")
            if since_dt:
                since_ts = int(since_dt.timestamp()) if hasattr(since_dt, "timestamp") else int(since_dt)

        if since_ts >= device_last_ts:
            _LOGGER.debug("HT1 %s history up to date (since_ts=%s)", self.address, since_ts)
            return

        # Collect history packets via notifications
        all_records: list[HT1HistoryRecord] = []
        done_event = asyncio.Event()
        notify_count = 0

        def on_notify(_char, data: bytearray) -> None:
            nonlocal notify_count
            notify_count += 1
            records = decode_history_packet(bytes(data))
            if records:
                all_records.extend(records)
            # Sentinel in last slot or empty parse = download complete
            if not records or bytes(data[16:20]) == b"\xff\xff\xff\xff":
                done_event.set()

        await client.start_notify(CHAR_HISTORY_DATA, on_notify)
        await client.write_gatt_char(CHAR_HISTORY_CMD, struct.pack("<I", 1), response=True)
        _LOGGER.debug("HT1 %s history download started", self.address)

        try:
            await asyncio.wait_for(done_event.wait(), timeout=120.0)
        except asyncio.TimeoutError:
            _LOGGER.warning("HT1 %s history download timed out", self.address)

        _LOGGER.debug("HT1 %s history download complete (%d packets)", self.address, notify_count)
        try:
            await client.stop_notify(CHAR_HISTORY_DATA)
        except Exception:
            pass

        # Filter to only new records, deduplicate, sort oldest→newest
        seen: set[int] = set()
        new_records = []
        for r in sorted(all_records, key=lambda x: x.timestamp):
            if r.timestamp > since_ts and r.timestamp not in seen:
                seen.add(r.timestamp)
                new_records.append(r)

        if not new_records:
            _LOGGER.debug("HT1 %s no new history records", self.address)
            return

        _LOGGER.info(
            "HT1 %s injecting %d history records (%s → %s)",
            self.address,
            len(new_records),
            datetime.fromtimestamp(new_records[0].timestamp, tz=timezone.utc).isoformat(),
            datetime.fromtimestamp(new_records[-1].timestamp, tz=timezone.utc).isoformat(),
        )

        addr_slug = self.address.replace(":", "").lower()
        short_id = self.address.replace(":", "")[-4:].upper()
        temp_unit = self.hass.config.units.temperature_unit
        temp_values = [
            (r.timestamp, r.temp_f if temp_unit == UnitOfTemperature.FAHRENHEIT else r.temp_c)
            for r in new_records
        ]
        self._inject_statistics(
            statistic_id=f"{DOMAIN}:{addr_slug}_temperature",
            name=f"HT1 {short_id} Temperature",
            unit=temp_unit,
            unit_class=TemperatureConverter.UNIT_CLASS,
            values=temp_values,
        )
        self._inject_statistics(
            statistic_id=f"{DOMAIN}:{addr_slug}_humidity",
            name=f"HT1 {short_id} Humidity",
            unit=PERCENTAGE,
            unit_class=None,
            values=[(r.timestamp, r.humidity) for r in new_records],
        )

    def _inject_statistics(
        self,
        statistic_id: str,
        name: str,
        unit: str,
        unit_class: str | None,
        values: list[tuple[int, float]],
    ) -> None:
        """Push hourly-bucketed statistics into HA long-term statistics.

        HA external statistics require timestamps at the top of the hour.
        We use the reading closest to the top of each hour rather than
        averaging, to preserve the actual sensor value at that moment.
        """
        # Bucket by hour, storing (timestamp, value) pairs
        hourly: dict[datetime, list[tuple[int, float]]] = {}
        for ts, value in values:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            hour_start = dt.replace(minute=0, second=0, microsecond=0)
            hourly.setdefault(hour_start, []).append((ts, value))

        metadata = StatisticMetaData(
            has_mean=True,
            has_sum=False,
            mean_type=StatisticMeanType.ARITHMETIC,
            name=name,
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=unit,
            unit_class=unit_class,
        )
        stats = [
            StatisticData(
                start=hour_start,
                mean=round(
                    min(bucket, key=lambda x: abs(x[0] - int(hour_start.timestamp())))[1],
                    2,
                ),
            )
            for hour_start, bucket in sorted(hourly.items())
        ]
        async_add_external_statistics(self.hass, metadata, stats)
