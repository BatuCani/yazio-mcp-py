# yazio-mcp-py

A small, typed **Python MCP server** for the (unofficial) [Yazio](https://www.yazio.com)
nutrition API. It exposes your Yazio diary — daily summaries, consumed items,
weight, water, exercises, goals, product search — and lets you **log food and
water** from any MCP client (Claude Desktop, Cursor, or your own host).

```
┌──────────────┐   HTTP    ┌──────────────────────┐   MCP    ┌─────────────┐
│ Yazio backend│◄─────────►│ yazio-mcp-py         │◄────────►│ Your MCP    │
│ (unofficial) │   OAuth2  │  auth · client · MCP │  stdio   │ host / agent│
└──────────────┘           └──────────────────────┘          └─────────────┘
```

> **Heads-up:** Yazio has **no official API**. This talks to the same internal
> endpoints the Yazio apps use, reverse-engineered by the community. It can break
> any time Yazio changes their backend. Use it for personal projects, not
> production.

> 📋 **Continuing on another machine?** See [SETUP.md](SETUP.md) for the full
> current state, architecture, and a from-zero install/run guide.

## Why this exists

There's a solid JavaScript MCP (`yazio-mcp`) and a JS client library (`juriadams/yazio`),
but no maintained **Python** equivalent. This implements the Yazio client *and*
the MCP layer from scratch in Python so it drops cleanly into a Python-based
agent stack — and so the data can be piped into a personal health system.

## Tools

| Tool | What it does |
|------|--------------|
| `get_daily_summary(date)` | Meals, activity, steps, water, goals for a day |
| `get_consumed_items(date)` | Everything logged that day |
| `get_goals(date)` | Energy + macro targets |
| `get_weight(date)` | Latest weight on/before the date |
| `get_water_intake(date)` | Water (ml) |
| `get_exercises(date)` | Training + activity |
| `get_user_profile()` | Profile, units, premium status |
| `search_products(query)` | Search the Yazio food database |
| `get_product(product_id)` | Full nutrition for one product |
| `add_consumed_item(...)` | Log a product to the diary |
| `add_water_intake(date, ml)` | Log water |
| `remove_consumed_item(item_id)` | Delete a diary entry |

Dates are ISO `YYYY-MM-DD`.

## Setup

```bash
git clone https://github.com/<you>/yazio-mcp-py
cd yazio-mcp-py
uv sync                      # install
cp .env.example .env         # add your Yazio credentials
```

Set credentials in the environment (or `.env`):

```bash
export YAZIO_USERNAME=you@example.com
export YAZIO_PASSWORD=...
```

Run the server (stdio transport):

```bash
uv run yazio-mcp
```

## Use it from an MCP client

Add it to your client's MCP config — e.g. Claude Desktop's
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "yazio": {
      "command": "uv",
      "args": ["--directory", "/path/to/yazio-mcp-py", "run", "yazio-mcp"],
      "env": {
        "YAZIO_USERNAME": "you@example.com",
        "YAZIO_PASSWORD": "..."
      }
    }
  }
}
```

The same block works for any MCP host that speaks stdio.

## Use the client directly (no MCP)

The `YazioClient` is usable on its own if you just want the data in Python:

```python
import asyncio
from yazio_mcp import YazioClient

async def main():
    async with YazioClient("you@example.com", "password") as yazio:
        summary = await yazio.daily_summary("2026-05-29")
        print(summary["steps"])

asyncio.run(main())
```

## Development

```bash
uv sync --extra dev
uv run pytest      # tests use mocked HTTP — no real account needed
uv run ruff check .
uv run mypy src
```

## Credits

Endpoint paths verified against the open-source clients
[`aleksandr-bogdanov/yazio-exporter`](https://github.com/aleksandr-bogdanov/yazio-exporter)
and [`juriadams/yazio`](https://github.com/juriadams/yazio), and the community API
description at [`saganos/yazio_public_api`](https://github.com/saganos/yazio_public_api).

## License

MIT
