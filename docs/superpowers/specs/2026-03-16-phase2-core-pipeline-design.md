# Phase 2: Core Pipeline — Design Spec

**Date:** 2026-03-16
**Project:** Kore — Personal AI Assistant Platform
**Phase:** 2 of 7

---

## Scope

Build the agent pipeline on top of the Phase 1 foundation:

- Planner agent (structured `PlanResult` output, intent classification + executor routing)
- Executors (three config-driven agents: `general`, `search`, `writer`)
- Orchestrator (sequential feed-forward planner → executor pipeline)
- Conversation buffer (session-based persistence, LLM-based compaction)
- File I/O tools (`read_file`, `write_file`, sandboxed to `~/.kore/workspace/files/`)
- Full tests for every component above

**Explicitly out of scope for this phase:** skills system (Phase 3), memory layers (Phase 4), Telegram channel (Phase 5), gateway auth, rate limiting, Web UI.

---

## Code Conventions (mandatory for all Phase 2 files)

All new Python files must begin with:

```python
from __future__ import annotations
```

This is a project-wide convention (see CLAUDE.md). No exceptions.

---

## Architecture Overview

```
User message
      │
      ▼
ConversationBuffer.load(session_id)    ← loads from ~/.kore/workspace/conversations/
      │  history injected into planner context only
      ▼
Planner (BaseAgent, result_type=PlanResult)
      │  system prompt lists available executors by name + description
      │  PlanResult: {intent, reasoning, steps: [{executor, instruction}]}
      ▼
Orchestrator loop (sequential, feed-forward)
  ├─ step 1 → Executor (no message_history) → output
  ├─ step 2 → Executor (receives step 1 output as context, no message_history) → output
  └─ ...
      │
      ▼
ConversationBuffer.append() + compact_if_needed() + save()
      │
      ▼
AgentResponse (final executor's output)
```

**History injection:** `buffer.history()` is passed only to the planner, not to individual executor steps. Executors receive the full conversation context indirectly via the feed-forward `instruction` string. This avoids double-injecting history into every step and prevents context window exhaustion in multi-step pipelines.

**Empty plan guard:** If the planner returns `PlanResult(steps=[])` (a valid but unhelpful LLM output), the orchestrator returns a canned `AgentResponse` with content `"I wasn't sure how to handle that. Could you rephrase?"` and an empty `tool_calls` list. No executor is invoked.

### New files

```
src/kore/
├── agents/
│   ├── planner.py           # PlanResult model + planner factory
│   ├── executor.py          # executor factory (config-driven)
│   └── orchestrator.py      # coordinates planner → executor(s) pipeline
│   # agents/__init__.py already exists from Phase 1 — not recreated
├── conversation/
│   ├── __init__.py
│   ├── buffer.py            # session load/save, history, compaction trigger
│   └── compactor.py         # LLM summarisation of old turns
└── tools/
    └── file_rw.py           # read_file, write_file (sandboxed)
tests/
├── test_planner.py
├── test_executor.py
├── test_orchestrator.py
└── test_conversation.py
```

---

## Components

### 1. Planner (`src/kore/agents/planner.py`)

The planner classifies user intent and produces a structured execution plan. It never calls tools.

**Structured output:**

```python
class PlanStep(BaseModel):
    executor: str      # must match a key in config.agents.executors
    instruction: str   # what this executor should do

class PlanResult(BaseModel):
    intent: str        # one-line description of what the user wants
    reasoning: str     # why these steps/executors were chosen
    steps: list[PlanStep] = Field(min_length=1)  # at least one step required
```

`steps` has `min_length=1` enforced at the Pydantic model level. If the LLM produces an empty list, Pydantic raises `ValidationError` and Pydantic AI retries. After `max_retries` exhausted, the orchestrator's empty-plan guard catches the `None` result (see Orchestrator section).

**System prompt** (`prompts/planner.md`) includes a `{{EXECUTORS}}` placeholder that is replaced at construction time with a summary of available executors (name + one-line description). This means adding an executor to `config.json` automatically makes it visible to the planner — no prompt edits required.

**Factory:**

```python
def create_planner(config: KoreConfig) -> BaseAgent:
    executors_summary = _build_executors_summary(config)
    prompt = _load_prompt("planner.md").replace("{{EXECUTORS}}", executors_summary)
    model = get_model(config.agents.planner.model, config)
    return BaseAgent(model, config.agents.planner.model, prompt, result_type=PlanResult)
```

**Config:**

