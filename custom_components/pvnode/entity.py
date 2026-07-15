"""Base entity classes for the pvnode integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    API_VERSION_V2,
    CONF_API_VERSION,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import PvnodeConfigEntry, PvnodeDataUpdateCoordinator, PvnodeRoofData


class PvnodeRoofEntity(CoordinatorEntity[PvnodeDataUpdateCoordinator], SensorEntity):
    """Base class for entities tied to a single pvnode roof surface."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PvnodeDataUpdateCoordinator,
        entry: PvnodeConfigEntry,
        roof_key: str,
    ) -> None:
        """Initialize the entity and its device info."""
        super().__init__(coordinator)
        self._entry = entry
        self._roof_key = roof_key

        roof = self._roof
        model = (
            "pvnode API v2 (Dachfläche/String)"
            if entry.data.get(CONF_API_VERSION) == API_VERSION_V2
            else "pvnode API v1 (Dachfläche)"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{roof_key}")},
            name=roof.name if roof else roof_key,
            manufacturer=MANUFACTURER,
            model=model,
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def _roof(self) -> PvnodeRoofData | None:
        """Return the current data for this roof surface, if available."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.roofs.get(self._roof_key)

    @property
    def available(self) -> bool:
        """Return whether this roof surface is currently reporting data."""
        return super().available and self._roof is not None


class PvnodeTotalEntity(CoordinatorEntity[PvnodeDataUpdateCoordinator], SensorEntity):
    """Base class for entities on the pvnode overview device (site-wide)."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: PvnodeDataUpdateCoordinator, entry: PvnodeConfigEntry
    ) -> None:
        """Initialize the entity and attach it to the account/site hub device."""
        super().__init__(coordinator)
        self._entry = entry
        api_version = entry.data.get(CONF_API_VERSION, API_VERSION_V2).upper()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=f"pvnode API {api_version}",
            configuration_url="https://pvnode.com",
        )
