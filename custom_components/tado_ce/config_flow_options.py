"""Options flow for Tado CE."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    DOMAIN,
    OVERLAY_MODE_DEFAULT,
    OVERLAY_MODE_OPTIONS,
    TIMER_DURATION_DEFAULT,
    TIMER_DURATION_MIN,
    TIMER_DURATION_MAX,
    WINDOW_DETECTION_MODE_DEFAULT,
    WINDOW_DETECTION_MODE_OPTIONS,
    WINDOW_SENSITIVITY_DEFAULT,
    WINDOW_SENSITIVITY_OPTIONS,
    SURFACE_TEMP_OFFSET_MIN,
    SURFACE_TEMP_OFFSET_MAX,
    SURFACE_TEMP_OFFSET_STEP,
    _ALL_TOGGLE_KEYS,
    RESET_DEFAULTS,
    _RESET_SCOPE_OPTIONS,
)
from .helpers import is_climate_zone

_LOGGER = logging.getLogger(__name__)


class TadoCEOptionsFlow(config_entries.OptionsFlow):
    """Handle Tado CE options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self._pending_general_options: dict[str, Any] = {}
        self._selected_zone_id: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options main entry point."""
        errors: dict[str, str] = {}
        options = self.config_entry.options

        if user_input is not None:
            self._pending_general_options = {}
            self._process_smart_comfort(user_input, self._pending_general_options)
            self._process_polling_api(user_input, self._pending_general_options, errors)
            self._process_internet_bridge(user_input, self._pending_general_options)
            self._process_weather_compensation(user_input, self._pending_general_options, errors)

            self._pending_general_options = {**options, **self._pending_general_options}

            if not errors:
                redirect = await self._detect_first_enable(self._pending_general_options)
                if redirect:
                    return await getattr(self, f"async_step_{redirect}")()

                return self.async_create_entry(title="", data=self._pending_general_options)

        homekit_status = "Unknown"  # Dynamisch op te halen indien gewenst

        # Hoofdschema placeholder voor de initiele form weergave
        schema = vol.Schema({})

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={"homekit_status": homekit_status},
        )

    async def _detect_first_enable(self, options: dict[str, Any]) -> str | None:
        """Detect if a feature requires a setup wizard redirect."""
        if options.get("enable_bridge") and not options.get("bridge_serial"):
            return "bridge_setup"
        if options.get("enable_homekit") and not options.get("homekit_paired"):
            return "homekit_pairing"
        return None

    def _process_smart_comfort(
        self, user_input: dict[str, Any], processed_input: dict[str, Any]
    ) -> None:
        """Process smart comfort section."""
        if "smart_comfort" in user_input:
            section = user_input["smart_comfort"]
            for key in (
                "use_outdoor_temp_entity",
                "outdoor_temp_entity",
                "smart_comfort_mode",
                "use_feels_like",
                "mold_risk_window_type",
                "smart_comfort_history_days",
            ):
                if key in section:
                    processed_input[key] = section[key]

    def _process_polling_api(
        self, user_input: dict[str, Any], processed_input: dict[str, Any], errors: dict[str, str]
    ) -> None:
        """Process polling and API section."""
        if "polling_api" in user_input:
            section = user_input["polling_api"]
            for key in (
                "day_start_hour",
                "night_start_hour",
                "custom_day_interval",
                "custom_night_interval",
                "presence_min_refresh_minutes",
                "weather_min_refresh_minutes",
                "mobile_devices_frequent_sync",
                "mobile_devices_min_refresh_minutes",
                "refresh_debounce_seconds",
                "api_history_retention_days",
                "smart_actions_debounce_seconds",
                "device_sync_delay_seconds",
                "hot_water_timer_duration",
            ):
                if key in section:
                    processed_input[key] = section[key]

    def _process_internet_bridge(
        self, user_input: dict[str, Any], processed_input: dict[str, Any]
    ) -> None:
        """Process internet bridge section."""
        if "internet_bridge" in user_input:
            section = user_input["internet_bridge"]
            for key in ("bridge_serial", "bridge_auth_key"):
                if key in section:
                    processed_input[key] = section[key]

    def _process_weather_compensation(
        self, user_input: dict[str, Any], processed_input: dict[str, Any], errors: dict[str, str]
    ) -> None:
        """Process weather compensation section."""
        if "weather_compensation" in user_input:
            section = user_input["weather_compensation"]
            for key in (
                "wc_heating_system_preset",
                "wc_slope",
                "wc_design_outdoor_temp",
                "wc_max_flow_temp",
                "wc_min_flow_temp",
                "wc_shutoff_temp",
                "wc_smoothing_method",
                "wc_smoothing_window",
                "wc_room_compensation_enabled",
                "wc_room_compensation_factor",
                "wc_step_size",
                "wc_hysteresis",
            ):
                if key in section:
                    processed_input[key] = section[key]

    async def _load_zones_with_heating_power(self) -> list[dict[str, str]]:
        """Load zones that have heating capabilities from coordinator data."""
        coordinator = self.config_entry.runtime_data
        zones = []
        if hasattr(coordinator, "zones") and coordinator.zones:
            for zone_id, zone_data in coordinator.zones.items():
                if is_climate_zone(zone_data):
                    zones.append({"value": str(zone_id), "label": zone_data.get("name", f"Zone {zone_id}")})
        elif hasattr(coordinator, "data") and isinstance(coordinator.data, dict) and "zones" in coordinator.data:
            for zone_id, zone_data in coordinator.data["zones"].items():
                zones.append({"value": str(zone_id), "label": zone_data.get("name", f"Zone {zone_id}")})
        return zones

    async def async_step_bridge_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step to configure the Internet Bridge credentials upon first enable."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._pending_general_options["bridge_serial"] = user_input["bridge_serial"]
            self._pending_general_options["bridge_auth_key"] = user_input["bridge_auth_key"]

            redirect = await self._detect_first_enable(self._pending_general_options)
            if redirect:
                return await getattr(self, f"async_step_{redirect}")()

            return self.async_create_entry(title="", data=self._pending_general_options)

        schema = vol.Schema(
            {
                vol.Required("bridge_serial"): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                vol.Required("bridge_auth_key"): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            }
        )
        return self.async_show_form(
            step_id="bridge_setup",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_homekit_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step to pair HomeKit locally if first enabled."""
        errors: dict[str, str] = {}
        if user_input is not None:
            from .homekit_client import HomeKitClient
            client = HomeKitClient(
                self.hass, self.config_entry.data.get("home_id") or "default",
            )
            try:
                await client.async_pair(user_input["pairing_pin"])

                redirect = await self._detect_first_enable(self._pending_general_options)
                if redirect:
                    return await getattr(self, f"async_step_{redirect}")()

                return self.async_create_entry(title="", data=self._pending_general_options)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("HomeKit pairing failed")
                errors["base"] = "homekit_pairing_failed"

        schema = vol.Schema(
            {
                vol.Required("pairing_pin"): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            }
        )
        return self.async_show_form(
            step_id="homekit_pairing",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_wc_bridge_prompt(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt user that weather compensation requires bridge setup."""
        if user_input is not None:
            return await self.async_step_bridge_setup()

        return self.async_show_form(
            step_id="wc_bridge_prompt",
            data_schema=vol.Schema({}),
        )

    async def async_step_homekit_unpair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle unpairing from HomeKit local connection."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get("confirm_unpair", False):
                from .homekit_client import HomeKitClient
                client = HomeKitClient(
                    self.hass, self.config_entry.data.get("home_id") or "default",
                )
                try:
                    await client.async_unpair()
                    return self.async_create_entry(title="", data=self.config_entry.options)
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("HomeKit unpairing failed")
                    errors["base"] = "homekit_unpair_failed"
            else:
                return await self.async_step_init()

        return self.async_show_form(
            step_id="homekit_unpair",
            data_schema=vol.Schema({vol.Required("confirm_unpair", default=False): BooleanSelector()}),
            errors=errors,
        )

    async def async_step_zone_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a zone to configure specific offset and overlay overrides."""
        if user_input is not None:
            self._selected_zone_id = user_input["zone_id"]
            return await self.async_step_zone_settings()

        zones_with_heating_power = await self._load_zones_with_heating_power()
        schema = vol.Schema(
            {
                vol.Required("zone_id"): SelectSelector(
                    SelectSelectorConfig(
                        options=zones_with_heating_power,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="zone_config",
            data_schema=schema,
        )

    async def async_step_zone_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure parameters for the selected zone."""
        errors: dict[str, str] = {}
        zone_id = self._selected_zone_id
        options = self.config_entry.options
        zone_key = f"zone_{zone_id}_"

        if user_input is not None:
            new_options = dict(options)
            for k, v in user_input.items():
                new_options[f"{zone_key}{k}"] = v
            return self.async_create_entry(title="", data=new_options)

        schema = vol.Schema(
            {
                vol.Optional(
                    "overlay_mode",
                    default=options.get(f"{zone_key}overlay_mode", OVERLAY_MODE_DEFAULT),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=OVERLAY_MODE_OPTIONS,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="overlay_mode",
                    )
                ),
                vol.Optional(
                    "overlay_duration",
                    default=options.get(f"{zone_key}overlay_duration", TIMER_DURATION_DEFAULT),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=TIMER_DURATION_MIN,
                        max=TIMER_DURATION_MAX,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Optional(
                    "window_detection_mode",
                    default=options.get(f"{zone_key}window_detection_mode", WINDOW_DETECTION_MODE_DEFAULT),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=WINDOW_DETECTION_MODE_OPTIONS,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="window_detection_mode",
                    )
                ),
                vol.Optional(
                    "window_sensitivity",
                    default=options.get(f"{zone_key}window_sensitivity", WINDOW_SENSITIVITY_DEFAULT),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=WINDOW_SENSITIVITY_OPTIONS,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="window_sensitivity",
                    )
                ),
                vol.Optional(
                    "surface_temp_offset",
                    default=options.get(f"{zone_key}surface_temp_offset", 0.0),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=SURFACE_TEMP_OFFSET_MIN,
                        max=SURFACE_TEMP_OFFSET_MAX,
                        step=SURFACE_TEMP_OFFSET_STEP,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="zone_settings",
            data_schema=schema,
            errors=errors,
            description_placeholders={"zone_id": zone_id or ""},
        )

    async def async_step_reset_to_defaults(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reset configuration parameters to factory defaults by scope."""
        if user_input is not None:
            scope = user_input["reset_scope"]
            new_options = dict(self.config_entry.options)

            if scope == "everything":
                for key in _ALL_TOGGLE_KEYS:
                    new_options[key] = False
                for scope_key, defaults in RESET_DEFAULTS.items():
                    for k, v in defaults.items():
                        new_options[k] = v
            elif scope in RESET_DEFAULTS:
                for k, v in RESET_DEFAULTS[scope].items():
                    new_options[k] = v

            return self.async_create_entry(title="", data=new_options)

        schema = vol.Schema(
            {
                vol.Required("reset_scope", default="everything"): SelectSelector(
                    SelectSelectorConfig(
                        options=_RESET_SCOPE_OPTIONS,
                        translation_key="reset_scope",
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="reset_to_defaults",
            data_schema=schema,
        )