```json
"agents": {
  "planner": {
    "model": "anthropic:claude-sonnet-4-6",
    "prompt_file": "planner.md",
    "tools": []
  }
}
```

---

### 2. Executors (`src/kore/agents/executor.py`)

Executors are `BaseAgent` instances, each with their own model, system prompt, and tools. They handle the ReAct loop internally via Pydantic AI.

**Factory:**

```python
def create_executor(name: str, config: KoreConfig) -> BaseAgent:
    exec_cfg = config.agents.executors[name]
    model = get_model(exec_cfg.model, config)
    prompt = _load_prompt(exec_cfg.prompt_file)
    tools = get_tools(exec_cfg.tools)
    return BaseAgent(model, exec_cfg.model, prompt, tools=tools)
```

**v1 built-in executors:**

| Name | Model | Tools | Purpose |
|------|-------|-------|---------|
| `general` | claude-sonnet-4-6 | web_search, scrape_url, read_file, write_file, get_current_time | Catch-all; handles complex or mixed tasks |
| `search` | claude-haiku-4-5 | web_search, scrape_url, get_current_time | Web research and information retrieval |
| `writer` | claude-haiku-4-5 | read_file, write_file, get_current_time | Writing, editing, file-based tasks |

Executors are instantiated **lazily** (on first use per orchestrator instance) and cached. No pre-warming at startup.

**Config (example):**

```json
"executors": {
  "general": {
    "model": "anthropic:claude-sonnet-4-6",
    "prompt_file": "general.md",
    "tools": ["web_search", "scrape_url", "read_file", "write_file", "get_current_time"]
  },
  "search": {
    "model": "anthropic:claude-haiku-4-5-20251001",
    "prompt_file": "search.md",
    "tools": ["web_search", "scrape_url", "get_current_time"]
  },
  "writer": {
    "model": "anthropic:claude-haiku-4-5-20251001",
    "prompt_file": "writer.md",
    "tools": ["read_file", "write_file", "get_current_time"]
  }
}
```

---

### 3. Orchestrator (`src/kore/agents/orchestrator.py`)

The orchestrator is the main entry point for processing a user message end-to-end.

```python
class Orchestrator:
    def __init__(self, config: KoreConfig) -> None:
        self._config = config
        self._planner = create_planner(config)
        self._executors: dict[str, BaseAgent] = {}   # lazy cache

    async def run(self, message: str, session_id: str) -> AgentResponse:
        buffer = ConversationBuffer.load(session_id)

        # 1. Plan — history passed only to planner
        plan_response = await self._planner.run(
            message,
            message_history=buffer.history(),
        )
        plan: PlanResult = plan_response.data  # structured PlanResult via AgentResponse.data

        # Empty plan guard (steps=[] shouldn't reach here due to min_length=1,
        # but guard defensively in case retries are exhausted)
        if not plan.steps:
            return AgentResponse(
                content="I wasn't sure how to handle that. Could you rephrase?",
                tool_calls=[],
                model_used=self._config.agents.planner.model,
            )

        # 2. Execute steps sequentially, feed-forward
        # Executors do NOT receive message_history — context flows via instruction string
        context = message
        last_response: AgentResponse | None = None
        for step in plan.steps:
            executor = self._get_executor(step.executor)
            instruction = f"{step.instruction}\n\nContext from previous step:\n{context}"
            last_response = await executor.run(instruction)
            context = last_response.content

        # 3. Persist turn and compact if needed
        buffer.append(role="user", content=message)
        buffer.append(role="assistant", content=last_response.content)
        await buffer.compact_if_needed(self._config)
        buffer.save()

        return last_response

    def _get_executor(self, name: str) -> BaseAgent:
        if name not in self._config.agents.executors:
            logger.warning("Unknown executor %r — falling back to 'general'", name)
            name = "general"
        if name not in self._executors:
            self._executors[name] = create_executor(name, self._config)
        return self._executors[name]
```

**`session_id`** is a UUID4 string (e.g. `"a3f2c1d4-..."`). The caller generates a new UUID4 for `/new` or first-ever message. In Phase 2, the test harness generates it; in Phase 5, the gateway manages it per user. UUID4 provides sufficient entropy to make collisions practically impossible.

**Accessing structured planner output:** `self._planner.run()` returns `AgentResponse`. To carry the typed `PlanResult` back to the orchestrator, `AgentResponse` gains a new optional field:

```python
@dataclass
class AgentResponse:
    content: str
    tool_calls: list[ToolCall]
    model_used: str
    data: Any | None = None   # populated with raw result.data when result_type is set
```

