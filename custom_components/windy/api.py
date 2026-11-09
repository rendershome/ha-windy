"""Minimal async client for the Windy Point Forecast and Webcams APIs.

API keys are never logged or included in raised error messages.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import aiohttp

POINT_URL = "https://api.windy.com/api/point-forecast/v2"
WEBCAMS_URL = "https://api.windy.com/webcams/api/v3/webcams"
TIMEOUT = aiohttp.ClientTimeout(total=30)
WEBCAM_INCLUDE = "images,location,player,urls"


class WindyError(Exception):
    """A Windy API request failed."""


class WindyAuthError(WindyError):
    """Windy rejected the API key."""


class WindyNoData(WindyError):
    """The model has no data for the requested parameters."""


async def fetch_point_forecast(
    session: aiohttp.ClientSession,
    key: str,
    lat: float,
    lon: float,
    model: str,
    parameters: Iterable[str],
) -> dict[str, Any]:
    """Return a raw Point Forecast response."""
    body = {
        "lat": round(lat, 2),
        "lon": round(lon, 2),
        "model": model,
        "parameters": list(parameters),
        "levels": ["surface"],
        "key": key,
    }
    try:
        async with session.post(POINT_URL, json=body, timeout=TIMEOUT) as resp:
            if resp.status == 204:
                raise WindyNoData(f"Model {model} has no data for this request")
            if resp.status == 200:
                data = await resp.json(content_type=None)
                if not isinstance(data, dict):
                    raise WindyError("Unexpected Point Forecast response")
                return data
            message = await _error_message(resp)
            # An invalid key is reported as 400 "Invalid API key".
            if resp.status in (401, 403) or "api key" in message.lower():
                raise WindyAuthError(message or f"HTTP {resp.status}")
            raise WindyError(f"Point Forecast HTTP {resp.status}: {message}")
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise WindyError(f"Point Forecast request failed: {type(err).__name__}") from err


async def fetch_webcams(
    session: aiohttp.ClientSession,
    key: str,
    *,
    nearby: tuple[float, float, int] | None = None,
    webcam_ids: Iterable[int] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return webcams near a location, or by ID."""
    params: dict[str, str | int] = {"limit": limit, "include": WEBCAM_INCLUDE}
    if webcam_ids is not None:
        params["webcamIds"] = ",".join(str(i) for i in webcam_ids)
    elif nearby is not None:
        lat, lon, radius = nearby
        params["nearby"] = f"{lat:.4f},{lon:.4f},{radius}"
    try:
        async with session.get(
            WEBCAMS_URL,
            params=params,
            headers={"x-windy-api-key": key},
            timeout=TIMEOUT,
        ) as resp:
            if resp.status in (401, 403):
                raise WindyAuthError(await _error_message(resp))
            if resp.status != 200:
                raise WindyError(
                    f"Webcams HTTP {resp.status}: {await _error_message(resp)}"
                )
            data = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise WindyError(f"Webcams request failed: {type(err).__name__}") from err
    webcams = data.get("webcams") if isinstance(data, dict) else None
    if not isinstance(webcams, list):
        raise WindyError("Unexpected Webcams response")
    return webcams


async def _error_message(resp: aiohttp.ClientResponse) -> str:
    """Return the API's error message, falling back to a truncated body."""
    text = await resp.text()
    try:
        data = await resp.json(content_type=None)
    except ValueError:
        return text[:200]
    if isinstance(data, dict) and isinstance(data.get("message"), str):
        return data["message"][:200]
    return text[:200]
