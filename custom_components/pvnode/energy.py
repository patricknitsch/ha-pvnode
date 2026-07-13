"""Energy platform for the pvnode integration.

Implements Home Assistant's solar forecast contract (the same one used by
the built-in forecast.solar integration and by Solcast) so a pvnode config
entry can be picked as a "Forecast production" source for a solar panel in
the Energy dashboard.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import PvnodeDataUpdateCoordinator


async def async_get_solar_forecast(
    hass: HomeAssistant, config_entry_id: str
) -> dict[str, dict[str, float | int]] | None:
    """Get the combined solar forecast (all roof surfaces) for a config entry."""
    coordinator: PvnodeDataUpdateCoordinator | None = hass.data.get(DOMAIN, {}).get(
        config_entry_id
    )
    if coordinator is None or not coordinator.data:
        return None

    wh_hours: dict[str, float] = {}
    for roof in coordinator.data.roofs.values():
        for timestamp, value in roof.forecast.watt_hours_period.items():
            key = timestamp.isoformat()
            wh_hours[key] = wh_hours.get(key, 0) + value

    return {"wh_hours": wh_hours}
