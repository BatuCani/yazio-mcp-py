# yazio-mcp

[![CI](https://github.com/BatuCani/yazio-mcp-py/actions/workflows/ci.yml/badge.svg)](https://github.com/BatuCani/yazio-mcp-py/actions/workflows/ci.yml)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A small, typed **Python MCP server** for the (unofficial) [Yazio](https://www.yazio.com)
nutrition API. Read your diary — daily summaries, consumed items, weight, water,
exercises, goals — search the food database, and **log food and water**, all from
any MCP client (Claude Desktop, Cursor) or your own Python agent.

```
┌──────────────┐   HTTP    ┌──────────────────────┐   MCP    ┌─────────────┐
│ Yazio backend│◄─────────►│ yazio-mcp            │◄────────►│ Your MCP    │
│ (unofficial) │   OAuth2  │  auth · client · MCP │  stdio   │ host / agent│
└──────────────┘           └──────────────────────┘          └─────────────┘
```

**Why this one?** There are several *JavaScript* Yazio MCP servers, but this is
the first **Python** one — it implements the Yazio client *and* the MCP layer
from scratch, so it drops cleanly into a Python agent stack (FastMCP, LangChain,
your own host). Works on a **free** Yazio account.

> **Heads-up:** Yazio has no official API. This uses the same internal endpoints
> the Yazio apps use, reverse-engineered by the community. It can break if Yazio
> changes their backend. Personal use only.

## Install

```bash
# One-shot run (nothing to install permanently):
uvx yazio-mcp

# or install it:
pip install yazio-mcp
```

Set your Yazio credentials in the environment:

```bash
export YAZIO_USERNAME=you@example.com
export YAZIO_PASSWORD=...
```

## Use it from an MCP client

Add this to your client's MCP config (e.g. Claude Desktop's
`claude_desktop_config.json`). Works for any stdio MCP host:

```json
{
  "mcpServers": {
    "yazio": {
      "command": "uvx",
      "args": ["yazio-mcp"],
      "env": {
        "YAZIO_USERNAME": "you@example.com",
        "YAZIO_PASSWORD": "..."
      }
    }
  }
}
```

Then ask your assistant things like *"What did I eat today and how many calories
am I under my goal?"* — it gets clean, readable data back:

```json
{
  "date": "2026-05-30",
  "total_kcal": 734.5,
  "goals": { "energy_kcal": 2370, "protein_g": 116, "fat_g": 76, "carb_g": 289 },
  "meals": [
    { "name": "breakfast", "energy_kcal": 613, "protein_g": 37 },
    { "name": "lunch", "energy_kcal": 82, "protein_g": 7 }
  ]
}
```

## Tools

**Read (single day, dates are `YYYY-MM-DD`)**

| Tool | What it does |
|------|--------------|
| `get_daily_summary(date)` | Totals + per-meal macros + goals for a day |
| `get_consumed_items(date)` | Everything logged, with food **names** resolved |
| `get_goals(date)` | Energy + macro targets |
| `get_weight(date)` | Latest weight on/before the date |
| `get_water_intake(date)` | Water (ml) |
| `get_exercises(date)` | Training + activity |
| `get_user_profile()` | Profile (sensitive fields stripped) |

**Read (date ranges — efficient multi-day)**

| Tool | What it does |
|------|--------------|
| `get_nutrients_range(start, end)` | Energy + macros + goal per day, **one request** |
| `get_weight_range(start, end)` | Weight per day (fetched concurrently) |
| `get_water_range(start, end)` | Water per day |
| `get_exercises_range(start, end)` | Exercises per day |

**Search & write**

| Tool | What it does |
|------|--------------|
| `search_products(query)` | Search the Yazio food database |
| `get_product(product_id)` | Full nutrition for one product |
| `add_consumed_item(...)` | Log a product to the diary |
| `add_water_intake(date, ml)` | Log water |
| `remove_consumed_item(item_id)` | Delete a diary entry |

## Use the client directly (no MCP)

`YazioClient` works standalone if you just want the data in Python:

```python
import asyncio
from yazio_mcp import YazioClient

async def main():
    async with YazioClient("you@example.com", "password") as yazio:
        summary = await yazio.daily_summary("2026-05-30")
        print(summary["total_kcal"])

asyncio.run(main())
```

It logs in once, caches/refreshes the token, reuses a warm connection pool,
collapses multi-day reads into single requests, retries transient errors
(reads only — never writes, to avoid double-logging), and trims responses to
clean, readable shapes.

## Development

```bash
git clone https://github.com/BatuCani/yazio-mcp-py
cd yazio-mcp-py
uv sync --extra dev
uv run pytest      # tests use mocked HTTP — no real account needed
uv run ruff check .
uv run mypy src
```

See [SETUP.md](SETUP.md) for architecture and full setup notes.

## Credits

Endpoint paths verified against the open-source clients
[`aleksandr-bogdanov/yazio-exporter`](https://github.com/aleksandr-bogdanov/yazio-exporter)
and [`juriadams/yazio`](https://github.com/juriadams/yazio), and the community API
description at [`saganos/yazio_public_api`](https://github.com/saganos/yazio_public_api).

## License

MIT — see [LICENSE](LICENSE).
