"""Binary sensors for Brady M211 errors and connection state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BradyM211ConfigEntry, BradyM211Coordinator
from .entity import BradyM211Entity
from .models import PrinterStatus


@dataclass(frozen=True, kw_only=True)
class M211BinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[PrinterStatus, BradyM211Coordinator], bool | None]


BINARIES: tuple[M211BinaryDescription, ...] = (
    M211BinaryDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda _s, c: c.client.is_connected,
    ),
    M211BinaryDescription(
        key="media_out",
        translation_key="media_out",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s, _c: s.media_out,
    ),
    M211BinaryDescription(
        key="fatal_error",
        translation_key="fatal_error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s, _c: s.fatal_error,
    ),
    M211BinaryDescription(
        key="cut_error",
        translation_key="cut_error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s, _c: s.cut_error,
    ),
    M211BinaryDescription(
        key="print_job_error",
        translation_key="print_job_error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s, _c: s.print_job_error,
    ),
    M211BinaryDescription(
        key="ac_power",
        translation_key="ac_power",
        device_class=BinarySensorDeviceClass.PLUG,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s, _c: s.battery_ac,
    ),
    M211BinaryDescription(
        key="die_cut",
        translation_key="die_cut",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s, _c: s.die_cut,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BradyM211ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(M211BinarySensor(coordinator, desc) for desc in BINARIES)


class M211BinarySensor(BradyM211Entity, BinarySensorEntity):
    entity_description: M211BinaryDescription

    def __init__(
        self, coordinator: BradyM211Coordinator, description: M211BinaryDescription
    ) -> None:
        self.entity_description = description
        super().__init__(coordinator, description.key)

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None and self.entity_description.key != "connected":
            return None
        status = self.coordinator.data or PrinterStatus()
        return self.entity_description.value_fn(status, self.coordinator)
