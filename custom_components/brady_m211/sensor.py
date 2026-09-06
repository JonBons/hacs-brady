"""Sensors for Brady M211 Compact PICL properties."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import BradyM211ConfigEntry, BradyM211Coordinator
from .entity import BradyM211Entity
from .models import PrinterStatus


@dataclass(frozen=True, kw_only=True)
class M211SensorDescription(SensorEntityDescription):
    value_fn: Callable[[PrinterStatus], StateType]


SENSORS: tuple[M211SensorDescription, ...] = (
    M211SensorDescription(
        key="battery",
        translation_key="battery",
        value_fn=lambda s: _battery_percent(s.battery),
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    M211SensorDescription(
        key="media_remaining",
        translation_key="media_remaining",
        value_fn=lambda s: s.media_remaining,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    M211SensorDescription(
        key="firmware",
        translation_key="firmware",
        value_fn=lambda s: s.firmware,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    M211SensorDescription(
        key="printable_width",
        translation_key="printable_width",
        value_fn=lambda s: s.printable_width,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="dots",
    ),
    M211SensorDescription(
        key="printable_height",
        translation_key="printable_height",
        value_fn=lambda s: s.printable_height,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="dots",
    ),
    M211SensorDescription(
        key="job_status",
        translation_key="job_status",
        value_fn=lambda s: s.job_status,
    ),
    M211SensorDescription(
        key="unique_id",
        translation_key="cartridge_id",
        value_fn=lambda s: s.unique_id,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    M211SensorDescription(
        key="knockoff_count",
        translation_key="knockoff_count",
        value_fn=lambda s: s.knockoff_count,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


def _battery_percent(raw: str | None) -> int | None:
    if raw is None:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None
    return max(0, min(int(digits), 100))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BradyM211ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(M211Sensor(coordinator, desc) for desc in SENSORS)


class M211Sensor(BradyM211Entity, SensorEntity):
    entity_description: M211SensorDescription

    def __init__(
        self, coordinator: BradyM211Coordinator, description: M211SensorDescription
    ) -> None:
        self.entity_description = description
        super().__init__(coordinator, description.key)

    @property
    def native_value(self) -> StateType:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
