# Kore — Personal AI Assistant Platform

## What is this project

Kore is a Python-native, Docker-first personal AI assistant platform. It uses a planner/executor agent pattern with multi-provider LLM support via Pydantic AI — Anthropic Claude is the default, with OpenAI, OpenRouter, and Ollama supported out of the box. Users interact via Telegram. The system runs scheduled tasks via CRON, remembers context long-term via a three-layer memory system, and exposes a Web UI dashboard for monitoring.

## Commands

```bash
# First-time setup — bootstrap ~/.kore/ (SOUL.md, USER.md, config stubs)
python -m kore.init

# Run tests
pytest

# Start gateway (Docker)
docker-compose up

# UI dev server
cd ui && npm install && npm run dev   # http://localhost:5173

# Build UI for production
cd ui && npm run build
```

## Tech stack

- **Python 3.12**, async-native throughout (asyncio)
- **Pydantic AI** — LLM abstraction layer (v1 stable). Wraps native SDKs. Single-string provider switching. Auto-generates tool JSON schemas from Python type hints
- **Anthropic SDK** (via Pydantic AI) — Default LLM provider. Claude Sonnet for planning, Haiku for cheap tasks. Prompt caching and extended thinking preserved
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
- **respx** — Mock httpx requests (LLM API, web search, scraping)

## Project structure

