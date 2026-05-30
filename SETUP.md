# Setup & Stand — yazio-mcp-py

Diese Datei ist die Mitnahme-Doku, um auf einem anderen Rechner (z. B. dem Mac
Mini) nahtlos weiterzuarbeiten. Sie enthält **keine** Zugangsdaten — die `.env`
mit dem Yazio-Login wird lokal neu angelegt (siehe unten) und ist git-ignored.

---

## Was das ist

Ein Python-MCP-Server, der die (inoffizielle) Yazio-API anzapft und deine
Ernährungsdaten als saubere MCP-Tools bereitstellt — gedacht zur Einbindung in
ein eigenes Agent-/Mission-Control-System.

**Status: funktioniert, live gegen einen echten Free-Account verifiziert.**

---

## Auf dem Mac Mini einrichten (von 0)

Voraussetzungen: `git`, `uv` (https://docs.astral.sh/uv/).

```bash
# 1. Repo holen
git clone https://github.com/BatuCani/yazio-mcp-py
cd yazio-mcp-py

# 2. Abhängigkeiten installieren
uv sync --extra dev

# 3. Zugangsdaten lokal anlegen (NICHT committen — .env ist git-ignored)
printf 'YAZIO_USERNAME=DEINE_EMAIL\nYAZIO_PASSWORD=DEIN_PASSWORT\n' > .env

# 4. Prüfen, dass alles läuft
uv run pytest -q          # 21 Tests, alle gegen gemocktes HTTP (kein Account nötig)
uv run ruff check .
uv run mypy src

# 5. Server starten (stdio)
uv run yazio-mcp
```

### In einen MCP-Client / Agenten einbinden

Standard-stdio-Konfig (Claude Desktop, Cursor, eigener Host):

```json
{
  "mcpServers": {
    "yazio": {
      "command": "uv",
      "args": ["--directory", "/PFAD/zu/yazio-mcp-py", "run", "yazio-mcp"],
      "env": {
        "YAZIO_USERNAME": "deine@email.de",
        "YAZIO_PASSWORD": "..."
      }
    }
  }
}
```

---

## Verfügbare Tools (16)

**Lesen (Einzeltag, Datum = `YYYY-MM-DD`):**
`get_daily_summary`, `get_consumed_items`, `get_goals`, `get_weight`,
`get_water_intake`, `get_exercises`, `get_user_profile`

**Lesen (Zeitraum):**
`get_nutrients_range(start,end)` — ein Request für viele Tage (Yazio-Endpoint,
auf /v10 verifiziert). `get_weight_range`, `get_water_range`,
`get_exercises_range` — paralleler Fan-out, da kein echter Range-Endpoint.

**Suchen:** `search_products(query)`, `get_product(product_id)`

**Schreiben:** `add_consumed_item`, `add_water_intake`, `remove_consumed_item`

---

## Architektur

```
src/yazio_mcp/
  auth.py     OAuth2 password-grant + Token-Cache/Refresh; InvalidCredentialsError
  client.py   Async-HTTP-Client: langlebig, Retry/Backoff, TTL-Cache, Range/Fan-out
  models.py   Pydantic-Modelle: trimmen Rohdaten, filtern sensible Felder
  server.py   FastMCP-Server: hält EINEN Client via lifespan, registriert die Tools
```

Wichtige Designentscheidungen (warum es schnell/sicher ist):

- **Ein langlebiger Client** (FastMCP-`lifespan`): loggt **einmal** beim Start
  ein statt bei jedem Tool-Aufruf. Live verifiziert: 1 Login, dann 0 weitere.
- **Range + Concurrency:** ganze Zeiträume in einem bzw. parallelen Requests.
- **Retry/Backoff** im `_request`-Chokepoint — **methoden-bewusst**: GET wird
  wiederholt, POST/DELETE NICHT (sonst Doppel-Logging von Mahlzeiten).
- **TTL-Cache** nur für unveränderliche Daten (Produkte lang, Suche kurz);
  Tagesdaten werden NIE gecacht (sonst veraltet nach dem Loggen).
- **Pydantic-Modelle** filtern sensible Felder (`user_token`, `email`, `uuid`,
  `stripe_customer_id`) raus, bevor Daten an den Agenten gehen, und flachen
  Yazios dotted keys (`energy.energy`) zu lesbaren Werten ab.
- **Namensauflösung:** `get_consumed_items` löst `product_id` → Produktname auf
  und reicht AI-/Schnell-Einträge (`simple_products`) mit Name+Nährwerten durch,
  sodass der Agent sieht, WAS gegessen wurde, nicht nur eine ID.

---

## Wichtige Fakten (live verifiziert)

- Funktioniert mit einem **kostenlosen** Yazio-Account (kein Premium nötig).
- Endpoints liegen auf **/v10** (`yzapi.yazio.com`); Range-Endpoint dort bestätigt.
- Daten sind **live**: in der App geloggte Einträge sind Sekunden später abrufbar.

## Sicherheit

- `.env` (Passwort) ist git-ignored und war nie im Git-Verlauf.
- Profil-Antworten werden getrimmt, sodass Token/E-Mail/UUID nicht durchsickern.
- Inoffizielle API → kann brechen, wenn Yazio das Backend ändert. Nur Eigennutzung.

---

## Offen / Ideen

- Pydantic-Modelle für die Read-Tools sind da; ggf. weitere Felder ergänzen,
  falls neue Eintragstypen auftauchen.
- Optional: aggregiertes `get_day_overview` (alle Einzeltag-Reads gebündelt).
- Optional: auf PyPI veröffentlichen für `uvx yazio-mcp` (Ein-Befehl-Start).
