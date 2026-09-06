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
from .logutil import (
    char_label,
    describe_ble_device,
    flag_label,
    format_bytes,
    format_picl_updates,
    log_verbose,
)
from .models import PrinterStatus
from .protocol import (
    BradyOwnershipError,
    BradyProtocolError,
    build_session_payload,
    build_set_packet,
    build_subscribe_packet,
    chunk_payload_size,
    extract_picl_json,
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
                log_verbose(
                    _LOGGER,
                    "Connect skipped; already on GATT session ownership_id=%s %s",
                    self.ownership_id,
                    describe_ble_device(ble_device),
                )
                return self.ownership_id or ownership_id or ""
            log_verbose(
                _LOGGER,
                "Connecting to M211 name=%s stored_ownership=%s %s",
                name,
                ownership_id,
                describe_ble_device(ble_device),
            )
            self._disconnected.clear()
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                ble_device.name or name,
                disconnected_callback=self._on_disconnect,
                max_attempts=5,
            )
            self._client = client
            log_verbose(
                _LOGGER,
                "GATT up mtu=%s connected=%s %s",
                getattr(client, "mtu_size", None),
                client.is_connected,
                describe_ble_device(ble_device),
            )
            try:
                self._log_gatt_map(client)
            except Exception:
                _LOGGER.debug("Could not dump GATT map", exc_info=True)
            try:
                log_verbose(
                    _LOGGER,
                    "start_notify %s (PICL indications)",
                    char_label(CHAR_PICL_RESPONSE),
                )
                await client.start_notify(CHAR_PICL_RESPONSE, self._on_picl)
                guid, first_claim = self._resolve_guid(ownership_id)
                session = build_session_payload(guid, first_claim)
                log_verbose(
                    _LOGGER,
                    "Writing %s guid=%s first_claim=%s %s",
                    char_label(CHAR_SESSION_ID),
                    guid,
                    first_claim,
                    format_bytes(session),
                )
                await client.write_gatt_char(
                    CHAR_SESSION_ID,
                    session,
                    response=True,
                )
                self.ownership_id = str(guid)
                self._released = False
                log_verbose(
                    _LOGGER,
                    "Session claimed ownership_id=%s; sending PICL subscribe",
                    self.ownership_id,
                )
                await self._write_chunked(CHAR_PICL_REQUEST, build_subscribe_packet())
            except BleakError as err:
                _LOGGER.exception(
                    "Failed to claim M211 GATT session (%s). Printer may be owned "
                    "by another device.",
                    err,
                )
                await self._disconnect_unlocked(release=False)
                raise BradyOwnershipError(
                    "Could not claim the M211. If the Bluetooth LED is solid, "
                    "hold the power button for 5 seconds to release the other "
                    f"device, then try again. ({err})"
                ) from err
            except Exception:
                _LOGGER.exception("Unexpected error while connecting to M211")
                await self._disconnect_unlocked(release=False)
                raise
            return self.ownership_id

    async def disconnect(self, *, release: bool = True) -> None:
        async with self._lock:
            await self._disconnect_unlocked(release=release)

    async def refresh_status(self, timeout: float = _STATUS_WAIT_S) -> PrinterStatus:
        log_verbose(_LOGGER, "Refreshing PICL status (timeout=%ss)", timeout)
        async with self._lock:
            self._ensure_connected()
            self._status_event.clear()
            await self._write_chunked(CHAR_PICL_REQUEST, build_subscribe_packet())
        try:
            async with asyncio.timeout(timeout):
                await self._status_event.wait()
        except TimeoutError:
            _LOGGER.warning(
                "Timed out waiting for PICL status after %ss; using cached values %s",
                timeout,
                self._properties,
            )
        else:
            log_verbose(_LOGGER, "PICL status received: %s", self._status_summary())
        return self.status

    async def feed(self) -> None:
        log_verbose(_LOGGER, "Sending PICL feed")
        async with self._lock:
            self._ensure_connected()
            await self._write_chunked(
                CHAR_PICL_REQUEST, build_set_packet(PROP_FEED, "True")
            )

    async def cut(self) -> None:
        log_verbose(_LOGGER, "Sending PICL cut")
        async with self._lock:
            self._ensure_connected()
            await self._write_chunked(
                CHAR_PICL_REQUEST, build_set_packet(PROP_CUT, "True")
            )

    async def print_job(self, payload: bytes, job_name: str | None = None) -> None:
        log_verbose(
            _LOGGER,
            "Starting print job name=%s mtu=%s %s",
            job_name,
            self.mtu_size,
            format_bytes(payload, limit=48),
        )
        async with self._lock:
            self._ensure_connected()
            self._job_event.clear()
            self._properties.pop("0029", None)
            await self._write_chunked(CHAR_PRINT_JOB, payload)
        log_verbose(_LOGGER, "Print payload written; waiting for PICL job status")
        try:
            async with asyncio.timeout(_PRINT_WAIT_S):
                while True:
                    await self._job_event.wait()
                    self._job_event.clear()
                    succeeded = self.status.job_succeeded(job_name)
                    log_verbose(
                        _LOGGER,
                        "Print job PICL update job_name=%s job_status=%r "
                        "job_complete=%s succeeded=%s",
                        job_name,
                        self.status.job_status,
                        self.status.job_complete,
                        succeeded,
                    )
                    if succeeded is True:
                        log_verbose(_LOGGER, "Print job succeeded")
                        return
                    if succeeded is False:
                        raise BradyProtocolError(
                            f"M211 rejected print job: {self.status.job_status}"
                        )
                    if self.status.job_complete:
                        log_verbose(_LOGGER, "Print job marked complete without explicit success")
                        return
        except TimeoutError as err:
            _LOGGER.error(
                "Timed out waiting for print job name=%s last_status=%r properties=%s",
                job_name,
                self.status.job_status,
                self._properties,
            )
            raise BradyProtocolError("Timed out waiting for the M211 to finish printing") from err

    def _resolve_guid(self, ownership_id: str | None) -> tuple[uuid.UUID, bool]:
        stored = ownership_id or self.ownership_id
        if stored:
            try:
                return uuid.UUID(stored), self._released
            except ValueError:
                _LOGGER.warning("Ignoring invalid stored ownership id %r", stored)
        return uuid.uuid4(), True

    def _ensure_connected(self) -> None:
        if not self.is_connected or self._client is None:
            raise BradyProtocolError("M211 is not connected")

    def _status_summary(self) -> str:
        status = self.status
        return (
            f"battery={status.battery!r} media_remaining={status.media_remaining} "
            f"printable={status.printable_width}x{status.printable_height} "
            f"firmware={status.firmware!r} job_status={status.job_status!r} "
            f"media_out={status.media_out} fatal_error={status.fatal_error}"
        )

    def _log_gatt_map(self, client: BleakClient) -> None:
        services = getattr(client, "services", None)
        if not services:
            _LOGGER.warning("No GATT services on M211 after connect")
            return
        count = 0
        for service in services:
            chars: list[str] = []
            for characteristic in service.characteristics:
                count += 1
                props = ",".join(characteristic.properties or ())
                chars.append(f"{char_label(characteristic.uuid)}[{props}]")
            log_verbose(
                _LOGGER,
                "GATT service %s: %s",
                service.uuid,
                "; ".join(chars) if chars else "<no characteristics>",
            )
        log_verbose(_LOGGER, "GATT map: %s characteristics across discovered services", count)

    async def _write_chunked(self, char_uuid: str, payload: bytes) -> None:
        assert self._client is not None
        size = chunk_payload_size(self.mtu_size)
        chunks = list(iter_chunks(payload, size))
        log_verbose(
            _LOGGER,
            "Writing %s bytes to %s in %s chunks of up to %s payload bytes (MTU %s)",
            len(payload),
            char_label(char_uuid),
            len(chunks),
            size,
            self.mtu_size,
        )
        noisy_chunks = char_uuid.lower() != CHAR_PRINT_JOB.lower()
        for index, chunk in enumerate(chunks, start=1):
            flag = chunk[0]
            seq = int.from_bytes(chunk[1:3], "little")
            message = (
                "GATT write %s chunk %s/%s flag=%s seq=%s %s"
            )
            args = (
                char_label(char_uuid),
                index,
                len(chunks),
                flag_label(flag),
                seq,
                format_bytes(chunk, limit=48 if noisy_chunks else 24),
            )
            if noisy_chunks:
                log_verbose(_LOGGER, message, *args)
            else:
                _LOGGER.debug(message, *args)
            try:
                await self._client.write_gatt_char(char_uuid, chunk, response=True)
            except BleakError:
                _LOGGER.exception(
                    "GATT write failed on %s chunk %s/%s flag=%s seq=%s",
                    char_label(char_uuid),
                    index,
                    len(chunks),
                    flag_label(flag),
                    seq,
                )
                raise
            if flag == 2:
                await asyncio.sleep(_FLUSH_PAUSE_S)
        if not noisy_chunks:
            log_verbose(
                _LOGGER,
                "Finished print_job write: %s chunks, %s payload bytes",
                len(chunks),
                len(payload),
            )

    def _on_picl(self, _char: Any, data: bytearray) -> None:
        raw = bytes(data)
        json_text = extract_picl_json(raw)
        updates = parse_picl_notification(raw)
        if not updates:
            _LOGGER.warning(
                "PICL indication had no PropertyGetResponses raw=%s json=%r",
                format_bytes(raw, limit=96),
                json_text,
            )
            return
        for prop_id, value, _status in updates:
            self._properties[prop_id] = value
        log_verbose(
            _LOGGER,
            "PICL indication %s json=%s",
            format_picl_updates(updates),
            json_text or "<binary envelope only>",
        )
        self._status_event.set()
        self._job_event.set()

    def _on_disconnect(self, _client: BleakClient) -> None:
        log_verbose(_LOGGER, "M211 BLE disconnect callback fired")
        self._disconnected.set()

    async def _disconnect_unlocked(self, *, release: bool) -> None:
        client = self._client
        self._client = None
        if client is None:
            _LOGGER.debug("Disconnect requested with no client")
            self._disconnected.set()
            return
        log_verbose(
            _LOGGER,
            "Disconnecting M211 release=%s still_connected=%s ownership_id=%s",
            release,
            client.is_connected,
            self.ownership_id,
        )
        try:
            if client.is_connected and release:
                try:
                    payload = release_session_payload()
                    log_verbose(
                        _LOGGER,
                        "Writing session release %s",
                        format_bytes(payload),
                    )
                    await client.write_gatt_char(
                        CHAR_SESSION_ID, payload, response=True
                    )
                    self._released = True
                except BleakError:
                    _LOGGER.warning("Failed to release M211 ownership", exc_info=True)
            elif not release:
                self._released = False
                log_verbose(_LOGGER, "Keeping ownership on disconnect (release=False)")
            if client.is_connected:
                try:
                    await client.stop_notify(CHAR_PICL_RESPONSE)
                except BleakError:
                    _LOGGER.debug("stop_notify failed during disconnect", exc_info=True)
                await client.disconnect()
                log_verbose(_LOGGER, "Bleak disconnect completed")
        finally:
            self._disconnected.set()
