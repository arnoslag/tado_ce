"""Tado CE API Auth Mixin — token management and config I/O.

Provides OAuth token refresh, config file loading/saving, and token
caching logic. Designed as a mixin class for TadoApiClient.
"""

from __future__ import annotations

import asyncio  # noqa: TC003 — used in Protocol class body annotation
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

import aiohttp

from .const import CLIENT_ID, CONFIG_FILE, TADO_AUTH_URL
from .exceptions import TadoAuthError

if TYPE_CHECKING:
    from pathlib import Path

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .data_loader import DataLoader

_LOGGER = logging.getLogger(__name__)


class _AuthHost(Protocol):
    """Protocol describing attributes the auth mixin expects on its host class.

    Includes both host-provided attributes (from TadoApiClient.__init__)
    and mixin-provided members so ``self: _AuthHost`` resolves everywhere.
    """

    # --- Host-provided attributes ---
    _session: aiohttp.ClientSession
    _hass: HomeAssistant | None
    _access_token: str | None
    _token_expiry: datetime | None
    _refresh_lock: asyncio.Lock
    _home_id: str | None
    _injected_refresh_token: str | None
    _data_loader: DataLoader | None
    _config_entry: ConfigEntry | None

    def _get_data_file(self, base_name: str) -> Path: ...

    # --- Mixin-provided members (for cross-method calls) ---
    TOKEN_CACHE_DURATION: int

    async def _load_config(self) -> dict[str, Any]: ...
    async def _save_config(self, config: dict[str, Any]) -> None: ...
    async def _refresh_token(self) -> str | None: ...


