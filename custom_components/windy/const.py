"""Constants for the Windy integration."""

from __future__ import annotations

DOMAIN = "windy"
VERSION = "0.2.0"
ATTRIBUTION = "Data provided by Windy.com"
WEBCAM_ATTRIBUTION = "Webcams provided by windy.com"

CONF_POINT_KEY = "point_api_key"
CONF_MAP_KEY = "map_api_key"
CONF_WEBCAMS_KEY = "webcams_api_key"

CONF_MODEL = "model"
CONF_AIR_QUALITY_MODEL = "air_quality_model"
CONF_POINT_INTERVAL = "point_interval_minutes"
CONF_WEBCAM_INTERVAL = "webcam_interval_minutes"
CONF_WEBCAM_RADIUS = "webcam_radius_km"
CONF_WEBCAM_COUNT = "webcam_count"
CONF_WEBCAM_IDS = "webcam_ids"

DEFAULT_MODEL = "gfs"
AIR_QUALITY_OFF = "off"
DEFAULT_AIR_QUALITY_MODEL = "cams"
DEFAULT_POINT_INTERVAL = 30
# Free-tier webcam image URLs expire after 10 minutes.
DEFAULT_WEBCAM_INTERVAL = 5
DEFAULT_WEBCAM_RADIUS = 50
DEFAULT_WEBCAM_COUNT = 3
MAX_WEBCAM_RADIUS = 250
MAX_WEBCAMS = 50

STATIC_URL = "/windy_static"

_BASE = (
    "temp",
    "dewpoint",
    "precip",
    "wind",
    "windGust",
    "cape",
    "lclouds",
    "mclouds",
    "hclouds",
    "rh",
    "pressure",
)
_SNOW_PTYPE = (*_BASE, "snowPrecip", "ptype")

# From the support matrix in the Point Forecast API documentation.
MODEL_PARAMETERS: dict[str, tuple[str, ...]] = {
    "gfs": _SNOW_PTYPE,
    "icon": (*_SNOW_PTYPE, "weatherWarnings"),
    "iconD2": (*_SNOW_PTYPE, "cbase", "visibility", "weatherWarnings"),
    "iconEu": (*_SNOW_PTYPE, "cbase", "visibility", "weatherWarnings"),
    "arome": _SNOW_PTYPE,
    "aromeAntilles": _SNOW_PTYPE,
    "aromeFrance": _SNOW_PTYPE,
    "aromeReunion": _SNOW_PTYPE,
    "namConus": _SNOW_PTYPE,
    "namHawaii": _SNOW_PTYPE,
    "namAlaska": _SNOW_PTYPE,
    "hrrrConus": (*_BASE, "snowPrecip"),
    "hrrrAlaska": (*_BASE, "snowPrecip"),
    "canHrdps": _BASE,
}

MODEL_LABELS: dict[str, str] = {
    "gfs": "GFS (global)",
    "icon": "ICON (global)",
    "iconEu": "ICON-EU (Europe)",
    "iconD2": "ICON-D2 (Germany)",
    "arome": "AROME (France and nearby)",
    "aromeFrance": "AROME France",
    "aromeAntilles": "AROME Antilles",
    "aromeReunion": "AROME Réunion",
    "namConus": "NAM (contiguous USA)",
    "namHawaii": "NAM (Hawaii)",
    "namAlaska": "NAM (Alaska)",
    "hrrrConus": "HRRR (contiguous USA)",
    "hrrrAlaska": "HRRR (Alaska)",
    "canHrdps": "HRDPS (Canada)",
}

AIR_QUALITY_LABELS: dict[str, str] = {
    AIR_QUALITY_OFF: "Off",
    "cams": "CAMS (global)",
    "camsEu": "CAMS (Europe)",
}
AIR_QUALITY_PARAMETERS = (
    "aqi",
    "so2sm",
    "dustsm",
    "cosc",
    "go3",
    "no2",
    "pm10",
    "pm2p5",
)