`BaseAgent.run()` sets `data = result.output` when the Pydantic AI result carries a structured value (i.e. when `result_type` was passed to the Agent constructor), and leaves it `None` otherwise. The orchestrator accesses the plan via `plan_response.data`:

```python
plan: PlanResult = plan_response.data
```

Executors (no `result_type`) always return `AgentResponse` with `data=None`.

**Planner failure:** If `self._planner.run()` raises (network error, retries exhausted), the exception propagates to the caller. The buffer is not saved. The caller is responsible for surfacing the error to the user.

**Serialisation:** The orchestrator must be called serially per session — concurrent calls with the same `session_id` are not safe (both would load, modify, and save the same file). Phase 5 gateway enforces per-session serialisation via an asyncio lock.

---

### 4. Conversation Buffer (`src/kore/conversation/buffer.py` + `compactor.py`)

#### Session file format

Stored at `~/.kore/workspace/conversations/<session_id>.json`:

```json
{
  "session_id": "a3f2c1d4-9e8b-4a2f-b1c3-d5e6f7a8b9c0",
  "created_at": "2026-03-16T14:00:00Z",
  "summary": null,
  "turns": [
    {"role": "user", "content": "...", "timestamp": "2026-03-16T14:00:01Z"},
    {"role": "assistant", "content": "...", "timestamp": "2026-03-16T14:00:03Z"}
  ]
}
```

#### `ConversationBuffer` API

```python
class ConversationBuffer:
    @classmethod
    def load(cls, session_id: str) -> ConversationBuffer:
        """Load from disk. Creates a new empty session if file absent."""

    def append(self, role: str, content: str) -> None:
        """Append a turn to the in-memory buffer."""

    def history(self) -> list[KoreMessage]:
        """Return summary block (if any) + all turns as KoreMessage list.

        If summary exists, it is prepended as:
            KoreMessage(role="assistant",
                        content="[Conversation summary]\n{summary}",
                        timestamp=turns[0].timestamp if turns else datetime.now(UTC))
        The timestamp uses the oldest available turn's timestamp so that
        the Pydantic AI history converter sees a monotonically increasing sequence.
        If no turns exist yet, datetime.now(UTC) is used.
        """

    async def compact_if_needed(self, config: KoreConfig) -> None:
        """Compact if token estimate of turns + summary exceeds threshold."""

    def save(self) -> None:
        """Write session JSON to disk atomically (write to random .tmp, then rename)."""
```

#### Compaction

Triggers when the estimated token count of `turns` **plus the existing summary** exceeds the configurable threshold (default: 6 000 tokens). Token estimate: `(sum(len(t["content"]) for t in turns) + len(summary or "")) // 4`.

When triggered:
1. Keep the **last 10 turns** verbatim (configurable via `keep_recent_turns`)
2. Take all older turns + existing `summary` (if any)
3. Call the compaction model with a merge prompt:
   > "Here is an existing summary of this conversation (may be empty): `{summary}`. The following turns occurred after that summary: `{old_turns}`. Produce a concise updated summary that incorporates both, preserving key facts, decisions, and context."
4. Store the result in `summary`, remove the old turns from `turns`

Running compaction multiple times is safe: each run merges the existing summary with newly-aged turns into a single updated summary. The `summary` field is always a single string block.

**Compaction model config:**

```json
"conversation": {
  "compaction_model": "anthropic:claude-haiku-4-5-20251001",
  "compaction_token_threshold": 6000,
  "keep_recent_turns": 10
}
```

#### Directory creation

`ConversationBuffer.load()` and `save()` both call `mkdir(parents=True, exist_ok=True)` on the conversations directory (`~/.kore/workspace/conversations/`) before any file operations. This ensures the directory exists on first use without requiring `kore init` to be updated.

#### Atomic save

`save()` writes to `<session_id>.<uuid4_hex>.tmp` then renames to `<session_id>.json`. Using a randomised temp filename ensures concurrent saves (same session, different coroutines) do not clobber each other's temp file. The last rename wins in the race, but neither process writes a partial file. Phase 5 gateway serialises per-session calls via asyncio lock, so this is a defence-in-depth measure.

---

### 5. File I/O Tools (`src/kore/tools/file_rw.py`)

Both tools are sandboxed to `KORE_HOME / "workspace" / "files"`. Path traversal is rejected at the boundary.

