"""Microsoft Graph authentication helper (client-credentials / daemon flow).

Uses MSAL ``ConfidentialClientApplication`` with the application's client
secret to acquire an application-level access token for
``https://graph.microsoft.com/.default``. MSAL caches tokens in memory and
transparently refreshes them when they're within ~5 minutes of expiry, so
callers can safely invoke :func:`get_access_token` on every request.

Configuration (read from environment at first-use):
    AXIS_GRAPH_TENANT_ID      — Directory (tenant) ID, a GUID
    AXIS_GRAPH_CLIENT_ID      — Application (client) ID, a GUID
    AXIS_GRAPH_CLIENT_SECRET  — Client secret value (not the secret ID)

Why client-credentials and not device-code?
    The orchestrator runs headless on a server. It needs to send mail, create
    Teams meetings, and read calendars as the service mailbox (``axis-hiring-
    agent@…``) without any human sitting in front of it to sign in. App-only
    permissions granted with admin consent are the only flow that supports
    this, and we already granted admin consent in step 3 of the Azure setup.

Raises
------
GraphConfigError
    If required env vars are missing, or MSAL cannot acquire a token.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

try:
    import msal  # type: ignore
except ImportError as e:  # pragma: no cover - surfaced only when graph mode is used
    msal = None  # type: ignore
    _IMPORT_ERROR: Optional[ImportError] = e
else:
    _IMPORT_ERROR = None

log = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class GraphConfigError(RuntimeError):
    """Raised when Graph auth can't be configured or the token call fails."""


class GraphAuth:
    """Thread-safe singleton-style helper that returns a valid Graph bearer.

    Instances are lightweight; there is no harm in constructing more than
    one, but typically the module-level :func:`get_access_token` is used.
    """

    def __init__(
        self,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> None:
        if msal is None:
            raise GraphConfigError(
                f"msal package not installed — run `pip install msal`. "
                f"Underlying error: {_IMPORT_ERROR!r}"
            )

        self.tenant_id = tenant_id or os.getenv("AXIS_GRAPH_TENANT_ID", "")
        self.client_id = client_id or os.getenv("AXIS_GRAPH_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("AXIS_GRAPH_CLIENT_SECRET", "")

        missing = [
            name for name, val in [
                ("AXIS_GRAPH_TENANT_ID", self.tenant_id),
                ("AXIS_GRAPH_CLIENT_ID", self.client_id),
                ("AXIS_GRAPH_CLIENT_SECRET", self.client_secret),
            ]
            if not val
        ]
        if missing:
            raise GraphConfigError(
                f"Missing required Graph environment variables: {', '.join(missing)}. "
                f"Set them in .env or export them before starting the server."
            )

        self._authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        self._app = msal.ConfidentialClientApplication(
            client_id=self.client_id,
            client_credential=self.client_secret,
            authority=self._authority,
        )
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def get_access_token(self) -> str:
        """Return a valid bearer token for ``https://graph.microsoft.com``.

        MSAL's in-memory token cache is checked first; if a non-expired token
        is present it is reused. Otherwise a new one is minted via
        ``acquire_token_for_client``. Thread-safe.
        """
        with self._lock:
            result = self._app.acquire_token_silent([GRAPH_SCOPE], account=None)
            if not result:
                log.debug("No cached Graph token — acquiring a fresh one.")
                result = self._app.acquire_token_for_client(scopes=[GRAPH_SCOPE])

            if not result or "access_token" not in result:
                err = (result or {}).get("error")
                desc = (result or {}).get("error_description", "")
                raise GraphConfigError(
                    f"Failed to acquire Graph token: {err} — {desc[:400]}"
                )

            return result["access_token"]

    def auth_header(self) -> dict:
        """Return ``{'Authorization': 'Bearer <token>'}`` ready for httpx."""
        return {"Authorization": f"Bearer {self.get_access_token()}"}


# ---------------------------------------------------------------------------
# Module-level convenience — most callers use these two.
# ---------------------------------------------------------------------------


_INSTANCE_LOCK = threading.Lock()
_INSTANCE: Optional[GraphAuth] = None


def get_auth() -> GraphAuth:
    """Return the process-wide GraphAuth singleton, constructing on first use."""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = GraphAuth()
    return _INSTANCE


def get_access_token() -> str:
    return get_auth().get_access_token()


def reset_auth() -> None:
    """Test helper — drop the cached singleton and any MSAL token cache."""
    global _INSTANCE
    with _INSTANCE_LOCK:
        _INSTANCE = None
