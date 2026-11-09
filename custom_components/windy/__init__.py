"""The Windy integration."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    AIR_QUALITY_OFF,
    AIR_QUALITY_PARAMETERS,
    CONF_AIR_QUALITY_MODEL,
    CONF_MAP_KEY,
    CONF_MODEL,
    CONF_POINT_INTERVAL,
    CONF_POINT_KEY,
    CONF_WEBCAM_COUNT,
    CONF_WEBCAM_IDS,
    CONF_WEBCAM_INTERVAL,
    CONF_WEBCAM_RADIUS,
    CONF_WEBCAMS_KEY,
    DEFAULT_AIR_QUALITY_MODEL,
    DEFAULT_MODEL,
    DEFAULT_POINT_INTERVAL,
    DEFAULT_WEBCAM_COUNT,
    DEFAULT_WEBCAM_INTERVAL,
    DEFAULT_WEBCAM_RADIUS,
    DOMAIN,
    MODEL_PARAMETERS,
    STATIC_URL,
    VERSION,
)
from .coordinator import (
    PointForecastCoordinator,
    WebcamCoordinator,
    WindyConfigEntry,
    WindyRuntimeData,
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.CAMERA, Platform.SENSOR, Platform.WEATHER]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the dashboard cards and the API they use to get the map key."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                STATIC_URL, str(Path(__file__).parent / "frontend"), False
            )
        ]
    )
    add_extra_js_url(hass, f"{STATIC_URL}/windy-cards.js?v={VERSION}")
    websocket_api.async_register_command(hass, websocket_map_config)
    return True


@websocket_api.websocket_command({"type": "windy/map_config"})
@callback
def websocket_map_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return map settings to a logged-in dashboard.

    The Map Forecast library runs in the browser, so its key must reach the
    browser. This keeps it out of dashboard YAML and static files.
    """
    connection.send_result(
        msg["id"],
        [
            {
                "title": entry.title,
                "latitude": entry.data[CONF_LATITUDE],
                "longitude": entry.data[CONF_LONGITUDE],
                "key": entry.data[CONF_MAP_KEY],
            }
            for entry in hass.config_entries.async_loaded_entries(DOMAIN)
            if entry.data.get(CONF_MAP_KEY)
        ],
    )


def parse_webcam_ids(value: str | None) -> list[int]:
    """Parse a comma-separated list of webcam IDs."""
    return [int(part) for part in (value or "").replace(" ", "").split(",") if part]


async def async_setup_entry(hass: HomeAssistant, entry: WindyConfigEntry) -> bool:
    """Set up one Windy location."""
    options = entry.options
    runtime = WindyRuntimeData()
    point_interval = timedelta(
        minutes=options.get(CONF_POINT_INTERVAL, DEFAULT_POINT_INTERVAL)
    )

    if point_key := entry.data.get(CONF_POINT_KEY):
        model = options.get(CONF_MODEL, DEFAULT_MODEL)
        runtime.weather = PointForecastCoordinator(
            hass, entry, point_key, model, MODEL_PARAMETERS[model], point_interval
        )
        await runtime.weather.async_config_entry_first_refresh()

        air_model = options.get(CONF_AIR_QUALITY_MODEL, DEFAULT_AIR_QUALITY_MODEL)
        if air_model != AIR_QUALITY_OFF:
            runtime.air_quality = PointForecastCoordinator(
                hass,
                entry,
                point_key,
                air_model,
                AIR_QUALITY_PARAMETERS,
                point_interval,
                allow_empty=True,
            )
            await runtime.air_quality.async_config_entry_first_refresh()

    if webcams_key := entry.data.get(CONF_WEBCAMS_KEY):
        runtime.webcams = WebcamCoordinator(
            hass,
            entry,
            webcams_key,
            int(options.get(CONF_WEBCAM_RADIUS, DEFAULT_WEBCAM_RADIUS)),
            int(options.get(CONF_WEBCAM_COUNT, DEFAULT_WEBCAM_COUNT)),
            parse_webcam_ids(options.get(CONF_WEBCAM_IDS)),
            timedelta(
                minutes=options.get(CONF_WEBCAM_INTERVAL, DEFAULT_WEBCAM_INTERVAL)
            ),
        )
        await runtime.webcams.async_config_entry_first_refresh()

    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WindyConfigEntry) -> bool:
    """Unload a Windy location."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
