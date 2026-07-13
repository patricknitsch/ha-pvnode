"""Config flow for the pvnode integration."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import slugify

from .api import (
    PvnodeApiClient,
    PvnodeAuthError,
    PvnodeConnectionError,
    PvnodeError,
    discover_string_indexes,
)
from .const import (
    API_VERSION_V1,
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
    DEFAULT_AZIMUTH,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_PEAK_POWER,
    DEFAULT_TIER,
    DEFAULT_TILT,
    DOMAIN,
    TIER_FREE,
    TIER_LIGHT,
    TIER_PLUS,
)

_LOGGER = logging.getLogger(__name__)

_API_VERSION_OPTIONS = [
    SelectOptionDict(
        value=API_VERSION_V2, label="API v2 (empfohlen, Site-ID im pvnode-Portal)"
    ),
    SelectOptionDict(
        value=API_VERSION_V1,
        label="API v1 (veraltet, wird zum 31.12.2026 abgeschaltet)",
    ),
]

_TIER_OPTIONS = [
    SelectOptionDict(value=TIER_FREE, label="Free – 1 Update/Tag, max. 2 Prognosetage"),
    SelectOptionDict(
        value=TIER_LIGHT, label="Light – stündliche Updates, max. 7 Prognosetage"
    ),
    SelectOptionDict(
        value=TIER_PLUS, label="Plus – Nowcasting alle 10 Min., max. 7 Prognosetage"
    ),
]


def _api_version_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=_API_VERSION_OPTIONS, mode=SelectSelectorMode.DROPDOWN
        )
    )


def _tier_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(options=_TIER_OPTIONS, mode=SelectSelectorMode.DROPDOWN)
    )


def _roof_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the schema for a single roof surface (pvnode API v1)."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_ROOF_NAME, default=defaults.get(CONF_ROOF_NAME, "Dach 1")
            ): str,
            vol.Required(
                CONF_ROOF_AZIMUTH,
                default=defaults.get(CONF_ROOF_AZIMUTH, DEFAULT_AZIMUTH),
            ): vol.All(vol.Coerce(float), vol.Range(min=-180, max=180)),
            vol.Required(
                CONF_ROOF_TILT, default=defaults.get(CONF_ROOF_TILT, DEFAULT_TILT)
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=90)),
            vol.Required(
                CONF_ROOF_PEAK_POWER,
                default=defaults.get(CONF_ROOF_PEAK_POWER, DEFAULT_PEAK_POWER),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1)),
            vol.Optional("add_another", default=False): bool,
        }
    )


def _general_schema(
    defaults: dict[str, Any] | None = None, *, include_extra_params: bool = True
) -> dict[Any, Any]:
    """Build the schema fields shared by config- and options-flow "general" steps."""
    defaults = defaults or {}
    schema: dict[Any, Any] = {
        vol.Required(
            CONF_TIER, default=defaults.get(CONF_TIER, DEFAULT_TIER)
        ): _tier_selector(),
        vol.Required(
            CONF_FORECAST_DAYS,
            default=defaults.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS),
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=7)),
    }
    if include_extra_params:
        schema[
            vol.Optional(CONF_EXTRA_PARAMS, default=defaults.get(CONF_EXTRA_PARAMS, ""))
        ] = str
    return schema


def _generate_roof_id(existing_ids: set[str], name: str) -> str:
    """Generate a stable, unique id for a roof surface based on its name."""
    base = slugify(name) or "roof"
    candidate = base
    counter = 2
    while candidate in existing_ids:
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


class PvnodeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for pvnode."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow state."""
        self._data: dict[str, Any] = {}
        self._roofs: list[dict[str, Any]] = []
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step: name, API version and API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data = {
                CONF_NAME: user_input[CONF_NAME],
                CONF_API_VERSION: user_input[CONF_API_VERSION],
                CONF_API_KEY: user_input[CONF_API_KEY],
            }
            if self._data[CONF_API_VERSION] == API_VERSION_V2:
                return await self.async_step_site()
            return await self.async_step_roof()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="pvnode"): str,
                vol.Required(
                    CONF_API_VERSION, default=API_VERSION_V2
                ): _api_version_selector(),
                vol.Required(CONF_API_KEY): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_site(self, user_input: dict[str, Any] | None = None):
        """Handle the pvnode API v2 Site-ID step (roof surfaces are auto-discovered)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            site_id = user_input[CONF_SITE_ID].strip()
            client = PvnodeApiClient(
                async_get_clientsession(self.hass), self._data[CONF_API_KEY]
            )
            try:
                raw = await client.async_get_v2_forecast(
                    site_id=site_id, forecast_days=1
                )
            except PvnodeAuthError:
                errors["base"] = "invalid_auth"
            except PvnodeConnectionError:
                errors["base"] = "cannot_connect"
            except PvnodeError:
                errors["base"] = "unknown"
            else:
                roof_count = len(discover_string_indexes(raw)) or 1
                _LOGGER.debug(
                    "pvnode site %s validated, %d roof surface(s) auto-discovered",
                    site_id,
                    roof_count,
                )

                self._data[CONF_SITE_ID] = site_id
                await self.async_set_unique_id(f"{API_VERSION_V2}_{site_id}")
                self._abort_if_unique_id_configured()

                options = {
                    CONF_TIER: user_input[CONF_TIER],
                    CONF_FORECAST_DAYS: user_input[CONF_FORECAST_DAYS],
                }
                return self.async_create_entry(
                    title=self._data[CONF_NAME], data=self._data, options=options
                )

        schema_dict: dict[Any, Any] = {vol.Required(CONF_SITE_ID): str}
        schema_dict.update(_general_schema(include_extra_params=False))
        return self.async_show_form(
            step_id="site", data_schema=vol.Schema(schema_dict), errors=errors
        )

    async def async_step_roof(self, user_input: dict[str, Any] | None = None):
        """Handle a single roof surface for pvnode API v1 (repeatable)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            add_another = user_input.pop("add_another")

            if not self._roofs:
                # Validate the API key once, using the first configured roof surface.
                client = PvnodeApiClient(
                    async_get_clientsession(self.hass), self._data[CONF_API_KEY]
                )
                try:
                    await client.async_get_v1_forecast(
                        latitude=self.hass.config.latitude,
                        longitude=self.hass.config.longitude,
                        tilt=user_input[CONF_ROOF_TILT],
                        azimuth=user_input[CONF_ROOF_AZIMUTH],
                        peak_power_kw=user_input[CONF_ROOF_PEAK_POWER],
                        forecast_days=1,
                    )
                except PvnodeAuthError:
                    errors["base"] = "invalid_auth"
                except PvnodeConnectionError:
                    errors["base"] = "cannot_connect"
                except PvnodeError:
                    errors["base"] = "unknown"

            if not errors:
                existing_ids = {roof[CONF_ROOF_ID] for roof in self._roofs}
                roof_id = _generate_roof_id(existing_ids, user_input[CONF_ROOF_NAME])
                self._roofs.append(
                    {
                        CONF_ROOF_ID: roof_id,
                        CONF_ROOF_NAME: user_input[CONF_ROOF_NAME],
                        CONF_ROOF_AZIMUTH: user_input[CONF_ROOF_AZIMUTH],
                        CONF_ROOF_TILT: user_input[CONF_ROOF_TILT],
                        CONF_ROOF_PEAK_POWER: user_input[CONF_ROOF_PEAK_POWER],
                    }
                )
                if add_another:
                    return await self.async_step_roof()
                return await self.async_step_general()

        default_name = f"Dach {len(self._roofs) + 1}"
        return self.async_show_form(
            step_id="roof",
            data_schema=_roof_schema({CONF_ROOF_NAME: default_name}),
            errors=errors,
        )

    async def async_step_general(self, user_input: dict[str, Any] | None = None):
        """Handle the final step for pvnode API v1: tier, forecast days, extras."""
        if user_input is not None:
            key_hash = hashlib.sha256(self._data[CONF_API_KEY].encode()).hexdigest()[
                :16
            ]
            await self.async_set_unique_id(f"{API_VERSION_V1}_{key_hash}")
            self._abort_if_unique_id_configured()

            options = {
                CONF_TIER: user_input[CONF_TIER],
                CONF_FORECAST_DAYS: user_input[CONF_FORECAST_DAYS],
                CONF_EXTRA_PARAMS: user_input.get(CONF_EXTRA_PARAMS, ""),
                CONF_ROOFS: self._roofs,
            }
            return self.async_create_entry(
                title=self._data[CONF_NAME], data=self._data, options=options
            )

        return self.async_show_form(
            step_id="general", data_schema=vol.Schema(_general_schema())
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        """Handle re-authentication when pvnode rejects the stored API key."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        """Ask for a new API key and verify it against the existing configuration."""
        errors: dict[str, str] = {}
        entry = self._reauth_entry
        assert entry is not None

        if user_input is not None:
            client = PvnodeApiClient(
                async_get_clientsession(self.hass), user_input[CONF_API_KEY]
            )
            try:
                if entry.data[CONF_API_VERSION] == API_VERSION_V2:
                    await client.async_get_v2_forecast(
                        site_id=entry.data[CONF_SITE_ID], forecast_days=1
                    )
                else:
                    roofs = entry.options.get(CONF_ROOFS, [])
                    if roofs:
                        roof = roofs[0]
                        await client.async_get_v1_forecast(
                            latitude=self.hass.config.latitude,
                            longitude=self.hass.config.longitude,
                            tilt=roof[CONF_ROOF_TILT],
                            azimuth=roof[CONF_ROOF_AZIMUTH],
                            peak_power_kw=roof[CONF_ROOF_PEAK_POWER],
                            forecast_days=1,
                        )
            except PvnodeAuthError:
                errors["base"] = "invalid_auth"
            except PvnodeConnectionError:
                errors["base"] = "cannot_connect"
            except PvnodeError:
                errors["base"] = "unknown"
            else:
                new_data = {**entry.data, CONF_API_KEY: user_input[CONF_API_KEY]}
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PvnodeOptionsFlowHandler:
        """Return the options flow handler for this integration."""
        return PvnodeOptionsFlowHandler()


class PvnodeOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle pvnode options: subscription tier, forecast days, roof surfaces."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Show the options menu."""
        menu_options = ["general"]
        if self.config_entry.data[CONF_API_VERSION] == API_VERSION_V1:
            menu_options += ["add_roof", "remove_roof"]
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_general(self, user_input: dict[str, Any] | None = None):
        """Edit the subscription tier, forecast days and extra API parameters."""
        if user_input is not None:
            updated = dict(self.config_entry.options)
            updated.update(user_input)
            return self.async_create_entry(title="", data=updated)

        include_extra_params = (
            self.config_entry.data[CONF_API_VERSION] == API_VERSION_V1
        )
        schema = vol.Schema(
            _general_schema(
                self.config_entry.options, include_extra_params=include_extra_params
            )
        )
        return self.async_show_form(step_id="general", data_schema=schema)

    async def async_step_add_roof(self, user_input: dict[str, Any] | None = None):
        """Add a roof surface (pvnode API v1 only)."""
        if user_input is not None:
            roofs = list(self.config_entry.options.get(CONF_ROOFS, []))
            existing_ids = {roof[CONF_ROOF_ID] for roof in roofs}
            roof_id = _generate_roof_id(existing_ids, user_input[CONF_ROOF_NAME])
            roofs.append(
                {
                    CONF_ROOF_ID: roof_id,
                    CONF_ROOF_NAME: user_input[CONF_ROOF_NAME],
                    CONF_ROOF_AZIMUTH: user_input[CONF_ROOF_AZIMUTH],
                    CONF_ROOF_TILT: user_input[CONF_ROOF_TILT],
                    CONF_ROOF_PEAK_POWER: user_input[CONF_ROOF_PEAK_POWER],
                }
            )
            updated = dict(self.config_entry.options)
            updated[CONF_ROOFS] = roofs
            return self.async_create_entry(title="", data=updated)

        roof_count = len(self.config_entry.options.get(CONF_ROOFS, []))
        schema = _roof_schema({CONF_ROOF_NAME: f"Dach {roof_count + 1}"})
        # The options-flow roof step never needs the "add another" loop toggle.
        schema = vol.Schema(
            {key: value for key, value in schema.schema.items() if key != "add_another"}
        )
        return self.async_show_form(step_id="add_roof", data_schema=schema)

    async def async_step_remove_roof(self, user_input: dict[str, Any] | None = None):
        """Remove one or more roof surfaces (pvnode API v1 only)."""
        roofs = list(self.config_entry.options.get(CONF_ROOFS, []))
        if not roofs:
            return self.async_abort(reason="no_roofs")

        if user_input is not None:
            keep = [
                roof
                for roof in roofs
                if roof[CONF_ROOF_ID] not in user_input[CONF_ROOFS]
            ]
            updated = dict(self.config_entry.options)
            updated[CONF_ROOFS] = keep
            return self.async_create_entry(title="", data=updated)

        schema = vol.Schema(
            {
                vol.Required(CONF_ROOFS): cv.multi_select(
                    {roof[CONF_ROOF_ID]: roof[CONF_ROOF_NAME] for roof in roofs}
                )
            }
        )
        return self.async_show_form(step_id="remove_roof", data_schema=schema)
