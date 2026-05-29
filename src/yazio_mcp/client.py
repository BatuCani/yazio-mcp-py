"""Async HTTP client for the (unofficial) Yazio API.

Endpoint paths were verified against two open-source reverse-engineered clients:
  - aleksandr-bogdanov/yazio-exporter  (Python, read endpoints)
  - juriadams/yazio                    (TypeScript, read + write + search)

All paths are relative to ``{base_url}/{api_version}``. Dates are ISO ``YYYY-MM-DD``.
"""

from __future__ import annotations

from datetime import date as date_cls
from typing import Any

import httpx

from .auth import DEFAULT_BASE_URL, AuthError, YazioAuth

API_VERSION = "v10"


class YazioError(RuntimeError):
    """Raised when an API call fails after authentication."""


def _fmt_date(value: str | date_cls | None) -> str:
    if value is None:
        raise ValueError("a date is required (YYYY-MM-DD)")
    if isinstance(value, date_cls):
        return value.isoformat()
    return value


class YazioClient:
    """Thin async wrapper over the Yazio REST endpoints.

    Use as an async context manager so the underlying ``httpx.AsyncClient`` is
    closed cleanly::

        async with YazioClient(username, password) as yazio:
            summary = await yazio.daily_summary("2026-05-29")
    """

    def __init__(
        self,
        username: str,
        password: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._auth = YazioAuth(username=username, password=password, base_url=base_url)
        self._base_url = base_url
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=30.0)

    async def __aenter__(self) -> YazioClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # -- core request plumbing ------------------------------------------------

    def _url(self, path: str) -> str:
        path = path.lstrip("/")
        return f"{self._base_url}/{API_VERSION}/{path}"

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> Any:
        token = await self._auth.access_token(self._http)
        headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
        try:
            resp = await self._http.request(
                method, self._url(path), headers=headers, **kwargs
            )
        except httpx.HTTPError as exc:
            raise YazioError(f"{method} {path} failed: {exc}") from exc

        if resp.status_code == httpx.codes.UNAUTHORIZED:
            raise AuthError(f"Unauthorized for {method} {path} (token rejected)")
        if resp.status_code >= 400:
            raise YazioError(
                f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:200]}"
            )
        if not resp.content:
            return None
        return resp.json()

    async def _get(self, path: str, **kwargs: Any) -> Any:
        return await self._request("GET", path, **kwargs)

    # -- read: profile & goals ------------------------------------------------

    async def user(self) -> Any:
        """Full user profile (name, premium status, units, goals)."""
        return await self._get("user")

    async def goals(self, date: str | date_cls) -> Any:
        """Nutrition goals (energy + macro targets) for a given day."""
        return await self._get(f"user/goals?date={_fmt_date(date)}")

    # -- read: daily nutrition ------------------------------------------------

    async def daily_summary(self, date: str | date_cls) -> Any:
        """Widget-style daily summary: meals, activity, steps, water, goals."""
        return await self._get(f"user/widgets/daily-summary?date={_fmt_date(date)}")

    async def consumed_items(self, date: str | date_cls) -> Any:
        """All consumed products, recipes and simple products for a day."""
        return await self._get(f"user/consumed-items?date={_fmt_date(date)}")

    # -- read: body, water, exercise ------------------------------------------

    async def weight(self, date: str | date_cls) -> Any:
        """Most recent weight entry on or before the given date."""
        return await self._get(f"user/bodyvalues/weight/last?date={_fmt_date(date)}")

    async def water_intake(self, date: str | date_cls) -> Any:
        """Water intake (ml) for a day."""
        return await self._get(f"user/water-intake?date={_fmt_date(date)}")

    async def exercises(self, date: str | date_cls) -> Any:
        """Logged training, custom training and activity for a day."""
        return await self._get(f"user/exercises?date={_fmt_date(date)}")

    # -- read: products -------------------------------------------------------

    async def search_products(self, query: str) -> Any:
        """Search the Yazio food database."""
        return await self._get("products/search", params={"query": query})

    async def product(self, product_id: str) -> Any:
        """Detailed nutrition info for a single product."""
        return await self._get(f"products/{product_id}")

    # -- write: log & remove --------------------------------------------------

    async def add_consumed_item(
        self,
        *,
        product_id: str,
        date: str | date_cls,
        daytime: str,
        amount: float,
        serving: str | None = None,
        serving_quantity: float | None = None,
    ) -> Any:
        """Log a product to the diary.

        ``daytime`` is one of: breakfast, lunch, dinner, snack.
        ``amount`` is grams/ml unless a ``serving`` is given.
        """
        body: dict[str, Any] = {
            "product_id": product_id,
            "date": _fmt_date(date),
            "daytime": daytime,
            "amount": amount,
        }
        if serving is not None:
            body["serving"] = serving
        if serving_quantity is not None:
            body["serving_quantity"] = serving_quantity
        return await self._request("POST", "user/consumed-items", json=body)

    async def add_water_intake(
        self, *, date: str | date_cls, water_intake_ml: float
    ) -> Any:
        """Set the water intake (ml) for a day."""
        body = {"date": _fmt_date(date), "water_intake": water_intake_ml}
        return await self._request("POST", "user/water-intake", json=body)

    async def remove_consumed_item(self, item_id: str) -> Any:
        """Delete a logged diary entry by its id."""
        return await self._request(
            "DELETE", "user/consumed-items", json={"id": item_id}
        )
