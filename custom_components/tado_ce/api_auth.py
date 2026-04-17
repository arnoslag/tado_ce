"""Tado CE API Auth Mixin — token management via ConfigEntry."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
import logging
from typing import TYPE_CHECKING, Any, Protocol

import aiohttp

from .const import CLIENT_ID, MAX_RETRY_ATTEMPTS, TADO_AUTH_URL
from .exceptions import TadoAuthError
from .helpers import retry_delay

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .data_loader import DataLoader

_LOGGER = logging.getLogger(__name__)

# HTTP timeout for OAuth token refresh (15s — auth endpoint should be fast)
_TOKEN_REFRESH_TIMEOUT = aiohttp.ClientTimeout(total=15)


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

    # --- Mixin-provided members (for cross-method calls) ---
    TOKEN_CACHE_DURATION: int

    async def _load_config(self) -> dict[str, Any]: ...
    async def _save_config(self, config: dict[str, Any]) -> None: ...
    async def _refresh_token(self) -> str | None: ...


class TadoAuthMixin:
    """Mixin providing OAuth token management.

    Token source of truth is the HA ConfigEntry (``entry.data["refresh_token"]``).
    The host class injects the refresh token via constructor; rotated tokens
    are persisted back to ConfigEntry via ``async_update_entry``.

    The host class must satisfy the ``_AuthHost`` protocol.
    See ``_AuthHost`` for the full contract.
    """

    # Explicit type so mypy doesn't narrow from the datetime assignment in _refresh_token.
    _token_expiry: datetime | None

    # Token cache duration (5 minutes to be safe, Tado tokens valid for ~10 minutes)
    TOKEN_CACHE_DURATION = 300

    # --- Config I/O ---

    async def _load_config(self: _AuthHost) -> dict[str, Any]:
        """Build config dict from injected values.

        Refresh token comes from ConfigEntry (injected at construction time).
        No file I/O needed — ConfigEntry is the source of truth.
        """
        return {
            "home_id": self._home_id,
            "refresh_token": self._injected_refresh_token,
        }

    async def _save_config(self: _AuthHost, config: dict[str, Any]) -> None:
        """Persist rotated refresh token to ConfigEntry.

        ConfigEntry is the sole source of truth for auth credentials.
        DataLoader cache is also updated for in-memory consumers.
        """
        if self._hass and self._config_entry:
            new_data = {**self._config_entry.data, **config}
            self._hass.config_entries.async_update_entry(
                self._config_entry, data=new_data,
            )

        # Update DataLoader cache for in-memory consumers
        if self._data_loader is not None:
            self._data_loader.update_cache("config", config)

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

    async def _handle_successful_token_response(
        self: _AuthHost, data: dict[str, Any], config: dict[str, Any], refresh_token: str,
    ) -> str | None:
        """Handle a successful token refresh response."""
        self._access_token = data.get("access_token")
        new_refresh_token = data.get("refresh_token")

        if not self._access_token:
            _LOGGER.error("No access token in response")
            return None

        # Save new refresh token if rotated
        if new_refresh_token and new_refresh_token != refresh_token:
            config["refresh_token"] = new_refresh_token
            self._injected_refresh_token = new_refresh_token
            await self._save_config(config)
            _LOGGER.debug("Refresh token rotated and saved to ConfigEntry")

        self._token_expiry = datetime.now(UTC) + timedelta(seconds=self.TOKEN_CACHE_DURATION)
        _LOGGER.debug("Access token refreshed successfully")
        return self._access_token

    async def _attempt_token_refresh(
        self: _AuthHost,
        config: dict[str, Any],
        refresh_token: str,
        attempt: int,
    ) -> str | None:
        """Execute a single token refresh HTTP request.

        Returns:
            Access token on success, None on non-retryable HTTP error.

        Raises:
            TadoAuthError: On auth failure (401/invalid_grant) or exhausted 403 retries.
        """
        async with self._session.post(
            f"{TADO_AUTH_URL}/token",
            data={
                "client_id": CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=_TOKEN_REFRESH_TIMEOUT,
        ) as resp:
            if resp.status == HTTPStatus.OK:
                data = await resp.json()
                return await self._handle_successful_token_response(data, config, refresh_token)  # type: ignore[attr-defined, no-any-return]  # mixin cross-method call

            error_text = await resp.text()

            # 401 / invalid_grant = real auth failure — no retry
            if resp.status == HTTPStatus.UNAUTHORIZED or "invalid_grant" in error_text:
                _LOGGER.error("Token refresh auth failure: %s - %s", resp.status, error_text)
                config["refresh_token"] = None
                await self._save_config(config)
                raise TadoAuthError("Refresh token invalid (auth failure)")

            # 403 = likely transient CDN/WAF block — retry via loop
            if resp.status == HTTPStatus.FORBIDDEN:
                if attempt < MAX_RETRY_ATTEMPTS:
                    _LOGGER.debug("Token refresh got 403, retry %s/%s", attempt, MAX_RETRY_ATTEMPTS)
                    return None  # signal caller to retry
                _LOGGER.error("Token refresh 403 after %s attempts: %s", MAX_RETRY_ATTEMPTS, error_text[:200])
                raise TadoAuthError(f"Token refresh failed after {MAX_RETRY_ATTEMPTS} attempts (403)")

            # Other HTTP errors — no retry
            _LOGGER.error("Token refresh failed: %s - %s", resp.status, error_text)
            return None

    async def _refresh_token(self: _AuthHost) -> str | None:
        """Refresh access token with retry for transient 403 and network errors.

        OAuth2 refresh token requests are idempotent — safe to retry.
        Transient errors (403 CDN/WAF block, DNS failures, connection
        timeouts) are retried; 401 / invalid_grant are never retried.
        """
        config = await self._load_config()
        refresh_token = config.get("refresh_token")

        if not refresh_token:
            _LOGGER.error("No refresh token available")
            return None

        _LOGGER.debug("Refreshing access token...")

        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            try:
                result = await self._attempt_token_refresh(config, refresh_token, attempt)  # type: ignore[attr-defined]  # mixin cross-method call
                if result is not None:
                    return result  # type: ignore[no-any-return]  # mixin return type
                # None = transient (403), retry after backoff
            except TadoAuthError:
                raise
            except aiohttp.ClientError:
                if attempt >= MAX_RETRY_ATTEMPTS:
                    _LOGGER.exception("Network error during token refresh (exhausted %s retries)", MAX_RETRY_ATTEMPTS)
                    return None
            except Exception:
                _LOGGER.exception("Unexpected error during token refresh")
                return None

            # Backoff before next attempt (403 or network error)
            delay = retry_delay(attempt)
            _LOGGER.warning("Token refresh failed (attempt %s/%s), retrying in %.1fs", attempt, MAX_RETRY_ATTEMPTS, delay)
            await asyncio.sleep(delay)

        return None  # unreachable but satisfies type checker