```
kore/
├── docker-compose.yml
├── Dockerfile
├── config.json                    # Main configuration (mounted read-only)
├── config/
│   └── jobs.json                  # CRON job definitions
├── prompts/                       # System prompts for each agent (Markdown files)
│   ├── planner.md
│   ├── general.md
│   ├── writer.md
│   ├── search.md
│   └── digest.md
├── data/                          # ~/.kore/ on host (mounted volume — persists across restarts)
│   ├── kore.db                    # SQLite database (events, logs)
│   ├── jobs.json                  # CRON job store (authoritative, survives restarts)
│   ├── core_memory.json           # Layer 1: always-in-context structured memory
│   ├── skills/                    # User-installed skills (ClawHub downloads, custom)
│   └── files/                     # Sandboxed file storage for tools
├── skills/                        # Built-in skills (SKILL.md format, OpenClaw/Nanobot compatible)
│   ├── search-topic-online/SKILL.md  # Search strategy, source evaluation, synthesis
│   ├── content-writer/SKILL.md    # LinkedIn, emails, summaries — tone, structure
│   ├── memory-management/SKILL.md # When/how to use memory tools (always-on)
│   ├── skill-creator/SKILL.md     # Meta-skill: how to create new skills
│   └── skill-vetter/SKILL.md      # Security vetting protocol before installing skills
│   # email-management and daily-digest skills not yet implemented
├── src/
│   └── kore/
│       ├── __init__.py
│       ├── main.py                # Entry point — starts FastAPI + scheduler + channels
│       ├── config.py              # Config loader and validation (Pydantic)
│       ├── gateway/
│       │   ├── server.py          # FastAPI app definition and routes
│       │   ├── routes_api.py      # REST endpoints (/api/*)
│       │   ├── routes_webhook.py  # Telegram webhook endpoint
│       │   ├── routes_ws.py       # WebSocket endpoints (log streaming only; /ws/sessions removed — session traces use REST polling)
│       │   ├── auth.py            # Basic auth enforcement
│       │   ├── log_handler.py     # Log handler that feeds WebSocket stream
│       │   ├── trace_store.py     # SQLite-backed session trace persistence (7-day TTL)
│       │   └── queue.py           # Async message queue
│       ├── agents/
│       │   ├── base.py            # Base agent using Pydantic AI Agent class
│       │   ├── deps.py            # Pydantic AI dependency injection types (AgentDeps)
│       │   ├── planner.py         # Planner agent (intent classification + executor routing)
│       │   ├── executor.py        # Generic executor (config-driven model, tools, prompt, skills)
│       │   └── orchestrator.py    # Runs planner → executor pipeline
│       ├── llm/
│       │   ├── provider.py        # Provider factory: model string → Pydantic AI model instance
│       │   └── types.py           # Shared types: KoreMessage, ToolCall, AgentResponse
│       ├── skills/
│       │   ├── loader.py          # SKILL.md parser: YAML frontmatter + Markdown body extraction
│       │   ├── registry.py        # Skill discovery, dependency checking, executor mapping
│       │   └── clawhub.py         # ClawHub client: search, install, update skills
│       ├── tools/
│       │   ├── registry.py        # Tool collection and executor access mapping
│       │   ├── web_search.py      # Brave Search API
│       │   ├── scrape.py          # URL content extraction
│       │   ├── file_rw.py         # Sandboxed file I/O
│       │   ├── memory_tools.py    # core_memory_update, memory_search, memory_store
│       │   ├── cron_tools.py      # cron_create, cron_list, cron_delete
│       │   ├── skill_tools.py     # skill_search, read_skill, skill_install
│       │   ├── shell.py           # Sandboxed run_shell (per-executor allowlist)
│       │   └── custom/            # User-defined tools (registered via config)
│       ├── memory/
│       │   ├── core_memory.py     # Layer 1: JSON-based always-in-context memory
│       │   ├── event_log.py       # Layer 2: Append-only SQLite event store
│       │   ├── retrieval.py       # Hybrid BM25+vector search with temporal decay
│       │   ├── consolidation.py   # Layer 3: Background consolidation agent
│       │   ├── extraction.py      # Automatic post-conversation memory extraction
│       │   └── embeddings.py      # Embedding model wrapper (local + API fallback)
│       ├── channels/
│       │   ├── base.py            # Channel ABC (send, on_message)
│       │   └── telegram.py        # Telegram adapter (webhook)
│       ├── session/               # Session buffer (renamed from conversation/)
│       │   ├── buffer.py          # In-memory message buffer per session
│       │   └── compactor.py       # LLM-based compaction when context limit approached
│       ├── scheduler/
│       │   └── cron.py            # Asyncio-based CRON scheduler (jobs.json store)
│       # event_bus.py — DELETED; replaced by gateway/trace_store.py
│       ├── logging_config.py      # JSON-structured logging setup
│       ├── init.py                # ~/.kore directory bootstrap
│       ├── db/
│       │   ├── database.py        # SQLAlchemy async engine setup
│       │   └── models.py          # ORM models (events, logs, job_runs)
│       └── ui/
│           └── static/            # Built React frontend
├── ui/                            # React source (Vite)
│   ├── package.json
│   └── src/
│       ├── App.jsx
│       └── pages/                 # Overview, Logs, Jobs, Agents, Memory, Settings
├── tests/
│   ├── conftest.py                # Shared fixtures (Pydantic AI TestModel, test DB, sample config)
│   ├── test_config.py             # Config loading and validation
│   ├── test_agents.py             # Pydantic AI agent creation, model resolution, tool registration
│   ├── test_skills.py             # SKILL.md parsing, discovery, dependency check, executor mapping
│   ├── test_tools.py              # Tool functions, schema generation from type hints
│   ├── test_planner.py            # Planner intent classification + routing
│   ├── test_executor.py           # Executor ReAct loop + tool calling
│   ├── test_orchestrator.py       # End-to-end planner → executor pipeline
│   ├── test_core_memory.py        # Core memory CRUD, token cap enforcement
│   ├── test_event_log.py          # Event store, FTS5, sqlite-vec retrieval
│   ├── test_retrieval.py          # Hybrid search, temporal decay, score fusion
│   ├── test_consolidation.py      # Consolidation agent: promotion, contradiction, GC
│   ├── test_extraction.py         # Automatic post-conversation extraction
│   ├── test_telegram.py           # Telegram adapter (mocked webhook)
│   ├── test_cron.py               # Scheduler, job persistence, timezone handling
│   ├── test_gateway.py            # FastAPI routes, auth, rate limiting
│   └── test_integration.py        # Full message → plan → execute → memory flow
├── pyproject.toml
└── README.md
```

## Architecture rules

### Agent pattern: planner → executor(s)

- The **planner** is a Pydantic AI `Agent` with `result_type=PlanResult` (Pydantic model) for structured JSON output: `{ intent, reasoning, steps: [{ executor, instruction }] }`. Uses Claude Sonnet, temperature 0.3. It never calls tools directly.
- **Executors** are Pydantic AI `Agent` instances, each with their own model string, system prompt, and registered tools. Pydantic AI handles the ReAct loop internally — tool calls, result injection, and iteration. Max iterations configurable via `max_retries`.
- Built-in executors: `general` (Sonnet, all tools), `search` (Sonnet, web_search + scrape), `writer` (Haiku, memory_read), `digest` (Haiku, search + memory tools).
- All agents are config-driven. Adding an executor = adding a JSON block in `config.json` + a prompt file in `prompts/`. The `llm/provider.py` factory creates the right Pydantic AI model instance from the config model string.

### Memory system: three layers

