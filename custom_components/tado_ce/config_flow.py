"""Tado CE config flow — device authorization and options."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
import logging
from typing import TYPE_CHECKING, Any

from homeassistant import config_entries, data_entry_flow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .const import API_ENDPOINT_ME, AUTH_ENDPOINT_DEVICE, AUTH_ENDPOINT_TOKEN, CLIENT_ID, DATA_DIR, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry, ConfigFlowResult

_LOGGER = logging.getLogger(__name__)


class TadoCEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tado CE."""

    VERSION = 11

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._device_code: str | None = None
        self._user_code: str | None = None
        self._verify_url: str | None = None
        self._interval: int = 5
        self._expires_in: int = 300
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._homes: list[dict[str, Any]] = []
        self._check_count: int = 0

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TadoCEOptionsFlow:
        """Get the options flow for this handler."""
        return TadoCEOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step - start device authorization.

        Note: unique_id is set later in _create_entry() after we know the home_id.
        This allows for multi-home support in future versions.
        """
        # Don't set unique_id here - we don't know home_id yet
        # unique_id will be set in _create_entry() as tado_ce_{home_id}

        errors = {}

        if user_input is not None:
            try:
                await self._request_device_code()
                # Show URL for user to click
                return await self.async_step_authorize()
            except Exception:
                _LOGGER.exception("Failed to start authorization")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            errors=errors,
        )

    async def _request_device_code(self) -> None:
        """Request device code from Tado."""
        session = async_get_clientsession(self.hass)

        async with session.post(
            AUTH_ENDPOINT_DEVICE,
            data={
                "client_id": CLIENT_ID,
                "scope": "home.user offline_access",
            },
        ) as resp:
            if resp.status != HTTPStatus.OK:
                raise Exception(f"Failed to get device code: {resp.status}")

            data = await resp.json()
            self._device_code = data.get("device_code")
            self._user_code = data.get("user_code")
            self._verify_url = data.get("verification_uri_complete")
            # Workaround: Tado sometimes returns URL without /authorize path
            # See: https://github.com/hiall-fyi/tado_ce/issues/104
            if self._verify_url and "/device?" in self._verify_url and "/oauth2/" not in self._verify_url:
                self._verify_url = self._verify_url.replace(
                    "/device?",
                    "/device/authorize?",
                )
            self._interval = data.get("interval", 5)
            self._expires_in = data.get("expires_in", 300)

            if not self._device_code:
                raise Exception("No device code in response")

    async def async_step_authorize(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show authorization URL and wait for user to authorize."""
        errors = {}

        if user_input is not None:
            # User clicked Submit - check if they've authorized
            self._check_count += 1
            _LOGGER.debug("Checking authorization status (attempt %s)", self._check_count)

            result = await self._check_authorization()

            if result == "success":
                _LOGGER.info("Authorization successful!")
                return await self.async_step_select_home()
            if result == "pending":
                # Still waiting - show form again with hint
                errors["base"] = "auth_pending"
            elif result == "expired":
                return self.async_abort(reason="timeout")
            else:
                errors["base"] = "authorization_failed"

        return self.async_show_form(
            step_id="authorize",
            data_schema=vol.Schema({}),
            description_placeholders={
                "url": self._verify_url,  # type: ignore[dict-item]
            },
            errors=errors,
        )

    async def _check_authorization(self) -> str:
        """Check if user has completed authorization."""
        session = async_get_clientsession(self.hass)

        try:
            async with session.post(
                AUTH_ENDPOINT_TOKEN,
                data={
                    "client_id": CLIENT_ID,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": self._device_code,
                },
            ) as resp:
                _LOGGER.debug("Authorization check response status: %s", resp.status)

                if resp.status == HTTPStatus.OK:
                    data = await resp.json()
                    self._access_token = data.get("access_token")
                    self._refresh_token = data.get("refresh_token")

                    if self._access_token and self._refresh_token:
                        await self._fetch_homes()
                        return "success"
                    return "error"

                if resp.status == HTTPStatus.BAD_REQUEST:
                    data = await resp.json()
                    error = data.get("error", "")
                    _LOGGER.debug("Authorization check error: %s", error)

                    if error == "authorization_pending":
                        return "pending"
                    if error == "slow_down":
                        # Wait a bit before allowing next check
                        await asyncio.sleep(2)
                        return "pending"
                    if error == "expired_token":
                        return "expired"
                    _LOGGER.error("Authorization error: %s", error)
                    return "error"
                return "error"

        except Exception:
            _LOGGER.exception("Authorization check error")
            return "error"

    async def _fetch_homes(self) -> None:
        """Fetch available homes from Tado API."""
        session = async_get_clientsession(self.hass)

        async with session.get(
            API_ENDPOINT_ME,
            headers={"Authorization": f"Bearer {self._access_token}"},
        ) as resp:
            if resp.status != HTTPStatus.OK:
                raise Exception(f"Failed to fetch homes: {resp.status}")

            data = await resp.json()
            self._homes = data.get("homes", [])

    async def async_step_select_home(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle home selection (if multiple homes)."""
        if not self._homes:
            return self.async_abort(reason="no_homes")

        if len(self._homes) == 1:
            home = self._homes[0]
            return await self._create_entry(home["id"], home.get("name", "Tado Home"))

        if user_input is not None:
            home_id = user_input["home"]
            home_name = next(
                (h.get("name", "Tado Home") for h in self._homes if str(h["id"]) == home_id),
                "Tado Home",
            )
            return await self._create_entry(home_id, home_name)

        home_options = {str(home["id"]): home.get("name", f"Home {home['id']}") for home in self._homes}

        return self.async_show_form(
            step_id="select_home",
            data_schema=vol.Schema(
                {
                    vol.Required("home"): vol.In(home_options),
                },
            ),
        )

    async def _create_entry(self, home_id: str, home_name: str) -> ConfigFlowResult:
        """Create the config entry and save credentials."""
        # Set unique_id based on home_id for multi-home support
        await self.async_set_unique_id(f"tado_ce_{home_id}")
        self._abort_if_unique_id_configured()

        config = {
            "home_id": str(home_id),
            "refresh_token": self._refresh_token,
        }

        # Use executor to avoid blocking I/O in event loop
        await self.hass.async_add_executor_job(
            self._save_config_sync,
            config,
        )

        _LOGGER.info("Saved credentials for home: %s (ID: %s)", home_name, home_id)

        return self.async_create_entry(
            title=f"Tado CE ({home_name})",
            data={
                "home_id": str(home_id),
                "refresh_token": self._refresh_token,
            },
        )

    def _save_config_sync(self, config: dict[str, Any]) -> None:
        """Save config synchronously using atomic write.

        Performs blocking file I/O — call via ``hass.async_add_executor_job()``.

        Writes to per-home config file (config_{home_id}.json) only.
        """
        import json
        import shutil
        import tempfile

        from .const import get_data_file

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        home_id = config.get("home_id")

        if home_id:
            config_path = get_data_file("config", str(home_id))
        else:
            # No home_id — write to DATA_DIR/config.json as last resort
            config_path = DATA_DIR / "config.json"

        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=DATA_DIR,
            delete=False,
            suffix=".tmp",
        ) as tmp:
            json.dump(config, tmp, indent=2)
            temp_path = tmp.name
        shutil.move(temp_path, config_path)

    # ========== Reauth Flow (HA-triggered when ConfigEntryAuthFailed) ==========

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle HA-triggered reauthentication (ConfigEntryAuthFailed)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show reauth confirmation and start device authorization."""
        errors = {}

        if user_input is not None:
            try:
                await self._request_device_code()
                return await self.async_step_reauth_authorize()
            except Exception:
                _LOGGER.exception("Failed to start re-authorization")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({}),
            errors=errors,
        )

    async def async_step_reauth_authorize(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show authorization URL for reauth flow."""
        errors = {}

        if user_input is not None:
            self._check_count += 1
            _LOGGER.debug("Checking reauth authorization status (attempt %s)", self._check_count)

            result = await self._check_authorization()

            if result == "success":
                _LOGGER.info("Reauth authorization successful!")
                return await self._async_finish_reauth()
            if result == "pending":
                errors["base"] = "auth_pending"
            elif result == "expired":
                return self.async_abort(reason="timeout")
            else:
                errors["base"] = "authorization_failed"

        return self.async_show_form(
            step_id="reauth_authorize",
            data_schema=vol.Schema({}),
            description_placeholders={
                "url": self._verify_url,  # type: ignore[dict-item]
            },
            errors=errors,
        )

    async def _async_finish_reauth(self) -> ConfigFlowResult:
        """Save new credentials and finish reauth flow."""
        reauth_entry = self._get_reauth_entry()
        home_id = reauth_entry.data.get("home_id")

        # Save new credentials
        config = {
            "home_id": str(home_id),
            "refresh_token": self._refresh_token,
        }
        await self.hass.async_add_executor_job(self._save_config_sync, config)

        _LOGGER.info("Reauth successful, saved new credentials for home ID: %s", home_id)

        # Dismiss auth repair issue
        from .repairs import async_dismiss_auth_issue

        async_dismiss_auth_issue(self.hass, home_id)

        # Update entry data with new refresh token
        new_data = {**reauth_entry.data, "refresh_token": self._refresh_token}
        self.hass.config_entries.async_update_entry(reauth_entry, data=new_data)

        await self.hass.config_entries.async_reload(reauth_entry.entry_id)
        return self.async_abort(reason="reauth_successful")

    # ========== Reconfigure Flow (User-initiated re-authenticate) ==========

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle reconfiguration - allows re-authentication."""
        errors = {}

        if user_input is not None:
            try:
                await self._request_device_code()
                return await self.async_step_reconfigure_authorize()
            except Exception:
                _LOGGER.exception("Failed to start re-authorization")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({}),
            errors=errors,
        )

    async def async_step_reconfigure_authorize(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show authorization URL for reconfigure flow."""
        errors = {}

        if user_input is not None:
            self._check_count += 1
            _LOGGER.debug("Checking re-authorization status (attempt %s)", self._check_count)

            result = await self._check_authorization()

            if result == "success":
                _LOGGER.info("Re-authorization successful!")
                return await self.async_step_reconfigure_confirm()
            if result == "pending":
                errors["base"] = "auth_pending"
            elif result == "expired":
                return self.async_abort(reason="timeout")
            else:
                errors["base"] = "authorization_failed"

        return self.async_show_form(
            step_id="reconfigure_authorize",
            data_schema=vol.Schema({}),
            description_placeholders={
                "url": self._verify_url,  # type: ignore[dict-item]
            },
            errors=errors,
        )

    async def async_step_reconfigure_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Save new credentials and finish reconfigure."""
        # Get the existing config entry
        reconfigure_entry = self._get_reconfigure_entry()
        home_id = reconfigure_entry.data.get("home_id")

        # If we have homes from the new auth, verify the home still exists
        if self._homes:
            home_exists = any(str(h["id"]) == str(home_id) for h in self._homes)
            if not home_exists:
                # Home no longer exists, let user select a new one
                return await self.async_step_reconfigure_select_home()

        # Save new credentials (mkdir handled inside _save_config_sync)
        config = {
            "home_id": str(home_id),
            "refresh_token": self._refresh_token,
        }

        # Use executor to avoid blocking I/O in event loop
        await self.hass.async_add_executor_job(
            self._save_config_sync,
            config,
        )

        _LOGGER.info("Re-authentication successful, saved new credentials for home ID: %s", home_id)

        # Dismiss auth repair issue on successful re-auth
        from .repairs import async_dismiss_auth_issue

        async_dismiss_auth_issue(self.hass, home_id)

        # Store refresh_token in entry.data for HA-standard recovery
        new_data = {**reconfigure_entry.data, "refresh_token": self._refresh_token}
        self.hass.config_entries.async_update_entry(reconfigure_entry, data=new_data)

        # Finish reconfigure - this updates the existing entry
        return self.async_abort(reason="reconfigure_successful")

    async def async_step_reconfigure_select_home(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle home selection during reconfigure (if original home no longer exists)."""
        if not self._homes:
            return self.async_abort(reason="no_homes")

        if user_input is not None:
            home_id = user_input["home"]

            # Save new credentials with new home (mkdir handled inside _save_config_sync)
            config = {
                "home_id": str(home_id),
                "refresh_token": self._refresh_token,
            }

            # Use executor to avoid blocking I/O in event loop
            await self.hass.async_add_executor_job(
                self._save_config_sync,
                config,
            )

            _LOGGER.info("Re-authentication successful with new home ID: %s", home_id)

            # Store refresh_token in entry.data for HA-standard recovery
            reconfigure_entry = self._get_reconfigure_entry()
            new_data = {**reconfigure_entry.data, "home_id": str(home_id), "refresh_token": self._refresh_token}
            self.hass.config_entries.async_update_entry(reconfigure_entry, data=new_data)

            return self.async_abort(reason="reconfigure_successful")

        home_options = {str(home["id"]): home.get("name", f"Home {home['id']}") for home in self._homes}

        return self.async_show_form(
            step_id="reconfigure_select_home",
            data_schema=vol.Schema(
                {
                    vol.Required("home"): vol.In(home_options),
                },
            ),
        )


class TadoCEOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Tado CE with user mental model sections.

    Restructured into 4 sections based on user mental model:
    1. Tado CE Exclusive (collapsed) - CE-only features + Test Mode
    2. Tado Data (collapsed) - Extra API calls for Tado data
    3. Settings (collapsed) - Global default values
    4. Polling & API (collapsed) - API management

    CORE features (always ON, not in UI):
    - Zone Diagnostics, Device Controls, Boost Buttons, Environment Sensors

    Removed (Per-Zone handles these):
    - ufh_buffer_minutes, ufh_zones, adaptive_preheat_zones
    """

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options with user mental model sections."""
        errors = {}

        # Load zones with heatingPower for thermal_analytics_zones multi-select
        zones_with_heating_power = []
        coordinator = self.config_entry.runtime_data
        data_loader = coordinator.data_loader
        zones_info = await self.hass.async_add_executor_job(data_loader.load_zones_info_file)
        zones_data = await self.hass.async_add_executor_job(data_loader.load_zones_file)

        if zones_data and zones_info:
            zone_states = zones_data.get("zoneStates") or {}
            zone_names_map = {str(z.get("id")): z.get("name", f"Zone {z.get('id')}") for z in zones_info}

            for zone_id, zone_data in zone_states.items():
                activity_data = zone_data.get("activityDataPoints") or {}
                if activity_data.get("heatingPower") is not None:
                    zone_name = zone_names_map.get(zone_id, f"Zone {zone_id}")
                    zones_with_heating_power.append({"value": zone_id, "label": zone_name})

        if user_input is not None:
            processed_input = {}

            # Flatten tado_ce_exclusive section
            if "tado_ce_exclusive" in user_input:
                section = user_input["tado_ce_exclusive"]
                for key in [
                    "smart_comfort_enabled",
                    "thermal_analytics_enabled",
                    "thermal_analytics_zones",
                    "adaptive_preheat_enabled",
                    "schedule_calendar_enabled",
                    "zone_configuration_enabled",
                    "test_mode_enabled",
                ]:
                    if key in section:
                        processed_input[key] = section[key]

            # Flatten tado_data section
            if "tado_data" in user_input:
                section = user_input["tado_data"]
                for key in [
                    "weather_enabled",
                    "home_state_sync_enabled",
                    "mobile_devices_enabled",
                    "mobile_devices_frequent_sync",
                    "offset_enabled",
                ]:
                    if key in section:
                        processed_input[key] = section[key]

            # Flatten settings section
            if "settings" in user_input:
                section = user_input["settings"]
                settings_keys = [
                    "outdoor_temp_entity",
                    "hot_water_timer_duration",
                    "smart_comfort_mode",
                    "use_feels_like",
                    "mold_risk_window_type",
                    "smart_comfort_history_days",
                    "heating_cycle_history_days",
                    "heating_cycle_min_cycles",
                    "heating_cycle_inertia_threshold",
                ]
                for key in settings_keys:
                    if key in section:
                        processed_input[key] = section[key]

            # Flatten polling_api section
            if "polling_api" in user_input:
                section = user_input["polling_api"]
                polling_keys = [
                    "day_start_hour",
                    "night_start_hour",
                    "refresh_debounce_seconds",
                    "api_history_retention_days",
                    "quota_reserve_enabled",
                ]
                for key in polling_keys:
                    if key in section:
                        processed_input[key] = section[key]

                # Fix persistence bug - explicitly handle custom intervals
                # When user clears the field, HA doesn't include the key in section
                # We need to explicitly set None to clear the old value
                processed_input["custom_day_interval"] = section.get("custom_day_interval")
                processed_input["custom_night_interval"] = section.get("custom_night_interval")

            # Handle custom day interval (NumberSelector returns int or None)
            day_interval = processed_input.get("custom_day_interval")
            if day_interval is not None and (day_interval < 1 or day_interval > 1440):
                errors["custom_day_interval"] = "interval_out_of_range"
                processed_input["custom_day_interval"] = None

            # Handle custom night interval (NumberSelector returns int or None)
            night_interval = processed_input.get("custom_night_interval")
            if night_interval is not None and (night_interval < 1 or night_interval > 1440):
                errors["custom_night_interval"] = "interval_out_of_range"
                processed_input["custom_night_interval"] = None

            if not errors:
                # Save previous feature states for cleanup in async_reload_entry
                prev_options = self.config_entry.options

                from .entity_cleanup import detect_cleanup_flags

                cleanup_flags = detect_cleanup_flags(dict(prev_options), processed_input)

                if cleanup_flags:
                    # Store cleanup flags on coordinator (consumed after reload)
                    coordinator = self.config_entry.runtime_data
                    coordinator._pending_cleanup[self.config_entry.entry_id] = cleanup_flags

                return self.async_create_entry(title="", data=processed_input)

        options = self.config_entry.options
        custom_day_interval = options.get("custom_day_interval")
        custom_night_interval = options.get("custom_night_interval")

        # Fix persistence bug - use suggested_value instead of default
        # When using 'default', voluptuous auto-fills missing keys with the default value
        # This prevents users from clearing the field (clearing = key not sent = default used)
        # Using 'suggested_value' pre-fills the field but allows clearing to persist None
        if custom_day_interval is not None:
            custom_day_schema = vol.Optional(
                "custom_day_interval",
                description={"suggested_value": custom_day_interval},
            )
        else:
            custom_day_schema = vol.Optional("custom_day_interval")

        if custom_night_interval is not None:
            custom_night_schema = vol.Optional(
                "custom_night_interval",
                description={"suggested_value": custom_night_interval},
            )
        else:
            custom_night_schema = vol.Optional("custom_night_interval")

        current_thermal_zones = options.get("thermal_analytics_zones", [])
        if not current_thermal_zones and zones_with_heating_power:
            # Default: all zones enabled
            current_thermal_zones = [z["value"] for z in zones_with_heating_power]

        # Build thermal_analytics_zones selector (empty list if no zones available)
        thermal_zones_options = zones_with_heating_power or []

        # Extract defaults for cleaner schema definitions
        opt = options.get  # Shorthand
        smart_comfort_default = opt("smart_comfort_mode", opt("weather_compensation", "none"))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    # === Tado CE Exclusive (collapsed) ===
                    vol.Required("tado_ce_exclusive"): data_entry_flow.section(
                        vol.Schema(
                            {
                                vol.Optional(
                                    "smart_comfort_enabled",
                                    default=opt("smart_comfort_enabled", False),
                                ): BooleanSelector(),
                                vol.Optional(
                                    "thermal_analytics_enabled",
                                    default=opt("thermal_analytics_enabled", False),
                                ): BooleanSelector(),
                                # Per-zone Thermal Analytics control
                                vol.Optional(
                                    "thermal_analytics_zones",
                                    default=current_thermal_zones,
                                ): SelectSelector(
                                    SelectSelectorConfig(
                                        options=thermal_zones_options,  # type: ignore[typeddict-item]
                                        multiple=True,
                                        mode=SelectSelectorMode.DROPDOWN,
                                    ),
                                ),
                                vol.Optional(
                                    "adaptive_preheat_enabled",
                                    default=opt("adaptive_preheat_enabled", False),
                                ): BooleanSelector(),
                                vol.Optional(
                                    "schedule_calendar_enabled",
                                    default=opt("schedule_calendar_enabled", False),
                                ): BooleanSelector(),
                                vol.Optional(
                                    "zone_configuration_enabled",
                                    default=opt("zone_configuration_enabled", False),
                                ): BooleanSelector(),
                                vol.Optional(
                                    "test_mode_enabled",
                                    default=opt("test_mode_enabled", False),
                                ): BooleanSelector(),
                            },
                        ),
                        {"collapsed": True},
                    ),
                    # === Tado Data (collapsed) ===
                    vol.Required("tado_data"): data_entry_flow.section(
                        vol.Schema(
                            {
                                vol.Optional(
                                    "weather_enabled",
                                    default=opt("weather_enabled", False),
                                ): BooleanSelector(),
                                vol.Optional(
                                    "home_state_sync_enabled",
                                    default=opt("home_state_sync_enabled", False),
                                ): BooleanSelector(),
                                vol.Optional(
                                    "mobile_devices_enabled",
                                    default=opt("mobile_devices_enabled", False),
                                ): BooleanSelector(),
                                vol.Optional(
                                    "mobile_devices_frequent_sync",
                                    default=opt("mobile_devices_frequent_sync", False),
                                ): BooleanSelector(),
                                vol.Optional(
                                    "offset_enabled",
                                    default=opt("offset_enabled", False),
                                ): BooleanSelector(),
                            },
                        ),
                        {"collapsed": True},
                    ),
                    # === Settings (collapsed) ===
                    vol.Required("settings"): data_entry_flow.section(
                        vol.Schema(
                            {
                                # General
                                vol.Optional(
                                    "outdoor_temp_entity",
                                    default=opt("outdoor_temp_entity", ""),
                                ): EntitySelector(EntitySelectorConfig(domain=["sensor", "weather"])),
                                vol.Optional(
                                    "hot_water_timer_duration",
                                    default=opt("hot_water_timer_duration", 60),
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=1,
                                        max=1440,
                                        step=1,
                                        mode=NumberSelectorMode.BOX,
                                        unit_of_measurement="min",
                                    ),
                                ),
                                # Smart Comfort defaults (Per-Zone can override)
                                vol.Optional(
                                    "smart_comfort_mode",
                                    default=smart_comfort_default,
                                ): SelectSelector(
                                    SelectSelectorConfig(
                                        options=["none", "light", "moderate", "aggressive"],
                                        translation_key="smart_comfort_mode",
                                        mode=SelectSelectorMode.DROPDOWN,
                                    ),
                                ),
                                vol.Optional(
                                    "use_feels_like",
                                    default=opt("use_feels_like", False),
                                ): BooleanSelector(),
                                vol.Optional(
                                    "mold_risk_window_type",
                                    default=opt("mold_risk_window_type", "double_pane"),
                                ): SelectSelector(
                                    SelectSelectorConfig(
                                        options=["single_pane", "double_pane", "triple_pane", "passive_house"],
                                        translation_key="mold_risk_window_type",
                                        mode=SelectSelectorMode.DROPDOWN,
                                    ),
                                ),
                                vol.Optional(
                                    "smart_comfort_history_days",
                                    default=opt("smart_comfort_history_days", 7),
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=1,
                                        max=30,
                                        step=1,
                                        mode=NumberSelectorMode.BOX,
                                        unit_of_measurement="d",
                                    ),
                                ),
                                # Thermal Analytics settings
                                vol.Optional(
                                    "heating_cycle_history_days",
                                    default=opt("heating_cycle_history_days", 7),
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=1,
                                        max=30,
                                        step=1,
                                        mode=NumberSelectorMode.BOX,
                                        unit_of_measurement="d",
                                    ),
                                ),
                                vol.Optional(
                                    "heating_cycle_min_cycles",
                                    default=opt("heating_cycle_min_cycles", 3),
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=1,
                                        max=10,
                                        step=1,
                                        mode=NumberSelectorMode.BOX,
                                    ),
                                ),
                                vol.Optional(
                                    "heating_cycle_inertia_threshold",
                                    default=opt("heating_cycle_inertia_threshold", 0.1),
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=0.05,
                                        max=0.5,
                                        step=0.05,
                                        mode=NumberSelectorMode.BOX,
                                        unit_of_measurement="°C",
                                    ),
                                ),
                            },
                        ),
                        {"collapsed": True},
                    ),
                    # === Polling & API (collapsed) ===
                    vol.Required("polling_api"): data_entry_flow.section(
                        vol.Schema(
                            {
                                vol.Required(
                                    "day_start_hour",
                                    default=opt("day_start_hour", 7),
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=0,
                                        max=23,
                                        step=1,
                                        mode=NumberSelectorMode.BOX,
                                    ),
                                ),
                                vol.Required(
                                    "night_start_hour",
                                    default=opt("night_start_hour", 23),
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=0,
                                        max=23,
                                        step=1,
                                        mode=NumberSelectorMode.BOX,
                                    ),
                                ),
                                custom_day_schema: NumberSelector(
                                    NumberSelectorConfig(
                                        min=1,
                                        max=1440,
                                        step=1,
                                        mode=NumberSelectorMode.BOX,
                                        unit_of_measurement="min",
                                    ),
                                ),
                                custom_night_schema: NumberSelector(
                                    NumberSelectorConfig(
                                        min=1,
                                        max=1440,
                                        step=1,
                                        mode=NumberSelectorMode.BOX,
                                        unit_of_measurement="min",
                                    ),
                                ),
                                vol.Optional(
                                    "refresh_debounce_seconds",
                                    default=opt("refresh_debounce_seconds", 15),
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=1,
                                        max=60,
                                        step=1,
                                        mode=NumberSelectorMode.BOX,
                                        unit_of_measurement="s",
                                    ),
                                ),
                                vol.Optional(
                                    "api_history_retention_days",
                                    default=opt("api_history_retention_days", 14),
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=0,
                                        max=365,
                                        step=1,
                                        mode=NumberSelectorMode.BOX,
                                        unit_of_measurement="d",
                                    ),
                                ),
                                vol.Optional(
                                    "quota_reserve_enabled",
                                    default=opt("quota_reserve_enabled", True),
                                ): BooleanSelector(),
                            },
                        ),
                        {"collapsed": True},
                    ),
                },
            ),
            errors=errors,
        )
