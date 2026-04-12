"""Tado CE Bridge API Client — boiler wiring data and flow temperature control."""

from __future__ import annotations

from http import HTTPStatus
import logging

import aiohttp

from .exceptions import TadoBridgeApiError
from .helpers import async_retry_with_backoff

_LOGGER = logging.getLogger(__name__)

_BRIDGE_API_BASE = "https://my.tado.com/api/v2/homeByBridge"

# HTTP timeout for Bridge API calls (10s — simple GET/PUT operations)
_BRIDGE_API_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Temperature constraints (matches Tado app)
MIN_FLOW_TEMP = 25.0
MAX_FLOW_TEMP = 80.0
FLOW_TEMP_STEP = 0.5


def validate_flow_temperature(celsius: float) -> float:
    """Validate and snap flow temperature to nearest 0.5°C step.

    Raises TadoBridgeApiError if value is outside 25.0-80.0 range.
    Returns the snapped value.
    """
    if celsius < MIN_FLOW_TEMP or celsius > MAX_FLOW_TEMP:
        msg = "Flow temperature %s°C outside valid range %s-%s°C"
        raise TadoBridgeApiError(msg % (celsius, MIN_FLOW_TEMP, MAX_FLOW_TEMP))
    # Snap to nearest 0.5 step
    return round(celsius * 2) / 2


class TadoBridgeApiClient:
    """Handle Bridge API communication for flow temperature control."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        bridge_serial: str,
        auth_key: str,
    ) -> None:
        """Initialize the TadoBridgeApiClient."""
        self._session = session
        self._bridge_serial = bridge_serial
        self._auth_key = auth_key
        self._base_url = f"{_BRIDGE_API_BASE}/{bridge_serial}"

    async def async_get_wiring_state(self) -> dict[str, object]:
        """Fetch boiler wiring installation state from Bridge API."""
        url = f"{self._base_url}/boilerWiringInstallationState"
        params = {"authKey": self._auth_key}
        _LOGGER.debug("Bridge API GET request - URL: %s", url.replace(self._auth_key, "[AUTH_KEY]"))

        async def _do_get() -> dict[str, object]:
            async with self._session.get(url, params=params, timeout=_BRIDGE_API_TIMEOUT) as resp:
                _LOGGER.debug("Bridge API response status: %s", resp.status)
                if resp.status != HTTPStatus.OK:
                    msg = "Bridge API GET wiring state failed: HTTP %s"
                    raise TadoBridgeApiError(msg % resp.status)
                result = await resp.json()
                _LOGGER.debug("Bridge API full response: %s", result)
                return result  # type: ignore[no-any-return]

        try:
            return await async_retry_with_backoff(
                _do_get,
                no_retry_exceptions=(TadoBridgeApiError,),
                retryable_exceptions=(aiohttp.ClientError,),
            )
        except aiohttp.ClientError as err:
            msg = "Bridge API network error: %s"
            raise TadoBridgeApiError(msg % err) from err

    async def async_set_max_output_temperature(self, celsius: float) -> bool:
        """Set boiler max output temperature via Bridge API.

        Validates range 25.0-80.0°C with 0.5 step, then PUTs to the API.
        Idempotent PUT — safe to retry on network errors.
        Returns True on success. Raises TadoBridgeApiError on failure.
        """
        snapped = validate_flow_temperature(celsius)
        url = f"{self._base_url}/boilerMaxOutputTemperature"
        params = {"authKey": self._auth_key}
        payload = {"boilerMaxOutputTemperatureInCelsius": snapped}

        async def _do_put() -> bool:
            async with self._session.put(url, params=params, json=payload, timeout=_BRIDGE_API_TIMEOUT) as resp:
                if resp.status not in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
                    msg = "Bridge API PUT max temp failed: HTTP %s"
                    raise TadoBridgeApiError(msg % resp.status)
                return True

        try:
            return await async_retry_with_backoff(
                _do_put,
                no_retry_exceptions=(TadoBridgeApiError,),
                retryable_exceptions=(aiohttp.ClientError,),
            )
        except aiohttp.ClientError as err:
            msg = "Bridge API network error: %s"
            _LOGGER.debug(msg, err)
            raise TadoBridgeApiError(msg % err) from err

    async def async_validate_credentials(self) -> bool:
        """Validate bridge credentials by making a test API call.

        Returns True if credentials are valid, False otherwise.
        """
        try:
            await self.async_get_wiring_state()
        except TadoBridgeApiError:
            return False
        return True
