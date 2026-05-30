import httpx
import pytest
import respx

from yazio_mcp import client as client_mod
from yazio_mcp.auth import TOKEN_PATH
from yazio_mcp.client import API_VERSION, YazioClient, YazioError

BASE = "https://yzapi.yazio.com"
V = f"{BASE}/{API_VERSION}"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Make retry backoff instant so tests don't actually wait."""

    async def _instant(*_args, **_kwargs):
        return None

    monkeypatch.setattr(client_mod.YazioClient, "_backoff", staticmethod(_instant))


def _auth_route():
    return respx.post(f"{BASE}{TOKEN_PATH}").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "tok", "refresh_token": "ref", "expires_in": 3600},
        )
    )


@respx.mock
async def test_daily_summary_sends_bearer_and_flattens():
    _auth_route()
    raw = {
        "steps": 1234,
        "water_intake": 500,
        "goals": {"energy.energy": 2200},
        "meals": {
            "breakfast": {"nutrients": {"energy.energy": 300, "nutrient.protein": 20}},
            "lunch": {"nutrients": {"energy.energy": 0}},
        },
    }
    route = respx.get(f"{V}/user/widgets/daily-summary").mock(
        return_value=httpx.Response(200, json=raw)
    )
    async with YazioClient("u", "p") as yazio:
        data = await yazio.daily_summary("2026-05-29")
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Bearer tok"
    assert req.url.params["date"] == "2026-05-29"
    # flattened + summed
    assert data["date"] == "2026-05-29"
    assert data["total_kcal"] == 300
    assert data["steps"] == 1234
    assert data["water_ml"] == 500
    assert data["goals"]["energy_kcal"] == 2200
    breakfast = next(m for m in data["meals"] if m["name"] == "breakfast")
    assert breakfast["protein_g"] == 20


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
async def test_add_consumed_item_posts_body_and_confirms():
    _auth_route()
    route = respx.post(f"{V}/user/consumed-items").mock(
        return_value=httpx.Response(201, json={"ok": True})
    )
    async with YazioClient("u", "p") as yazio:
        result = await yazio.add_consumed_item(
            product_id="abc", date="2026-05-29", daytime="breakfast", amount=100
        )
    body = route.calls[0].request.read()
    assert b'"daytime":"breakfast"' in body.replace(b" ", b"")
    assert b'"product_id":"abc"' in body.replace(b" ", b"")
    # deterministic confirmation regardless of response body
    assert result == {
        "status": "ok",
        "action": "add_consumed_item",
        "product_id": "abc",
        "date": "2026-05-29",
        "daytime": "breakfast",
        "amount": 100,
    }


@respx.mock
async def test_add_water_intake_empty_body_still_confirms():
    _auth_route()
    respx.post(f"{V}/user/water-intake").mock(return_value=httpx.Response(200))
    async with YazioClient("u", "p") as yazio:
        result = await yazio.add_water_intake(date="2026-05-29", water_intake_ml=500)
    # empty 200 body used to return None; now a clear confirmation
    assert result["status"] == "ok"
    assert result["water_intake"] == 500


@respx.mock
async def test_remove_consumed_item_uses_delete_and_confirms():
    _auth_route()
    route = respx.delete(f"{V}/user/consumed-items").mock(
        return_value=httpx.Response(200)
    )
    async with YazioClient("u", "p") as yazio:
        result = await yazio.remove_consumed_item("item-123")
    assert route.calls[0].request.method == "DELETE"
    assert b"item-123" in route.calls[0].request.read()
    assert result == {
        "status": "ok",
        "action": "remove_consumed_item",
        "id": "item-123",
    }


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


# -- optimizations -----------------------------------------------------------


@respx.mock
async def test_single_login_across_many_calls():
    """The whole point of the long-lived client: log in once, not per call."""
    auth = _auth_route()
    respx.get(f"{V}/user/goals").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{V}/user/water-intake").mock(return_value=httpx.Response(200, json={}))
    async with YazioClient("u", "p") as yazio:
        await yazio.goals("2026-05-29")
        await yazio.water_intake("2026-05-29")
        await yazio.goals("2026-05-28")
    assert auth.call_count == 1  # not 3


@respx.mock
async def test_nutrients_range_single_request():
    _auth_route()
    route = respx.get(f"{V}/user/consumed-items/nutrients-daily").mock(
        return_value=httpx.Response(200, json=[{"date": "2026-05-01", "energy": 2000}])
    )
    async with YazioClient("u", "p") as yazio:
        data = await yazio.nutrients_range("2026-05-01", "2026-05-31")
    assert route.call_count == 1  # 31 days, 1 request
    assert data[0]["energy"] == 2000
    params = route.calls[0].request.url.params
    assert params["start"] == "2026-05-01"
    assert params["end"] == "2026-05-31"


