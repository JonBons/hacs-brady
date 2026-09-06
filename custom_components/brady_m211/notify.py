"""Notify entity so automations can print a text label."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.notify import NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BradyM211ConfigEntry, BradyM211Coordinator
from .entity import BradyM211Entity
from .logutil import log_verbose

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BradyM211ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([M211NotifyEntity(entry.runtime_data)])


class M211NotifyEntity(BradyM211Entity, NotifyEntity):
    """Print the notification message as a label."""

    _attr_translation_key = "label"

    def __init__(self, coordinator: BradyM211Coordinator) -> None:
        super().__init__(coordinator, "notify")

    async def async_send_message(
        self, message: str, title: str | None = None, **kwargs: Any
    ) -> None:
        text = f"{title}\n{message}" if title else message
        log_verbose(_LOGGER, "Notify print title=%r message=%r", title, message)
        await self.coordinator.async_print_text(text)
