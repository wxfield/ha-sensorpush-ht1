"""SensorPush HT1 integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import HT1GattCoordinator, HT1PassiveCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SensorPush HT1 from a config entry."""
    address = entry.data[CONF_ADDRESS]

    passive_coordinator = HT1PassiveCoordinator(hass, address)
    gatt_coordinator    = HT1GattCoordinator(hass, address, entry)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "passive": passive_coordinator,
        "gatt":    gatt_coordinator,
    }

    # Set up sensor platform first so entities exist before callbacks fire
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start passive Bluetooth callback — fires on every advertisement
    entry.async_on_unload(passive_coordinator.async_start())

    # Kick off first GATT poll in the background — don't block setup if
    # the device isn't connectable right now (it may be out of range).
    entry.async_create_background_task(
        hass,
        gatt_coordinator.async_refresh(),
        name=f"{DOMAIN}_initial_gatt_{address}",
    )

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
