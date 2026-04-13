"""SensorPush HT1 sensor entities."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_ADDRESS,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HT1GattCoordinator, HT1PassiveCoordinator
from .models import HT1GattData, HT1SensorData

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entity description types
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class HT1PassiveSensorDescription(SensorEntityDescription):
    """Describes a passive (advertisement-driven) HT1 sensor."""
    value_fn: Callable[[HT1SensorData], float | int | None] = lambda _: None


@dataclass(frozen=True, kw_only=True)
class HT1GattSensorDescription(SensorEntityDescription):
    """Describes a GATT-polled HT1 sensor."""
    value_fn: Callable[[HT1GattData], float | int | None] = lambda _: None


# ---------------------------------------------------------------------------
# Sensor descriptions
# ---------------------------------------------------------------------------

PASSIVE_SENSORS: tuple[HT1PassiveSensorDescription, ...] = (
    HT1PassiveSensorDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda d: d.advertisement.temp_c if d.advertisement else None,
    ),
    HT1PassiveSensorDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value_fn=lambda d: d.advertisement.humidity if d.advertisement else None,
    ),
    HT1PassiveSensorDescription(
        key="rssi",
        translation_key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.advertisement.rssi if d.advertisement else None,
    ),
)

GATT_SENSORS: tuple[HT1GattSensorDescription, ...] = (
    HT1GattSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda d: d.battery_pct,
    ),
    HT1GattSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="V",
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.battery_v,
    ),
)


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------

class HT1PassiveSensor(CoordinatorEntity[HT1PassiveCoordinator], SensorEntity):
    """Sensor updated on every passive BLE advertisement."""

    _attr_has_entity_name = True
    entity_description: HT1PassiveSensorDescription

    def __init__(
        self,
        coordinator: HT1PassiveCoordinator,
        description: HT1PassiveSensorDescription,
        device_info: DeviceInfo,
        unique_id_base: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_device_info  = device_info
        self._attr_unique_id    = f"{unique_id_base}_{description.key}"

    @property
    def native_value(self) -> float | int | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        # Stay available as long as we've received at least one advertisement.
        # Don't go unavailable during brief gaps (e.g. GATT connection windows).
        return self.coordinator.data.advertisement is not None


class HT1GattSensor(CoordinatorEntity[HT1GattCoordinator], SensorEntity):
    """Sensor updated every 30 minutes via GATT connection."""

    _attr_has_entity_name = True
    entity_description: HT1GattSensorDescription

    def __init__(
        self,
        coordinator: HT1GattCoordinator,
        description: HT1GattSensorDescription,
        device_info: DeviceInfo,
        unique_id_base: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_device_info  = device_info
        self._attr_unique_id    = f"{unique_id_base}_{description.key}"

    @property
    def native_value(self) -> float | int | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up all HT1 sensor entities for a config entry."""
    coordinators    = hass.data[DOMAIN][entry.entry_id]
    passive_coord: HT1PassiveCoordinator = coordinators["passive"]
    gatt_coord:    HT1GattCoordinator    = coordinators["gatt"]

    unique_id_base = entry.unique_id or entry.data[CONF_ADDRESS].replace(":", "").lower()

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id)},
        name=entry.title,
        manufacturer="SensorPush",
        model="HT1",
    )

    async_add_entities([
        HT1PassiveSensor(passive_coord, desc, device_info, unique_id_base)
        for desc in PASSIVE_SENSORS
    ])

    async_add_entities([
        HT1GattSensor(gatt_coord, desc, device_info, unique_id_base)
        for desc in GATT_SENSORS
    ])
