"""Config flow for SensorPush HT1."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_GATT_POLL_INTERVAL,
    DOMAIN,
    GATT_POLL_INTERVAL_DEFAULT,
    GATT_POLL_INTERVAL_MAX,
    GATT_POLL_INTERVAL_MIN,
)
from .decoder import decode_advertisement

_LOGGER = logging.getLogger(__name__)


class SensorPushHT1OptionsFlow(OptionsFlow):
    """Options flow to configure the GATT poll interval."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_GATT_POLL_INTERVAL, GATT_POLL_INTERVAL_DEFAULT
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_GATT_POLL_INTERVAL, default=current_interval): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=GATT_POLL_INTERVAL_MIN,
                        max=GATT_POLL_INTERVAL_MAX,
                        step=1,
                        unit_of_measurement="minutes",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }),
        )


class SensorPushHT1ConfigFlow(ConfigFlow, domain=DOMAIN):
    """
    Config flow for SensorPush HT1.

    Entry points:
    - async_step_bluetooth: HA discovered a matching service UUID automatically.
      User just confirms — no typing required.
    - async_step_user: Manual setup fallback (user provides MAC address).
    """

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SensorPushHT1OptionsFlow:
        return SensorPushHT1OptionsFlow(config_entry)

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._address: str | None = None
        self._name: str | None = None

    # ------------------------------------------------------------------
    # Automatic Bluetooth discovery (primary path)
    # ------------------------------------------------------------------

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a device discovered via Bluetooth."""
        _LOGGER.debug("Bluetooth discovery: %s  rssi=%d", discovery_info.address, discovery_info.rssi)

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        # Verify it actually has HT1 advertisement data before accepting
        adv = decode_advertisement(discovery_info.manufacturer_data)
        if adv is None:
            return self.async_abort(reason="not_ht1")

        self._discovery_info = discovery_info
        self._address = discovery_info.address
        self._name = f"SensorPush HT1 ({discovery_info.address[-5:]})"
        self.context["title_placeholders"] = {"name": self._name}

        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovered device with the user."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._name,
                data={CONF_ADDRESS: self._address},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name":    self._name,
                "address": self._address,
            },
        )

    # ------------------------------------------------------------------
    # Manual setup fallback
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual setup — not normally needed."""
        # In practice, Bluetooth discovery handles everything.
        # This step exists so the integration appears in the UI add-integration list.
        return self.async_abort(reason="use_bluetooth_discovery")
