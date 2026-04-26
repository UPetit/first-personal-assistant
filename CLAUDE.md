# Kore — Personal AI Assistant Platform

## What is this project

**The assistant is named "Kore."** This repo (`first-personal-assistant`) is the platform Kore runs on: a Python-native, Docker-first personal AI assistant. Kore runs as a single conversational primary agent (per-turn) with two on-demand subagents (`deep_research`, `draft_longform`) for tasks that benefit from context isolation. Multi-provider LLM support comes via Pydantic AI — Anthropic Claude is the default, with OpenAI, OpenRouter, and Ollama supported out of the box. Users interact via Telegram. The system runs scheduled tasks via CRON, remembers context long-term via a three-layer memory system, and exposes a React dashboard for monitoring.

## Commands

```bash
# First-time setup — bootstrap ~/.kore/ (SOUL.md, USER.md, config stubs, jobs.json)
python -m kore.main init

# Apply any pending data migrations
python -m kore.main migrate

# Run the gateway locally (FastAPI + scheduler + Telegram webhook)
python -m kore.main gateway

# Run tests
pytest

# Start the gateway (Docker)
docker compose up -d gateway

# UI dev server (proxies to localhost:8000)
cd ui && npm install && npm run dev   # http://localhost:5173

# Build UI for production (output: src/kore/ui/static/)
cd ui && npm run build
```

`python -m kore.main` dispatches subcommands via `_cli_main()` in `kore/main.py`; default is `gateway`. There is no `kore/__main__.py`, so `python -m kore <cmd>` won't work — always invoke `kore.main`. The Docker entrypoint runs `python -m kore.main "$@"`, so `docker compose run --rm gateway init` reaches the same dispatcher.

## Tech stack

- **Python 3.12**, async-native throughout (asyncio)
- **Pydantic AI** — LLM abstraction layer. Wraps native SDKs. Single-string provider switching. Auto-generates tool JSON schemas from Python type hints. Provides the `UsageLimits` safety net used on every agent run
- **Anthropic SDK** (via Pydantic AI) — Default LLM provider. Sonnet for the primary agent; Haiku for cheap/narrow work (subagents, consolidation, session compaction). Prompt caching and extended thinking preserved
- **OpenAI SDK** (via Pydantic AI) — Supports OpenAI models, OpenRouter (300+ models), and Ollama (local models) through the same SDK with different `base_url`
- **FastAPI** — Gateway API + WebSocket log streaming + static file serving for UI
- **python-telegram-bot v20+** — Telegram channel (webhook mode)
- **croniter 2.x + asyncio** — CRON scheduler (no APScheduler; custom asyncio timer loop with `jobs.json` as authoritative store)
- **SQLAlchemy 2.0 (async) + aiosqlite** — ORM, Postgres-portable later
- **SQLite FTS5** — BM25 keyword search on memory events
- **sqlite-vec** — Vector cosine similarity search in SQLite
- **sentence-transformers** — Local embeddings (all-MiniLM-L6-v2), zero API cost
- **httpx + trafilatura** — Async web scraping + content extraction
- **Brave Search API** — Web search for agents (default provider, free tier available)
- **Pydantic v2** — Config validation, env var loading
- **PyYAML** — SKILL.md frontmatter parsing
- **React + Vite** — Dashboard frontend (built and served as static files by FastAPI)
- **Docker + docker-compose** — Container isolation, read-only filesystem
- **pytest + pytest-asyncio** — Test framework, async test support
- **respx** — Mock httpx requests (web search, scraping, Telegram webhook — but not LLMs; see Testing rules)

## Project structure

