"""Async HTTP client for the (unofficial) Yazio API.

Endpoint paths were verified against two open-source reverse-engineered clients:
  - aleksandr-bogdanov/yazio-exporter  (Python, read endpoints)
  - juriadams/yazio                    (TypeScript, read + write + search)

All paths are relative to ``{base_url}/{api_version}``. Dates are ISO ``YYYY-MM-DD``.

The client is designed to be **long-lived**: build one instance, keep it open for
the lifetime of the server, and reuse it across calls. It then logs in once,
caches the token, refreshes it transparently, and reuses a warm connection pool.
"""

from __future__ import annotations

import asyncio
import random
import time
from datetime import date as date_cls
from datetime import timedelta
from typing import Any

import httpx

from .auth import DEFAULT_BASE_URL, AuthError, YazioAuth

API_VERSION = "v10"

# Cache TTLs (seconds). Tiered by how mutable the data is.
#   - product details: effectively immutable global catalog -> long.
#   - product search:  results are stable enough -> short/medium.
# Day-scoped diary data (consumed items, summaries, water, weight) is NEVER
# cached: it's edited out-of-band and by this server's own write tools, so a
# cached read could be stale right after a log.
_PRODUCT_TTL = 24 * 60 * 60
_SEARCH_TTL = 5 * 60

# Status codes worth retrying (transient server / rate-limit conditions).
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.5  # seconds; grows exponentially with jitter
_MAX_BACKOFF = 8.0
# Bound concurrent per-day fan-out so we don't hammer Yazio (the reference
# exporter uses ~10 workers).
_FANOUT_LIMIT = 8


class YazioError(RuntimeError):
    """Raised when an API call fails after authentication."""


def _fmt_date(value: str | date_cls | None) -> str:
    if value is None:
        raise ValueError("a date is required (YYYY-MM-DD)")
    if isinstance(value, date_cls):
        return value.isoformat()
    return value


def _parse_date(value: str | date_cls) -> date_cls:
    if isinstance(value, date_cls):
        return value
    return date_cls.fromisoformat(value)


