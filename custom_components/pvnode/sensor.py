"""Sensor platform for the pvnode integration.

Every roof surface ("Dachfläche") gets its own device with its own set of
sensors - forecasts are never merged into a single combined entity. An
additional "pvnode" overview device aggregates power/energy totals across all
roof surfaces, and is also the only place clear-sky power (when it can't be
attributed to an individual roof), temperature and weather code are shown -
those are site/location properties, not roof properties.
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

from .const import (
    API_VERSION_V1,
    API_VERSION_V2,
    CONF_API_VERSION,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import PvnodeDataUpdateCoordinator, PvnodeRoofData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up pvnode sensors for a config entry."""
    coordinator: PvnodeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    added_roof_keys: set[str] = set()

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

    _add_roofs(set(coordinator.data.roofs))
    entry.async_on_unload(coordinator.add_new_roof_listener(_add_roofs))

    async_add_entities(_build_site_entities(coordinator, entry))


def _apply_day_offset_translation(
    entity: SensorEntity, offset: int, key_prefix: str
) -> None:
    """Pick a translation key/placeholder for a day-offset energy sensor."""
    if offset == 0:
        entity._attr_translation_key = f"{key_prefix}_today"
    elif offset == 1:
        entity._attr_translation_key = f"{key_prefix}_tomorrow"
    else:
        entity._attr_translation_key = f"{key_prefix}_offset"
        entity._attr_translation_placeholders = {"day": str(offset)}


def _build_roof_entities(
    coordinator: PvnodeDataUpdateCoordinator, entry: ConfigEntry, roof_key: str
) -> list[SensorEntity]:
    """Build the full set of sensors for a single roof surface."""
    entities: list[SensorEntity] = [PvnodePowerSensor(coordinator, entry, roof_key)]
    entities.extend(
        PvnodeEnergySensor(coordinator, entry, roof_key, offset)
        for offset in range(coordinator.forecast_days)
    )
    if entry.data[CONF_API_VERSION] == API_VERSION_V1:
        # Only API v1 fetches each roof surface individually, so clear-sky
        # power is genuinely roof-specific here. API v2 only returns
        # clear-sky/temperature/weather for the site as a whole (see
        # `_build_site_entities`), never per string.
        entities.append(PvnodeClearskyPowerSensor(coordinator, entry, roof_key))
    return entities


def _build_site_entities(
    coordinator: PvnodeDataUpdateCoordinator, entry: ConfigEntry
) -> list[SensorEntity]:
    """Build the sensors for the pvnode overview ("total") device."""
    entities: list[SensorEntity] = [PvnodeTotalPowerSensor(coordinator, entry)]
    entities.extend(
        PvnodeTotalEnergySensor(coordinator, entry, offset)
        for offset in range(coordinator.forecast_days)
    )
    entities.append(PvnodeSiteClearskyPowerSensor(coordinator, entry))
    entities.append(PvnodeSiteTemperatureSensor(coordinator, entry))
    entities.append(PvnodeSiteWeatherCodeSensor(coordinator, entry))
    return entities


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
    """Forecast energy total for one day (today, tomorrow, ...) of a roof surface."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR

    def __init__(
        self,
        coordinator: PvnodeDataUpdateCoordinator,
        entry: ConfigEntry,
        roof_key: str,
        day_offset: int,
    ) -> None:
        """Initialize the energy sensor for the given day offset (0=today)."""
        super().__init__(coordinator, entry, roof_key)
        self._day_offset = day_offset
        self._attr_unique_id = f"{entry.entry_id}_{roof_key}_energy_day{day_offset}"
        _apply_day_offset_translation(self, day_offset, "energy")

    @property
    def native_value(self) -> float | None:
        """Return the forecast energy total for the selected day."""
        roof = self._roof
        if not roof:
            return None
        target = dt_util.now().date() + timedelta(days=self._day_offset)
        return roof.forecast.energy_for(target)


class PvnodeClearskyPowerSensor(PvnodeRoofEntity):
    """Clear-sky reference power for a roof surface (pvnode API v1 only)."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
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


class PvnodeTotalEntity(CoordinatorEntity[PvnodeDataUpdateCoordinator], SensorEntity):
    """Base class for entities on the pvnode overview device (site-wide)."""

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
    """Total forecast energy for one day across all roof surfaces."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR

    def __init__(
        self,
        coordinator: PvnodeDataUpdateCoordinator,
        entry: ConfigEntry,
        day_offset: int,
    ) -> None:
        """Initialize the total energy sensor for the given day offset (0=today)."""
        super().__init__(coordinator, entry)
        self._day_offset = day_offset
        self._attr_unique_id = f"{entry.entry_id}_total_energy_day{day_offset}"
        _apply_day_offset_translation(self, day_offset, "total_energy")

    @property
    def native_value(self) -> float | None:
        """Return the summed forecast energy total of all roof surfaces."""
        if not self.coordinator.data:
            return None
        target = dt_util.now().date() + timedelta(days=self._day_offset)
        total = 0.0
        found = False
        for roof in self.coordinator.data.roofs.values():
            value = roof.forecast.energy_for(target)
            if value is not None:
                total += value
                found = True
        return total if found else None


class PvnodeSiteClearskyPowerSensor(PvnodeTotalEntity):
    """Site-wide clear-sky reference power.

    For API v1 this is the sum of every roof surface's own clear-sky power
    (each roof genuinely has its own). For API v2 this is the single
    site-wide value reported by pvnode - it can't be split per roof surface.
    """

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "total_clearsky_power"

    def __init__(
        self, coordinator: PvnodeDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the site-wide clear-sky power sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_total_clearsky_power"

    @property
    def native_value(self) -> float | None:
        """Return the site-wide clear-sky power for the current time slot."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.site.current_clearsky_power


class PvnodeSiteTemperatureSensor(PvnodeTotalEntity):
    """Site-wide forecast temperature (pvnode extension)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "temperature"

    def __init__(
        self, coordinator: PvnodeDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the site-wide temperature sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_temperature"

    @property
    def native_value(self) -> float | None:
        """Return the site-wide forecast temperature for the current time slot."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.site.current_temperature


class PvnodeSiteWeatherCodeSensor(PvnodeTotalEntity):
    """Site-wide WMO weather code (pvnode extension)."""

    _attr_translation_key = "weather_code"

    def __init__(
        self, coordinator: PvnodeDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the site-wide weather code sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_weather_code"

    @property
    def native_value(self) -> int | None:
        """Return the site-wide WMO weather code for the current time slot."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.site.current_weather_code
