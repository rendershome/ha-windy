"""Config flow for the Windy integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_LATITUDE, CONF_LOCATION, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    LocationSelector,
    LocationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import parse_webcam_ids
from .api import (
    WindyAuthError,
    WindyError,
    WindyNoData,
    fetch_point_forecast,
    fetch_webcams,
)
from .const import (
    AIR_QUALITY_LABELS,
    CONF_AIR_QUALITY_MODEL,
    CONF_MAP_KEY,
    CONF_MODEL,
    CONF_POINT_INTERVAL,
    CONF_POINT_KEY,
    CONF_WEBCAM_COUNT,
    CONF_WEBCAM_IDS,
    CONF_WEBCAM_INTERVAL,
    CONF_WEBCAM_RADIUS,
    CONF_WEBCAMS_KEY,
    DEFAULT_AIR_QUALITY_MODEL,
    DEFAULT_MODEL,
    DEFAULT_POINT_INTERVAL,
    DEFAULT_WEBCAM_COUNT,
    DEFAULT_WEBCAM_INTERVAL,
    DEFAULT_WEBCAM_RADIUS,
    DOMAIN,
    MAX_WEBCAM_RADIUS,
    MAX_WEBCAMS,
    MODEL_LABELS,
    MODEL_PARAMETERS,
)

KEY_FIELDS = (CONF_POINT_KEY, CONF_MAP_KEY, CONF_WEBCAMS_KEY)
_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _number(minimum: int, maximum: int, unit: str | None = None) -> NumberSelector:
    config = NumberSelectorConfig(
        min=minimum, max=maximum, step=1, mode=NumberSelectorMode.BOX
    )
    if unit:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _keys_schema(defaults: Mapping[str, Any]) -> dict[Any, Any]:
    return {
        vol.Optional(field, description={"suggested_value": defaults.get(field)}): (
            _PASSWORD
        )
        for field in KEY_FIELDS
    }


async def _validate_keys(
    hass: HomeAssistant,
    data: Mapping[str, Any],
    lat: float,
    lon: float,
    model: str,
) -> dict[str, str]:
    """Check keys against Windy. The map key only works in a browser."""
    errors: dict[str, str] = {}
    if not any(data.get(field) for field in KEY_FIELDS):
        return {"base": "no_keys"}
    session = async_get_clientsession(hass)
    if key := data.get(CONF_POINT_KEY):
        try:
            await fetch_point_forecast(
                session, key, lat, lon, model, MODEL_PARAMETERS[model]
            )
        except WindyAuthError:
            errors[CONF_POINT_KEY] = "invalid_auth"
        except WindyNoData:
            errors["base"] = "model_no_data"
        except WindyError:
            errors["base"] = "cannot_connect"
    if key := data.get(CONF_WEBCAMS_KEY):
        try:
            await fetch_webcams(session, key, nearby=(lat, lon, 1), limit=1)
        except WindyAuthError:
            errors[CONF_WEBCAMS_KEY] = "invalid_auth"
        except WindyError:
            errors["base"] = "cannot_connect"
    return errors


class WindyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Windy."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> WindyOptionsFlow:
        """Return the options flow."""
        return WindyOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a location."""
        errors: dict[str, str] = {}
        if user_input is not None:
            location = user_input[CONF_LOCATION]
            lat, lon = location[CONF_LATITUDE], location[CONF_LONGITUDE]
            await self.async_set_unique_id(f"{lat:.2f}_{lon:.2f}")
            self._abort_if_unique_id_configured()
            model = user_input[CONF_MODEL]
            errors = await _validate_keys(self.hass, user_input, lat, lon, model)
            if not errors:
                data = {CONF_LATITUDE: lat, CONF_LONGITUDE: lon}
                for field in KEY_FIELDS:
                    if user_input.get(field):
                        data[field] = user_input[field].strip()
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=data,
                    options={CONF_MODEL: model},
                )

        # Offer the keys from an existing location, so they aren't re-typed.
        defaults: dict[str, Any] = dict(user_input or {})
        if user_input is None:
            for entry in self._async_current_entries(include_ignore=False):
                defaults.update(
                    {f: entry.data[f] for f in KEY_FIELDS if f in entry.data}
                )
        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME,
                        default=defaults.get(CONF_NAME, self.hass.config.location_name),
                    ): str,
                    vol.Required(
                        CONF_LOCATION,
                        default=defaults.get(
                            CONF_LOCATION,
                            {
                                CONF_LATITUDE: self.hass.config.latitude,
                                CONF_LONGITUDE: self.hass.config.longitude,
                            },
                        ),
                    ): LocationSelector(LocationSelectorConfig(radius=False)),
                    vol.Required(
                        CONF_MODEL, default=defaults.get(CONF_MODEL, DEFAULT_MODEL)
                    ): _model_selector(),
                    **_keys_schema(defaults),
                }
            ),
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Ask for keys after Windy rejects one."""
        return await self.async_step_keys()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change keys on request."""
        return await self.async_step_keys()

    async def async_step_keys(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and validate the API key form."""
        entry = (
            self._get_reauth_entry()
            if self.source == SOURCE_REAUTH
            else self._get_reconfigure_entry()
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _validate_keys(
                self.hass,
                user_input,
                entry.data[CONF_LATITUDE],
                entry.data[CONF_LONGITUDE],
                entry.options.get(CONF_MODEL, DEFAULT_MODEL),
            )
            if not errors:
                data = {k: v for k, v in entry.data.items() if k not in KEY_FIELDS}
                for field in KEY_FIELDS:
                    if user_input.get(field):
                        data[field] = user_input[field].strip()
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="keys",
            errors=errors,
            data_schema=vol.Schema(_keys_schema(user_input or entry.data)),
        )


def _select(labels: dict[str, str]) -> SelectSelector:
    # Windy's mixed-case model names aren't valid translation keys, so the
    # labels are set here instead of in translations.
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=value, label=label)
                for value, label in labels.items()
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _model_selector() -> SelectSelector:
    return _select(MODEL_LABELS)


class WindyOptionsFlow(OptionsFlowWithReload):
    """Change how a location is polled."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options form."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                ids = parse_webcam_ids(user_input.get(CONF_WEBCAM_IDS))
            except ValueError:
                errors[CONF_WEBCAM_IDS] = "invalid_webcam_ids"
            else:
                if len(ids) > MAX_WEBCAMS:
                    errors[CONF_WEBCAM_IDS] = "invalid_webcam_ids"
            if not errors:
                return self.async_create_entry(data=user_input)

        options = user_input or self.config_entry.options
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MODEL, default=options.get(CONF_MODEL, DEFAULT_MODEL)
                    ): _model_selector(),
                    vol.Required(
                        CONF_AIR_QUALITY_MODEL,
                        default=options.get(
                            CONF_AIR_QUALITY_MODEL, DEFAULT_AIR_QUALITY_MODEL
                        ),
                    ): _select(AIR_QUALITY_LABELS),
                    vol.Required(
                        CONF_POINT_INTERVAL,
                        default=options.get(
                            CONF_POINT_INTERVAL, DEFAULT_POINT_INTERVAL
                        ),
                    ): _number(10, 360, "min"),
                    vol.Required(
                        CONF_WEBCAM_INTERVAL,
                        default=options.get(
                            CONF_WEBCAM_INTERVAL, DEFAULT_WEBCAM_INTERVAL
                        ),
                    ): _number(5, 60, "min"),
                    vol.Required(
                        CONF_WEBCAM_RADIUS,
                        default=options.get(CONF_WEBCAM_RADIUS, DEFAULT_WEBCAM_RADIUS),
                    ): _number(1, MAX_WEBCAM_RADIUS, "km"),
                    vol.Required(
                        CONF_WEBCAM_COUNT,
                        default=options.get(CONF_WEBCAM_COUNT, DEFAULT_WEBCAM_COUNT),
                    ): _number(0, MAX_WEBCAMS),
                    vol.Optional(
                        CONF_WEBCAM_IDS,
                        description={
                            "suggested_value": options.get(CONF_WEBCAM_IDS)
                        },
                    ): str,
                }
            ),
        )
