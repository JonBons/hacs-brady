"""The Brady M211 Home Assistant integration."""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path

import voluptuous as vol

from homeassistant.const import CONF_ADDRESS, CONF_DEVICE_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN, VERBOSE_LOGGING
from .coordinator import BradyM211ConfigEntry, BradyM211Coordinator
from .logutil import log_verbose

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NOTIFY,
    Platform.SENSOR,
]

SERVICE_PRINT_TEXT = "print_text"
SERVICE_PRINT_IMAGE = "print_image"

PRINT_TEXT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Required("message"): cv.string,
        vol.Optional("copies", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
        vol.Optional("length_in"): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=36.0)),
    }
)
PRINT_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Exclusive("filename", "image"): cv.string,
        vol.Exclusive("camera_entity_id", "image"): cv.entity_id,
        vol.Optional("copies", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
        vol.Optional("length_in"): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=36.0)),
    }
)


def _register_services(hass: HomeAssistant) -> None:
    """Register print services once for all M211 config entries."""

    def _coordinator_for_device(device_id: str) -> BradyM211Coordinator:
        registry = dr.async_get(hass)
        device = registry.async_get(device_id)
        if device is None:
            raise ServiceValidationError("Unknown Brady M211 device")
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry and entry.domain == DOMAIN:
                return entry.runtime_data
        raise ServiceValidationError("Device is not a Brady M211 printer")

    async def _print_text(call: ServiceCall) -> None:
        coordinator = _coordinator_for_device(call.data[CONF_DEVICE_ID])
        log_verbose(
            _LOGGER,
            "Service print_text device_id=%s copies=%s length_in=%s message=%r",
            call.data[CONF_DEVICE_ID],
            call.data["copies"],
            call.data.get("length_in"),
            call.data["message"],
        )
        await coordinator.async_print_text(
            call.data["message"],
            copies=call.data["copies"],
            length_in=call.data.get("length_in"),
        )

    async def _print_image(call: ServiceCall) -> None:
        coordinator = _coordinator_for_device(call.data[CONF_DEVICE_ID])
        log_verbose(
            _LOGGER,
            "Service print_image device_id=%s copies=%s length_in=%s filename=%s camera=%s",
            call.data[CONF_DEVICE_ID],
            call.data["copies"],
            call.data.get("length_in"),
            call.data.get("filename"),
            call.data.get("camera_entity_id"),
        )
        image: bytes
        if not call.data.get("filename") and not call.data.get("camera_entity_id"):
            raise ServiceValidationError("Provide filename or camera_entity_id")
        if filename := call.data.get("filename"):
            path = hass.config.path(filename)
            try:
                image = await hass.async_add_executor_job(partial(Path.read_bytes, Path(path)))
            except OSError as err:
                raise HomeAssistantError(f"Could not read image: {err}") from err
        else:
            from homeassistant.components.camera import async_get_image

            camera_id = call.data["camera_entity_id"]
            snap = await async_get_image(hass, camera_id)
            image = snap.content
        await coordinator.async_print_image(
            image,
            copies=call.data["copies"],
            length_in=call.data.get("length_in"),
        )

    hass.services.async_register(
        DOMAIN, SERVICE_PRINT_TEXT, _print_text, schema=PRINT_TEXT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PRINT_IMAGE, _print_image, schema=PRINT_IMAGE_SCHEMA
    )


async def async_setup_entry(hass: HomeAssistant, entry: BradyM211ConfigEntry) -> bool:
    """Set up one M211 from a config entry."""
    log_verbose(
        _LOGGER,
        "Setting up entry_id=%s title=%s address=%s verbose_logging=%s options=%s",
        entry.entry_id,
        entry.title,
        entry.data.get(CONF_ADDRESS),
        VERBOSE_LOGGING,
        dict(entry.options),
    )
    if not hass.services.has_service(DOMAIN, SERVICE_PRINT_TEXT):
        _register_services(hass)
    coordinator = BradyM211Coordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: BradyM211ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BradyM211ConfigEntry) -> bool:
    log_verbose(_LOGGER, "Unloading entry_id=%s title=%s", entry.entry_id, entry.title)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown_client()
    return unload_ok