**Layer 1 — Core Memory** (`data/core_memory.json`):
- Structured JSON loaded into every prompt. User profile, preferences, active projects, rules.
- Hard cap: 4,000 tokens. Writes exceeding cap are rejected.
- Updated by agent via `core_memory_update(path, value)` and `core_memory_delete(path)` tools.
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
- Endpoints: `/api/message`, `/api/jobs`, `/api/agents`, `/api/logs`, `/api/memory`.

### Channels

- Abstract `Channel` class with `send()` and `on_message()`.
- Telegram: webhook mode (not polling), Markdown formatting, 4096-char chunking, `/status`, `/jobs`, `/memory`, `/cancel`, `/new` commands.
- `allowed_user_ids` whitelist — unknown users get no response.
- **Telegram HTML formatting:** `send()` converts Markdown via `_md_to_telegram_html()`. Supported tags only: `<b>`, `<i>`, `<u>`, `<s>`, `<code>`, `<pre>`, `<a>`, `<blockquote>`. No `<table>`, `<p>`, `<h1>`–`<h6>`, `<ul>`/`<li>`, `<br>`. Tables → `<pre>` with padded columns. Use `_esc()` (only escapes `&`, `<`, `>`) not `html.escape()` — the latter produces `&#x27;` which Telegram rejects and silently drops the entire message.
- **Session resumption:** `_resolve_session()` scans `~/.kore/workspace/sessions/telegram_{uid}*.json` by mtime on first message after restart. `/new` creates a timestamped session ID to start fresh.

### CRON

- Custom asyncio timer loop using `croniter` for cron expression parsing. No APScheduler.
- **`jobs.json`** (`~/.kore/jobs.json`) is the authoritative job store — survives restarts, no SQLite dependency.
- **Dynamic jobs** created by the agent at runtime via `cron_create(schedule, prompt, executor)` tool. The `channel` parameter was removed; jobs fire as `source=telegram`.
- `cron_list` and `cron_delete` tools for agent-managed job lifecycle.
- Also hosts the memory consolidation timer (every 30 min).
- When a job fires, it injects a Message with `source: "cron"` into the gateway queue.

### Skills (OpenClaw/Nanobot SKILL.md format)

Skills are **Markdown instruction documents** that teach agents how to approach tasks. They are NOT executable code and NOT tool definitions — they are procedural knowledge injected into the agent's context window. The agent reads the skill and decides which tools to call.

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
- **Level 1 — Summary (every turn):** All discovered skills listed as compact XML with name, description, path. ~100 tokens per skill.
- **Level 2 — Always-on:** Skills with `"always": true` in metadata have full body loaded every turn. Use sparingly (only memory-management in v1).
- **Level 3 — On-demand:** Agent reads full SKILL.md via `read_file` when relevant, based on Level 1 summary.

**Per-executor skill assignment:** Each executor's config specifies which skills it loads. The `search` executor loads `web-research`, the `writer` loads `content-writer`, etc. The `general` executor loads all skills.

**Discovery precedence:** User skills (`data/skills/`) override built-in skills (`skills/`). ClawHub-installed skills go to `data/skills/`.

**ClawHub integration:** The `clawhub.py` client can search, install, and update skills from ClawHub (13,000+ community skills). Skills install as directories into `data/skills/`. Dependency checking validates required tools/bins/env vars before activation.

**Hot-reload after install:** When a skill is installed via ClawHub (or manually dropped into `data/skills/`), the skill registry auto-reloads: re-scans directories, runs dependency checks, rebuilds the Level 1 summary XML. The new skill is immediately available to executors with wildcard `"skills": ["*"]` (i.e., the `general` executor) — no restart required. Executors with explicit skill lists only see new skills after a config update. This enables a single-session flow: user says "install the git-manager skill and use it" → ClawHub downloads → registry reloads → agent uses the skill immediately.

**Skill visibility:** `BaseAgent` has a `skills_loaded: list[str]` attribute (set by `create_executor`) that records the names of skills injected at creation time. The orchestrator emits this list in `executor_start` trace events. Level 3 on-demand skill reads (agent calls `read_file` on a `SKILL.md` path) are also tagged as `skill_read` in `tool_call` trace events.

**v1 built-in skills (implemented):** `search-topic-online`, `content-writer`, `memory-management` (always-on), `skill-creator`, `skill-vetter` (security vetting protocol for skills before install). (`email-management` and `daily-digest` are planned but not yet written.) `summarize` (CLI-based URL/file summarizer, requires `summarize` bin) is a user-installed skill (`data/skills/`).

