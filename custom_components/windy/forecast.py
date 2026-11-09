"""Parse Point Forecast responses and derive Home Assistant weather values."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import math
import re
from typing import Any

from homeassistant.util import dt as dt_util

from .api import WindyError

TEMP = "temp-surface"
DEW_POINT = "dewpoint-surface"
HUMIDITY = "rh-surface"
PRESSURE = "pressure-surface"
PRECIP = "past3hprecip-surface"
SNOW = "past3hsnowprecip-surface"
GUST = "gust-surface"
CAPE = "cape-surface"
PTYPE = "ptype-surface"
LOW_CLOUDS = "lclouds-surface"
MID_CLOUDS = "mclouds-surface"
HIGH_CLOUDS = "hclouds-surface"
CLOUD_BASE = "cbase-surface"
VISIBILITY = "visibility-surface"
WARNINGS = "weatherwarnings-surface"
WIND_U = "wind_u-surface"
WIND_V = "wind_v-surface"
# Derived series
WIND_SPEED = "wind_speed"
WIND_BEARING = "wind_bearing"
CLOUD_COVER = "cloud_cover"

_ACCUMULATIONS = {PRECIP, SNOW, "past3hconvprecip-surface"}
PRECIP_WINDOW_HOURS = 3
_UNIT_PART = re.compile(r"^(.*?)(-?\d+)?$")
_SUPERSCRIPT = {2: "²", 3: "³"}


def format_unit(unit: str | None) -> str | None:
    """Convert Windy's unit format, such as m*s-1, to a display unit."""
    if not unit:
        return None
    top: list[str] = []
    bottom: list[str] = []
    # Windy uses the micro sign; Home Assistant's units use the Greek letter mu.
    for part in unit.replace("µ", "μ").split("*"):
        match = _UNIT_PART.match(part)
        base, exp = match.group(1), int(match.group(2) or 1)  # type: ignore[union-attr]
        target = top if exp > 0 else bottom
        target.append(base + _SUPERSCRIPT.get(abs(exp), ""))
    return "*".join(top or ["1"]) + "".join(f"/{b}" for b in bottom)


def _normalize(
    key: str, unit: str | None, values: list[float | None]
) -> tuple[list[float | None], str | None]:
    """Convert a series to the units used by Home Assistant entities."""
    convert: Callable[[float], float] | None = None
    display = format_unit(unit)
    if unit == "K":
        convert, display = (lambda v: v - 273.15), "°C"
    elif unit == "Pa":
        convert, display = (lambda v: v / 100), "hPa"
    elif key in _ACCUMULATIONS and unit == "m":
        convert, display = (lambda v: v * 1000), "mm"
    elif key in _ACCUMULATIONS and unit == "kg*m-2":
        display = "mm"  # 1 kg/m² of water is a 1 mm column
    elif key == VISIBILITY and unit == "m":
        convert, display = (lambda v: v / 1000), "km"
    if convert is None:
        return values, display
    return [None if v is None else convert(v) for v in values], display


@dataclass(slots=True)
class PointForecast:
    """A parsed forecast with all series indexed to ``times``."""

    times: list[datetime] = field(default_factory=list)
    series: dict[str, list[float | None]] = field(default_factory=dict)
    units: dict[str, str | None] = field(default_factory=dict)

    def has(self, key: str) -> bool:
        """Return whether the model returned usable values for a series."""
        return any(v is not None for v in self.series.get(key, ()))

    def value(self, key: str, index: int) -> float | None:
        """Return one value of a series."""
        values = self.series.get(key)
        return values[index] if values else None

    def current_index(self, now: datetime | None = None) -> int | None:
        """Return the index of the time step closest to now."""
        if not self.times:
            return None
        now = now or dt_util.utcnow()
        return min(
            range(len(self.times)),
            key=lambda i: abs((self.times[i] - now).total_seconds()),
        )

    def current(self, key: str, now: datetime | None = None) -> float | None:
        """Return the value of a series for the closest time step."""
        index = self.current_index(now)
        return None if index is None else self.value(key, index)

    def step_hours(self, index: int) -> float:
        """Return the hours covered by a time step."""
        if len(self.times) < 2:
            return PRECIP_WINDOW_HOURS
        if index == 0:
            delta = self.times[1] - self.times[0]
        else:
            delta = self.times[index] - self.times[index - 1]
        return delta.total_seconds() / 3600

    def step_precipitation(self, index: int) -> float | None:
        """Estimate precipitation in a step from the 3-hour accumulation.

        Windy reports the preceding 3 hours for every step, so summing the raw
        values of an hourly model would count the same rain three times.
        """
        value = self.value(PRECIP, index)
        if value is None:
            return None
        return value * self.step_hours(index) / PRECIP_WINDOW_HOURS

    def precipitation_next(
        self, hours: int, now: datetime | None = None
    ) -> float | None:
        """Return estimated precipitation over the next hours."""
        if not self.has(PRECIP):
            return None
        now = now or dt_util.utcnow()
        end = now + timedelta(hours=hours)
        values = [
            self.step_precipitation(i)
            for i, time in enumerate(self.times)
            if now < time <= end
        ]
        known = [v for v in values if v is not None]
        return sum(known) if known else None


def parse_point_forecast(raw: dict[str, Any]) -> PointForecast:
    """Parse a raw Point Forecast response."""
    timestamps = raw.get("ts")
    if not isinstance(timestamps, list):
        raise WindyError("Point Forecast response has no timestamps")
    units = raw.get("units") if isinstance(raw.get("units"), dict) else {}
    forecast = PointForecast(
        times=[datetime.fromtimestamp(ts / 1000, UTC) for ts in timestamps]
    )
    for key, values in raw.items():
        if key in ("ts", "units") or not isinstance(values, list):
            continue
        if len(values) != len(timestamps):
            continue
        forecast.series[key], forecast.units[key] = _normalize(
            key, units.get(key), values
        )
    _add_derived(forecast)
    return forecast


