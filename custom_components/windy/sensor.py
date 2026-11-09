"""Sensors for the Windy integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    DEGREE,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION
from .coordinator import PointForecastCoordinator, WindyConfigEntry
from .entity import device_info
from .forecast import (
    CAPE,
    CLOUD_BASE,
    CLOUD_COVER,
    DEW_POINT,
    GUST,
    HIGH_CLOUDS,
    HUMIDITY,
    LOW_CLOUDS,
    MID_CLOUDS,
    PRECIP,
    PRESSURE,
    SNOW,
    TEMP,
    VISIBILITY,
    WIND_BEARING,
    WIND_SPEED,
    PointForecast,
)


@dataclass(frozen=True, kw_only=True)
class WindySensorDescription(SensorEntityDescription):
    """Describe a forecast sensor; ``key`` names its response series."""

    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    value_fn: Callable[[PointForecast], float | None] | None = None
    unit: str | None = None
    # Only claim a device class when Windy reports a unit it accepts.
    device_class_units: frozenset[str] | None = None


def _measure(
    key: str, name: str, device_class: SensorDeviceClass | None = None, **kwargs
) -> WindySensorDescription:
    return WindySensorDescription(
        key=key, name=name, device_class=device_class, **kwargs
    )


WEATHER_SENSORS = (
    _measure(TEMP, "Temperature", SensorDeviceClass.TEMPERATURE),
    _measure(DEW_POINT, "Dew point", SensorDeviceClass.TEMPERATURE),
    _measure(HUMIDITY, "Humidity", SensorDeviceClass.HUMIDITY),
    _measure(PRESSURE, "Pressure", SensorDeviceClass.ATMOSPHERIC_PRESSURE),
    _measure(WIND_SPEED, "Wind speed", SensorDeviceClass.WIND_SPEED),
    _measure(GUST, "Wind gust", SensorDeviceClass.WIND_SPEED),
    WindySensorDescription(
        key=WIND_BEARING,
        name="Wind direction",
        device_class=SensorDeviceClass.WIND_DIRECTION,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        unit=DEGREE,
    ),
    _measure(CLOUD_COVER, "Cloud cover", icon="mdi:cloud-percent"),
    _measure(VISIBILITY, "Visibility", SensorDeviceClass.DISTANCE),
    WindySensorDescription(
        key=PRECIP,
        name="Precipitation past 3 hours",
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    WindySensorDescription(
        key="precipitation_next_24h",
        name="Precipitation next 24 hours",
        device_class=SensorDeviceClass.PRECIPITATION,
        state_class=None,
        unit="mm",
        value_fn=lambda data: data.precipitation_next(24),
    ),
    WindySensorDescription(
        key=SNOW,
        name="Snow past 3 hours (water equivalent)",
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    _measure(LOW_CLOUDS, "Low clouds", entity_registry_enabled_default=False),
    _measure(MID_CLOUDS, "Medium clouds", entity_registry_enabled_default=False),
    _measure(HIGH_CLOUDS, "High clouds", entity_registry_enabled_default=False),
    _measure(
        CAPE,
        "CAPE",
        icon="mdi:weather-lightning",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    _measure(
        CLOUD_BASE,
        "Cloud base",
        SensorDeviceClass.DISTANCE,
        entity_registry_enabled_default=False,
    ),
)

_UG = frozenset({CONCENTRATION_MICROGRAMS_PER_CUBIC_METER})

AIR_QUALITY_SENSORS = (
    _measure("aqi_us-surface", "Air quality index", SensorDeviceClass.AQI),
    _measure(
        "pm2p5-surface",
        "PM2.5",
        SensorDeviceClass.PM25,
        device_class_units=_UG,
    ),
    _measure(
        "pm10-surface", "PM10", SensorDeviceClass.PM10, device_class_units=_UG
    ),
    _measure(
        "no2-surface",
        "Nitrogen dioxide",
        SensorDeviceClass.NITROGEN_DIOXIDE,
        device_class_units=_UG,
    ),
    _measure(
        "go3-surface", "Ozone", SensorDeviceClass.OZONE, device_class_units=_UG
    ),
    _measure(
        "chem_so2sm-surface",
        "Sulphur dioxide",
        SensorDeviceClass.SULPHUR_DIOXIDE,
        device_class_units=_UG,
    ),
    _measure("chem_cosc-surface", "Carbon monoxide", icon="mdi:molecule-co"),
    _measure("chem_dustsm-surface", "Dust", icon="mdi:weather-dust"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WindyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create sensors for the series each model actually returned."""
    entities: list[WindySensor] = []
    for coordinator, descriptions in (
        (entry.runtime_data.weather, WEATHER_SENSORS),
        (entry.runtime_data.air_quality, AIR_QUALITY_SENSORS),
    ):
        if coordinator is None:
            continue
        for description in descriptions:
            source = PRECIP if description.value_fn else description.key
            if coordinator.data.has(source):
                entities.append(WindySensor(entry, coordinator, description))
    async_add_entities(entities)


class WindySensor(CoordinatorEntity[PointForecastCoordinator], SensorEntity):
    """The value of a forecast series for the current time step."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    entity_description: WindySensorDescription

    def __init__(
        self,
        entry: WindyConfigEntry,
        coordinator: PointForecastCoordinator,
        description: WindySensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info(entry)
        unit = description.unit or coordinator.data.units.get(description.key)
        self._attr_native_unit_of_measurement = unit
        allowed = description.device_class_units
        if allowed is not None and unit not in allowed:
            self._attr_device_class = None

    @property
    def native_value(self) -> float | None:
        """Return the value for the closest time step."""
        description = self.entity_description
        if description.value_fn:
            value = description.value_fn(self.coordinator.data)
        else:
            value = self.coordinator.data.current(description.key)
        return None if value is None else round(value, 2)
