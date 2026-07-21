# ha-pvnode

[![hacs_badge][hacsbadge]][hacs] [![hainstall][hainstallbadge]][hainstall]

Home Assistant integration for the PV forecast service [pvnode](https://pvnode.com).

It follows the pvnode integration of the ioBroker adapter
[ioBroker.pvforecast](https://github.com/iobroker-community-adapters/ioBroker.pvforecast)
and supports both **API v1** and **API v2**.

## Prerequisites

- A [pvnode](https://pvnode.com) account with an API key.
- For API v2 (recommended), a site created at
  <https://pvnode.com/sites/new> with at least one configured plant.

## Installation

### Via HACS (recommended)

1. HACS → Integrations → "⋮" menu → "Custom repositories".
2. Add this repository (`patricknitsch/ha-pvnode`) as a repository of type
   "Integration".
3. Install "pvnode" and restart Home Assistant.

### Manual

1. Copy the `custom_components/pvnode` folder into the `custom_components`
   directory of your Home Assistant configuration.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration → "pvnode"**.

## Setup

When adding the integration, you first choose the **API version**:

### API v2 (recommended)

- Only the **API key** and the **Site ID** from the pvnode portal (created at
  <https://pvnode.com/sites/new>) are required.
- The **roof surfaces** (orientation, tilt, power) are already stored in the
  pvnode portal and are **fetched automatically** - every configured plant
  shows up as its own roof surface in Home Assistant, with no further local
  configuration needed.
- New roof surfaces added in the portal are automatically created as new
  devices in Home Assistant on one of the following refreshes.

### API v1 (deprecated)

pvnode is shutting down API v1 on **2026-12-31**; from 2027-01-01 onward this
integration will no longer return data over v1. Use API v2 for new setups.

- For each roof surface, **name, azimuth, tilt and peak power** are entered
  manually (the setup dialog can be repeated to add multiple roof surfaces).
- Azimuth convention matches forecast.solar: `-180/180=North, -90=East,
  0=South, 90=West`.
- The location is taken from the Home Assistant configuration.

### Shared settings

- **Subscription tier** (Free/Light/Plus) - automatically determines the
  polling interval (Free: 24 h, Light: 60 min, Plus: 10 min) and the maximum
  forecast horizon (Free: 2 days, Light/Plus: 7 days).
- **Number of forecast days** - clamped to whatever the selected tier allows.
- Go to **Settings → Configure integration** to change the subscription tier,
  number of forecast days and (for API v1) roof surfaces at any time.
- Use the "⋮" menu on the integration entry → **Reconfigure** to replace the
  API key (and, for API v2, the Site ID) without deleting and re-adding the
  entry.

## Entities

Every roof surface is created as its **own device** (never merged into a
single combined entity), with the following sensors:

- Power forecast (W, current time slot, including a time series in the
  `forecast` attribute)
- Energy forecast per configured forecast day (today, tomorrow, ... - based
  on the configured number of forecast days)
- Clear-sky power **only for API v1**, since each roof surface is fetched
  individually there and therefore has a genuine value of its own

The integration also always creates a **"Summary" overview device** (named
"Gesamt" if Home Assistant's language is set to German) with:

- Total power and total energy forecast (sum of all roof surfaces, also
  including a `forecast` attribute)
- Total clear-sky power (for API v1, the sum of all roof surfaces; for API
  v2, the value pvnode reports for the whole plant)
- Temperature forecast and weather code

Each of these sensors carries its own `forecast` attribute: a list with one
object per 15-minute time slot (daylight hours only, across all configured
forecast days), containing only `datetime` and the one metric matching that
sensor (`watts`, `watts_clearsky`, `temperature` or `weather_code`) -
deliberately not merged into one large combined attribute, so each individual
attribute stays small. For API v2 roof surfaces/strings there is only
`watts`, since pvnode doesn't report clear-sky power, temperature or weather
code per string there - at the overview device, all four metrics are
available for **both** API versions, since they're derived from the summed
roof data and the site-wide values respectively.

All `forecast` attributes are deliberately **excluded** from being stored by
the recorder in the history database (`_unrecorded_attributes`), since they
can grow to several KB depending on the number of forecast days. They are
still useful for analysis outside Home Assistant (e.g. InfluxDB), provided
the receiving integration itself reacts to state changes and reads out the
attribute.

Temperature, weather code and (for API v2) clear-sky power are
location/plant properties that pvnode doesn't report per roof surface/string
- they therefore only appear on the overview device, not on the individual
roof surfaces.

## Energy Dashboard

The integration implements the same interface as forecast.solar and Solcast,
so it can be selected in the Energy dashboard as a **solar production
forecast**:

1. **Settings → Dashboards → Energy** → edit solar production.
2. Under "Solar production forecast", select **pvnode**.

The forecast contains the combined power of **all roof surfaces** of this
pvnode account (not per roof surface, the same way forecast.solar and
Solcast each provide one combined forecast per config entry). Multiple
forecast sources can be added together for a single solar installation in
the Energy dashboard anyway, e.g. if part of the installation should be
forecast by a different source.

## Use Cases

- **Energy Dashboard**: compare the solar forecast against actual production
  (see above).
- **Automations**: e.g. start a consumer (EV charger, water heater) once
  `sensor.summary_total_current_power_forecast` exceeds a threshold, or plan a battery
  storage charge state based on tomorrow's energy forecast.
- **Shading/orientation comparison**: with multiple roof surfaces, compare
  the individual power forecasts, e.g. to spot a shaded surface.

## Known Limitations

- **API v1 is being shut down** (2026-12-31, see above) - always use API v2
  for new setups.
- **Clear-sky power, temperature and weather code**: pvnode only reports
  these for the whole plant under API v2, not per roof surface/string -
  these values therefore only appear on the overview device (see
  "Entities").
- **No discovery**: pvnode is a pure cloud service with no local network
  discovery (no mDNS/SSDP/DHCP) - the integration must be set up manually.
- **Subscription limits aren't enforced server-side**: polling intervals are
  based on the selected tier (Free/Light/Plus); choosing a tier that's too
  low for your actual pvnode subscription can still lead to rate-limit
  errors from pvnode.

## Troubleshooting

- **New features (e.g. Energy dashboard, new sensors) don't show up after an
  update**: **fully restart** Home Assistant after every update of this
  integration (not just "reload integration") - some extensions (e.g.
  `energy.py`) are only picked up on a full start.
- **pvnode doesn't show up as a forecast source in the Energy dashboard**:
  make sure a full restart happened after installation. To check: browser
  developer tools console → `hass.callWS({type:"energy/info"})` should list
  `"pvnode"` under `solar_forecast_domains`.
- **Error message "pvnode rejected the API key"**: check the API key in the
  pvnode portal; the integration will then automatically request
  re-authentication (a reauth notification under Settings → Devices &
  Services).
- **Diagnostics**: use the three-dot menu on the integration entry →
  "Download diagnostics" to export the internal state (number of loaded
  time-series values per roof surface, last update, configuration without
  the API key/Site ID) for bug reports.

## Uninstallation

1. **Settings → Devices & Services → pvnode** → "⋮" menu → **Delete**.
2. If installed manually: remove the `custom_components/pvnode` folder from
   your Home Assistant configuration.
3. If installed via HACS: also uninstall pvnode from HACS.
4. Restart Home Assistant.

All devices, entities and repair issues created by the integration are
automatically removed when it's deleted.

## License

MIT, see [LICENSE](LICENSE).

[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge&logo=homeassistantcommunitystore&logoColor=ccc
[hainstall]: https://my.home-assistant.io/redirect/config_flow_start/?domain=pvnode
[hainstallbadge]: https://img.shields.io/badge/dynamic/json?style=for-the-badge&logo=home-assistant&logoColor=ccc&label=usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.pvnode.total
