"""Constants for the pvnode integration."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "pvnode"
MANUFACTURER: Final = "pvnode"

PLATFORMS: Final = [Platform.SENSOR]

# Config entry (immutable connection data)
CONF_API_VERSION: Final = "api_version"
CONF_SITE_ID: Final = "site_id"

# Options (user adjustable without recreating the entry)
CONF_TIER: Final = "tier"
CONF_FORECAST_DAYS: Final = "forecast_days"
CONF_EXTRA_PARAMS: Final = "extra_params"
CONF_ROOFS: Final = "roofs"

# Fields of a single roof surface entry (API v1 only)
CONF_ROOF_ID: Final = "id"
CONF_ROOF_NAME: Final = "name"
CONF_ROOF_AZIMUTH: Final = "azimuth"
CONF_ROOF_TILT: Final = "tilt"
CONF_ROOF_PEAK_POWER: Final = "peak_power"

API_VERSION_V1: Final = "v1"
API_VERSION_V2: Final = "v2"

TIER_FREE: Final = "free"
TIER_LIGHT: Final = "light"
TIER_PLUS: Final = "plus"
TIERS: Final = [TIER_FREE, TIER_LIGHT, TIER_PLUS]
DEFAULT_TIER: Final = TIER_FREE

# Poll interval per subscription tier - mirrors the ioBroker.pvforecast adapter,
# which auto-manages the interval per pvnode plan instead of exposing it directly.
TIER_UPDATE_INTERVAL: Final[dict[str, timedelta]] = {
    TIER_FREE: timedelta(hours=24),
    TIER_LIGHT: timedelta(hours=1),
    TIER_PLUS: timedelta(minutes=10),
}

# Free tier only allows today + tomorrow; Light/Plus allow up to 7 days.
TIER_MAX_FORECAST_DAYS: Final[dict[str, int]] = {
    TIER_FREE: 2,
    TIER_LIGHT: 7,
    TIER_PLUS: 7,
}
DEFAULT_FORECAST_DAYS: Final = 7

DEFAULT_AZIMUTH: Final = 0.0
DEFAULT_TILT: Final = 45.0
DEFAULT_PEAK_POWER: Final = 9.9

API_V1_BASE_URL: Final = "https://api.pvnode.com/v1/forecast/"
API_V2_BASE_URL: Final = "https://api.pvnode.com/v2/forecast/"

# pvnode has announced the shutdown of API v1.
V1_SHUTDOWN_WARN_DATE: Final = date(2026, 12, 31)
V1_SHUTDOWN_HARD_DATE: Final = date(2027, 1, 1)

# Matches the daylight window used by the ioBroker.pvforecast adapter's converters.
DAYLIGHT_START_HOUR: Final = 5
DAYLIGHT_END_HOUR: Final = 22

SITE_ROOF_KEY: Final = "site"
