"""Tests for the Windy integration against a simulated Windy API."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windy.api import POINT_URL, WEBCAMS_URL
from custom_components.windy.const import (
    AIR_QUALITY_OFF,
    CONF_AIR_QUALITY_MODEL,
    CONF_MAP_KEY,
    CONF_MODEL,
    CONF_POINT_KEY,
    CONF_WEBCAM_COUNT,
    CONF_WEBCAM_IDS,
    CONF_WEBCAMS_KEY,
    DOMAIN,
)
from custom_components.windy.diagnostics import async_get_config_entry_diagnostics
from custom_components.windy.forecast import (
    PRECIP,
    WIND_BEARING,
    WIND_SPEED,
    derive_condition,
    format_unit,
    parse_point_forecast,
    summarize_daily,
)
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_LATITUDE, CONF_LOCATION, CONF_LONGITUDE, CONF_NAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

POINT_SECRET = "point-secret-value"
MAP_SECRET = "map-secret-value"
WEBCAM_SECRET = "webcam-secret-value"
IMAGE_1 = "https://images.example/1.jpg?token=first"
IMAGE_2 = "https://images.example/1.jpg?token=second"


@pytest.fixture(autouse=True)
def _enable(enable_custom_integrations):
    yield


def weather_response(step_hours: int = 3, steps: int = 24, ptype: bool = True) -> dict:
    """Return a response in the documented format with SI units."""
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    ts = [
        int((start + timedelta(hours=i * step_hours)).timestamp() * 1000)
        for i in range(steps)
    ]
    data = {
        "ts": ts,
        "units": {
            "temp-surface": "K",
            "dewpoint-surface": "K",
            "rh-surface": "%",
            "pressure-surface": "Pa",
            "past3hprecip-surface": "m",
            "gust-surface": "m*s-1",
            "wind_u-surface": "m*s-1",
            "wind_v-surface": "m*s-1",
            "lclouds-surface": "%",
            "mclouds-surface": "%",
            "hclouds-surface": "%",
            "cape-surface": "J*kg-1",
        },
        "temp-surface": [283.15] * steps,
        "dewpoint-surface": [278.15] * steps,
        "rh-surface": [70.0] * steps,
        "pressure-surface": [101300.0] * steps,
        "past3hprecip-surface": [0.003] * steps,
        "gust-surface": [9.0] * steps,
        # Blowing toward the south, so it comes from the north.
        "wind_u-surface": [0.0] * steps,
        "wind_v-surface": [-5.0] * steps,
        "lclouds-surface": [10.0] * steps,
        "mclouds-surface": [90.0] * steps,
        "hclouds-surface": [None] * steps,
        "cape-surface": [12.0] * steps,
    }
    if ptype:
        data["units"]["ptype-surface"] = None
        data["ptype-surface"] = [1] * steps
    return data


def webcam(webcam_id: int, lat: float, image: str = IMAGE_1) -> dict:
    return {
        "webcamId": webcam_id,
        "title": f"Cam {webcam_id}",
        "status": "active",
        "lastUpdatedOn": "2026-11-08T12:17:24.000Z",
        "images": {"current": {"preview": image}, "daylight": {}, "sizes": {}},
        "location": {
            "latitude": lat,
            "longitude": -81.57,
            "city": "Town",
            "region": "Ontario",
            "country": "Canada",
            "continent": "North America",
        },
        "player": {"day": "https://player.example/day"},
        "urls": {"detail": f"https://webcams.example/{webcam_id}"},
    }


def make_entry(**data) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id="43.90_-81.57",
        data={CONF_LATITUDE: 43.9, CONF_LONGITUDE: -81.57, **data},
        options={CONF_MODEL: "gfs", CONF_AIR_QUALITY_MODEL: AIR_QUALITY_OFF},
    )


async def set_up(hass, entry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


# Parsing -------------------------------------------------------------------


def test_units_and_wind_are_normalized() -> None:
    data = parse_point_forecast(weather_response())
    assert data.current("temp-surface") == pytest.approx(10.0)
    assert data.units["temp-surface"] == "°C"
    assert data.current("pressure-surface") == pytest.approx(1013.0)
    assert data.units["pressure-surface"] == "hPa"
    assert data.current(PRECIP) == pytest.approx(3.0)
    assert data.units[PRECIP] == "mm"
    assert data.current(WIND_SPEED) == pytest.approx(5.0)
    assert data.current(WIND_BEARING) == pytest.approx(0.0)
    assert data.units["cape-surface"] == "J/kg"


@pytest.mark.parametrize(
    ("u", "v", "bearing"),
    [(0, -1, 0), (-1, 0, 90), (0, 1, 180), (1, 0, 270)],
)
def test_wind_bearing_is_where_wind_comes_from(u, v, bearing) -> None:
    raw = {"ts": [0], "units": {}, "wind_u-surface": [u], "wind_v-surface": [v]}
    assert parse_point_forecast(raw).value(WIND_BEARING, 0) == pytest.approx(bearing)


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("m*s-1", "m/s"),
        ("J*kg-1", "J/kg"),
        ("µg*m-3", "μg/m³"),
        ("%", "%"),
        (None, None),
    ],
)
def test_format_unit(raw, shown) -> None:
    assert format_unit(raw) == shown


def test_hourly_model_does_not_triple_count_rain() -> None:
    """Each hourly step reports the same rain for the preceding 3 hours."""
    hourly = parse_point_forecast(weather_response(step_hours=1, steps=48))
    three_hourly = parse_point_forecast(weather_response(step_hours=3, steps=16))
    now = dt_util.utcnow()
    # 3 mm per 3 hours for 24 hours is 24 mm, whatever the step size.
    assert hourly.precipitation_next(24, now) == pytest.approx(24.0, abs=1.01)
    assert three_hourly.precipitation_next(24, now) == pytest.approx(24.0, abs=3.01)


def test_mismatched_series_is_ignored() -> None:
    raw = {"ts": [0, 1], "units": {}, "temp-surface": [280.0]}
    assert not parse_point_forecast(raw).has("temp-surface")


def _condition(**series) -> str | None:
    raw = {"ts": [0], "units": {"past3hprecip-surface": "mm", "temp-surface": "K"}}
    raw |= {k: [v] for k, v in series.items()}
    return derive_condition(parse_point_forecast(raw), 0, lambda _t: True)


def test_conditions() -> None:
    wet = {"past3hprecip-surface": 2.0, "temp-surface": 283.15}
    assert _condition(**wet, **{"ptype-surface": 1}) == "rainy"
    assert _condition(**wet, **{"ptype-surface": 5}) == "snowy"
    assert _condition(**wet, **{"ptype-surface": 8}) == "hail"
    # Type 0 means it's dry now, even if rain fell in the past 3 hours.
    assert (
        _condition(**wet, **{"ptype-surface": 0, "lclouds-surface": 10.0}) == "sunny"
    )
    # canHrdps has no type, so temperature decides.
    assert _condition(**wet) == "rainy"
    assert (
        _condition(**{"past3hprecip-surface": 2.0, "temp-surface": 268.15}) == "snowy"
    )
    assert (
        _condition(**{"past3hprecip-surface": 2.0, "temp-surface": 274.15})
        == "snowy-rainy"
    )
    assert _condition(**{"weatherwarnings-surface": 45, "temp-surface": 280.0}) == "fog"
    assert _condition(**{"lclouds-surface": 90.0, "temp-surface": 280.0}) == "cloudy"
    assert _condition(**{"temp-surface": 280.0}) is None
    assert (
        _condition(**{"wind_u-surface": 12.0, "wind_v-surface": 0.0, "temp-surface": 1})
        == "windy"
    )


def test_daily_summary_uses_local_days() -> None:
    data = parse_point_forecast(weather_response())
    days = summarize_daily(data, lambda _t: True, now=data.times[0])
    assert sum(1 for _ in days) >= 3
    assert days[0].high == pytest.approx(10.0)
    assert days[1].precipitation == pytest.approx(24.0)
    assert days[1].condition == "rainy"


# Config flow ---------------------------------------------------------------


USER_INPUT = {
    CONF_NAME: "Home",
    CONF_LOCATION: {CONF_LATITUDE: 43.9, CONF_LONGITUDE: -81.57},
    CONF_MODEL: "gfs",
}


async def test_flow_creates_entry_and_validates_each_key(
    hass, aioclient_mock
) -> None:
    aioclient_mock.post(POINT_URL, json=weather_response())
    aioclient_mock.get(WEBCAMS_URL, json={"total": 0, "webcams": []})
    with patch("custom_components.windy.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                **USER_INPUT,
                CONF_POINT_KEY: f" {POINT_SECRET} ",
                CONF_MAP_KEY: MAP_SECRET,
                CONF_WEBCAMS_KEY: WEBCAM_SECRET,
            },
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_POINT_KEY] == POINT_SECRET
    assert result["data"][CONF_LATITUDE] == 43.9
    method, _url, body, headers = aioclient_mock.mock_calls[0][:4]
    assert method.upper() == "POST"
    assert body["lat"] == 43.9
    assert body["levels"] == ["surface"]
    assert "ptype" in body["parameters"]
    assert aioclient_mock.mock_calls[1][3]["x-windy-api-key"] == WEBCAM_SECRET


async def test_flow_reports_rejected_point_key(hass, aioclient_mock) -> None:
    aioclient_mock.post(
        POINT_URL,
        status=400,
        json={"message": "Invalid API key", "error": "Bad Request", "statusCode": 400},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_POINT_KEY: "bad"}
    )
    assert result["errors"] == {CONF_POINT_KEY: "invalid_auth"}


async def test_flow_reports_rejected_webcam_key(hass, aioclient_mock) -> None:
    aioclient_mock.get(
        WEBCAMS_URL,
        status=401,
        json={"message": "Invalid API key", "error": "Unauthorized", "statusCode": 401},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_WEBCAMS_KEY: "bad"}
    )
    assert result["errors"] == {CONF_WEBCAMS_KEY: "invalid_auth"}


async def test_flow_other_400_is_not_a_key_error(hass, aioclient_mock) -> None:
    aioclient_mock.post(POINT_URL, status=400, json={"message": "Bad model"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_POINT_KEY: "fine"}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_flow_requires_a_key(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["errors"] == {"base": "no_keys"}


async def test_flow_model_without_data(hass, aioclient_mock) -> None:
    aioclient_mock.post(POINT_URL, status=204)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_POINT_KEY: "fine"}
    )
    assert result["errors"] == {"base": "model_no_data"}


async def test_flow_rejects_duplicate_location(hass) -> None:
    make_entry(**{CONF_MAP_KEY: MAP_SECRET}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_MAP_KEY: MAP_SECRET}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_reload_and_reject_bad_ids(hass, aioclient_mock) -> None:
    aioclient_mock.post(POINT_URL, json=weather_response(ptype=False))
    entry = make_entry(**{CONF_POINT_KEY: POINT_SECRET})
    await set_up(hass, entry)
    user_input = {
        CONF_MODEL: "canHrdps",
        CONF_AIR_QUALITY_MODEL: AIR_QUALITY_OFF,
        "point_interval_minutes": 60,
        "webcam_interval_minutes": 5,
        "webcam_radius_km": 50,
        CONF_WEBCAM_COUNT: 3,
    }
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**user_input, CONF_WEBCAM_IDS: "12,abc"}
    )
    assert result["errors"] == {CONF_WEBCAM_IDS: "invalid_webcam_ids"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**user_input, CONF_WEBCAM_IDS: "12, 34"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    body = aioclient_mock.mock_calls[-1][2]
    assert body["model"] == "canHrdps"
    # canHrdps doesn't support these, according to Windy's matrix.
    assert "ptype" not in body["parameters"]
    assert "snowPrecip" not in body["parameters"]


# Entities ------------------------------------------------------------------


async def test_weather_and_sensors(hass, aioclient_mock) -> None:
    aioclient_mock.post(POINT_URL, json=weather_response())
    await set_up(hass, make_entry(**{CONF_POINT_KEY: POINT_SECRET}))

    state = hass.states.get("weather.home")
    assert state is not None
    assert state.state == "rainy"
    assert state.attributes["temperature"] == pytest.approx(10.0)
    assert state.attributes["wind_bearing"] == pytest.approx(0.0)

    for forecast_type in ("hourly", "daily"):
        response = await hass.services.async_call(
            "weather",
            "get_forecasts",
            {"entity_id": "weather.home", "type": forecast_type},
            blocking=True,
            return_response=True,
        )
        forecast = response["weather.home"]["forecast"]
        assert forecast, forecast_type
        assert forecast[0]["condition"] == "rainy"
    assert forecast[1]["templow"] == pytest.approx(10.0)

    assert float(hass.states.get("sensor.home_temperature").state) == 10.0
    assert hass.states.get("sensor.home_temperature").attributes[
        "unit_of_measurement"
    ] == "°C"
    # 5 m/s, displayed in the metric default for wind sensors.
    wind = hass.states.get("sensor.home_wind_speed")
    assert wind.attributes["unit_of_measurement"] == "km/h"
    assert float(wind.state) == pytest.approx(18.0)
    assert float(hass.states.get("sensor.home_precipitation_next_24_hours").state) > 0
    # The model returned no visibility, so there is no dead sensor.
    assert hass.states.get("sensor.home_visibility") is None


async def test_air_quality_and_model_without_data(hass, aioclient_mock) -> None:
    entry = make_entry(**{CONF_POINT_KEY: POINT_SECRET})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={CONF_MODEL: "gfs", CONF_AIR_QUALITY_MODEL: "cams"}
    )
    aioclient_mock.post(POINT_URL, json=_aq_or_weather_first())
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.home_air_quality_index").state == "42.0"
    state = hass.states.get("sensor.home_pm2_5")
    assert state.attributes["device_class"] == "pm25"
    assert state.attributes["unit_of_measurement"] == "μg/m³"
    # An unexpected unit must not claim the device class.
    assert "device_class" not in hass.states.get("sensor.home_ozone").attributes


def _aq_or_weather_first() -> dict:
    data = weather_response()
    steps = len(data["ts"])
    data["units"] |= {
        "aqi_us-surface": None,
        "pm2p5-surface": "µg*m-3",
        "go3-surface": "kg*kg-1",
    }
    data["aqi_us-surface"] = [42.0] * steps
    data["pm2p5-surface"] = [8.0] * steps
    data["go3-surface"] = [1e-8] * steps
    return data


async def test_rejected_key_starts_reauth(hass, aioclient_mock) -> None:
    aioclient_mock.post(
        POINT_URL, status=400, json={"message": "Invalid API key", "statusCode": 400}
    )
    entry = make_entry(**{CONF_POINT_KEY: "revoked"})
    await set_up(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]

    aioclient_mock.clear_requests()
    aioclient_mock.post(POINT_URL, json=weather_response())
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {CONF_POINT_KEY: "new-key"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_POINT_KEY] == "new-key"
    assert entry.state is ConfigEntryState.LOADED


async def test_server_error_retries_setup(hass, aioclient_mock) -> None:
    aioclient_mock.post(POINT_URL, status=500, json={"message": "backend"})
    entry = make_entry(**{CONF_POINT_KEY: POINT_SECRET})
    await set_up(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_webcams_pick_closest_then_track_ids(hass, aioclient_mock) -> None:
    aioclient_mock.get(
        WEBCAMS_URL,
        json={
            "total": 3,
            "webcams": [
                webcam(1, 45.0),
                webcam(2, 43.91),
                {**webcam(3, 43.9), "status": "inactive"},
            ],
        },
    )
    entry = make_entry(**{CONF_WEBCAMS_KEY: WEBCAM_SECRET})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_WEBCAM_COUNT: 1}
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    first_url = aioclient_mock.mock_calls[0][1]
    assert first_url.query["nearby"] == "43.9000,-81.5700,50"
    state = hass.states.get("camera.home_cam_2")
    assert state is not None
    assert hass.states.get("camera.home_cam_1") is None
    assert hass.states.get("camera.home_cam_3") is None
    assert state.attributes["windy_url"] == "https://webcams.example/2"
    assert state.attributes["attribution"] == "Webcams provided by windy.com"

    await entry.runtime_data.webcams.async_refresh()
    assert aioclient_mock.mock_calls[-1][1].query["webcamIds"] == "2"


async def test_webcam_image_is_cached_and_recovers_from_expiry(
    hass, aioclient_mock
) -> None:
    aioclient_mock.get(
        WEBCAMS_URL, json={"total": 1, "webcams": [webcam(1, 43.91, IMAGE_1)]}
    )
    aioclient_mock.get(IMAGE_1, content=b"first")
    entry = make_entry(**{CONF_WEBCAMS_KEY: WEBCAM_SECRET})
    await set_up(hass, entry)
    component = hass.data["camera"]
    camera = component.get_entity("camera.home_cam_1")

    assert await camera.async_camera_image() == b"first"
    calls = aioclient_mock.call_count
    assert await camera.async_camera_image() == b"first"
    assert aioclient_mock.call_count == calls  # served from cache

    # The token expires while the coordinator still holds an old URL.
    aioclient_mock.clear_requests()
    aioclient_mock.get(WEBCAMS_URL, json={"webcams": [webcam(1, 43.91, IMAGE_2)]})
    aioclient_mock.get(IMAGE_2, content=b"second")
    aioclient_mock.get(IMAGE_1, status=401)
    camera._cached_url = None
    assert await camera.async_camera_image() == b"second"


async def test_map_config_and_static_files(
    hass, aioclient_mock, hass_ws_client, hass_client
) -> None:
    assert await async_setup_component(hass, "http", {})
    entry = make_entry(**{CONF_MAP_KEY: MAP_SECRET})
    await set_up(hass, entry)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "windy/map_config"})
    response = await ws.receive_json()
    assert response["success"]
    assert response["result"] == [
        {"title": "Home", "latitude": 43.9, "longitude": -81.57, "key": MAP_SECRET}
    ]

    client = await hass_client()
    for path in ("windy-cards.js", "map.html"):
        resp = await client.get(f"/windy_static/{path}")
        assert resp.status == 200
        assert MAP_SECRET not in await resp.text()


async def test_map_config_excludes_entries_without_map_key(
    hass, aioclient_mock, hass_ws_client
) -> None:
    aioclient_mock.get(WEBCAMS_URL, json={"webcams": []})
    await set_up(hass, make_entry(**{CONF_WEBCAMS_KEY: WEBCAM_SECRET}))
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "windy/map_config"})
    assert (await ws.receive_json())["result"] == []


async def test_diagnostics_and_logs_never_contain_keys(
    hass, aioclient_mock, caplog
) -> None:
    aioclient_mock.post(POINT_URL, json=weather_response())
    aioclient_mock.get(WEBCAMS_URL, status=500, text="oops")
    entry = make_entry(
        **{
            CONF_POINT_KEY: POINT_SECRET,
            CONF_MAP_KEY: MAP_SECRET,
            CONF_WEBCAMS_KEY: WEBCAM_SECRET,
        }
    )
    with caplog.at_level("DEBUG"):
        await set_up(hass, entry)
    aioclient_mock.clear_requests()
    aioclient_mock.post(POINT_URL, json=weather_response())
    aioclient_mock.get(WEBCAMS_URL, json={"webcams": []})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    text = str(await async_get_config_entry_diagnostics(hass, entry))
    for secret in (POINT_SECRET, MAP_SECRET, WEBCAM_SECRET):
        assert secret not in text
        assert secret not in caplog.text
    assert "43.9" not in text.replace("43.90", "")


async def test_unload(hass, aioclient_mock) -> None:
    aioclient_mock.post(POINT_URL, json=weather_response())
    entry = make_entry(**{CONF_POINT_KEY: POINT_SECRET})
    await set_up(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
