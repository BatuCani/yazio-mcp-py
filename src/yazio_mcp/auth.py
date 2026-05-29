"""Authentication against the (unofficial) Yazio OAuth2 endpoint.

Yazio has no official, public API. The OAuth client credentials below are the
public credentials used by the Yazio mobile/web apps; they are widely published
across reverse-engineered clients (e.g. juriadams/yazio, saganos/yazio_public_api)
and are required to obtain a user access token via the password grant.

This may break at any time if Yazio changes their backend.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

# Public app credentials (not secret — shipped in the Yazio apps).
CLIENT_ID = "1_4hiybetvfksgw40o0sog4s884kwc840wwso8go4k8c04goo4c"
CLIENT_SECRET = "6rok2m65xuskgkgogw40wkkk8sw0osg84s8cggsc4woos4s8o"

DEFAULT_BASE_URL = "https://yzapi.yazio.com"
TOKEN_PATH = "/v10/oauth/token"

# Refresh the token this many seconds before it actually expires, to avoid
# racing a 401 on a long-running call.
_EXPIRY_SKEW_SECONDS = 60


class AuthError(RuntimeError):
    """Raised when authentication or token refresh fails."""


@dataclass
class Token:
    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - _EXPIRY_SKEW_SECONDS)


@dataclass
class YazioAuth:
    """Holds credentials and the current token, and knows how to (re)fetch it.

    The caller is responsible for providing an ``httpx.AsyncClient``; this keeps
    auth testable (inject a mock transport) and lets the client own connection
    pooling.
    """

    username: str
    password: str
    base_url: str = DEFAULT_BASE_URL
    _token: Token | None = field(default=None, repr=False)

    async def access_token(self, http: httpx.AsyncClient) -> str:
        """Return a valid access token, logging in or refreshing as needed."""
        if self._token is None:
            await self._login(http)
        elif self._token.is_expired:
            await self._refresh(http)
        assert self._token is not None
        return self._token.access_token

    async def _login(self, http: httpx.AsyncClient) -> None:
        payload = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "username": self.username,
            "password": self.password,
            "grant_type": "password",
        }
        self._token = await self._request_token(http, payload)

    async def _refresh(self, http: httpx.AsyncClient) -> None:
        assert self._token is not None
        payload = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": self._token.refresh_token,
        }
        try:
            self._token = await self._request_token(http, payload)
        except AuthError:
            # Refresh token may be stale; fall back to a full re-login.
            await self._login(http)

    async def _request_token(
        self, http: httpx.AsyncClient, payload: dict[str, str]
    ) -> Token:
        url = f"{self.base_url}{TOKEN_PATH}"
        try:
            resp = await http.post(url, json=payload)
        except httpx.HTTPError as exc:  # network-level failure
            raise AuthError(f"Token request failed: {exc}") from exc

        if resp.status_code != httpx.codes.OK:
            raise AuthError(
                f"Yazio auth returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.json()
        try:
            return Token(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=time.time() + float(data["expires_in"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthError(f"Unexpected token response shape: {data!r}") from exc
