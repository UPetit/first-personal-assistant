# kore-ai
Your personal AI core. Extensible, self-hosted, Python-first.

## Running with Docker (recommended)

**First-time setup** — initialise the `~/.kore` data directory and create a starter `config.json`:

```bash
docker compose run --rm gateway init
```

Then copy and fill in your environment variables:

```bash
cp .env.example ~/.kore/.env   # or create ~/.kore/.env manually
```

Minimal `~/.kore/.env`:

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

# Copy and fill in secrets
cp .env.example ~/.kore/.env

# Initialise data directory
python -m kore init

# Apply any pending data migrations
python -m kore migrate

# Start the gateway (FastAPI + scheduler + Telegram webhook)
python -m kore gateway
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

## Running tests

```bash
pytest
```
