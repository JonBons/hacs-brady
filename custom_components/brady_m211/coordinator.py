"""DataUpdateCoordinator for Brady M211."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from bleak.backends.device import BLEDevice

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothChange, BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.match import ADDRESS, BluetoothCallbackMatcher
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import BradyM211Client
from .const import (
    CONF_KEEP_CONNECTED,
    CONF_OWNERSHIP_ID,
    CONF_RELEASE_ON_DISCONNECT,
    DEFAULT_KEEP_CONNECTED,
    DEFAULT_RELEASE_ON_DISCONNECT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    KEEP_CONNECTED_SCAN_INTERVAL,
    MANUFACTURER,
    MODEL,
)
from .models import PrinterStatus
from .protocol import BradyOwnershipError, BradyProtocolError
from .render import render_image_bytes, render_text
from .vgl import encode_vgl6_job

_LOGGER = logging.getLogger(__name__)

type BradyM211ConfigEntry = ConfigEntry[BradyM211Coordinator]


class BradyM211Coordinator(DataUpdateCoordinator[PrinterStatus]):
    """Polls the M211 through HA Bluetooth (adapter or ESPHome proxy)."""

    config_entry: BradyM211ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: BradyM211ConfigEntry) -> None:
        self.address = entry.data[CONF_ADDRESS].upper()
        self.keep_connected = entry.options.get(
            CONF_KEEP_CONNECTED, DEFAULT_KEEP_CONNECTED
        )
        self.release_on_disconnect = entry.options.get(
            CONF_RELEASE_ON_DISCONNECT, DEFAULT_RELEASE_ON_DISCONNECT
        )
        if self.keep_connected:
            self.release_on_disconnect = False
        interval = (
            KEEP_CONNECTED_SCAN_INTERVAL
            if self.keep_connected
            else DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title or MODEL,
            update_interval=interval,
        )
        self.client = BradyM211Client()
        self.client.ownership_id = entry.data.get(CONF_OWNERSHIP_ID)
        self._ble_device: BLEDevice | None = None
        self._unsub_bt: Callable[[], None] | None = None

    @property
    def device_info(self) -> DeviceInfo:
        status = self.data
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self.address)},
            identifiers={(DOMAIN, self.address)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=self.config_entry.title or MODEL,
            sw_version=status.firmware if status else None,
        )

    async def async_setup(self) -> None:
        """Resolve the BLE device and subscribe to advertisement updates."""
        self._ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, True
        )
        if self._ble_device is None:
            raise ConfigEntryNotReady(
                f"Could not find {MODEL} {self.address}. Make sure an ESPHome "
                "Bluetooth proxy has active: true, or a Bluetooth adapter can "
                "reach the printer."
            )

        @callback
        def _async_update_ble(
            service_info: BluetoothServiceInfoBleak, _change: BluetoothChange
        ) -> None:
            self._ble_device = service_info.device

        self._unsub_bt = bluetooth.async_register_callback(
            self.hass,
            _async_update_ble,
            BluetoothCallbackMatcher({ADDRESS: self.address}),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
        self.config_entry.async_on_unload(self._unsub_bt)

    async def async_shutdown_client(self) -> None:
        await self.client.disconnect(release=self.release_on_disconnect)

    async def _async_update_data(self) -> PrinterStatus:
        try:
            await self._ensure_connected()
            status = await self.client.refresh_status()
        except BradyOwnershipError as err:
            raise UpdateFailed(str(err)) from err
        except (BradyProtocolError, OSError, TimeoutError) as err:
            raise UpdateFailed(f"M211 communication failed: {err}") from err
        finally:
            if not self.keep_connected:
                await self.client.disconnect(release=self.release_on_disconnect)
        return status

    async def async_feed(self) -> None:
        await self._run_command(self.client.feed)

    async def async_cut(self) -> None:
        await self._run_command(self.client.cut)

    async def async_print_text(
        self, message: str, copies: int = 1, length_in: float | None = None
    ) -> None:
        async def _print() -> None:
            status = await self.client.refresh_status()
            rows = render_text(
                message,
                printable_width=status.printable_width,
                printable_height=status.printable_height,
                length_in=length_in,
            )
            await self._send_rows(rows, status, copies, job_name="HA")

        await self._run_command(_print)

    async def async_print_image(
        self, image: bytes, copies: int = 1, length_in: float | None = None
    ) -> None:
        async def _print() -> None:
            status = await self.client.refresh_status()
            rows = render_image_bytes(
                image,
                printable_width=status.printable_width,
                printable_height=status.printable_height,
                length_in=length_in,
            )
            await self._send_rows(rows, status, copies, job_name="HA")

        await self._run_command(_print)

    async def _send_rows(
        self,
        rows: list[list[int]],
        status: PrinterStatus,
        copies: int,
        job_name: str,
    ) -> None:
        height = len(rows)
        width = len(rows[0]) if rows else 0
        page_w = status.printable_width or width
        page_h = status.printable_height or height
        if page_h <= 0:
            page_h = height
        payload = encode_vgl6_job(
            rows,
            page_width=page_w,
            page_height=page_h,
            printable_width=status.printable_width or width,
            printable_height=page_h,
            offset_x=status.left_offset or 0,
            offset_y=status.vertical_offset or 0,
            copies=copies,
            job_name=job_name,
        )
        await self.client.print_job(payload, job_name=job_name)

    async def _run_command(self, func: Callable[[], Coroutine[Any, Any, None]]) -> None:
        try:
            await self._ensure_connected()
            await func()
            self.async_set_updated_data(self.client.status)
        except BradyOwnershipError as err:
            raise HomeAssistantError(str(err)) from err
        except BradyProtocolError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            if not self.keep_connected:
                await self.client.disconnect(release=self.release_on_disconnect)

    async def _ensure_connected(self) -> None:
        ble_device = self._ble_device or bluetooth.async_ble_device_from_address(
            self.hass, self.address, True
        )
        if ble_device is None:
            raise HomeAssistantError(
                f"{MODEL} {self.address} is not currently reachable via any "
                "Bluetooth adapter or ESPHome Bluetooth proxy"
            )
        self._ble_device = ble_device
        ownership = await self.client.connect(
            ble_device,
            ownership_id=self.config_entry.data.get(CONF_OWNERSHIP_ID),
            name=self.config_entry.title or MODEL,
        )
        if ownership and ownership != self.config_entry.data.get(CONF_OWNERSHIP_ID):
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_OWNERSHIP_ID: ownership},
            )
