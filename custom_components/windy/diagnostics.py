"""Diagnostics for the Windy integration, with API keys redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant

from .const import CONF_MAP_KEY, CONF_POINT_KEY, CONF_WEBCAMS_KEY
from .coordinator import WindyConfigEntry

TO_REDACT = {
    CONF_POINT_KEY,
    CONF_MAP_KEY,
    CONF_WEBCAMS_KEY,
    CONF_LATITUDE,
    CONF_LONGITUDE,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WindyConfigEntry
) -> dict[str, Any]:
    """Return settings and data availability, without keys or location."""
    runtime = entry.runtime_data

    def describe(coordinator) -> dict[str, Any] | None:
        if coordinator is None:
            return None
        data = coordinator.data
        return {
            "model": coordinator.model,
            "last_update_success": coordinator.last_update_success,
            "steps": len(data.times),
            "first_step": data.times[0].isoformat() if data.times else None,
            "last_step": data.times[-1].isoformat() if data.times else None,
            "units": data.units,
            "series_with_values": sorted(k for k in data.series if data.has(k)),
        }

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "weather": describe(runtime.weather),
        "air_quality": describe(runtime.air_quality),
        "webcams": (
            sorted(runtime.webcams.data) if runtime.webcams else None
        ),
    }