### Persona layer (SOUL.md / USER.md)

Two Markdown files in `~/.kore/` are injected into every executor's system prompt at creation time (before the executor's own prompt):

- **`SOUL.md`** — agent personality: tone, communication style, values, anti-patterns to avoid.
- **`USER.md`** — user profile: name, timezone, role, current projects, priorities.

`create_executor()` calls `_load_persona(kore_home)` which reads both files, joins them with `---`, and prepends the result to the executor's system prompt. Missing files are silently skipped. `kore init` creates stub versions of both. These files are local config (not in the repo).

### Tools

- Tools are Python functions decorated with Pydantic AI's `@agent.tool` decorator. JSON schemas auto-generated from type hints and docstrings.
- Custom tools in `kore/tools/` are registered to agents via the executor config.
- v1 tools: `web_search` (Brave Search API — returns `[{title, url, snippet}]`), `scrape_url`, `read_file`, `write_file`, `core_memory_update`, `core_memory_delete`, `memory_search`, `memory_store`, `cron_create`, `cron_list`, `cron_delete`, `get_current_time`, `skill_search` (search ClawHub for skills), `read_skill` (load assigned skill body — scoped to executor's `allowed_skill_names`), `skill_install` (install skill from ClawHub + auto-reload registry), `run_shell` (sandboxed shell — only binaries in executor's `shell_allowlist` may run).
- Tool access per executor follows least privilege (configured in `config.json`).
- Skills reference tools by name — the agent reads skill instructions and calls the appropriate tools.

### LLM abstraction (Pydantic AI)

Pydantic AI is the LLM abstraction layer. It wraps native SDKs (Anthropic, OpenAI) preserving provider-specific features (prompt caching, extended thinking for Claude). Agents are created with a model string:

```python
from pydantic_ai import Agent, RunContext

planner = Agent(
    'anthropic:claude-sonnet-4-6',
    system_prompt="You are a task planner...",
    result_type=PlanResult,  # Pydantic model for structured output
)

@planner.tool
async def memory_search(ctx: RunContext, query: str, max_results: int = 10) -> str:
    """Search the event log for relevant memories."""
    return await ctx.deps.memory.search(query, max_results)
```

**Provider switching** is a config change — `'anthropic:claude-sonnet-4-6'` → `'openai:gpt-4o'` → `'openrouter:anthropic/claude-sonnet-4-6'` → `'ollama:qwen3:8b'`. No code changes. Pydantic AI handles format translation (tool schemas, messages, responses) automatically.

**v1 supports Anthropic, OpenAI, OpenRouter, and Ollama.** Anthropic is the default and recommended provider. Others work by changing the model string in `config.json` — Pydantic AI handles format translation automatically. Install the corresponding SDK (`openai` for OpenAI/OpenRouter/Ollama) as an optional dependency.

## Code conventions

- **Tests are mandatory.** Every module, feature, and bug fix must have corresponding tests. No PR or implementation is complete without tests. Write tests alongside the code, not after.
- **Async everywhere.** All I/O (LLM calls, DB, HTTP, Telegram) uses asyncio. No sync blocking in the main loop.
- **Pydantic for config.** `config.py` validates `config.json` using Pydantic v2 models. API keys are never in config — only env var names with `_env` suffix.
- **System prompts in Markdown files.** `prompts/*.md` — editable without code changes.
- **Shell execution is allowlisted.** `run_shell` exists but each executor declares which binaries it may run via `shell_allowlist` in config. Default is empty (no shell access). File I/O sandboxed to `~/.kore/files/`.
- **Structured logging.** JSON-formatted logs, filterable by agent/level.
- **Type hints on everything.** Use `from __future__ import annotations` in all files.

## Testing rules

**Tests are a must-have, not a nice-to-have. Every phase of implementation includes tests. Code without tests is incomplete code.**

### Test framework
- **pytest** with **pytest-asyncio** for all async code.
- **Pydantic AI's `TestModel`** for deterministic agent testing — returns predefined responses, captures tool calls, no real API calls needed. This replaces manual HTTP mocking for agent tests.
- **respx** to mock httpx requests for non-agent HTTP calls (Brave Search, scraped URLs, Telegram webhook).
- **In-memory SQLite** for database tests — no test pollution, fast teardown.
- Shared fixtures in `tests/conftest.py`: Pydantic AI `TestModel` instances, test SQLite database, sample `config.json`, sample `core_memory.json`.

### What to test per component