def _date_span(start: str | date_cls, end: str | date_cls) -> list[date_cls]:
    """Inclusive list of dates from start to end."""
    s, e = _parse_date(start), _parse_date(end)
    if e < s:
        raise ValueError("end must be on or after start")
    return [s + timedelta(days=i) for i in range((e - s).days + 1)]


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
        self._http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
        # Serialize the very first login so concurrent fan-out calls don't each
        # kick off their own token request.
        self._login_lock = asyncio.Lock()
        # TTL cache for immutable-ish reads only (products / search).
        self._cache: dict[str, tuple[float, Any]] = {}

    def _cache_get(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() >= expires_at:
            del self._cache[key]
            return None
        return value

    def _cache_put(self, key: str, value: Any, ttl: float) -> None:
        self._cache[key] = (time.time() + ttl, value)

    async def __aenter__(self) -> YazioClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def warm_up(self) -> None:
        """Acquire a token now (e.g. at server startup) so the first real call
        is fast and concurrent fan-out doesn't race on login."""
        async with self._login_lock:
            await self._auth.access_token(self._http)

    # -- core request plumbing ------------------------------------------------

    def _url(self, path: str) -> str:
        path = path.lstrip("/")
        return f"{self._base_url}/{API_VERSION}/{path}"

    async def _token(self) -> str:
        async with self._login_lock:
            return await self._auth.access_token(self._http)

    async def _request(
        self, method: str, path: str, *, retry: bool | None = None, **kwargs: Any
    ) -> Any:
        """Perform an authenticated request.

        Retries transient failures (429/5xx, transport errors) with exponential
        backoff — but only for idempotent methods unless ``retry=True`` is forced.
        Writes (POST/DELETE) are NOT retried by default, because a retry after a
        timeout where the request actually landed would double-log data.
        """
        idempotent = method.upper() in ("GET", "HEAD")
        do_retry = idempotent if retry is None else retry
        attempts = _MAX_RETRIES if do_retry else 1
        last_exc: Exception | None = None

        for attempt in range(attempts):
            token = await self._token()
            headers = {
                "Authorization": f"Bearer {token}",
                **kwargs.get("headers", {}),
            }
            call_kwargs = {**kwargs, "headers": headers}
            try:
                resp = await self._http.request(method, self._url(path), **call_kwargs)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt + 1 < attempts:
                    await self._backoff(attempt)
                    continue
                raise YazioError(f"{method} {path} failed: {exc}") from exc

            if resp.status_code == httpx.codes.UNAUTHORIZED:
                raise AuthError(f"Unauthorized for {method} {path} (token rejected)")

            if resp.status_code in _RETRY_STATUS and attempt + 1 < attempts:
                await self._backoff(attempt, resp)
                continue

            if resp.status_code >= 400:
                raise YazioError(
                    f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:200]}"
                )

            if not resp.content:
                return None
            try:
                return resp.json()
            except (ValueError, httpx.DecodingError) as exc:
                raise YazioError(
                    f"{method} {path}: expected JSON, got "
                    f"{resp.text[:120]!r}"
                ) from exc

        # Exhausted retries on transport errors.
        raise YazioError(f"{method} {path} failed after {attempts} attempts: {last_exc}")

    @staticmethod
    async def _backoff(attempt: int, resp: httpx.Response | None = None) -> None:
        # Honour Retry-After on 429s when present.
        if resp is not None and resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                await asyncio.sleep(min(float(retry_after), _MAX_BACKOFF))
                return
        delay = min(_BACKOFF_BASE * (2**attempt), _MAX_BACKOFF)
        delay += random.uniform(0, delay / 2)  # jitter
        await asyncio.sleep(delay)

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

    # -- read: ranges (one request for many days) -----------------------------

    async def nutrients_range(
        self, start: str | date_cls, end: str | date_cls
    ) -> Any:
        """Energy + macros + energy goal per tracked day across [start, end].

        Verified to exist on /v10. Returns one compact array — collapses what
        would otherwise be N daily-summary requests into a single call.
        """
        return await self._get(
            f"user/consumed-items/nutrients-daily"
            f"?start={_fmt_date(start)}&end={_fmt_date(end)}"
        )

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

    # -- read: concurrent fan-out for endpoints with no server-side range -----

    async def _fan_out_days(
        self,
        start: str | date_cls,
        end: str | date_cls,
        fetch: Any,
    ) -> dict[str, Any]:
        """Run a per-day fetch concurrently across [start, end].

        Returns {"days": [{date, data}...], "errors": [{date, error}...]} so a
        single bad day never aborts the whole window.
        """
        await self.warm_up()  # ensure token exists before coroutines race
        days = _date_span(start, end)
        sem = asyncio.Semaphore(_FANOUT_LIMIT)

        async def one(d: date_cls) -> tuple[str, Any, str | None]:
            async with sem:
                try:
                    return d.isoformat(), await fetch(d.isoformat()), None
                except (YazioError, AuthError) as exc:
                    return d.isoformat(), None, str(exc)

        results = await asyncio.gather(*(one(d) for d in days))
        ok = [{"date": d, "data": data} for d, data, err in results if err is None]
        errors = [{"date": d, "error": err} for d, _, err in results if err is not None]
        return {"days": ok, "errors": errors}

    async def weight_range(
        self, start: str | date_cls, end: str | date_cls
    ) -> dict[str, Any]:
        """Weight per day across [start, end] (concurrent fan-out)."""
        return await self._fan_out_days(start, end, self.weight)

    async def water_range(
        self, start: str | date_cls, end: str | date_cls
    ) -> dict[str, Any]:
        """Water intake per day across [start, end] (concurrent fan-out)."""
        return await self._fan_out_days(start, end, self.water_intake)

    async def exercises_range(
        self, start: str | date_cls, end: str | date_cls
    ) -> dict[str, Any]:
        """Exercises per day across [start, end] (concurrent fan-out)."""
        return await self._fan_out_days(start, end, self.exercises)

    # -- read: products -------------------------------------------------------

    async def search_products(self, query: str) -> Any:
        """Search the Yazio food database (short-TTL cached by normalized query)."""
        key = f"search:{query.strip().lower()}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        result = await self._get("products/search", params={"query": query})
        self._cache_put(key, result, _SEARCH_TTL)
        return result

    async def product(self, product_id: str) -> Any:
        """Detailed nutrition info for a single product (long-TTL cached)."""
        key = f"product:{product_id}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        result = await self._get(f"products/{product_id}")
        self._cache_put(key, result, _PRODUCT_TTL)
        return result

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
    ) -> dict[str, Any]:
        """Log a product to the diary.

        ``daytime`` is one of: breakfast, lunch, dinner, snack.
        ``amount`` is grams/ml unless a ``serving`` is given.
        Returns a deterministic confirmation rather than the (often empty) body.
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
        await self._request("POST", "user/consumed-items", json=body)
        return {"status": "ok", "action": "add_consumed_item", **body}

    async def add_water_intake(
        self, *, date: str | date_cls, water_intake_ml: float
    ) -> dict[str, Any]:
        """Set the water intake (ml) for a day."""
        body = {"date": _fmt_date(date), "water_intake": water_intake_ml}
        await self._request("POST", "user/water-intake", json=body)
        return {"status": "ok", "action": "add_water_intake", **body}

    async def remove_consumed_item(self, item_id: str) -> dict[str, Any]:
        """Delete a logged diary entry by its id."""
        await self._request("DELETE", "user/consumed-items", json={"id": item_id})
        return {"status": "ok", "action": "remove_consumed_item", "id": item_id}
