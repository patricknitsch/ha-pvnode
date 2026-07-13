"""Data update coordinator for the pvnode integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
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


@dataclass
class PvnodeRoofData:
    """Forecast data plus display metadata for a single roof surface."""

    key: str
    name: str
    forecast: RoofForecast


@dataclass
class PvnodeData:
    """All data produced by one coordinator refresh."""

    roofs: dict[str, PvnodeRoofData] = field(default_factory=dict)


class PvnodeDataUpdateCoordinator(DataUpdateCoordinator[PvnodeData]):
    """Fetch pvnode forecasts on a tier-appropriate schedule."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
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
            raise ConfigEntryAuthFailed(str(err)) from err
        except PvnodeError as err:
            raise UpdateFailed(str(err)) from err

        new_keys = set(data.roofs) - self.known_roof_keys
        if new_keys:
            self.known_roof_keys |= new_keys
            for listener in list(self._new_roof_listeners):
                listener(new_keys)

        return data

    async def _async_update_v1(self) -> PvnodeData:
        """Fetch a v1 forecast for every manually configured roof surface."""
        if dt_util.now().date() >= V1_SHUTDOWN_HARD_DATE:
            raise UpdateFailed(
                "pvnode API v1 has been shut down. Please switch to API v2 "
                "(pvnode Site-ID) in the integration options."
            )

        roofs_cfg = self.entry.options.get(CONF_ROOFS, [])
        if not roofs_cfg:
            raise UpdateFailed("No roof surfaces configured for pvnode API v1")

        latitude = self.hass.config.latitude
        longitude = self.hass.config.longitude
        forecast_days = self.forecast_days
        extra_params = self.entry.options.get(CONF_EXTRA_PARAMS)

        roofs: dict[str, PvnodeRoofData] = {}
        for roof in roofs_cfg:
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

        return PvnodeData(roofs=roofs)

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
            for position, index in enumerate(string_indexes):
                forecast = parse_v2_string_response(raw, index, tz)
                if position == 0:
                    # Clear-sky/temperature/weather are site-wide, not per-string.
                    # Surface them once on the first discovered roof surface only,
                    # to avoid multiplying the site total in HA statistics.
                    forecast.watts_clearsky = site_forecast.watts_clearsky
                    forecast.temperature = site_forecast.temperature
                    forecast.weather_code = site_forecast.weather_code
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

        return PvnodeData(roofs=roofs)
