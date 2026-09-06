"""Diagnostics for Brady M211."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import CONF_KEEP_CONNECTED, CONF_RELEASE_ON_DISCONNECT
from .coordinator import BradyM211ConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BradyM211ConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    status = coordinator.data
    ble = coordinator._ble_device  # noqa: SLF001
    details = getattr(ble, "details", None) if ble else None
    return {
        "address": coordinator.address,
        "title": entry.title,
        "has_ownership_id": bool(entry.data.get("ownership_id")),
        "keep_connected": entry.options.get(CONF_KEEP_CONNECTED),
        "release_on_disconnect": entry.options.get(CONF_RELEASE_ON_DISCONNECT),
        "connected": coordinator.client.is_connected,
        "mtu": coordinator.client.mtu_size if coordinator.client.is_connected else None,
        "ble_name": getattr(ble, "name", None),
        "ble_details": details if isinstance(details, dict) else str(details) if details else None,
        "status": None
        if status is None
        else {
            "battery": status.battery,
            "media_remaining": status.media_remaining,
            "printable_width": status.printable_width,
            "printable_height": status.printable_height,
            "firmware": status.firmware,
            "job_status": status.job_status,
            "fatal_error": status.fatal_error,
            "media_out": status.media_out,
            "raw_ids": sorted(status.raw),
        },
    }
