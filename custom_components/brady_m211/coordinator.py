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
    VERBOSE_LOGGING,
)
from .logutil import describe_ble_device, describe_service_info, log_verbose
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
        log_verbose(
            _LOGGER,
            "Coordinator init address=%s keep_connected=%s release_on_disconnect=%s "
            "interval=%s verbose_logging=%s ownership_id=%s",
            self.address,
            self.keep_connected,
            self.release_on_disconnect,
            interval,
            VERBOSE_LOGGING,
            entry.data.get(CONF_OWNERSHIP_ID),
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
            _LOGGER.error(
                "Could not resolve BLEDevice for %s (connectable=True). No adapter "
                "or ESPHome proxy currently sees the printer.",
                self.address,
            )
            raise ConfigEntryNotReady(
                f"Could not find {MODEL} {self.address}. Make sure an ESPHome "
                "Bluetooth proxy has active: true, or a Bluetooth adapter can "
                "reach the printer."
            )
        log_verbose(
            _LOGGER,
            "Resolved BLEDevice at setup: %s",
            describe_ble_device(self._ble_device),
        )

        @callback
        def _async_update_ble(
            service_info: BluetoothServiceInfoBleak, change: BluetoothChange
        ) -> None:
            _LOGGER.debug(
                "Advertisement update change=%s %s device=%s",
                change,
                describe_service_info(service_info),
                describe_ble_device(service_info.device),
            )
            self._ble_device = service_info.device

        self._unsub_bt = bluetooth.async_register_callback(
            self.hass,
            _async_update_ble,
            BluetoothCallbackMatcher({ADDRESS: self.address}),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
        self.config_entry.async_on_unload(self._unsub_bt)

    async def async_shutdown_client(self) -> None:
        log_verbose(_LOGGER, "Shutting down M211 client release=%s", self.release_on_disconnect)
        await self.client.disconnect(release=self.release_on_disconnect)

    async def _async_update_data(self) -> PrinterStatus:
        log_verbose(
            _LOGGER,
            "Status poll starting keep_connected=%s connected=%s",
            self.keep_connected,
            self.client.is_connected,
        )
        try:
            await self._ensure_connected()
            status = await self.client.refresh_status()
        except BradyOwnershipError as err:
            _LOGGER.error("Status poll ownership failure: %s", err)
            raise UpdateFailed(str(err)) from err
        except (BradyProtocolError, OSError, TimeoutError) as err:
            _LOGGER.exception("Status poll failed: %s", err)
            raise UpdateFailed(f"M211 communication failed: {err}") from err
        finally:
            if not self.keep_connected:
                log_verbose(
                    _LOGGER,
                    "Status poll finished; disconnecting (connect-on-demand) release=%s",
                    self.release_on_disconnect,
                )
                await self.client.disconnect(release=self.release_on_disconnect)
        log_verbose(
            _LOGGER,
            "Status poll ok battery=%r firmware=%r printable=%sx%s media=%s",
            status.battery,
            status.firmware,
            status.printable_width,
            status.printable_height,
            status.media_remaining,
        )
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
            log_verbose(
                _LOGGER,
                "Rendering text copies=%s length_in=%s printable=%sx%s message=%r",
                copies,
                length_in,
                status.printable_width,
                status.printable_height,
                message,
            )
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
            log_verbose(
                _LOGGER,
                "Rendering image copies=%s length_in=%s printable=%sx%s bytes=%s",
                copies,
                length_in,
                status.printable_width,
                status.printable_height,
                len(image),
            )
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
        blocked = status.print_blocked_reason()
        if blocked:
            raise HomeAssistantError(f"M211 cannot print: {blocked}")
        log_verbose(
            _LOGGER,
            "Encoding VGL6 job=%s copies=%s raster=%sx%s page=%sx%s offsets=%s,%s",
            job_name,
            copies,
            width,
            height,
            page_w,
            page_h,
            status.left_offset or 0,
            status.vertical_offset or 0,
        )
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
        log_verbose(
            _LOGGER,
            "Command starting keep_connected=%s connected=%s",
            self.keep_connected,
            self.client.is_connected,
        )
        try:
            await self._ensure_connected()
            await func()
            self.async_set_updated_data(self.client.status)
        except BradyOwnershipError as err:
            _LOGGER.error("Command ownership failure: %s", err)
            raise HomeAssistantError(str(err)) from err
        except BradyProtocolError as err:
            _LOGGER.exception("Command protocol failure: %s", err)
            raise HomeAssistantError(str(err)) from err
        finally:
            if not self.keep_connected:
                log_verbose(
                    _LOGGER,
                    "Command finished; disconnecting (connect-on-demand) release=%s",
                    self.release_on_disconnect,
                )
                await self.client.disconnect(release=self.release_on_disconnect)

    async def _ensure_connected(self) -> None:
        ble_device = self._ble_device or bluetooth.async_ble_device_from_address(
            self.hass, self.address, True
        )
        if ble_device is None:
            _LOGGER.error(
                "M211 %s not reachable via any Bluetooth adapter or ESPHome proxy",
                self.address,
            )
            raise HomeAssistantError(
                f"{MODEL} {self.address} is not currently reachable via any "
                "Bluetooth adapter or ESPHome Bluetooth proxy"
            )
        self._ble_device = ble_device
        log_verbose(
            _LOGGER,
            "Ensuring GATT session via %s",
            describe_ble_device(ble_device),
        )
        ownership = await self.client.connect(
            ble_device,
            ownership_id=self.config_entry.data.get(CONF_OWNERSHIP_ID),
            name=self.config_entry.title or MODEL,
        )
        if ownership and ownership != self.config_entry.data.get(CONF_OWNERSHIP_ID):
            log_verbose(_LOGGER, "Persisting new ownership_id=%s", ownership)
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_OWNERSHIP_ID: ownership},
            )
