"""Shared entity base for Brady M211."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import BradyM211Coordinator


class BradyM211Entity(CoordinatorEntity[BradyM211Coordinator]):
    """Coordinator entity attached to a single M211."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BradyM211Coordinator, unique_suffix: str) -> None:
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.address}_{unique_suffix}"
