"""FastMCP server exposing Yazio data as MCP tools.

Credentials are read from the environment so the server can be dropped into any
MCP client (Claude Desktop, Cursor, your own host) via a standard config block:

    YAZIO_USERNAME=you@example.com
    YAZIO_PASSWORD=...

Run with:  yazio-mcp     (stdio transport)
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import YazioClient

mcp = FastMCP("yazio")


def _client() -> YazioClient:
    username = os.environ.get("YAZIO_USERNAME")
    password = os.environ.get("YAZIO_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "Set YAZIO_USERNAME and YAZIO_PASSWORD in the environment."
        )
    return YazioClient(username, password)


# -- read tools --------------------------------------------------------------


@mcp.tool()
async def get_daily_summary(date: str) -> Any:
    """Daily nutrition summary (meals, activity, steps, water, goals) for YYYY-MM-DD."""
    async with _client() as yazio:
        return await yazio.daily_summary(date)


@mcp.tool()
async def get_consumed_items(date: str) -> Any:
    """All logged food, recipes and simple products for the day YYYY-MM-DD."""
    async with _client() as yazio:
        return await yazio.consumed_items(date)


@mcp.tool()
async def get_goals(date: str) -> Any:
    """Energy and macro goals for the day YYYY-MM-DD."""
    async with _client() as yazio:
        return await yazio.goals(date)


@mcp.tool()
async def get_weight(date: str) -> Any:
    """Most recent weight entry on or before YYYY-MM-DD."""
    async with _client() as yazio:
        return await yazio.weight(date)


@mcp.tool()
async def get_water_intake(date: str) -> Any:
    """Water intake (ml) for the day YYYY-MM-DD."""
    async with _client() as yazio:
        return await yazio.water_intake(date)


@mcp.tool()
async def get_exercises(date: str) -> Any:
    """Logged training and activity for the day YYYY-MM-DD."""
    async with _client() as yazio:
        return await yazio.exercises(date)


@mcp.tool()
async def get_user_profile() -> Any:
    """The Yazio user profile (name, units, premium status, goals)."""
    async with _client() as yazio:
        return await yazio.user()


# -- search tools ------------------------------------------------------------


@mcp.tool()
async def search_products(query: str) -> Any:
    """Search the Yazio food database by name."""
    async with _client() as yazio:
        return await yazio.search_products(query)


@mcp.tool()
async def get_product(product_id: str) -> Any:
    """Detailed nutrition info for a single product id."""
    async with _client() as yazio:
        return await yazio.product(product_id)


# -- write tools -------------------------------------------------------------


@mcp.tool()
async def add_consumed_item(
    product_id: str,
    date: str,
    daytime: str,
    amount: float,
    serving: str | None = None,
    serving_quantity: float | None = None,
) -> Any:
    """Log a product to the diary.

    daytime: one of breakfast, lunch, dinner, snack.
    amount: grams/ml, unless a serving is given.
    """
    async with _client() as yazio:
        return await yazio.add_consumed_item(
            product_id=product_id,
            date=date,
            daytime=daytime,
            amount=amount,
            serving=serving,
            serving_quantity=serving_quantity,
        )


@mcp.tool()
async def add_water_intake(date: str, water_intake_ml: float) -> Any:
    """Set water intake (ml) for the day YYYY-MM-DD."""
    async with _client() as yazio:
        return await yazio.add_water_intake(date=date, water_intake_ml=water_intake_ml)


@mcp.tool()
async def remove_consumed_item(item_id: str) -> Any:
    """Delete a logged diary entry by its id."""
    async with _client() as yazio:
        return await yazio.remove_consumed_item(item_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
