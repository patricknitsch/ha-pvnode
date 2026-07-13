"""Sensor platform for the pvnode integration.

Every roof surface ("Dachfläche") gets its own device with its own set of
sensors - forecasts are never merged into a single combined entity. An
additional "total" device aggregates all roof surfaces for convenience once
more than one is known.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import API_VERSION_V2, CONF_API_VERSION, DOMAIN, MANUFACTURER
from .coordinator import PvnodeDataUpdateCoordinator, PvnodeRoofData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up pvnode sensors for a config entry."""
    coordinator: PvnodeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    added_roof_keys: set[str] = set()
    summary_added = False

    def _update_summary() -> None:
        nonlocal summary_added
        if summary_added or len(coordinator.data.roofs) <= 1:
            return
        summary_added = True
        async_add_entities(
            [
                PvnodeTotalPowerSensor(coordinator, entry),
                PvnodeTotalEnergySensor(coordinator, entry, "today"),
                PvnodeTotalEnergySensor(coordinator, entry, "tomorrow"),
            ]
        )

    @callback
    def _add_roofs(roof_keys: set[str]) -> None:
        new_entities: list[SensorEntity] = []
        for key in roof_keys:
            if key in added_roof_keys:
                continue
            added_roof_keys.add(key)
            new_entities.extend(_build_roof_entities(coordinator, entry, key))
        if new_entities:
            async_add_entities(new_entities)
        _update_summary()

    _add_roofs(set(coordinator.data.roofs))
    entry.async_on_unload(coordinator.add_new_roof_listener(_add_roofs))


def _build_roof_entities(
    coordinator: PvnodeDataUpdateCoordinator, entry: ConfigEntry, roof_key: str
) -> list[SensorEntity]:
    """Build the full set of sensors for a single roof surface."""
    return [
        PvnodePowerSensor(coordinator, entry, roof_key),
        PvnodeEnergySensor(coordinator, entry, roof_key, "today"),
        PvnodeEnergySensor(coordinator, entry, roof_key, "tomorrow"),
        PvnodeClearskyPowerSensor(coordinator, entry, roof_key),
        PvnodeTemperatureSensor(coordinator, entry, roof_key),
        PvnodeWeatherCodeSensor(coordinator, entry, roof_key),
    ]


class PvnodeRoofEntity(CoordinatorEntity[PvnodeDataUpdateCoordinator], SensorEntity):
    """Base class for entities tied to a single pvnode roof surface."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PvnodeDataUpdateCoordinator,
        entry: ConfigEntry,
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


class PvnodePowerSensor(PvnodeRoofEntity):
    """Current forecast power for a roof surface."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "power"

    def __init__(
        self,
        coordinator: PvnodeDataUpdateCoordinator,
        entry: ConfigEntry,
        roof_key: str,
    ) -> None:
        """Initialize the power sensor."""
        super().__init__(coordinator, entry, roof_key)
        self._attr_unique_id = f"{entry.entry_id}_{roof_key}_power"

    @property
    def native_value(self) -> float | None:
        """Return the forecast power for the current time slot."""
        roof = self._roof
        return roof.forecast.current_power if roof else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the full forecast time series for charting."""
        roof = self._roof
        if not roof:
            return None
        return {
            "forecast": [
                {"datetime": timestamp.isoformat(), "watts": watts}
                for timestamp, watts in sorted(roof.forecast.watts.items())
            ]
        }


class PvnodeEnergySensor(PvnodeRoofEntity):
    """Forecast energy total (today/tomorrow) for a roof surface."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR

    def __init__(
        self,
        coordinator: PvnodeDataUpdateCoordinator,
        entry: ConfigEntry,
        roof_key: str,
        day: str,
    ) -> None:
        """Initialize the energy sensor for "today" or "tomorrow"."""
        super().__init__(coordinator, entry, roof_key)
        self._day = day
        self._attr_unique_id = f"{entry.entry_id}_{roof_key}_energy_{day}"
        self._attr_translation_key = f"energy_{day}"

    @property
    def native_value(self) -> float | None:
        """Return the forecast energy total for the selected day."""
        roof = self._roof
        if not roof:
            return None
        target = dt_util.now().date()
        if self._day == "tomorrow":
            target += timedelta(days=1)
        return roof.forecast.energy_for(target)


