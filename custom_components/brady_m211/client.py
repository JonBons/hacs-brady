"""Bleak GATT client for the Brady M211 Apollo protocol.

Resolves devices through Home Assistant's Bluetooth stack (local adapter or
ESPHome Bluetooth proxy) when the caller supplies a ``BLEDevice``. Do not
construct this client with a raw MAC string — that bypasses proxy routing.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import (
    CHAR_PICL_REQUEST,
    CHAR_PICL_RESPONSE,
    CHAR_PRINT_JOB,
    CHAR_SESSION_ID,
    PROP_CUT,
    PROP_FEED,
)
from .models import PrinterStatus
from .protocol import (
    BradyOwnershipError,
    BradyProtocolError,
    build_session_payload,
    build_set_packet,
    build_subscribe_packet,
    chunk_payload_size,
    iter_chunks,
    parse_picl_notification,
    release_session_payload,
)

_LOGGER = logging.getLogger(__name__)

_STATUS_WAIT_S = 8.0
_PRINT_WAIT_S = 90.0
_FLUSH_PAUSE_S = 0.01


class BradyM211Client:
    """Connect, own, subscribe, print, feed, and cut an M211."""

    def __init__(self) -> None:
        self._client: BleakClient | None = None
        self._lock = asyncio.Lock()
        self._properties: dict[str, str] = {}
        self._status_event = asyncio.Event()
        self._job_event = asyncio.Event()
        self._disconnected = asyncio.Event()
        self._disconnected.set()
        self.ownership_id: str | None = None
        self._released = True

    @property
    def is_connected(self) -> bool:
        return bool(self._client and self._client.is_connected)

    @property
    def mtu_size(self) -> int:
        if not self._client:
            return 23
        return int(getattr(self._client, "mtu_size", 23) or 23)

    @property
    def status(self) -> PrinterStatus:
        return PrinterStatus.from_properties(self._properties)

    async def connect(
        self,
        ble_device: BLEDevice,
        *,
        ownership_id: str | None = None,
        name: str = "M211",
    ) -> str:
        """Connect via HA's BLEDevice so Bluetooth proxies are used when present."""
        async with self._lock:
            if self.is_connected:
                return self.ownership_id or ownership_id or ""
            self._disconnected.clear()
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                ble_device.name or name,
                disconnected_callback=self._on_disconnect,
                max_attempts=5,
            )
            self._client = client
            try:
                await client.start_notify(CHAR_PICL_RESPONSE, self._on_picl)
                guid, first_claim = self._resolve_guid(ownership_id)
                await client.write_gatt_char(
                    CHAR_SESSION_ID,
                    build_session_payload(guid, first_claim),
                    response=True,
                )
                self.ownership_id = str(guid)
                self._released = False
                await self._write_chunked(CHAR_PICL_REQUEST, build_subscribe_packet())
            except BleakError as err:
                await self._disconnect_unlocked(release=False)
                raise BradyOwnershipError(
                    "Could not claim the M211. If the Bluetooth LED is solid, "
                    "hold the power button for 5 seconds to release the other "
                    f"device, then try again. ({err})"
                ) from err
            except Exception:
                await self._disconnect_unlocked(release=False)
                raise
            return self.ownership_id

    async def disconnect(self, *, release: bool = True) -> None:
        async with self._lock:
            await self._disconnect_unlocked(release=release)

    async def refresh_status(self, timeout: float = _STATUS_WAIT_S) -> PrinterStatus:
        async with self._lock:
            self._ensure_connected()
            self._status_event.clear()
            await self._write_chunked(CHAR_PICL_REQUEST, build_subscribe_packet())
        try:
            async with asyncio.timeout(timeout):
                await self._status_event.wait()
        except TimeoutError:
            _LOGGER.debug("Timed out waiting for PICL status; using cached values")
        return self.status

    async def feed(self) -> None:
        async with self._lock:
            self._ensure_connected()
            await self._write_chunked(
                CHAR_PICL_REQUEST, build_set_packet(PROP_FEED, "True")
            )

    async def cut(self) -> None:
        async with self._lock:
            self._ensure_connected()
            await self._write_chunked(
                CHAR_PICL_REQUEST, build_set_packet(PROP_CUT, "True")
            )

    async def print_job(self, payload: bytes, job_name: str | None = None) -> None:
        async with self._lock:
            self._ensure_connected()
            self._job_event.clear()
            self._properties.pop("0029", None)
            await self._write_chunked(CHAR_PRINT_JOB, payload)
        try:
            async with asyncio.timeout(_PRINT_WAIT_S):
                while True:
                    await self._job_event.wait()
                    self._job_event.clear()
                    succeeded = self.status.job_succeeded(job_name)
                    if succeeded is True:
                        return
                    if succeeded is False:
                        raise BradyProtocolError(
                            f"M211 rejected print job: {self.status.job_status}"
                        )
                    if self.status.job_complete:
                        return
        except TimeoutError as err:
            raise BradyProtocolError("Timed out waiting for the M211 to finish printing") from err

    def _resolve_guid(self, ownership_id: str | None) -> tuple[uuid.UUID, bool]:
        stored = ownership_id or self.ownership_id
        if stored:
            try:
                return uuid.UUID(stored), self._released
            except ValueError:
                _LOGGER.warning("Ignoring invalid stored ownership id")
        return uuid.uuid4(), True

    def _ensure_connected(self) -> None:
        if not self.is_connected or self._client is None:
            raise BradyProtocolError("M211 is not connected")

    async def _write_chunked(self, char_uuid: str, payload: bytes) -> None:
        assert self._client is not None
        size = chunk_payload_size(self.mtu_size)
        _LOGGER.debug(
            "Writing %s bytes to %s in %s-byte chunks (MTU %s)",
            len(payload),
            char_uuid,
            size,
            self.mtu_size,
        )
        for chunk in iter_chunks(payload, size):
            await self._client.write_gatt_char(char_uuid, chunk, response=True)
            if chunk[0] == 2:
                await asyncio.sleep(_FLUSH_PAUSE_S)

    def _on_picl(self, _char: Any, data: bytearray) -> None:
        updates = parse_picl_notification(bytes(data))
        if not updates:
            return
        for prop_id, value, _status in updates:
            self._properties[prop_id] = value
        self._status_event.set()
        self._job_event.set()

    def _on_disconnect(self, _client: BleakClient) -> None:
        _LOGGER.debug("M211 disconnected")
        self._disconnected.set()

    async def _disconnect_unlocked(self, *, release: bool) -> None:
        client = self._client
        self._client = None
        if client is None:
            self._disconnected.set()
            return
        try:
            if client.is_connected and release:
                try:
                    await client.write_gatt_char(
                        CHAR_SESSION_ID, release_session_payload(), response=True
                    )
                    self._released = True
                except BleakError:
                    _LOGGER.debug("Failed to release M211 ownership", exc_info=True)
            elif not release:
                self._released = False
            if client.is_connected:
                try:
                    await client.stop_notify(CHAR_PICL_RESPONSE)
                except BleakError:
                    pass
                await client.disconnect()
        finally:
            self._disconnected.set()
