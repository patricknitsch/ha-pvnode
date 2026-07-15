"""Data update coordinator for the pvnode integration."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    PvnodeApiClient,
    PvnodeAuthError,
    PvnodeError,
    RoofForecast,
    discover_string_indexes,
    parse_v1_response,
    parse_v2_site_response,
    parse_v2_string_response,
)
from .const import (
    API_VERSION_V2,
    CONF_API_VERSION,
    CONF_EXTRA_PARAMS,
    CONF_FORECAST_DAYS,
    CONF_ROOF_AZIMUTH,
    CONF_ROOF_ID,
    CONF_ROOF_NAME,
    CONF_ROOF_PEAK_POWER,
    CONF_ROOF_TILT,
    CONF_ROOFS,
    CONF_SITE_ID,
    CONF_TIER,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_TIER,
    DOMAIN,
    SITE_ROOF_KEY,
    TIER_MAX_FORECAST_DAYS,
    TIER_UPDATE_INTERVAL,
    V1_SHUTDOWN_HARD_DATE,
)

_LOGGER = logging.getLogger(__name__)

type PvnodeConfigEntry = ConfigEntry["PvnodeDataUpdateCoordinator"]

# Matches the unique_id suffix of a day-offset energy sensor, e.g.
# "..._energy_day5" (roof) or "..._total_energy_day5" (overview device).
_ENERGY_DAY_OFFSET_RE = re.compile(r"_energy_day(\d+)$")


@dataclass
class PvnodeRoofData:
    """Forecast data plus display metadata for a single roof surface."""

    key: str
    name: str
    forecast: RoofForecast


@dataclass
class PvnodeData:
    """All data produced by one coordinator refresh.

    `site` only carries clear-sky power, temperature and weather code - these
    are location/site-wide properties, not meaningfully tied to a single roof
    surface, so they are only ever shown on the pvnode overview device.
    """

    roofs: dict[str, PvnodeRoofData] = field(default_factory=dict)
    site: RoofForecast = field(default_factory=RoofForecast)


class PvnodeDataUpdateCoordinator(DataUpdateCoordinator[PvnodeData]):
    """Fetch pvnode forecasts on a tier-appropriate schedule."""

    def __init__(self, hass: HomeAssistant, entry: PvnodeConfigEntry) -> None:
        """Initialize the coordinator for a config entry."""
        self.entry = entry
        self.api = PvnodeApiClient(
            async_get_clientsession(hass), entry.data[CONF_API_KEY]
        )
        self.known_roof_keys: set[str] = set()
        self._new_roof_listeners: list[Callable[[set[str]], None]] = []

        tier = entry.options.get(CONF_TIER, DEFAULT_TIER)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=TIER_UPDATE_INTERVAL.get(
                tier, TIER_UPDATE_INTERVAL[DEFAULT_TIER]
            ),
        )

    def add_new_roof_listener(
        self, listener: Callable[[set[str]], None]
    ) -> Callable[[], None]:
        """Register a callback invoked with newly discovered roof keys.

        Used by the sensor platform to add entities for roof surfaces that are
        auto-discovered later on (e.g. a new string appearing on a pvnode v2 site).
        """
        self._new_roof_listeners.append(listener)

        def _remove() -> None:
            self._new_roof_listeners.remove(listener)

        return _remove

    @property
    def forecast_days(self) -> int:
        """Return the forecast_days value clamped to the current tier's limit."""
        tier = self.entry.options.get(CONF_TIER, DEFAULT_TIER)
        max_days = TIER_MAX_FORECAST_DAYS.get(tier, 7)
        requested = self.entry.options.get(CONF_FORECAST_DAYS) or DEFAULT_FORECAST_DAYS
        return max(1, min(int(requested), max_days))

    async def _async_update_data(self) -> PvnodeData:
        """Fetch the latest forecast(s) from pvnode."""
        tier = self.entry.options.get(CONF_TIER, DEFAULT_TIER)
        new_interval = TIER_UPDATE_INTERVAL.get(
            tier, TIER_UPDATE_INTERVAL[DEFAULT_TIER]
        )
        if new_interval != self.update_interval:
            _LOGGER.debug("pvnode tier changed - poll interval now %s", new_interval)
            self.update_interval = new_interval

        try:
            if self.entry.data[CONF_API_VERSION] == API_VERSION_V2:
                data = await self._async_update_v2()
            else:
                data = await self._async_update_v1()
        except PvnodeAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except PvnodeError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        new_keys = set(data.roofs) - self.known_roof_keys
        if new_keys:
            self.known_roof_keys |= new_keys
            for listener in list(self._new_roof_listeners):
                listener(new_keys)

        await self._async_remove_stale_roofs(set(data.roofs))
        self._remove_stale_day_offset_entities()

        return data

    async def _async_remove_stale_roofs(self, valid_roof_keys: set[str]) -> None:
        """Remove devices (and their entities) for roof surfaces no longer present.

        Covers both a roof surface removed via the options flow (API v1) and a
        string that disappeared from the pvnode site (API v2), keeping the
        device registry in sync with what pvnode actually reports.
        """
        device_registry = dr.async_get(self.hass)
        valid_identifiers = {f"{self.entry.entry_id}_{key}" for key in valid_roof_keys}

        for device in dr.async_entries_for_config_entry(
            device_registry, self.entry.entry_id
        ):
            device_ids = {
                identifier[1]
                for identifier in device.identifiers
                if identifier[0] == DOMAIN
            }
            # Skip the overview/hub device itself (identifier == entry_id).
            if self.entry.entry_id in device_ids:
                continue
            if not device_ids & valid_identifiers:
                device_registry.async_update_device(
                    device.id, remove_config_entry_id=self.entry.entry_id
                )

    def _remove_stale_day_offset_entities(self) -> None:
        """Remove per-day energy sensors beyond the currently configured horizon.

        Roof surfaces and the overview device get one energy sensor per
        forecast day (0..forecast_days-1). If forecast_days is reduced (e.g.
        from 7 to 5), the sensors for the dropped days would otherwise remain
        in the entity registry forever, permanently "unavailable".
        """
        entity_registry = er.async_get(self.hass)
        max_offset = self.forecast_days

        for entity in list(
            er.async_entries_for_config_entry(entity_registry, self.entry.entry_id)
        ):
            match = _ENERGY_DAY_OFFSET_RE.search(entity.unique_id)
            if match and int(match.group(1)) >= max_offset:
                entity_registry.async_remove(entity.entity_id)

    async def _async_update_v1(self) -> PvnodeData:
        """Fetch a v1 forecast for every manually configured roof surface."""
        if dt_util.now().date() >= V1_SHUTDOWN_HARD_DATE:
            raise UpdateFailed(translation_domain=DOMAIN, translation_key="v1_shutdown")

        roofs_cfg = self.entry.options.get(CONF_ROOFS, [])
        if not roofs_cfg:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="no_roofs_configured"
            )

        latitude = self.hass.config.latitude
        longitude = self.hass.config.longitude
        forecast_days = self.forecast_days
        extra_params = self.entry.options.get(CONF_EXTRA_PARAMS)

        roofs: dict[str, PvnodeRoofData] = {}
        site_clearsky: dict[datetime, float] = {}
        site_temperature: dict[datetime, float] = {}
        site_weather_code: dict[datetime, int] = {}

        for position, roof in enumerate(roofs_cfg):
            raw = await self.api.async_get_v1_forecast(
                latitude=latitude,
                longitude=longitude,
                tilt=roof[CONF_ROOF_TILT],
                azimuth=roof[CONF_ROOF_AZIMUTH],
                peak_power_kw=roof[CONF_ROOF_PEAK_POWER],
                forecast_days=forecast_days,
                extra_params=extra_params,
            )
            forecast = parse_v1_response(raw)
            key = roof[CONF_ROOF_ID]
            roofs[key] = PvnodeRoofData(
                key=key, name=roof[CONF_ROOF_NAME], forecast=forecast
            )

            # Clear-sky power is roof-specific (depends on tilt/azimuth/power)
            # and adds up like regular power. Temperature/weather are location
            # properties - identical for every roof, so just take the first.
            for timestamp, value in forecast.watts_clearsky.items():
                site_clearsky[timestamp] = site_clearsky.get(timestamp, 0) + value
            if position == 0:
                site_temperature = forecast.temperature
                site_weather_code = forecast.weather_code

        site = RoofForecast(
            watts_clearsky=site_clearsky,
            temperature=site_temperature,
            weather_code=site_weather_code,
        )
        return PvnodeData(roofs=roofs, site=site)

    async def _async_update_v2(self) -> PvnodeData:
        """Fetch a v2 forecast for the whole site and split it per roof surface."""
        site_id = self.entry.data[CONF_SITE_ID]
        forecast_days = self.forecast_days
        extra_params = self.entry.options.get(CONF_EXTRA_PARAMS)

        raw = await self.api.async_get_v2_forecast(
            site_id=site_id, forecast_days=forecast_days, extra_params=extra_params
        )

        tz = dt_util.DEFAULT_TIME_ZONE
        string_indexes = discover_string_indexes(raw)
        site_forecast = parse_v2_site_response(raw, tz)

        roofs: dict[str, PvnodeRoofData] = {}

        if string_indexes:
            # Strings don't carry clear-sky/temperature/weather - those only
            # exist in the site-wide `values` array (see `site` below), so
            # per-roof forecasts here are power-only.
            for index in string_indexes:
                forecast = parse_v2_string_response(raw, index, tz)
                key = f"string_{index}"
                roofs[key] = PvnodeRoofData(
                    key=key, name=f"Dachfläche {index + 1}", forecast=forecast
                )
        else:
            # No per-string breakdown available (e.g. only one array on the
            # site) - fall back to a single roof surface with the site total.
            roofs[SITE_ROOF_KEY] = PvnodeRoofData(
                key=SITE_ROOF_KEY, name="Dachfläche", forecast=site_forecast
            )

        site = RoofForecast(
            watts_clearsky=site_forecast.watts_clearsky,
            temperature=site_forecast.temperature,
            weather_code=site_forecast.weather_code,
        )
        return PvnodeData(roofs=roofs, site=site)
