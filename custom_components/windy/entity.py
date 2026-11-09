"""Shared entity helpers for the Windy integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN
from .coordinator import WindyConfigEntry


def device_info(entry: WindyConfigEntry) -> DeviceInfo:
    """Return the service device for a configured location."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Windy",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://www.windy.com",
    )