class TadoAuthMixin:
    """Mixin providing OAuth token management and config file I/O.

    The host class must satisfy the ``_AuthHost`` protocol — i.e. provide
    ``_session``, ``_hass``, ``_home_id``, ``_get_data_file()``, etc.
    See ``_AuthHost`` for the full contract.
    """

    # Explicit type so mypy doesn't narrow from the datetime assignment in _refresh_token.
    _token_expiry: datetime | None

    # Token cache duration (5 minutes to be safe, Tado tokens valid for ~10 minutes)
    TOKEN_CACHE_DURATION = 300

    # --- Config I/O ---

    async def _load_config(self: _AuthHost) -> dict[str, Any]:
        """Load config from file using native async I/O.

        Uses per-home config file (config_{home_id}.json) when home_id is set.
        Falls back to DATA_DIR/config.json when no home_id (bootstrap only).
        If refresh_token was injected via constructor, it takes precedence.
        """
        try:
            # Use per-home config file when home_id is available
            if self._home_id:
                config_path = self._get_data_file("config")
            else:
                config_path = CONFIG_FILE

            if not await self._hass.async_add_executor_job(config_path.exists):  # type: ignore[union-attr]
                result: dict[str, Any] = {"home_id": self._home_id, "refresh_token": None}
                # Use injected refresh_token if available
                if self._injected_refresh_token:
                    result["refresh_token"] = self._injected_refresh_token
                return result

            content: str = await self._hass.async_add_executor_job(  # type: ignore[union-attr]
                config_path.read_text,
            )
            config: dict[str, Any] = json.loads(content)
            # Cache home_id when loading config
            if config.get("home_id"):
                self._home_id = config["home_id"]
            # Injected refresh_token takes precedence
            if self._injected_refresh_token:
                config["refresh_token"] = self._injected_refresh_token
            return config
        except (OSError, json.JSONDecodeError, KeyError):
            _LOGGER.exception("Failed to load config")
            result = {"home_id": self._home_id, "refresh_token": None}
            if self._injected_refresh_token:
                result["refresh_token"] = self._injected_refresh_token
            return result

    async def _save_config(self: _AuthHost, config: dict[str, Any]) -> None:
        """Save config to file atomically using native async I/O.

        Writes to per-home config file (config_{home_id}.json) when home_id
        is set. Falls back to DATA_DIR/config.json when no home_id.
        Per-home isolation prevents token rotation for one home from
        corrupting another home's config.
        """
        try:
            # Use per-home config file when home_id is available
            if self._home_id:
                config_path = self._get_data_file("config")
            else:
                config_path = CONFIG_FILE

            await self._hass.async_add_executor_job(  # type: ignore[union-attr]
                lambda: config_path.parent.mkdir(parents=True, exist_ok=True),
            )

            temp_path = config_path.with_suffix(".tmp")
            content = json.dumps(config, indent=2)
            await self._hass.async_add_executor_job(  # type: ignore[union-attr]
                temp_path.write_text,
                content,
            )

            # Atomic move
            await self._hass.async_add_executor_job(  # type: ignore[union-attr]
                temp_path.replace,
                config_path,
            )

            # Write-through: update DataLoader cache
            if self._data_loader is not None:
                self._data_loader.update_cache("config", config)
        except OSError:
            _LOGGER.exception("Failed to save config")

    # --- Token Management ---

    async def get_access_token(self: _AuthHost) -> str | None:
        """Get valid access token with automatic refresh.

        Uses lock to prevent concurrent token refreshes which would
        waste API calls and potentially cause race conditions.

        Returns:
            Valid access token, or None if refresh failed.
        """
        # All token checks must be inside lock to prevent race condition
        async with self._refresh_lock:
            # Check if cached token still valid (with 10s buffer for clock skew)
            if self._access_token and self._token_expiry:
                if datetime.now(UTC) < (self._token_expiry - timedelta(seconds=10)):
                    return self._access_token

            # Token expired or missing, refresh it
            return await self._refresh_token()

    async def _refresh_token(self: _AuthHost) -> str | None:
        """Refresh access token using refresh token."""
        config = await self._load_config()
        refresh_token = config.get("refresh_token")

        if not refresh_token:
            _LOGGER.error("No refresh token available")
            return None

        _LOGGER.debug("Refreshing access token...")

        try:
            async with self._session.post(
                f"{TADO_AUTH_URL}/token",
                data={
                    "client_id": CLIENT_ID,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            ) as resp:
                if resp.status != HTTPStatus.OK:
                    error_text = await resp.text()
                    _LOGGER.error("Token refresh failed: %s - %s", resp.status, error_text)
                    if "invalid_grant" in error_text:
                        _LOGGER.error("Refresh token expired - user must re-authenticate")
                        config["refresh_token"] = None
                        await self._save_config(config)
                        raise TadoAuthError("Refresh token expired (invalid_grant)")
                    return None

                data = await resp.json()
                self._access_token = data.get("access_token")
                new_refresh_token = data.get("refresh_token")

                if not self._access_token:
                    _LOGGER.error("No access token in response")
                    return None

                # Save new refresh token if rotated
                if new_refresh_token and new_refresh_token != refresh_token:
                    config["refresh_token"] = new_refresh_token
                    await self._save_config(config)
                    # Update in-memory injected token so _load_config() uses the new one
                    self._injected_refresh_token = new_refresh_token
                    # Persist to ConfigEntry.data so token survives HA restarts
                    if self._hass and self._config_entry:
                        new_data = {**self._config_entry.data, "refresh_token": new_refresh_token}
                        self._hass.config_entries.async_update_entry(self._config_entry, data=new_data)
                    _LOGGER.debug("Refresh token rotated and saved")

                self._token_expiry = datetime.now(UTC) + timedelta(seconds=self.TOKEN_CACHE_DURATION)
                _LOGGER.debug("Access token refreshed successfully")
                return self._access_token

        except TadoAuthError:
            # Must propagate so coordinator triggers reauth flow
            raise
        except aiohttp.ClientError:
            _LOGGER.exception("Network error during token refresh")
            return None
        except Exception:
            _LOGGER.exception("Unexpected error during token refresh")
            return None
