"""API client and response parsing for the pvnode forecast service."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from datetime import tzinfo as TzInfo
from typing import Any

import aiohttp
from homeassistant.util import dt as dt_util

from .const import (
    API_V1_BASE_URL,
    API_V2_BASE_URL,
    DAYLIGHT_END_HOUR,
    DAYLIGHT_START_HOUR,
)

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=30)


class PvnodeError(Exception):
    """Base error for the pvnode API client."""


class PvnodeAuthError(PvnodeError):
    """Raised when the API key (and/or site) is rejected by pvnode."""


class PvnodeConnectionError(PvnodeError):
    """Raised when the pvnode API cannot be reached."""


class PvnodeApiError(PvnodeError):
    """Raised for any other non-2xx pvnode API response."""

    def __init__(self, status: int, message: str) -> None:
        """Store the HTTP status alongside the error message."""
        super().__init__(message)
        self.status = status


def azimuth_to_orientation(azimuth: float) -> float:
    """Convert forecast.solar style azimuth to pvnode's orientation.

    forecast.solar / ioBroker.pvforecast convention: -180/180=North, -90=East,
    0=South, 90=West. pvnode convention: 0=North, 90=East, 180=South, 270=West.
    """
    orientation = (azimuth + 180) % 360
    if orientation < 0:
        orientation += 360
    return orientation


@dataclass
class RoofForecast:
    """Parsed forecast data for a single roof surface (or an entire site)."""

    watts: dict[datetime, float] = field(default_factory=dict)
    watt_hours_period: dict[datetime, float] = field(default_factory=dict)
    watts_clearsky: dict[datetime, float] = field(default_factory=dict)
    temperature: dict[datetime, float] = field(default_factory=dict)
    weather_code: dict[datetime, int] = field(default_factory=dict)
    energy_by_day: dict[date, float] = field(default_factory=dict)

    @property
    def current_power(self) -> float | None:
        """Return the forecast power for the most recent past/current time slot."""
        return _nearest_past(self.watts)

    @property
    def current_clearsky_power(self) -> float | None:
        """Return the clear-sky reference power for the current time slot."""
        return _nearest_past(self.watts_clearsky)

    @property
    def current_temperature(self) -> float | None:
        """Return the forecast temperature for the current time slot."""
        return _nearest_past(self.temperature)

    @property
    def current_weather_code(self) -> int | None:
        """Return the WMO weather code for the current time slot."""
        return _nearest_past(self.weather_code)

    def energy_for(self, day: date) -> float | None:
        """Return the total forecast energy (Wh) for the given day."""
        return self.energy_by_day.get(day)


def _nearest_past(mapping: dict[datetime, Any]) -> Any | None:
    """Return the value for the latest timestamp that is not in the future."""
    if not mapping:
        return None
    now = dt_util.now()
    candidates = [ts for ts in mapping if ts <= now]
    if not candidates:
        return None
    return mapping[max(candidates)]


def _parse_utc(timestamp: str) -> datetime:
    """Parse a pvnode v1 `dtm` timestamp, which is UTC without an explicit offset."""
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.UTC)
    return dt_util.as_local(parsed)


def _parse_local(timestamp: str, tz: TzInfo) -> datetime:
    """Parse a pvnode v2 `timestamp`, which is already local time without an offset."""
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def _bucket_by_day(
    entries: list[tuple[datetime, dict[str, Any]]],
    *,
    power_key: str,
    clearsky_key: str | None,
) -> RoofForecast:
    """Turn a list of (timestamp, raw-entry) tuples into a RoofForecast."""
    forecast = RoofForecast()
    by_day: dict[date, float] = {}

    for timestamp, entry in sorted(entries, key=lambda item: item[0]):
        if not (DAYLIGHT_START_HOUR <= timestamp.hour < DAYLIGHT_END_HOUR):
            continue

        power = round(float(entry.get(power_key) or 0))
        forecast.watts[timestamp] = power

        # 15-minute resolution: period energy = power (W) * 0.25 h
        period_energy = round(power * 0.25)
        forecast.watt_hours_period[timestamp] = period_energy
        by_day[timestamp.date()] = by_day.get(timestamp.date(), 0) + period_energy

        if clearsky_key and entry.get(clearsky_key) is not None:
            forecast.watts_clearsky[timestamp] = round(float(entry[clearsky_key]))
        if entry.get("temp") is not None:
            forecast.temperature[timestamp] = round(float(entry["temp"]), 1)
        if entry.get("weather_code") is not None:
            forecast.weather_code[timestamp] = int(entry["weather_code"])

    forecast.energy_by_day = by_day
    return forecast


def parse_v1_response(data: dict[str, Any]) -> RoofForecast:
    """Parse a pvnode API v1 `/v1/forecast/` response into a RoofForecast."""
    values = data.get("values") or []
    entries = [
        (_parse_utc(entry["dtm"]), entry) for entry in values if entry.get("dtm")
    ]
    return _bucket_by_day(
        entries, power_key="pv_watts", clearsky_key="pv_watts_clearsky"
    )


def parse_v2_site_response(data: dict[str, Any], tz: TzInfo) -> RoofForecast:
    """Parse the site-wide `values` array of a pvnode API v2 response."""
    values = data.get("values") or []
    entries = [
        (_parse_local(entry["timestamp"], tz), entry)
        for entry in values
        if entry.get("timestamp")
    ]
    return _bucket_by_day(
        entries, power_key="pv_power", clearsky_key="pv_power_clearsky"
    )


def parse_v2_string_response(
    data: dict[str, Any], string_index: int, tz: TzInfo
) -> RoofForecast:
    """Parse a single string's entries from a pvnode API v2 `strings` array.

    Strings don't carry clear-sky/temperature/weather data - that only exists in
    the site-wide `values` array (see `parse_v2_site_response`).
    """
    strings = data.get("strings") or []
    entries = [
        (_parse_local(entry["timestamp"], tz), entry)
        for entry in strings
        if entry.get("string_index") == string_index and entry.get("timestamp")
    ]
    return _bucket_by_day(entries, power_key="pv_power", clearsky_key=None)


def discover_string_indexes(data: dict[str, Any]) -> list[int]:
    """Return the sorted, distinct string_index values found in a v2 response.

    This is how roof surfaces ("Dachflächen") are auto-discovered for API v2:
    each configured plant/array on the pvnode portal shows up as its own
    string_index in the response, with no local configuration required.
    """
    strings = data.get("strings") or []
    return sorted(
        {entry["string_index"] for entry in strings if "string_index" in entry}
    )


def _merge_extra_params(params: dict[str, Any], extra_params: str | None) -> None:
    """Merge a raw `key=value&key2=value2` string into the params dict."""
    if not extra_params:
        return
    for part in extra_params.split("&"):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip()
        if key:
            params[key] = value.strip()


class PvnodeApiClient:
    """Thin async HTTP client for the pvnode forecast API (v1 and v2)."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        """Initialize the client with a shared aiohttp session and API key."""
        self._session = session
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """Perform a GET request and return the decoded JSON body."""
        _LOGGER.debug("GET %s params=%s", url, params)
        try:
            async with self._session.get(
                url, params=params, headers=self._headers, timeout=_TIMEOUT
            ) as response:
                if response.status in (401, 403):
                    raise PvnodeAuthError(
                        f"pvnode rejected the API key (HTTP {response.status})"
                    )
                if response.status >= 400:
                    body = await response.text()
                    raise PvnodeApiError(
                        response.status, f"HTTP {response.status}: {body[:200]}"
                    )
                return await response.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise PvnodeConnectionError(
                "Timeout while contacting the pvnode API"
            ) from err
        except aiohttp.ClientError as err:
            raise PvnodeConnectionError(
                f"Error contacting the pvnode API: {err}"
            ) from err

    async def async_get_v1_forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        tilt: float,
        azimuth: float,
        peak_power_kw: float,
        forecast_days: int,
        extra_params: str | None = None,
    ) -> dict[str, Any]:
        """Fetch a v1 forecast for a single roof surface."""
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "slope": tilt,
            "orientation": azimuth_to_orientation(azimuth),
            "pv_power_kw": peak_power_kw,
            "required_data": "pv_watts,temp,weather_code",
            "clearsky_data": "true",
            "past_days": 0,
            "forecast_days": forecast_days,
        }
        _merge_extra_params(params, extra_params)
        return await self._get(API_V1_BASE_URL, params)

    async def async_get_v2_forecast(
        self,
        *,
        site_id: str,
        forecast_days: int,
        extra_params: str | None = None,
    ) -> dict[str, Any]:
        """Fetch a v2 forecast for an entire site, including per-string data."""
        params: dict[str, Any] = {
            "forecast_days": forecast_days,
            "include": ["clearsky", "default", "weather", "strings"],
            "past_days": 0,
        }
        _merge_extra_params(params, extra_params)
        return await self._get(f"{API_V2_BASE_URL}{site_id}", params)