```
first-personal-assistant/
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh                     # Drops privileges to uid 1000, dispatches `python -m kore.main "$@"`
├── prompts/                          # System prompts (Markdown, baked into image as KORE_PROMPTS_DIR=/app/prompts)
│   ├── primary.md                    # Primary agent — "You are Kore..."
│   ├── deep_research.md              # Subagent: web research → compressed report
│   └── draft_longform.md             # Subagent: long-form writing
├── skills/                           # Built-in skills (SKILL.md format, OpenClaw/Nanobot compatible)
│   ├── search-topic-online/SKILL.md  # Search strategy, source evaluation, synthesis
│   ├── content-writer/SKILL.md       # LinkedIn, emails, summaries — tone, structure
│   ├── memory-management/SKILL.md    # When/how to use memory tools (always-on)
│   ├── skill-creator/SKILL.md        # Meta-skill: how to create new skills
│   └── skill-vetter/SKILL.md         # Security vetting protocol before installing skills
│   # email-management and daily-digest are planned but not yet written
├── src/
│   └── kore/
│       ├── __init__.py
│       ├── main.py                   # CLI entry — `init` / `migrate` / `gateway` (default)
│       ├── init.py                   # `~/.kore/` bootstrap (config.json, SOUL.md, USER.md, jobs.json) + migrate stub
│       ├── config.py                 # Pydantic models + `load_config()`. Defines KORE_HOME = ~/.kore
│       ├── logging_config.py         # JSON-structured logging setup
│       ├── gateway/
│       │   ├── server.py             # FastAPI app definition + lifespan
│       │   ├── routes_api.py         # REST endpoints (/api/*)
│       │   ├── routes_webhook.py     # Telegram webhook endpoint
│       │   ├── routes_ws.py          # WebSocket endpoint (log streaming only — session traces use REST polling)
│       │   ├── auth.py               # Basic auth enforcement
│       │   ├── log_handler.py        # Log handler that feeds the WS stream
│       │   ├── trace_events.py       # EventKind / EventType / span_event helpers (span-shaped)
│       │   ├── trace_store.py        # SQLite-backed session trace persistence (7-day TTL)
│       │   └── queue.py              # Async message queue
│       ├── agents/
│       │   ├── base.py               # Shared agent helpers
│       │   ├── deps.py               # `KoreDeps` — dependency injection container for tools (memory, registry, channel)
│       │   ├── primary.py            # `build_primary()` — single conversational agent + skill injection + subagent wiring
│       │   ├── orchestrator.py       # Runs one primary turn per message; emits span-shaped trace events
│       │   ├── system_prompts.py     # `current_time_fragment()` — refreshed per-run via `@agent.system_prompt`
│       │   └── subagents/
│       │       ├── deep_research.py  # `build_deep_research_agent()` + `make_deep_research_tool()`
│       │       └── draft_longform.py # `build_draft_longform_agent()` + `make_draft_longform_tool()`
│       ├── llm/
│       │   ├── provider.py           # `get_model()` — model string → Pydantic AI model instance, threading auth from KoreConfig
│       │   └── types.py              # Shared types: KoreMessage, ToolCall, AgentResponse
│       ├── skills/
│       │   ├── loader.py             # SKILL.md parser: YAML frontmatter + Markdown body
│       │   ├── registry.py           # Discovery, dependency checks, per-agent skill mapping, Level 1/2 context builders
│       │   └── clawhub.py            # ClawHub client: search, install, update skills
│       ├── tools/
│       │   ├── registry.py           # `register()` + `get_tools()` collection. `get_tools(["*"])` expands to every registered tool
│       │   ├── web_search.py         # Brave Search API
│       │   ├── scrape.py             # URL content extraction
│       │   ├── file_rw.py            # Sandboxed file I/O (read_file, write_file)
│       │   ├── memory_tools.py       # core_memory_update, core_memory_delete, memory_search, memory_store
│       │   ├── cron_tools.py         # cron_create, cron_list, cron_delete
│       │   ├── skill_tools.py        # skill_search, read_skill, skill_install
│       │   ├── time_tool.py          # get_current_time (also injected as a system-prompt fragment)
│       │   └── shell.py              # Sandboxed run_shell (per-agent allowlist)
│       ├── memory/
│       │   ├── core_memory.py        # Layer 1: JSON-based always-in-context memory
│       │   ├── event_log.py          # Layer 2: Append-only SQLite event store
│       │   ├── retrieval.py          # Hybrid BM25+vector search with temporal decay
│       │   ├── consolidation.py      # Layer 3: Background consolidation agent (Haiku, every 30 min)
│       │   ├── extraction.py         # Automatic post-conversation memory extraction
│       │   └── embeddings.py         # Embedding model wrapper (local + API fallback)
│       ├── channels/
│       │   ├── base.py               # Channel ABC (send, on_message)
│       │   └── telegram.py           # Telegram adapter (webhook). Markdown→HTML conversion + session resumption
│       ├── session/
│       │   ├── buffer.py             # In-memory message buffer per session
│       │   └── compactor.py          # LLM-based compaction when context limit approached
│       ├── scheduler/
│       │   └── cron.py               # `KoreCronScheduler` — asyncio CRON loop, jobs.json store
│       ├── db/
│       │   └── database.py           # SQLAlchemy async engine setup
│       └── ui/
│           └── static/               # Built React frontend (output of `cd ui && npm run build`)
├── ui/                               # React source (Vite)
│   ├── package.json
│   └── src/
│       ├── App.jsx
│       └── pages/                    # Overview, Logs, Jobs, Agents, Memory, Settings
├── prompts/                          # (see top of tree)
├── tests/                            # see tests/ directory — every module has corresponding tests
├── docs/superpowers/{plans,specs}/   # design/spec docs for v2 sub-projects
├── pyproject.toml
└── README.md
```