class PvnodeClearskyPowerSensor(PvnodeRoofEntity):
    """Clear-sky reference power for a roof surface (pvnode extension)."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "clearsky_power"

    def __init__(
        self,
        coordinator: PvnodeDataUpdateCoordinator,
        entry: ConfigEntry,
        roof_key: str,
    ) -> None:
        """Initialize the clear-sky power sensor."""
        super().__init__(coordinator, entry, roof_key)
        self._attr_unique_id = f"{entry.entry_id}_{roof_key}_clearsky_power"

    @property
    def native_value(self) -> float | None:
        """Return the clear-sky power for the current time slot."""
        roof = self._roof
        return roof.forecast.current_clearsky_power if roof else None


class PvnodeTemperatureSensor(PvnodeRoofEntity):
    """Forecast temperature for a roof surface (pvnode extension)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "temperature"

    def __init__(
        self,
        coordinator: PvnodeDataUpdateCoordinator,
        entry: ConfigEntry,
        roof_key: str,
    ) -> None:
        """Initialize the temperature sensor."""
        super().__init__(coordinator, entry, roof_key)
        self._attr_unique_id = f"{entry.entry_id}_{roof_key}_temperature"

    @property
    def native_value(self) -> float | None:
        """Return the forecast temperature for the current time slot."""
        roof = self._roof
        return roof.forecast.current_temperature if roof else None


class PvnodeWeatherCodeSensor(PvnodeRoofEntity):
    """WMO weather code for a roof surface (pvnode extension)."""

    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "weather_code"

    def __init__(
        self,
        coordinator: PvnodeDataUpdateCoordinator,
        entry: ConfigEntry,
        roof_key: str,
    ) -> None:
        """Initialize the weather code sensor."""
        super().__init__(coordinator, entry, roof_key)
        self._attr_unique_id = f"{entry.entry_id}_{roof_key}_weather_code"

    @property
    def native_value(self) -> int | None:
        """Return the WMO weather code for the current time slot."""
        roof = self._roof
        return roof.forecast.current_weather_code if roof else None


class PvnodeTotalEntity(CoordinatorEntity[PvnodeDataUpdateCoordinator], SensorEntity):
    """Base class for entities aggregating all roof surfaces of one entry."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: PvnodeDataUpdateCoordinator, entry: ConfigEntry
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


class PvnodeTotalPowerSensor(PvnodeTotalEntity):
    """Total forecast power across all roof surfaces."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "total_power"

    def __init__(
        self, coordinator: PvnodeDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the total power sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_total_power"

    @property
    def native_value(self) -> float | None:
        """Return the summed forecast power of all roof surfaces."""
        if not self.coordinator.data:
            return None
        total = 0.0
        found = False
        for roof in self.coordinator.data.roofs.values():
            value = roof.forecast.current_power
            if value is not None:
                total += value
                found = True
        return total if found else None


class PvnodeTotalEnergySensor(PvnodeTotalEntity):
    """Total forecast energy (today/tomorrow) across all roof surfaces."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR

    def __init__(
        self, coordinator: PvnodeDataUpdateCoordinator, entry: ConfigEntry, day: str
    ) -> None:
        """Initialize the total energy sensor for "today" or "tomorrow"."""
        super().__init__(coordinator, entry)
        self._day = day
        self._attr_unique_id = f"{entry.entry_id}_total_energy_{day}"
        self._attr_translation_key = f"total_energy_{day}"

    @property
    def native_value(self) -> float | None:
        """Return the summed forecast energy total of all roof surfaces."""
        if not self.coordinator.data:
            return None
        target = dt_util.now().date()
        if self._day == "tomorrow":
            target += timedelta(days=1)
        total = 0.0
        found = False
        for roof in self.coordinator.data.roofs.values():
            value = roof.forecast.energy_for(target)
            if value is not None:
                total += value
                found = True
        return total if found else None
