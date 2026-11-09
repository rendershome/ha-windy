"""Weather entity for the Windy integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.weather import (
    Forecast,
    SingleCoordinatorWeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.const import (
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.sun import is_up
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION
from .coordinator import PointForecastCoordinator, WindyConfigEntry
from .entity import device_info
from .forecast import (
    CLOUD_COVER,
    DEW_POINT,
    GUST,
    HUMIDITY,
    PRESSURE,
    TEMP,
    VISIBILITY,
    WIND_BEARING,
    WIND_SPEED,
    derive_condition,
    summarize_daily,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WindyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the weather entity."""
    if entry.runtime_data.weather:
        async_add_entities([WindyWeather(entry, entry.runtime_data.weather)])


class WindyWeather(SingleCoordinatorWeatherEntity[PointForecastCoordinator]):
    """Current conditions and forecasts from one Windy model."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_HOURLY | WeatherEntityFeature.FORECAST_DAILY
    )

    def __init__(
        self, entry: WindyConfigEntry, coordinator: PointForecastCoordinator
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_weather"
        self._attr_device_info = device_info(entry)

    def _is_day(self, time: datetime) -> bool:
        return is_up(self.hass, time)

    def _current(self, key: str) -> float | None:
        return self.coordinator.data.current(key)

    @property
    def condition(self) -> str | None:
        """Return the current condition."""
        index = self.coordinator.data.current_index()
        if index is None:
            return None
        return derive_condition(self.coordinator.data, index, self._is_day)

    @property
    def native_temperature(self) -> float | None:
        """Return the temperature."""
        return self._current(TEMP)

    @property
    def native_dew_point(self) -> float | None:
        """Return the dew point."""
        return self._current(DEW_POINT)

    @property
    def humidity(self) -> float | None:
        """Return the humidity."""
        return self._current(HUMIDITY)

    @property
    def native_pressure(self) -> float | None:
        """Return the air pressure."""
        return self._current(PRESSURE)

    @property
    def native_wind_speed(self) -> float | None:
        """Return the wind speed."""
        return self._current(WIND_SPEED)

    @property
    def native_wind_gust_speed(self) -> float | None:
        """Return the wind gust speed."""
        return self._current(GUST)

    @property
    def wind_bearing(self) -> float | None:
        """Return the direction the wind is coming from."""
        return self._current(WIND_BEARING)

    @property
    def cloud_coverage(self) -> float | None:
        """Return the cloud coverage."""
        return self._current(CLOUD_COVER)

    @property
    def native_visibility(self) -> float | None:
        """Return the visibility."""
        return self._current(VISIBILITY)

    @callback
    def _async_forecast_hourly(self) -> list[Forecast] | None:
        """Return every future time step of the model."""
        data = self.coordinator.data
        now = dt_util.utcnow()
        return [
            Forecast(
                datetime=time.isoformat(),
                condition=derive_condition(data, i, self._is_day),
                native_temperature=data.value(TEMP, i),
                native_dew_point=data.value(DEW_POINT, i),
                humidity=data.value(HUMIDITY, i),
                native_pressure=data.value(PRESSURE, i),
                native_precipitation=data.step_precipitation(i),
                native_wind_speed=data.value(WIND_SPEED, i),
                native_wind_gust_speed=data.value(GUST, i),
                wind_bearing=data.value(WIND_BEARING, i),
                cloud_coverage=data.value(CLOUD_COVER, i),
                is_daytime=self._is_day(time),
            )
            for i, time in enumerate(data.times)
            if time >= now
        ]

    @callback
    def _async_forecast_daily(self) -> list[Forecast] | None:
        """Return future time steps summarised by local day."""
        return [
            Forecast(
                datetime=day.start.isoformat(),
                condition=day.condition,
                native_temperature=day.high,
                native_templow=day.low,
                native_precipitation=day.precipitation,
                native_wind_speed=day.wind_speed,
                native_wind_gust_speed=day.wind_gust,
                humidity=day.humidity,
                cloud_coverage=day.cloud_cover,
            )
            for day in summarize_daily(self.coordinator.data, self._is_day)
        ]
