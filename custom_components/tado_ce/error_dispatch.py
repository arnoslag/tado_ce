"""Pattern B service-call dispatch — used by service-call wrappers."""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .exceptions import TadoAuthError, TadoRateLimitError
from .helpers import retry_after_to_minutes

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


def dispatch_to_service_call(
    exc: TadoAuthError | TadoRateLimitError,
    config_entry: ConfigEntry,
    hass: HomeAssistant,
) -> NoReturn:
    """Pattern B canonical dispatch — always raises HomeAssistantError.

    Auth path also calls config_entry.async_start_reauth(hass) before raising;
    the call is idempotent (HA dedups active reauth flows internally).
    """
    if isinstance(exc, TadoAuthError):
        # WHY: per HA docs, ConfigEntryAuthFailed raised from service-call paths
        # does NOT trigger reauth. Must call async_start_reauth explicitly.
        config_entry.async_start_reauth(hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="auth_required",
        ) from exc

    if isinstance(exc, TadoRateLimitError):
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="rate_limited",
            translation_placeholders={
                "retry_after_minutes": retry_after_to_minutes(exc.retry_after),
            },
        ) from exc

    # Unreachable per type signature, but keep a safe fallback
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="cloud_write_failed",
    ) from exc
