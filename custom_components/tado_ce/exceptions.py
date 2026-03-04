"""Tado CE custom exceptions.

Typed exceptions for async_sync() error handling.
Enables coordinator to distinguish auth failures from network failures:
- TadoAuthError → ConfigEntryAuthFailed (triggers HA reauth flow)
- TadoSyncError → UpdateFailed (coordinator retries on next poll)
"""


class TadoAuthError(Exception):
    """Raised when authentication fails (e.g., invalid_grant, expired refresh token).

    The coordinator catches this and raises ConfigEntryAuthFailed,
    which triggers HA's reauth flow prompting the user to re-authenticate.
    """


class TadoSyncError(Exception):
    """Raised when sync fails due to network/server errors (not auth-related).

    The coordinator catches this and raises UpdateFailed,
    which marks the coordinator as failed and retries on next poll.
    """