| Component | Must-test |
|-----------|-----------|
| **Config** | Valid config loads, missing required fields fail, env var resolution, Pydantic validation |
| **Agents / LLM** | Agent creation from config, model string resolution, tool registration, `TestModel` structured output, `FallbackModel` failover |
| **Skills** | SKILL.md parsing (frontmatter + body), discovery precedence (user overrides built-in), dependency checking (tools, bins, env), per-executor mapping, always-on loading, ClawHub search/install mock, **hot-reload after install** (registry picks up new skill, summary XML rebuilt, wildcard executors see it), `skill_search`/`skill_install` tools, `skills_loaded` on BaseAgent, `skill_read` tag in tool_call trace events |
| **Tools** | Type hint → JSON schema generation, tool execution, error handling, access filtering per executor |
| **Planner** | Intent classification → correct executor selection, structured `PlanResult` output, fallback to `general` executor |
| **Executor** | Tool call → result → next step → done via Pydantic AI run loop, tool error handling |
| **Orchestrator** | Full pipeline: message → planner → executor → response, memory context injection |
| **Core memory** | CRUD operations, 4K token cap enforcement, invalid path handling |
| **Event log** | Insert events, FTS5 keyword search, sqlite-vec vector search, hybrid score fusion |
| **Retrieval** | Temporal decay calculation, BM25+vector merge, min_score filtering, top-K ranking |
| **Consolidation** | Fact promotion to core memory, contradiction detection + resolution, event compression, GC threshold |
| **Extraction** | Conversation → event extraction, empty conversation handling, importance scoring |
| **Telegram** | Message normalization, chunking (>4096 chars), allowed_user_ids filtering, command parsing |
| **CRON** | Job scheduling, timezone handling (DST), job persistence across restart, consolidation timer, **dynamic job creation/deletion via tools**, cron expression validation |
| **Gateway** | Route responses, auth enforcement, rate limiting, WebSocket connection, `GET /api/skills` (builtin/user split, active/missing computation, reload-on-request, null registry fallback) |
| **Integration** | Full flow: Telegram message → gateway → planner → executor → tools → memory → response |

### Testing patterns
- **Use Pydantic AI's `TestModel` for agent tests.** `TestModel` returns structured responses, records tool calls, and requires no API keys. This is the primary mocking strategy for all agent/planner/executor tests.
- **Use `respx` for external HTTP calls.** Mock Brave Search, URL scraping, Telegram webhook — but NOT the LLM (that's `TestModel`'s job).
- **Mock external services, not internal modules.** Never mock the tool registry, memory retrieval, or agent orchestration logic.
- **Test memory in isolation and in integration.** Unit tests verify each memory layer independently. Integration tests verify the full flow: conversation → extraction → event store → retrieval → core memory promotion via consolidation.
- **Test failure paths.** Every component should have tests for: invalid input, API errors/timeouts, empty results, token limit exceeded, auth rejected.

## Environment variables

API keys go in `.env` only — never in `config.json` or logs. Reference them in config via the `_env` suffix convention (e.g. `"api_key_env": "ANTHROPIC_API_KEY"`).

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

## Security

- Docker: read-only filesystem, non-root user, `no-new-privileges`, only `/app/data` and `/tmp` writable.
- API keys: env vars only (`.env` file), never in config or logs.
- Telegram: `allowed_user_ids` whitelist.
- Scraped content: marked as `[EXTERNAL_CONTENT]` in messages to defend against prompt injection.
- Rate limiting: configurable per-user, max tool calls per request cap (default 15).
- UI: basic auth on all `/api` routes.

## Config structure

`config.json` top-level keys: `version`, `llm` (providers config: API keys, base URLs for OpenRouter/Ollama), `agents` (planner + executors with model string/tools/skills/prompt per executor), `skills` (directories, ClawHub settings), `channels` (telegram token + allowed users), `memory` (core_memory path + event_log retrieval settings + consolidation settings), `scheduler` (timezone + jobs file), `tools` (per-tool config — `web_search.provider: "brave"`, `web_search.api_key_env: "BRAVE_API_KEY"`), `security` (rate limits), `ui` (port + auth).

## What is NOT in v1

These are deferred to v2+. Do not implement unless explicitly asked:

- **Workflow engine** — YAML-based declarative pipelines (full design exists, see architecture doc Appendix A)
- **MCP server support**
- **Knowledge graph memory** (entity-relationship layer)
- **Additional channels** (Discord, Slack, WhatsApp, browser chat)
- **Voice input** (Whisper transcription)
- **PostgreSQL** (use SQLite for now)
- **Tavily web search** (alternative to Brave Search)

