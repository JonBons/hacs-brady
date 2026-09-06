"""Verbose logging helpers for M211 bring-up."""

from __future__ import annotations

import logging
from typing import Any

from .const import (
    CHAR_PICL_REQUEST,
    CHAR_PICL_RESPONSE,
    CHAR_PRINT_JOB,
    CHAR_SESSION_ID,
    CHUNK_FLAG_FLUSH,
    CHUNK_FLAG_LAST,
    CHUNK_FLAG_MORE,
    PICL_PROP_NAMES,
    VERBOSE_LOGGING,
)

_CHAR_LABELS = {
    CHAR_SESSION_ID.lower(): "session_id",
    CHAR_PRINT_JOB.lower(): "print_job",
    CHAR_PICL_REQUEST.lower(): "picl_request",
    CHAR_PICL_RESPONSE.lower(): "picl_response",
}

_FLAG_LABELS = {
    CHUNK_FLAG_MORE: "MORE",
    CHUNK_FLAG_FLUSH: "FLUSH",
    CHUNK_FLAG_LAST: "LAST",
}


def log_verbose(
    logger: logging.Logger, message: str, *args: Any, **kwargs: Any
) -> None:
    """Info while VERBOSE_LOGGING is on, otherwise debug."""
    if VERBOSE_LOGGING:
        logger.info(message, *args, **kwargs)
    else:
        logger.debug(message, *args, **kwargs)


def format_bytes(data: bytes | bytearray, *, limit: int = 64) -> str:
    """Length-prefixed hex preview, truncated for large payloads."""
    raw = bytes(data)
    if not raw:
        return "0B []"
    shown = raw[:limit]
    hexed = shown.hex(" ")
    extra = f" … +{len(raw) - limit}B" if len(raw) > limit else ""
    return f"{len(raw)}B [{hexed}{extra}]"


def char_label(uuid: str) -> str:
    return _CHAR_LABELS.get(uuid.lower(), uuid)


def flag_label(flag: int) -> str:
    return _FLAG_LABELS.get(flag, str(flag))


def format_picl_updates(updates: list[tuple[str, str, str]]) -> str:
    parts: list[str] = []
    for prop_id, value, status in updates:
        name = PICL_PROP_NAMES.get(prop_id, prop_id)
        extra = f" status={status}" if status else ""
        parts.append(f"{name}({prop_id})={value!r}{extra}")
    return ", ".join(parts) if parts else "<none>"


def describe_ble_device(device: Any) -> str:
    """Summarize a Bleak BLEDevice, including ESPHome proxy details when present."""
    if device is None:
        return "<no BLEDevice>"
    parts = [
        f"address={getattr(device, 'address', None)}",
        f"name={getattr(device, 'name', None)!r}",
    ]
    rssi = getattr(device, "rssi", None)
    if rssi is not None:
        parts.append(f"rssi={rssi}")
    details = getattr(device, "details", None)
    if isinstance(details, dict):
        for key in ("source", "path", "adapter", "address_type"):
            if details.get(key) is not None:
                parts.append(f"{key}={details[key]}")
        extra = sorted(k for k in details if k not in {"source", "path", "adapter", "address_type"})
        if extra:
            parts.append(f"details_keys={','.join(extra)}")
    elif details:
        parts.append(f"details={details!r}")
    return " ".join(parts)


def _hexify_map(mapping: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not mapping:
        return out
    for key, value in mapping.items():
        if isinstance(value, (bytes, bytearray)):
            out[str(key)] = bytes(value).hex()
        else:
            out[str(key)] = value
    return out


def describe_service_info(info: Any) -> str:
    """Summarize a Home Assistant BluetoothServiceInfoBleak advertisement."""
    if info is None:
        return "<no advertisement>"
    return (
        f"name={getattr(info, 'name', None)!r} "
        f"address={getattr(info, 'address', None)} "
        f"rssi={getattr(info, 'rssi', None)} "
        f"connectable={getattr(info, 'connectable', None)} "
        f"source={getattr(info, 'source', None)} "
        f"tx_power={getattr(info, 'tx_power', None)} "
        f"service_uuids={list(getattr(info, 'service_uuids', ()) or ())} "
        f"manufacturer_data={_hexify_map(getattr(info, 'manufacturer_data', None))} "
        f"service_data={_hexify_map(getattr(info, 'service_data', None))}"
    )