Runtime data lives at `~/.kore/` on the host (mounted into the container at `/root/.kore`) — see "Config structure" below for the layout.

## Architecture rules

### Agent pattern: primary + subagents (one Pydantic AI loop per turn)

- The **primary** agent (`agents/primary.py`, `prompts/primary.md`) holds the entire conversation in its own context. One `Agent.run()` per inbound message. It calls tools directly when needed and decides when to delegate.
- Two **subagents** are exposed as `@agent.tool` wrappers on the primary itself: `deep_research(query, focus?)` and `draft_longform(brief, audience?, constraints?)`. Each is an independent Pydantic AI `Agent` with its own model, prompt, tools, and skills. They return **compressed results** so their work doesn't pollute the primary's context for the rest of the turn. Delegation happens *inside* the primary's run loop — not in the orchestrator.
- The schema (`config.py:AgentsConfig`) only allows `primary` + a dict of subagents whitelisted to `{"deep_research", "draft_longform"}`. Adding more subagents is a deliberate code change, not a config flip. v1's `general` / `search` / `writer` / `digest` executors are gone — `load_config()` raises `ConfigError` with a migration pointer if it sees them.
- Every agent run carries a `UsageLimits` (`request_limit`, `total_tokens_limit`, `tool_calls_limit`) cap. Subagent token usage propagates via `ctx.usage`, so the primary's limit covers the whole run tree.
- The orchestrator (`agents/orchestrator.py`) emits **span-shaped** trace events: every event has `span_id` + `parent_span_id`. The `session_start` span is the root; `primary_start` is a child; subagent invocations form their own subtrees. The React UI groups by these spans.
- Public Agent contract: `build_primary()` sets three `_kore_*` attributes on the returned `Agent` that the orchestrator reads — `_kore_skills_loaded` (list[str]), `_kore_model_string` (str), `_kore_usage_limits` (UsageLimits). Renaming or removing any of these breaks the orchestrator.

### Memory system: three layers

**Layer 1 — Core Memory** (`~/.kore/data/core_memory.json`):
- Structured JSON loaded into every prompt. User profile, preferences, active projects, rules.
- Hard cap: 4,000 tokens. Writes exceeding cap are rejected.
- Updated by the agent via `core_memory_update(path, value)` and `core_memory_delete(path)` tools.
- Also updated by the consolidation agent when promoting durable facts.

**Layer 2 — Event Log** (SQLite table `events`):
- Append-only timestamped events: conversation summaries, facts, corrections.
- Schema: `id, timestamp, category, content, source, importance (0-1), embedding, consolidated, superseded_by`.
- Retrieved via hybrid search: 70% vector (sqlite-vec cosine), 30% BM25 (FTS5). Temporal decay with 60-day half-life applied to scores.
- Dual writes: automatic post-conversation extraction (always runs) + explicit `memory_store()` tool (agent-initiated).
- Embedding cascade: local sentence-transformers → Anthropic API → BM25-only fallback.

