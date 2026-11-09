"""Data update coordinators for the Windy integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import math
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    WindyAuthError,
    WindyError,
    WindyNoData,
    fetch_point_forecast,
    fetch_webcams,
)
from .const import MAX_WEBCAMS
from .forecast import PointForecast, parse_point_forecast

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class WindyRuntimeData:
    """Coordinators for one configured location."""

    weather: PointForecastCoordinator | None = None
    air_quality: PointForecastCoordinator | None = None
    webcams: WebcamCoordinator | None = None


type WindyConfigEntry = ConfigEntry[WindyRuntimeData]


class PointForecastCoordinator(DataUpdateCoordinator[PointForecast]):
    """Fetch a Point Forecast model for one location."""

    config_entry: WindyConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: WindyConfigEntry,
        key: str,
        model: str,
        parameters: tuple[str, ...],
        interval: timedelta,
        *,
        allow_empty: bool = False,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{entry.title} {model}",
            update_interval=interval,
        )
        self.model = model
        self._key = key
        self._parameters = parameters
        self._allow_empty = allow_empty

    async def _async_update_data(self) -> PointForecast:
        """Fetch and parse the forecast."""
        try:
            raw = await fetch_point_forecast(
                async_get_clientsession(self.hass),
                self._key,
                self.config_entry.data[CONF_LATITUDE],
                self.config_entry.data[CONF_LONGITUDE],
                self.model,
                self._parameters,
            )
            return parse_point_forecast(raw)
        except WindyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WindyNoData as err:
            if self._allow_empty:
                return PointForecast()
            raise UpdateFailed(str(err)) from err
        except WindyError as err:
            raise UpdateFailed(str(err)) from err


@dataclass(slots=True)
class Webcam:
    """A webcam with its current, short-lived image URL."""

    webcam_id: int
    title: str
    status: str
    image_url: str | None
    latitude: float | None
    longitude: float | None
    city: str | None
    region: str | None
    country: str | None
    distance_km: float | None
    detail_url: str | None
    day_timelapse_url: str | None
    live_url: str | None
    last_updated_on: datetime | None


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance between two points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((phi2 - phi1) / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(a))


def _image_url(images: dict[str, Any]) -> str | None:
    """Return the best image URL; some webcams omit some sizes or sets."""
    for group in ("current", "daylight"):
        urls = images.get(group)
        if isinstance(urls, dict):
            for size in ("preview", "thumbnail", "icon"):
                if isinstance(urls.get(size), str):
                    return urls[size]
    return None


def parse_webcam(raw: dict[str, Any], lat: float, lon: float) -> Webcam | None:
    """Parse one API webcam, or return None if it has no ID."""
    webcam_id = raw.get("webcamId")
    if webcam_id is None:
        return None
    location = raw.get("location") or {}
    cam_lat, cam_lon = location.get("latitude"), location.get("longitude")
    player = raw.get("player") or {}
    urls = raw.get("urls") or {}
    updated = raw.get("lastUpdatedOn")
    return Webcam(
        webcam_id=int(webcam_id),
        title=raw.get("title") or f"Webcam {webcam_id}",
        status=raw.get("status") or "active",
        image_url=_image_url(raw.get("images") or {}),
        latitude=cam_lat,
        longitude=cam_lon,
        city=location.get("city"),
        region=location.get("region"),
        country=location.get("country"),
        distance_km=(
            round(_distance_km(lat, lon, cam_lat, cam_lon), 1)
            if cam_lat is not None and cam_lon is not None
            else None
        ),
        detail_url=urls.get("detail"),
        day_timelapse_url=player.get("day"),
        live_url=player.get("live"),
        last_updated_on=dt_util.parse_datetime(updated) if updated else None,
    )


class WebcamCoordinator(DataUpdateCoordinator[dict[int, Webcam]]):
    """Refresh webcam metadata and short-lived image URLs."""

    config_entry: WindyConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: WindyConfigEntry,
        key: str,
        radius: int,
        count: int,
        webcam_ids: list[int],
        interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{entry.title} webcams",
            update_interval=interval,
        )
        self._key = key
        self._radius = radius
        self._count = count
        self._ids = webcam_ids

    async def _async_update_data(self) -> dict[int, Webcam]:
        """Fetch the closest webcams once, then keep tracking the same IDs."""
        lat = self.config_entry.data[CONF_LATITUDE]
        lon = self.config_entry.data[CONF_LONGITUDE]
        session = async_get_clientsession(self.hass)
        try:
            if self._ids:
                raw = await fetch_webcams(
                    session, self._key, webcam_ids=self._ids, limit=MAX_WEBCAMS
                )
            else:
                raw = await fetch_webcams(
                    session,
                    self._key,
                    nearby=(lat, lon, self._radius),
                    limit=MAX_WEBCAMS,
                )
        except WindyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WindyError as err:
            raise UpdateFailed(str(err)) from err

        webcams = [cam for r in raw if (cam := parse_webcam(r, lat, lon))]
        if not self._ids:
            active = [c for c in webcams if c.status == "active" and c.image_url]
            active.sort(
                key=lambda c: math.inf if c.distance_km is None else c.distance_km
            )
            webcams = active[: self._count]
            self._ids = [c.webcam_id for c in webcams]
        return {cam.webcam_id: cam for cam in webcams}
