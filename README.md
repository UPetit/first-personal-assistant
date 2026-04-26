# first-personal-assistant

**Kore** — your personal AI assistant. Extensible, self-hosted, Python-first.

Kore is a single conversational agent that runs over Telegram, remembers context across days and weeks via a three-layer memory system, runs scheduled tasks via CRON, and delegates narrow work (web research, long-form drafting) to two on-demand subagents. It uses [Pydantic AI](https://ai.pydantic.dev) under the hood, so swapping between Anthropic Claude (default), OpenAI, OpenRouter, and Ollama is a single config change.

For architecture, conventions, and the v2 sub-project roadmap, see [CLAUDE.md](./CLAUDE.md).

## Running with Docker (recommended)

**First-time setup** — initialise the `~/.kore/` data directory and create starter config files:

```bash
docker compose run --rm gateway init
```

This creates `~/.kore/config.json`, `~/.kore/SOUL.md`, `~/.kore/USER.md`, and `~/.kore/data/jobs.json`.

Create your secrets file at `~/.kore/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
BRAVE_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_URL=https://your-domain.com/telegram/webhook
```

Apply any pending data migrations:

```bash
docker compose run --rm gateway migrate
```

Build the images:

```bash
docker compose build
```

Start both services in the background:

```bash
docker compose up -d gateway
docker compose up -d ui
```

| Service | URL |
|---------|-----|
| Dashboard (ui) | `http://localhost:5173` |
| Gateway API | `http://localhost:8000` |

---

## Running locally (development)

### Backend

**Requirements:** Python 3.12+

```bash
# Install dependencies
pip install -e ".[dev]"

# Initialise data directory (creates ~/.kore/ with starter files)
python -m kore.main init

# Create ~/.kore/.env with your API keys (see Docker section for required vars)

# Apply any pending data migrations
python -m kore.main migrate

# Start the gateway (FastAPI + scheduler + Telegram webhook)
python -m kore.main gateway
```

The API is available at `http://localhost:8000`.

### Frontend

**Requirements:** Node.js 18+

The dashboard is a React + Vite app in `ui/`. In development it runs against the backend on port 8000.

```bash
cd ui
npm install
npm run dev
```

The dev server starts at `http://localhost:5173` and proxies API calls to the backend.

To build the frontend and embed it into the backend's static file serving:

```bash
cd ui
npm run build        # outputs to src/kore/ui/static/
```

After building, the dashboard is served directly by FastAPI at `http://localhost:8000`.

---

## Customising Kore

Two Markdown files in `~/.kore/` shape Kore's behaviour and what it knows about you:

- **`~/.kore/SOUL.md`** — Kore's personality (tone, values, anti-patterns). Created as a stub by `init`.
- **`~/.kore/USER.md`** — your profile (name, timezone, role, current projects). Created as a stub by `init`.

Both files are prepended to every agent's system prompt at build time. Edit and restart the gateway to apply changes.

---

## Running tests

```bash
pytest
```