**Layer 3 — Consolidation Agent** (background, every 30 min):
- Reads unconsolidated events.
- Promotes durable facts to core memory.
- Detects contradictions → resolves by timestamp (newer wins), marks old events `superseded_by`.
- Compresses old events into weekly summaries.
- Garbage-collects stale low-importance events (>90 days, importance <0.3).
- Uses Claude Haiku (cheap, fast).

### Gateway

- FastAPI serves: REST API (`/api/*`), Telegram webhook, WebSocket for log streaming, React static files.
- All inbound messages (Telegram, CRON, API) normalize to a `Message` object and enter an async queue.
- Endpoints: `/api/message`, `/api/jobs`, `/api/agents`, `/api/logs`, `/api/memory`, `/api/skills`, `/api/sessions/*` (trace polling).

### Channels

- Abstract `Channel` class with `send()` and `on_message()`.
- Telegram: webhook mode (not polling), Markdown-formatted replies, 4096-char chunking, `/status`, `/jobs`, `/memory`, `/cancel`, `/new` commands.
- `allowed_user_ids` whitelist — unknown users get no response.
- **Telegram HTML formatting:** `send()` converts Markdown via `_md_to_telegram_html()`. Supported tags only: `<b>`, `<i>`, `<u>`, `<s>`, `<code>`, `<pre>`, `<a>`, `<blockquote>`. No `<table>`, `<p>`, `<h1>`–`<h6>`, `<ul>`/`<li>`, `<br>`. Tables → `<pre>` with padded columns. Use `_esc()` (only escapes `&`, `<`, `>`) **not** `html.escape()` — the latter produces `&#x27;` which Telegram rejects and silently drops the entire message.
- **Session resumption:** `_resolve_session()` scans `~/.kore/workspace/sessions/telegram_{uid}*.json` by mtime on first message after restart. `/new` creates a timestamped session ID to start fresh.

### CRON

- Custom asyncio timer loop using `croniter` for cron expression parsing. No APScheduler. Class: `KoreCronScheduler` (`scheduler/cron.py`).
- **`~/.kore/data/jobs.json`** is the authoritative job store — survives restarts, no SQLite dependency.
- **Dynamic jobs** are created by the agent at runtime via `cron_create(schedule, prompt)` + `cron_list` / `cron_delete`. Jobs fire as `source=cron` and inject a `Message` into the gateway queue.
- The same scheduler also hosts the memory consolidation timer (every 30 min).

### Skills (OpenClaw/Nanobot SKILL.md format)

Skills are **Markdown instruction documents** that teach Kore how to approach a class of tasks. They are NOT executable code and NOT tool definitions — they are procedural knowledge injected into the agent's context window. The agent reads the skill and decides which tools to call.

**Format:** Each skill is a directory containing a `SKILL.md` file with YAML frontmatter (name, description, metadata) and a Markdown body (instructions). Optional `scripts/` and `references/` subdirectories for helpers and docs. Fully compatible with OpenClaw and Nanobot skills.

```yaml
---
name: web-research
description: How to search the web effectively and synthesize findings
metadata: '{"kore":{"emoji":"🔍","always":false,"requires":{"tools":["web_search","scrape_url"]}}}'
---
# Web Research Skill

When asked to research a topic:
1. Break the query into 2-3 specific search queries
2. Use `web_search` for each query
3. Evaluate results — prefer primary sources over aggregators
4. Use `scrape_url` on the top 2-3 results for full content
5. Synthesize findings, noting contradictions between sources
...
```

**Loading strategy (progressive disclosure):**
- **Level 1 — Summary (every turn):** All assigned skills listed as compact XML with name, description, path. ~100 tokens per skill.
- **Level 2 — Always-on:** Skills with `"always": true` in metadata have their full body loaded every turn. Use sparingly (only `memory-management` today).
- **Level 3 — On-demand:** Agent calls `read_skill` (scoped to its `allowed_skill_names`) to load the full SKILL.md when relevant.

