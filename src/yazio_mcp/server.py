"""FastMCP server exposing Yazio data as MCP tools.

A single authenticated :class:`YazioClient` is built once at startup (via the
FastMCP ``lifespan`` hook) and reused across every tool call. This means the
server logs in once — not on every request — and keeps a warm connection pool,
which is what makes reading your data fast.

Credentials are read from the environment so the server can be dropped into any
MCP client (Claude Desktop, Cursor, your own host) via a standard config block:

    YAZIO_USERNAME=you@example.com
    YAZIO_PASSWORD=...

Run with:  yazio-mcp     (stdio transport)
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from .client import YazioClient


@dataclass
class AppContext:
    """Shared state available to every tool for the server's lifetime."""

    yazio: YazioClient


# Concrete Context type carrying our lifespan state.
YazioContext = Context[ServerSession, AppContext, Any]


@asynccontextmanager
async def lifespan(_server: FastMCP) -> AsyncIterator[AppContext]:
    """Build one YazioClient at startup, log in once, tear down at shutdown."""
    username = os.environ.get("YAZIO_USERNAME")
    password = os.environ.get("YAZIO_PASSWORD")
    if not username or not password:
        raise RuntimeError("Set YAZIO_USERNAME and YAZIO_PASSWORD in the environment.")

    client = YazioClient(username, password)
    try:
        # Acquire the token now so the first tool call is already warm.
        await client.warm_up()
        yield AppContext(yazio=client)
    finally:
        await client.aclose()


mcp = FastMCP("yazio", lifespan=lifespan)


def _yazio(ctx: YazioContext) -> YazioClient:
    app: AppContext = ctx.request_context.lifespan_context
    return app.yazio


# -- read tools --------------------------------------------------------------


@mcp.tool()
async def get_daily_summary(date: str, ctx: YazioContext) -> Any:
    """Daily nutrition summary (meals, activity, steps, water, goals) for YYYY-MM-DD."""
    return await _yazio(ctx).daily_summary(date)


@mcp.tool()
async def get_consumed_items(date: str, ctx: YazioContext) -> Any:
    """All logged food, recipes and simple products for the day YYYY-MM-DD."""
    return await _yazio(ctx).consumed_items(date)


@mcp.tool()
async def get_goals(date: str, ctx: YazioContext) -> Any:
    """Energy and macro goals for the day YYYY-MM-DD."""
    return await _yazio(ctx).goals(date)


@mcp.tool()
async def get_weight(date: str, ctx: YazioContext) -> Any:
    """Most recent weight entry on or before YYYY-MM-DD."""
    return await _yazio(ctx).weight(date)


@mcp.tool()
async def get_water_intake(date: str, ctx: YazioContext) -> Any:
    """Water intake (ml) for the day YYYY-MM-DD."""
    return await _yazio(ctx).water_intake(date)


@mcp.tool()
async def get_exercises(date: str, ctx: YazioContext) -> Any:
    """Logged training and activity for the day YYYY-MM-DD."""
    return await _yazio(ctx).exercises(date)


@mcp.tool()
async def get_user_profile(ctx: YazioContext) -> Any:
    """The Yazio user profile (name, units, premium status, goals)."""
    return await _yazio(ctx).user()


# -- range tools (efficient multi-day reads) ---------------------------------


@mcp.tool()
async def get_nutrients_range(start: str, end: str, ctx: YazioContext) -> Any:
    """Energy + macros + energy goal per tracked day across [start, end].

    One request for the whole window — use this instead of calling
    get_daily_summary once per day. Dates are inclusive, YYYY-MM-DD.
    """
    return await _yazio(ctx).nutrients_range(start, end)


@mcp.tool()
async def get_weight_range(start: str, end: str, ctx: YazioContext) -> Any:
    """Weight per day across [start, end] (fetched concurrently). YYYY-MM-DD."""
    return await _yazio(ctx).weight_range(start, end)


@mcp.tool()
async def get_water_range(start: str, end: str, ctx: YazioContext) -> Any:
    """Water intake per day across [start, end] (fetched concurrently). YYYY-MM-DD."""
    return await _yazio(ctx).water_range(start, end)


@mcp.tool()
async def get_exercises_range(start: str, end: str, ctx: YazioContext) -> Any:
    """Exercises per day across [start, end] (fetched concurrently). YYYY-MM-DD."""
    return await _yazio(ctx).exercises_range(start, end)


# -- search tools ------------------------------------------------------------


@mcp.tool()
async def search_products(query: str, ctx: YazioContext) -> Any:
    """Search the Yazio food database by name."""
    return await _yazio(ctx).search_products(query)


@mcp.tool()
async def get_product(product_id: str, ctx: YazioContext) -> Any:
    """Detailed nutrition info for a single product id."""
    return await _yazio(ctx).product(product_id)


# -- write tools -------------------------------------------------------------


@mcp.tool()
async def add_consumed_item(
    product_id: str,
    date: str,
    daytime: str,
    amount: float,
    ctx: YazioContext,
    serving: str | None = None,
    serving_quantity: float | None = None,
) -> Any:
    """Log a product to the diary.

    daytime: one of breakfast, lunch, dinner, snack.
    amount: grams/ml, unless a serving is given.
    """
    return await _yazio(ctx).add_consumed_item(
        product_id=product_id,
        date=date,
        daytime=daytime,
        amount=amount,
        serving=serving,
        serving_quantity=serving_quantity,
    )


@mcp.tool()
async def add_water_intake(date: str, water_intake_ml: float, ctx: YazioContext) -> Any:
    """Set water intake (ml) for the day YYYY-MM-DD."""
    return await _yazio(ctx).add_water_intake(date=date, water_intake_ml=water_intake_ml)


@mcp.tool()
async def remove_consumed_item(item_id: str, ctx: YazioContext) -> Any:
    """Delete a logged diary entry by its id."""
    return await _yazio(ctx).remove_consumed_item(item_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