def _add_derived(forecast: PointForecast) -> None:
    """Add wind speed, wind bearing and total cloud cover."""
    u_values = forecast.series.get(WIND_U)
    v_values = forecast.series.get(WIND_V)
    if u_values and v_values:
        speeds: list[float | None] = []
        bearings: list[float | None] = []
        for u, v in zip(u_values, v_values, strict=True):
            if u is None or v is None:
                speeds.append(None)
                bearings.append(None)
                continue
            speeds.append(math.hypot(u, v))
            # u and v say where the air is going; bearing is where it came from.
            bearings.append(math.degrees(math.atan2(-u, -v)) % 360)
        forecast.series[WIND_SPEED] = speeds
        forecast.series[WIND_BEARING] = bearings
        forecast.units[WIND_SPEED] = forecast.units.get(WIND_U)
        forecast.units[WIND_BEARING] = "°"

    layers = [
        forecast.series[key]
        for key in (LOW_CLOUDS, MID_CLOUDS, HIGH_CLOUDS)
        if key in forecast.series
    ]
    if layers:
        # Layers overlap, so the fullest layer is the conservative total.
        cover: list[float | None] = []
        for row in zip(*layers, strict=True):
            known = [v for v in row if v is not None]
            cover.append(max(known) if known else None)
        forecast.series[CLOUD_COVER] = cover
        forecast.units[CLOUD_COVER] = "%"


def derive_condition(
    forecast: PointForecast, index: int, is_day: Callable[[datetime], bool]
) -> str | None:
    """Derive a Home Assistant weather condition for a time step."""
    warning = forecast.value(WARNINGS, index)
    if warning in (95, 96):
        return "lightning-rainy"
    if warning in (45, 48):
        return "fog"

    precip = forecast.value(PRECIP, index)
    ptype = forecast.value(PTYPE, index)
    temp = forecast.value(TEMP, index)
    wet = precip is not None and precip >= 0.2

    if PTYPE in forecast.series and ptype is not None:
        # Models that report a type say explicitly when it is dry now.
        wet_condition = {
            1: "pouring" if precip is not None and precip >= 7.5 else "rainy",
            3: "snowy-rainy",
            5: "snowy",
            7: "snowy-rainy",
            8: "hail",
        }.get(int(ptype))
        if wet_condition and wet:
            return wet_condition
    elif wet:
        # canHrdps and HRRR have no precipitation type.
        if temp is not None and temp <= 0:
            return "snowy"
        if temp is not None and temp <= 2:
            return "snowy-rainy"
        return "pouring" if precip >= 7.5 else "rainy"  # type: ignore[operator]

    clouds = forecast.value(CLOUD_COVER, index)
    wind = forecast.value(WIND_SPEED, index)
    if wind is not None and wind >= 10.8:  # Beaufort 6, strong breeze
        return "windy-variant" if clouds is not None and clouds >= 85 else "windy"
    if clouds is None:
        return None
    if clouds >= 85:
        return "cloudy"
    if clouds >= 30:
        return "partlycloudy"
    return "sunny" if is_day(forecast.times[index]) else "clear-night"


@dataclass(slots=True)
class DailySummary:
    """Values summarised for one local calendar day."""

    start: datetime
    high: float | None
    low: float | None
    precipitation: float | None
    condition: str | None
    wind_speed: float | None
    wind_gust: float | None
    humidity: float | None
    cloud_cover: float | None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_daily(
    forecast: PointForecast,
    is_day: Callable[[datetime], bool],
    now: datetime | None = None,
) -> list[DailySummary]:
    """Group future time steps into local calendar days."""
    now = now or dt_util.utcnow()
    days: dict[Any, list[int]] = {}
    for index, time in enumerate(forecast.times):
        if time >= now:
            days.setdefault(dt_util.as_local(time).date(), []).append(index)

    result: list[DailySummary] = []
    for date, indexes in days.items():
        def known(key: str, indexes: list[int] = indexes) -> list[float]:
            values = (forecast.value(key, i) for i in indexes)
            return [v for v in values if v is not None]

        temps = known(TEMP)
        steps = (forecast.step_precipitation(i) for i in indexes)
        precip = [v for v in steps if v is not None]
        total = sum(precip) if precip else None
        conditions = [derive_condition(forecast, i, is_day) for i in indexes]
        named = [c for c in conditions if c]
        condition = None
        wet = [
            c
            for c in named
            if c in ("rainy", "pouring", "snowy", "snowy-rainy", "hail",
                     "lightning-rainy")
        ]
        if wet and total is not None and total >= 1:
            condition = Counter(wet).most_common(1)[0][0]
        elif named:
            # Use the middle of the day, so a clear night doesn't label the day.
            midday = min(
                indexes,
                key=lambda i: abs(dt_util.as_local(forecast.times[i]).hour - 12),
            )
            condition = derive_condition(
                forecast, midday, lambda _time: True
            ) or Counter(named).most_common(1)[0][0]
        winds = known(WIND_SPEED)
        gusts = known(GUST)
        first = dt_util.as_local(forecast.times[indexes[0]])
        result.append(
            DailySummary(
                start=dt_util.start_of_local_day(first),
                high=max(temps) if temps else None,
                low=min(temps) if temps else None,
                precipitation=total,
                condition=condition,
                wind_speed=max(winds) if winds else None,
                wind_gust=max(gusts) if gusts else None,
                humidity=_mean(known(HUMIDITY)),
                cloud_cover=_mean(known(CLOUD_COVER)),
            )
        )
    return result
