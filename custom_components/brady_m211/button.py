"""Feed and cut buttons for the Brady M211."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BradyM211ConfigEntry, BradyM211Coordinator
from .entity import BradyM211Entity


@dataclass(frozen=True, kw_only=True)
class M211ButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[BradyM211Coordinator], Coroutine[Any, Any, None]]


BUTTONS: tuple[M211ButtonDescription, ...] = (
    M211ButtonDescription(
        key="feed",
        translation_key="feed",
        press_fn=lambda c: c.async_feed(),
    ),
    M211ButtonDescription(
        key="cut",
        translation_key="cut",
        press_fn=lambda c: c.async_cut(),
    ),
    M211ButtonDescription(
        key="refresh",
        translation_key="refresh",
        press_fn=lambda c: c.async_refresh(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BradyM211ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(M211Button(coordinator, desc) for desc in BUTTONS)


class M211Button(BradyM211Entity, ButtonEntity):
    entity_description: M211ButtonDescription

    def __init__(
        self, coordinator: BradyM211Coordinator, description: M211ButtonDescription
    ) -> None:
        self.entity_description = description
        super().__init__(coordinator, description.key)

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator)