**Per-agent skill assignment.** Both the primary and each subagent declare `skills: ["*"]` (all) or an explicit list. `skill_registry.get_skills_for_executor(skills_list, available_tools=...)` resolves the list and filters out skills whose required tools aren't available to that agent. The primary defaults to `["*"]`; subagents typically pin a small set (`deep_research` → `search-topic-online`; `draft_longform` → `content-writer`).

**Discovery precedence:** User skills (`~/.kore/workspace/skills/`) override built-in skills (`skills/` baked into the image). ClawHub-installed skills go to the user dir.

**ClawHub integration:** The `clawhub.py` client searches, installs, and updates skills from ClawHub. Installed skills land as directories in the user dir. Dependency checking validates required tools/bins/env vars before activation.

**Hot-reload after install:** When a skill is installed via ClawHub (or manually dropped into the user dir), the registry auto-reloads: re-scans directories, runs dependency checks, rebuilds the Level 1 summary XML. The new skill is immediately available to agents whose skill list is `["*"]` — no restart required. Agents with explicit lists need a config update.

**Skill visibility:** The primary's `_kore_skills_loaded` records the names of skills injected at build time; the orchestrator emits this in `primary_start` trace events. Level 3 on-demand `read_skill` calls are tagged as `skill_read` in `tool_call` trace events.

**Built-in skills (implemented):** `search-topic-online`, `content-writer`, `memory-management` (always-on), `skill-creator`, `skill-vetter`. (`email-management` and `daily-digest` are planned but not written.)

### Persona layer (SOUL.md / USER.md)

Two Markdown files in `~/.kore/` are injected into every agent's system prompt at build time (before the agent's own prompt):

- **`SOUL.md`** — Kore's personality: tone, communication style, values, anti-patterns to avoid.
- **`USER.md`** — user profile: name, timezone, role, current projects, priorities.

`build_primary()` (and the `build_*_agent()` subagent builders) call `_load_persona(kore_home)`, which reads both files, joins them with `---`, and prepends to the prompt. Missing files are silently skipped. `python -m kore init` creates stub versions of both. These files are local config (not in the repo).

### Tools

