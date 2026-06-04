"""Tado CE repair-issue helpers — surface auth / config problems via HA's UI."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Issue IDs (stable identifiers for each repair type)
ISSUE_AUTH_EXPIRED = "auth_token_expired"


def async_create_auth_issue(hass: HomeAssistant, home_id: str | None = None) -> None:
    """Surface an "auth expired" repair so the user re-authenticates."""
    issue_id = f"{ISSUE_AUTH_EXPIRED}_{home_id}" if home_id else ISSUE_AUTH_EXPIRED
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="auth_token_expired",
        translation_placeholders={"home_id": home_id or "default"},
    )
    _LOGGER.debug("Repairs: created repair issue %s", issue_id)


def async_dismiss_auth_issue(hass: HomeAssistant, home_id: str | None = None) -> None:
    """Clear the auth-expired repair after a successful re-auth."""
    issue_id = f"{ISSUE_AUTH_EXPIRED}_{home_id}" if home_id else ISSUE_AUTH_EXPIRED
    ir.async_delete_issue(hass, DOMAIN, issue_id)
    _LOGGER.debug("Repairs: dismissed repair issue %s", issue_id)