@respx.mock
async def test_weight_range_fans_out_with_partial_failure():
    _auth_route()
    # day 2 fails (500 -> after retries, surfaces as error for that day only)
    def handler(request):
        if request.url.params["date"] == "2026-05-02":
            return httpx.Response(500, text="nope")
        return httpx.Response(200, json={"value": 80.0})

    respx.get(f"{V}/user/bodyvalues/weight/last").mock(side_effect=handler)
    async with YazioClient("u", "p") as yazio:
        result = await yazio.weight_range("2026-05-01", "2026-05-03")
    ok_dates = {d["date"] for d in result["days"]}
    err_dates = {e["date"] for e in result["errors"]}
    assert ok_dates == {"2026-05-01", "2026-05-03"}
    assert err_dates == {"2026-05-02"}  # one bad day didn't abort the window


@respx.mock
async def test_get_retries_on_5xx_then_succeeds():
    _auth_route()
    respx.get(f"{V}/user/goals").mock(
        side_effect=[
            httpx.Response(503, text="busy"),
            httpx.Response(200, json={"energy.energy": 2200}),
        ]
    )
    async with YazioClient("u", "p") as yazio:
        data = await yazio.goals("2026-05-29")
    assert data["energy_kcal"] == 2200


@respx.mock
async def test_post_not_retried():
    """Writes must NOT be retried — a retry could double-log."""
    _auth_route()
    route = respx.post(f"{V}/user/water-intake").mock(
        return_value=httpx.Response(503, text="busy")
    )
    async with YazioClient("u", "p") as yazio:
        with pytest.raises(YazioError):
            await yazio.add_water_intake(date="2026-05-29", water_intake_ml=500)
    assert route.call_count == 1  # no retry on a non-idempotent write


@respx.mock
async def test_product_is_cached():
    _auth_route()
    route = respx.get(f"{V}/products/abc").mock(
        return_value=httpx.Response(200, json={"name": "Apple"})
    )
    async with YazioClient("u", "p") as yazio:
        first = await yazio.product("abc")
        second = await yazio.product("abc")
    assert first == second
    assert route.call_count == 1  # second call served from cache


@respx.mock
async def test_bad_json_body_raises_yazio_error():
    _auth_route()
    respx.get(f"{V}/user/goals").mock(
        return_value=httpx.Response(200, text="<html>maintenance</html>")
    )
    async with YazioClient("u", "p") as yazio:
        with pytest.raises(YazioError):
            await yazio.goals("2026-05-29")


@respx.mock
async def test_user_profile_strips_sensitive_fields():
    _auth_route()
    respx.get(f"{V}/user").mock(
        return_value=httpx.Response(
            200,
            json={
                "first_name": "Batu",
                "is_premium": False,
                "user_token": "SECRET-TOKEN",
                "email": "batu@example.com",
                "uuid": "abc-123",
                "stripe_customer_id": "cus_x",
            },
        )
    )
    async with YazioClient("u", "p") as yazio:
        profile = await yazio.user()
    assert profile["first_name"] == "Batu"
    # sensitive fields must NOT survive
    assert "user_token" not in profile
    assert "email" not in profile
    assert "uuid" not in profile
    assert "stripe_customer_id" not in profile


@respx.mock
async def test_consumed_items_resolves_names_and_simple_products():
    _auth_route()
    respx.get(f"{V}/user/consumed-items").mock(
        return_value=httpx.Response(
            200,
            json={
                "products": [
                    {
                        "id": "item-1",
                        "daytime": "lunch",
                        "product_id": "p1",
                        "amount": 60,
                    }
                ],
                "simple_products": [
                    {
                        "id": "item-2",
                        "daytime": "breakfast",
                        "name": "Lachsbowl",
                        "is_ai_generated": True,
                        "nutrients": {"energy.energy": 613, "nutrient.protein": 37},
                    }
                ],
                "recipe_portions": [],
            },
        )
    )
    # catalog product name resolution
    respx.get(f"{V}/products/p1").mock(
        return_value=httpx.Response(200, json={"name": "Hühnerei, gekocht"})
    )
    async with YazioClient("u", "p") as yazio:
        result = await yazio.consumed_items("2026-05-29")

    assert result["date"] == "2026-05-29"
    assert len(result["items"]) == 2

    catalog = next(i for i in result["items"] if i["id"] == "item-1")
    assert catalog["name"] == "Hühnerei, gekocht"  # product_id was resolved
    assert catalog["daytime"] == "lunch"

    simple = next(i for i in result["items"] if i["id"] == "item-2")
    assert simple["name"] == "Lachsbowl"  # inline name carried through
    assert simple["energy_kcal"] == 613
    assert simple["protein_g"] == 37
    assert simple["is_ai_generated"] is True


@respx.mock
async def test_consumed_items_resolve_names_off():
    _auth_route()
    respx.get(f"{V}/user/consumed-items").mock(
        return_value=httpx.Response(
            200,
            json={
                "products": [{"id": "i1", "product_id": "p1", "daytime": "lunch"}],
                "simple_products": [],
                "recipe_portions": [],
            },
        )
    )
    product_route = respx.get(f"{V}/products/p1").mock(
        return_value=httpx.Response(200, json={"name": "X"})
    )
    async with YazioClient("u", "p") as yazio:
        result = await yazio.consumed_items("2026-05-29", resolve_names=False)
    assert "name" not in result["items"][0]  # no resolution requested
    assert product_route.call_count == 0  # and no extra product call made
