import httpx
import pytest
import respx

from yazio_mcp.auth import TOKEN_PATH
from yazio_mcp.client import API_VERSION, YazioClient, YazioError

BASE = "https://yzapi.yazio.com"
V = f"{BASE}/{API_VERSION}"


def _auth_route():
    return respx.post(f"{BASE}{TOKEN_PATH}").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "tok", "refresh_token": "ref", "expires_in": 3600},
        )
    )


@respx.mock
async def test_daily_summary_sends_bearer_and_date():
    _auth_route()
    route = respx.get(f"{V}/user/widgets/daily-summary").mock(
        return_value=httpx.Response(200, json={"steps": 1234})
    )
    async with YazioClient("u", "p") as yazio:
        data = await yazio.daily_summary("2026-05-29")
    assert data == {"steps": 1234}
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Bearer tok"
    assert req.url.params["date"] == "2026-05-29"


@respx.mock
async def test_search_products():
    _auth_route()
    route = respx.get(f"{V}/products/search").mock(
        return_value=httpx.Response(200, json=[{"product_id": "abc"}])
    )
    async with YazioClient("u", "p") as yazio:
        results = await yazio.search_products("oats")
    assert results[0]["product_id"] == "abc"
    assert route.calls[0].request.url.params["query"] == "oats"


@respx.mock
async def test_add_consumed_item_posts_body():
    _auth_route()
    route = respx.post(f"{V}/user/consumed-items").mock(
        return_value=httpx.Response(201, json={"ok": True})
    )
    async with YazioClient("u", "p") as yazio:
        await yazio.add_consumed_item(
            product_id="abc", date="2026-05-29", daytime="breakfast", amount=100
        )
    body = route.calls[0].request.read()
    assert b'"daytime":"breakfast"' in body.replace(b" ", b"")
    assert b'"product_id":"abc"' in body.replace(b" ", b"")


@respx.mock
async def test_remove_consumed_item_uses_delete():
    _auth_route()
    route = respx.delete(f"{V}/user/consumed-items").mock(
        return_value=httpx.Response(200)
    )
    async with YazioClient("u", "p") as yazio:
        await yazio.remove_consumed_item("item-123")
    assert route.calls[0].request.method == "DELETE"
    assert b"item-123" in route.calls[0].request.read()


@respx.mock
async def test_http_error_raises_yazio_error():
    _auth_route()
    respx.get(f"{V}/user/goals").mock(return_value=httpx.Response(500, text="boom"))
    async with YazioClient("u", "p") as yazio:
        with pytest.raises(YazioError):
            await yazio.goals("2026-05-29")


@respx.mock
async def test_missing_date_raises():
    _auth_route()
    async with YazioClient("u", "p") as yazio:
        with pytest.raises(ValueError):
            await yazio.daily_summary(None)  # type: ignore[arg-type]
