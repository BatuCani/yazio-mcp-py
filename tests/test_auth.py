import time

import httpx
import pytest
import respx

from yazio_mcp.auth import (
    TOKEN_PATH,
    InvalidCredentialsError,
    YazioAuth,
)

BASE = "https://yzapi.yazio.com"


def _token_response(access="acc", refresh="ref", expires_in=3600):
    return httpx.Response(
        200,
        json={
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": expires_in,
        },
    )


@respx.mock
async def test_login_fetches_token():
    route = respx.post(f"{BASE}{TOKEN_PATH}").mock(return_value=_token_response())
    auth = YazioAuth(username="u", password="p")
    async with httpx.AsyncClient() as http:
        token = await auth.access_token(http)
    assert token == "acc"
    assert route.called
    # password grant on first call
    assert route.calls[0].request.read().find(b"password") != -1


@respx.mock
async def test_cached_token_not_refetched():
    route = respx.post(f"{BASE}{TOKEN_PATH}").mock(return_value=_token_response())
    auth = YazioAuth(username="u", password="p")
    async with httpx.AsyncClient() as http:
        await auth.access_token(http)
        await auth.access_token(http)
    assert route.call_count == 1


@respx.mock
async def test_expired_token_refreshes():
    route = respx.post(f"{BASE}{TOKEN_PATH}").mock(
        side_effect=[
            _token_response(access="old", expires_in=0),
            _token_response(access="new"),
        ]
    )
    auth = YazioAuth(username="u", password="p")
    async with httpx.AsyncClient() as http:
        first = await auth.access_token(http)
        # force perceived expiry
        auth._token.expires_at = time.time() - 1  # type: ignore[union-attr]
        second = await auth.access_token(http)
    assert first == "old"
    assert second == "new"
    assert b"refresh_token" in route.calls[1].request.read()


@respx.mock
async def test_auth_error_on_bad_credentials():
    respx.post(f"{BASE}{TOKEN_PATH}").mock(
        return_value=httpx.Response(400, text="invalid_grant")
    )
    auth = YazioAuth(username="u", password="bad")
    async with httpx.AsyncClient() as http:
        # 400 is a terminal credential error, not a generic/transient one
        with pytest.raises(InvalidCredentialsError):
            await auth.access_token(http)
