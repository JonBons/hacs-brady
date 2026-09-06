"""Config flow for Brady M211."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .client import BradyM211Client
from .const import (
    CONF_KEEP_CONNECTED,
    CONF_OWNERSHIP_ID,
    CONF_RELEASE_ON_DISCONNECT,
    DEFAULT_KEEP_CONNECTED,
    DEFAULT_RELEASE_ON_DISCONNECT,
    DOMAIN,
    LOCAL_NAME_PREFIX,
)
from .logutil import describe_ble_device, describe_service_info, log_verbose
from .protocol import BradyOwnershipError, is_m211_name

_LOGGER = logging.getLogger(__name__)


def _label(info: BluetoothServiceInfoBleak) -> str:
    name = info.name or LOCAL_NAME_PREFIX
    return f"{name} ({info.address})"


class BradyM211ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Discover M211 printers advertised over HA Bluetooth (including proxies)."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> BradyM211OptionsFlow:
        return BradyM211OptionsFlow()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        if not is_m211_name(discovery_info.name):
            _LOGGER.debug(
                "Ignoring Bluetooth discovery (not an M211): %s",
                describe_service_info(discovery_info),
            )
            return self.async_abort(reason="not_supported")
        log_verbose(
            _LOGGER,
            "Bluetooth discovery: %s device=%s",
            describe_service_info(discovery_info),
            describe_ble_device(discovery_info.device),
        )
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": _label(discovery_info)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery_info is not None
        if user_input is not None:
            return await self._async_create_from_discovery(self._discovery_info)
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": _label(self._discovery_info)},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            info = self._discovered[address]
            await self.async_set_unique_id(info.address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            try:
                return await self._async_create_from_discovery(info)
            except BradyOwnershipError:
                _LOGGER.warning(
                    "Config flow could not claim %s",
                    describe_service_info(info),
                )
                errors["base"] = "owned"
            except Exception:
                _LOGGER.exception("Unexpected error connecting to M211")
                errors["base"] = "cannot_connect"

        current = self._async_current_ids(include_ignore=False)
        if self._discovery_info:
            self._discovered[self._discovery_info.address] = self._discovery_info
        for discovery in async_discovered_service_info(self.hass, connectable=True):
            if discovery.address in current or discovery.address in self._discovered:
                continue
            if not is_m211_name(discovery.name):
                continue
            self._discovered[discovery.address] = discovery

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): vol.In(
                    {
                        info.address: _label(info)
                        for info in self._discovered.values()
                    }
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def _async_create_from_discovery(
        self, info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        client = BradyM211Client()
        log_verbose(
            _LOGGER,
            "Config flow connecting to confirm printer: %s device=%s",
            describe_service_info(info),
            describe_ble_device(info.device),
        )
        try:
            ownership_id = await client.connect(info.device, name=info.name or "M211")
            status = await client.refresh_status()
            log_verbose(
                _LOGGER,
                "Config flow connected ownership_id=%s battery=%r firmware=%r "
                "printable=%sx%s",
                ownership_id,
                status.battery,
                status.firmware,
                status.printable_width,
                status.printable_height,
            )
        finally:
            await client.disconnect(release=True)
        return self.async_create_entry(
            title=info.name or LOCAL_NAME_PREFIX,
            data={
                CONF_ADDRESS: info.address,
                CONF_OWNERSHIP_ID: ownership_id,
            },
        )


class BradyM211OptionsFlow(OptionsFlow):
    """Connection behaviour: proxy-friendly connect-on-demand vs persistent."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_KEEP_CONNECTED,
                        default=self.config_entry.options.get(
                            CONF_KEEP_CONNECTED, DEFAULT_KEEP_CONNECTED
                        ),
                    ): bool,
                    vol.Required(
                        CONF_RELEASE_ON_DISCONNECT,
                        default=self.config_entry.options.get(
                            CONF_RELEASE_ON_DISCONNECT, DEFAULT_RELEASE_ON_DISCONNECT
                        ),
                    ): bool,
                }
            ),
        )
