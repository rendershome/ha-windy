"""Camera entities for Windy webcams."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import TIMEOUT
from .const import WEBCAM_ATTRIBUTION
from .coordinator import Webcam, WebcamCoordinator, WindyConfigEntry
from .entity import device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WindyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up cameras, adding any webcams discovered later."""
    coordinator = entry.runtime_data.webcams
    if coordinator is None:
        return
    known: set[int] = set()

    @callback
    def add_new() -> None:
        new = set(coordinator.data) - known
        if new:
            known.update(new)
            async_add_entities(
                WindyWebcam(entry, coordinator, webcam_id) for webcam_id in sorted(new)
            )

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class WindyWebcam(CoordinatorEntity[WebcamCoordinator], Camera):
    """A still image from a Windy webcam."""

    _attr_attribution = WEBCAM_ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: WindyConfigEntry,
        coordinator: WebcamCoordinator,
        webcam_id: int,
    ) -> None:
        """Initialize the camera."""
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._webcam_id = webcam_id
        self._attr_unique_id = f"{entry.entry_id}_webcam_{webcam_id}"
        self._attr_name = coordinator.data[webcam_id].title
        self._attr_device_info = device_info(entry)
        self._cached_url: str | None = None
        self._cached_image: bytes | None = None

    @property
    def _webcam(self) -> Webcam | None:
        return self.coordinator.data.get(self._webcam_id)

    @property
    def available(self) -> bool:
        """Return whether the webcam is active."""
        webcam = self._webcam
        return super().available and webcam is not None and webcam.status == "active"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return webcam details, including the links Windy requires."""
        webcam = self._webcam
        if webcam is None:
            return None
        return {
            "webcam_id": webcam.webcam_id,
            "city": webcam.city,
            "region": webcam.region,
            "country": webcam.country,
            "latitude": webcam.latitude,
            "longitude": webcam.longitude,
            "distance_km": webcam.distance_km,
            "windy_url": webcam.detail_url,
            "day_timelapse_url": webcam.day_timelapse_url,
            "live_url": webcam.live_url,
            "image_updated_on": (
                webcam.last_updated_on.isoformat() if webcam.last_updated_on else None
            ),
        }

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the image, fetching it once per refreshed URL.

        Windy's terms don't allow stretching, so size arguments are ignored.
        """
        webcam = self._webcam
        if webcam is None or webcam.image_url is None:
            return None
        if webcam.image_url == self._cached_url:
            return self._cached_image

        session = async_get_clientsession(self.hass)
        url = webcam.image_url
        image, expired = await self._fetch(session, url)
        if expired:
            # The tokenized URL expired, for example after a failed refresh.
            await self.coordinator.async_refresh()
            webcam = self._webcam
            if webcam is None or webcam.image_url in (None, url):
                return self._cached_image
            url = webcam.image_url
            image, _ = await self._fetch(session, url)
        if image is None:
            return self._cached_image
        self._cached_url, self._cached_image = url, image
        return image

    async def _fetch(
        self, session: aiohttp.ClientSession, url: str
    ) -> tuple[bytes | None, bool]:
        """Fetch an image, returning it and whether its URL has expired."""
        try:
            async with session.get(url, timeout=TIMEOUT) as resp:
                if resp.status == 401:
                    return None, True
                if resp.status != 200:
                    _LOGGER.debug(
                        "Webcam %s image returned HTTP %s",
                        self._webcam_id,
                        resp.status,
                    )
                    return None, False
                return await resp.read(), False
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug(
                "Webcam %s image failed: %s", self._webcam_id, type(err).__name__
            )
            return None, False