- Tools are Python functions registered into a global registry (`tools/registry.py`) and attached to an agent via `get_tools(["name", ...])`. JSON schemas auto-generated from type hints + docstrings by Pydantic AI.
- Built-in tools: `web_search` (Brave Search — `[{title, url, snippet}]`), `scrape_url`, `read_file`, `write_file`, `core_memory_update`, `core_memory_delete`, `memory_search`, `memory_store`, `cron_create`, `cron_list`, `cron_delete`, `get_current_time`, `skill_search`, `read_skill`, `skill_install`, `run_shell` (only binaries in the agent's `shell_allowlist` may run).
- The current UTC date/time is *also* injected on every run via the `current_time_fragment` system-prompt callback (`agents/system_prompts.py`), so subagents have it without an explicit `get_current_time` call.
- Tool access per agent follows least privilege (configured in `config.json`).

### LLM abstraction (Pydantic AI)

Pydantic AI is the LLM abstraction layer. It wraps native SDKs (Anthropic, OpenAI) preserving provider-specific features (prompt caching, extended thinking for Claude). Agents are created with a model string:

```python
from pydantic_ai import Agent
from kore.agents.deps import KoreDeps
from kore.agents.system_prompts import current_time_fragment
from kore.llm.provider import get_model
from kore.tools.registry import get_tools

agent: Agent[KoreDeps, str] = Agent(
    get_model("anthropic:claude-sonnet-4-6", kore_config),
    system_prompt=primary_prompt,            # SOUL.md + USER.md + prompts/primary.md + skill context
    tools=get_tools(["web_search", "scrape_url", "memory_search", ...]),
    output_type=str,
    deps_type=KoreDeps,
)

agent.system_prompt(current_time_fragment)   # refreshed on every agent.run()

# Subagents are wired in as @agent.tool wrappers — they are themselves Agents
# whose `await sub.run(...)` returns a compressed result the primary sees as a
# tool return.
```

**Provider switching** is a config change — `'anthropic:claude-sonnet-4-6'` → `'openai:gpt-4o'` → `'openrouter:anthropic/claude-sonnet-4-6'` → `'ollama:qwen3:8b'`. No code changes. Pydantic AI handles format translation (tool schemas, messages, responses) automatically.

**Supported providers: Anthropic, OpenAI, OpenRouter, Ollama.** Anthropic is the default. Others work by changing the model string in `config.json` — install the corresponding SDK (`openai` for OpenAI/OpenRouter/Ollama) as an optional dependency. Auth always flows through `KoreConfig.llm.providers`, never ambient env vars at LLM-call time.

## Code conventions

- **Tests are mandatory.** Every module, feature, and bug fix must have corresponding tests. No PR or implementation is complete without tests. Write tests alongside the code, not after.
- **Async everywhere.** All I/O (LLM calls, DB, HTTP, Telegram) uses asyncio. No sync blocking in the main loop.
- **Pydantic for config.** `config.py` validates `config.json` using Pydantic v2 models. API keys are never in config — only env var names with `_env` suffix.
- **System prompts in Markdown files.** `prompts/*.md` — editable without code changes. Baked into the image; the path is overridable via `KORE_PROMPTS_DIR`.
- **Shell execution is allowlisted.** `run_shell` exists but each agent declares which binaries it may run via `shell_allowlist` in config. Default is empty (no shell access). File I/O sandboxed to `~/.kore/workspace/files/`.
- **Structured logging.** JSON-formatted logs, filterable by agent/level.
- **Type hints on everything.** Use `from __future__ import annotations` in all files.

## Testing rules

**Tests are a must-have, not a nice-to-have. Every phase of implementation includes tests. Code without tests is incomplete code.**

### Test framework
- **pytest** with **pytest-asyncio** for all async code.
- **Pydantic AI's `TestModel`** for deterministic agent testing — returns predefined responses, captures tool calls, no real API calls needed. This is the primary mocking strategy for all agent/primary/subagent tests.
- **respx** to mock httpx requests for non-LLM HTTP calls (Brave Search, scraped URLs, Telegram webhook).
- **In-memory SQLite** for database tests — no test pollution, fast teardown.
- Shared fixtures in `tests/conftest.py`: Pydantic AI `TestModel` instances, test SQLite database, sample `config.json`, sample `core_memory.json`.

### What to test per component

| Component | Must-test |
|-----------|-----------|
| **Config** | Valid config loads, missing required fields fail, env var resolution, Pydantic validation, legacy v1 keys raise `ConfigError` with migration pointer |
| **Agents / LLM** | Agent creation from config, model string resolution, tool registration, persona injection, `_kore_*` orchestrator-contract attributes, `TestModel` round-trips |
| **Skills** | SKILL.md parsing (frontmatter + body), discovery precedence (user overrides built-in), dependency checking (tools, bins, env), per-agent mapping, always-on loading, ClawHub search/install mock, **hot-reload after install** (registry picks up new skill, summary XML rebuilt, wildcard agents see it), `skill_search`/`skill_install` tools, `_kore_skills_loaded` on the primary, `skill_read` tag in `tool_call` trace events |
| **Tools** | Type hint → JSON schema generation, tool execution, error handling, registry `get_tools` lookups |
| **Primary agent** | Single-loop turn, persona + skills injection, subagent tool wiring, `UsageLimits` enforcement, `current_time_fragment` is per-run not per-build |
| **Subagents** | `deep_research` and `draft_longform`: prompt loading, tool restrictions, compressed return shape, usage propagation via `ctx.usage` |
| **Orchestrator** | Single-primary turn end-to-end, span-shaped trace event emission (`session_start` → `primary_start` → `tool_call` / `subagent_start` ...), `UsageLimitExceeded` handling |
| **Core memory** | CRUD operations, 4K token cap enforcement, invalid path handling |
| **Event log** | Insert events, FTS5 keyword search, sqlite-vec vector search, hybrid score fusion |
| **Retrieval** | Temporal decay calculation, BM25+vector merge, min_score filtering, top-K ranking |
| **Consolidation** | Fact promotion to core memory, contradiction detection + resolution, event compression, GC threshold |
| **Extraction** | Conversation → event extraction, empty conversation handling, importance scoring |
| **Telegram** | Message normalization, chunking (>4096 chars), `allowed_user_ids` filtering, command parsing, Markdown→HTML conversion (with the `_esc` vs `html.escape` gotcha), session resumption by mtime |
| **CRON** | Job scheduling, timezone handling (DST), job persistence across restart, consolidation timer, **dynamic job creation/deletion via tools**, cron expression validation |
| **Gateway** | Route responses, auth enforcement, rate limiting, WebSocket connection, `GET /api/skills` (builtin/user split, active/missing computation, reload-on-request, null registry fallback), session-trace REST endpoints |
| **Trace store** | Append/read round-trip, 7-day TTL cleanup, span tree reconstruction |
| **Integration** | Full flow: Telegram message → gateway queue → primary → tools/subagents → memory → reply |

### Testing patterns
- **Use Pydantic AI's `TestModel` for agent tests.** It returns structured responses, records tool calls, and requires no API keys.
- **Use `respx` for external HTTP calls.** Mock Brave Search, URL scraping, Telegram webhook — but NOT the LLM (that's `TestModel`'s job).
- **Mock external services, not internal modules.** Never mock the tool registry, memory retrieval, or agent orchestration logic.
- **Test memory in isolation and in integration.** Unit tests verify each memory layer independently. Integration tests verify the full flow: conversation → extraction → event store → retrieval → core memory promotion via consolidation.
- **Test failure paths.** Every component should have tests for: invalid input, API errors/timeouts, empty results, token limit exceeded, auth rejected.

## Environment variables

API keys go in `~/.kore/.env` only — never in `config.json` or logs. Reference them in config via the `_env` suffix convention (e.g. `"api_key_env": "ANTHROPIC_API_KEY"`). `load_config()` calls `load_dotenv(KORE_HOME / ".env", override=False)` before parsing.

```
# Required
ANTHROPIC_API_KEY=...          # default LLM provider (Claude Sonnet/Haiku)
BRAVE_API_KEY=...              # web search (free tier available)
TELEGRAM_BOT_TOKEN=...         # Telegram channel
TELEGRAM_WEBHOOK_URL=...       # public HTTPS URL Telegram will POST to

# Optional — only needed if using alternative LLM providers
OPENAI_API_KEY=...             # OpenAI models or OpenRouter (300+ models)
                               # Also used for Ollama (set base_url in config)
```

`KORE_PROMPTS_DIR` (set to `/app/prompts` by the Dockerfile) overrides the prompt directory lookup — useful for tests or alternative deployments.

## Security

- Docker: read-only filesystem, non-root user (uid 1000), `no-new-privileges`, only `/root/.kore` (mount) and `/tmp` (tmpfs) writable.
- API keys: env vars only (`~/.kore/.env`), never in config or logs.
- Telegram: `allowed_user_ids` whitelist.
- Scraped content: marked as `[EXTERNAL_CONTENT]` in messages to defend against prompt injection.
- Rate limiting: configurable per-user, max tool calls per request cap (default 15), `UsageLimits` per agent run.
- UI: basic auth on all `/api` routes.

## Config structure

`config.json` top-level keys: `version`, `llm` (providers config: API keys, base URLs for OpenRouter/Ollama), `agents` (`primary` + `subagents` dict — see schema in `config.py:AgentsConfig`), `skills` (directories, ClawHub settings), `channels` (telegram token + allowed users), `memory` (core_memory path + event_log retrieval settings + consolidation settings), `scheduler` (timezone + jobs file), `tools` (per-tool config — `web_search.provider: "brave"`, `web_search.api_key_env: "BRAVE_API_KEY"`), `security` (rate limits), `ui` (port + auth), `session` (compaction model + thresholds), `debug` (`session_tracing` toggle).

**`~/.kore/` layout** (host path; mounted to `/root/.kore` in the container):

```
~/.kore/
├── config.json                       # Operational config (NOT in the repo)
├── .env                              # Secrets — loaded by load_config() via python-dotenv
├── SOUL.md                           # Kore's personality (prepended to every agent prompt)
├── USER.md                           # User profile (prepended to every agent prompt)
├── kore.db                           # SQLite — events, FTS5, sqlite-vec, trace store
├── data/
│   ├── core_memory.json              # Layer 1 memory (4k-token-capped JSON)
│   └── jobs.json                     # CRON jobs (authoritative)
└── workspace/
    ├── sessions/                     # Per-session message buffers (JSON, mtime-keyed)
    ├── skills/                       # User-installed skills (override built-ins)
    └── files/                        # Sandboxed file I/O (read_file/write_file)
```

**Runtime config location.** The operational config lives at `~/.kore/config.json` on the host and is mounted into the gateway container at `/root/.kore/config.json` via `docker-compose.yml` (volume `~/.kore:/root/.kore`). There is **no `config.json` in the repo** — edits for a deployed instance go to `~/.kore/config.json`. Back it up (`cp ~/.kore/config.json ~/.kore/config.json.bak`) before any schema change; `load_config()` raises `ConfigError` with a migration pointer when it sees removed v1 keys (`agents.planner` / `agents.executors`). After editing, `docker compose restart gateway` is enough unless code also changed.

**Tool list wildcard.** `tools.registry.get_tools(["*"])` expands to every registered tool (sorted by name for deterministic ordering). `"*"` may only appear as the sole entry — mixing it with explicit names raises `ValueError`. `PrimaryAgentConfig.tools` defaults to `["*"]`, so omitting `tools` grants the primary full access; subagents should enumerate an explicit allowlist for least privilege. Skills lists also accept `["*"]` (handled by `skill_registry.get_skills_for_executor`).

## v2 architecture roadmap — sub-project status

The v2 refactor is decomposed into four sub-projects. Specs and plans live under `docs/superpowers/{specs,plans}/`.

1. **Primary-agent refactor — SHIPPED.** Planner and per-task executors removed. One conversational primary per turn; `deep_research` and `draft_longform` are `@agent.tool`-exposed subagents. Span-shaped trace events. `UsageLimits` on every run. Spec: `docs/superpowers/specs/2026-04-19-primary-agent-refactor-design.md`. (This is what the codebase implements today — the sections above describe the shipped state.)
2. **Workflows for scheduled/known pipelines — PAUSED in brainstorming.** Direction set: workflows must be **declarative data files** (YAML/JSON, OpenClaw Lobster shape) listing ordered steps, with LLM calls as just another tool — not Python decorators. Reference workflow target: `daily_digest.json`. Spec draft: `docs/superpowers/specs/2026-04-24-workflows-design.md`. Resume by writing the schema, not the runtime.
3. **Sleep-time consolidator hardening — NOT STARTED.** Audit `memory/consolidation.py` for idle-time scheduling, race safety, and Generative-Agents-style reflection (rewriting core-memory blocks from raw observations).
4. **Observability upgrade — NOT STARTED.** Add `logfire.instrument_pydantic_ai()` + FastAPI/SQLAlchemy/httpx instrumentation. Decide whether to fold the custom `trace_store` into OTEL spans or keep both (OTEL for depth, trace_store for the UI).

Sub-projects 2–4 can happen in any order. Each goes through brainstorming → spec → plan → implementation as a separate cycle.

## What is NOT implemented

Deferred. Do not implement unless explicitly asked:

- **Workflow engine** — design in progress (sub-project 2 above), but no runtime yet
- **MCP server support**
- **Knowledge graph memory** (entity-relationship layer)
- **Additional channels** (Discord, Slack, WhatsApp, browser chat)
- **Voice input** (Whisper transcription)
- **PostgreSQL** (use SQLite for now)
- **Tavily web search** (alternative to Brave Search)
- **Logfire / OpenTelemetry** (sub-project 4)