```python
async def read_file(ctx: RunContext, path: str) -> str:
    """Read a file from the workspace. path is relative to ~/.kore/workspace/files/.

    Returns [FILE_CONTENT] tagged text. Truncates at 16,000 chars.
    Returns [FILE_CONTENT]\n[Error: ...] on failure — does not raise.
    """

async def write_file(ctx: RunContext, path: str, content: str) -> str:
    """Write content to a file in the workspace. path is relative to ~/.kore/workspace/files/.

    Creates parent directories automatically (within sandbox).
    Rejects files over 1 MB.
    Returns confirmation string or [Error: ...] on failure — does not raise.
    """
```

**Sandbox enforcement** uses `Path.is_relative_to()` (Python 3.9+, available in this project's 3.12 baseline) to correctly handle symlinks and avoid false-positive prefix matches:

```python
def _safe_path(relative: str) -> Path:
    base = (KORE_HOME / "workspace" / "files").resolve()
    resolved = (base / relative).resolve()
    if not resolved.is_relative_to(base):
        raise ValueError(f"Path escapes sandbox: {relative!r}")
    return resolved
```

Both tools self-register at module import via `register()`.

---

### 6. Config changes

**`ConversationConfig`** (new model):
```python
class ConversationConfig(BaseModel):
    compaction_model: str = "anthropic:claude-haiku-4-5-20251001"
    compaction_token_threshold: int = 6000
    keep_recent_turns: int = 10
```

**`KoreConfig`** gains:
```python
conversation: ConversationConfig = ConversationConfig()
```

**`AgentsConfig`** — `planner` remains `Optional` to preserve backward compatibility with Phase 1 config files. The orchestrator raises a clear `ConfigError("Planner not configured — add agents.planner to config.json")` at construction time if `planner` is absent, rather than failing with a cryptic `AttributeError` or silent `None`. `kore migrate` does not need to modify existing files since the error is surfaced clearly at runtime.

```python
class AgentsConfig(BaseModel):
    planner: ExecutorConfig | None = None  # optional for Phase 1 compat; required at runtime
    executors: dict[str, ExecutorConfig] = {}
```

---

### 7. Prompt files

New prompt files baked into the image:

| File | Used by |
|------|---------|
| `prompts/planner.md` | Planner — includes `{{EXECUTORS}}` placeholder |
| `prompts/general.md` | General executor |
| `prompts/search.md` | Search executor |
| `prompts/writer.md` | Writer executor |

Prompts are Markdown files baked into the Docker image. They are not user-editable (user-editable config is in `~/.kore`).

---

### 8. Tests

All agent tests use Pydantic AI's `TestModel` — no real API calls. File I/O and conversation tests use `tmp_path` with `KORE_HOME` monkeypatched.

#### `tests/test_planner.py`

| Test | What it verifies |
|------|-----------------|
| `test_planner_returns_plan_result` | `TestModel` → `PlanResult` with `intent`, `reasoning`, `steps` |
| `test_planner_single_step` | Single-step plan routes to correct executor |
| `test_planner_multi_step` | Multi-step plan preserves step order |
| `test_executor_list_in_prompt` | Available executor names appear in the planner system prompt |

#### `tests/test_executor.py`

| Test | What it verifies |
|------|-----------------|
| `test_create_executor_general` | `general` executor created with correct model and tools |
| `test_create_executor_search` | `search` executor created with correct model and tools |
| `test_create_executor_writer` | `writer` executor created with correct model and tools |
| `test_executor_run_returns_response` | `run()` returns `AgentResponse` via `TestModel` |
| `test_unknown_executor_raises` | `create_executor("nonexistent", config)` raises `KeyError` |

#### `tests/test_orchestrator.py`

| Test | What it verifies |
|------|-----------------|
| `test_full_pipeline` | Planner → executor → `AgentResponse` returned |
| `test_feed_forward_context` | Step 2 instruction includes step 1 output |
| `test_unknown_executor_fallback` | Planner routes to unknown executor → falls back to `general`, warning logged, non-empty `AgentResponse` returned |
| `test_empty_plan_steps` | `steps=[]` → canned response returned, no executor invoked |
| `test_planner_missing_raises` | `Orchestrator` with no `planner` in config raises `ConfigError` at construction |
| `test_session_saved_after_run` | Session file written to disk after `run()` |
| `test_executors_receive_no_history` | Executor `run()` called without `message_history` — history flows via instruction string only |

#### `tests/test_conversation.py`

| Test | What it verifies |
|------|-----------------|
| `test_new_session_created` | `load()` with unknown session_id returns empty buffer |
| `test_session_roundtrip` | `append()` + `save()` + `load()` → turns preserved |
| `test_history_returns_kore_messages` | `history()` returns correct `KoreMessage` list |
| `test_history_summary_timestamp` | Summary block timestamp equals oldest turn's timestamp |
| `test_compaction_triggers_at_threshold` | Token estimate (turns + summary) exceeds threshold → `compact_if_needed()` calls compactor |
| `test_compaction_keeps_recent_turns` | After compaction, last 10 turns remain verbatim |
| `test_compaction_merges_summary` | Second compaction merges existing summary with newly-aged turns |
| `test_history_includes_summary` | After compaction, `history()` prepends summary block |
| `test_atomic_save` | Save writes randomised `.tmp` then renames — no partial files |
| `test_symlink_escape_rejected` | Symlink inside sandbox pointing outside is rejected by `_safe_path` |

#### `tests/test_tools.py` (extended)

| Test | What it verifies |
|------|-----------------|
| `test_read_file_returns_content` | Returns `[FILE_CONTENT]` tagged text |
| `test_read_file_truncates` | Content >16k chars is truncated |
| `test_read_file_missing` | Missing file → `[FILE_CONTENT]\n[Error: ...]` |
| `test_write_file_creates_file` | File written to correct sandbox path |
| `test_write_file_creates_dirs` | Parent directories created automatically |
| `test_write_file_too_large` | Content >1 MB → error string returned |
| `test_path_traversal_rejected_read` | `../../config.json` → error string |
| `test_path_traversal_rejected_write` | `../../evil.sh` → error string |
| `test_symlink_escape_rejected` | Symlink inside sandbox pointing outside → error string |

---

## Data Flow

```
config.json + ~/.kore/.env
      │
      ▼
load_config()
      │
      ├─► create_planner(config)     ← BaseAgent(model, prompt+executors, result_type=PlanResult)
      └─► Orchestrator(config)       ← raises ConfigError if planner absent
                │
                ▼
         ConversationBuffer.load(session_id)   ← UUID4 session_id
                │  history() → [summary_block] + [recent turns]
                ▼
         planner.run(message, message_history=history)  → PlanResult
                │
                ├─ steps=[] → canned AgentResponse (guard)
                │
                ▼  for each step (sequential):
         executor.run(instruction + prev_context)  → AgentResponse
         # No message_history passed to executors
                │
                ▼
         buffer.append(user) + buffer.append(assistant)
         buffer.compact_if_needed(config)   ← token estimate includes summary
         buffer.save()   ← randomised .tmp → atomic rename
```

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Planner not in config | `ConfigError` raised at `Orchestrator.__init__` |
| Planner routes to unknown executor | Fall back to `general`, log warning, return valid `AgentResponse` |
| Planner returns empty `steps` | Return canned `AgentResponse`, no executor invoked |
| Planner raises (network/retry exhausted) | Exception propagates to caller; buffer not saved |
| Executor tool call fails | Tool returns error string; agent decides how to handle |
| Compaction model call fails | Log warning, skip compaction this turn — buffer grows until next opportunity |
| Session file corrupt/unreadable | Start fresh session, log warning |
| File I/O path traversal or symlink escape | Return error string, do not raise |
| Write >1 MB | Return error string, do not raise |

---

## Security Notes

- File I/O sandboxed to `~/.kore/workspace/files/` — path traversal and symlink escapes rejected via `Path.is_relative_to()`
- `read_file` prepends `[FILE_CONTENT]` tag (prompt injection defence, consistent with `scrape_url`)
- Session files written atomically with randomised temp filename — no partial state on disk
- Compaction prompt contains only assistant/user turn text — no raw tool outputs
- History passed only to planner — executors cannot see prior conversation context directly

---

## Files Produced

```
src/kore/
├── agents/
│   ├── planner.py           # (agents/__init__.py pre-exists from Phase 1)
│   ├── executor.py
│   └── orchestrator.py
├── conversation/
│   ├── __init__.py
│   ├── buffer.py
│   └── compactor.py
├── llm/
│   └── types.py             # modified: AgentResponse gains data: Any | None = None
└── tools/
    └── file_rw.py
prompts/
├── planner.md
├── general.md
├── search.md
└── writer.md
tests/
├── test_planner.py
├── test_executor.py
├── test_orchestrator.py
├── test_conversation.py
└── test_tools.py            # extended from Phase 1 — new file I/O test cases appended
```
