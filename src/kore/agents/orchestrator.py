from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from kore.agents.deps import KoreDeps
from kore.agents.primary import build_primary
from kore.config import ConfigError, KoreConfig
from kore.gateway.trace_events import EventKind, EventType, new_span_id, span_event
from kore.llm.types import AgentResponse, KoreMessage, ToolCall
from kore.session.buffer import SessionBuffer

if TYPE_CHECKING:
    from kore.gateway.trace_store import TraceStore

logger = logging.getLogger(__name__)


class Orchestrator:
    """Run a single primary-agent turn per message.

    The v2 orchestrator replaces the planner → executor pipeline with a single
    conversational primary agent. Subagents (``deep_research``, ``draft_longform``)
    are exposed as ``@agent.tool`` wrappers on the primary itself — delegation
    happens inside the primary's run loop, not here.

    Trace emission is span-shaped: every event carries a ``span_id`` and a
    ``parent_span_id``. The session_start span is the root; primary_start is a
    child of the session; tool_call/tool_result are children of primary_start.

    Memory components are optional. Core memory is prepended to the turn message
    when available. The retriever is *not* auto-invoked — the primary calls
    ``memory_search`` as a tool when it decides retrieval is useful.
    """

    def __init__(
        self,
        config: KoreConfig,
        core_memory: Any = None,
        event_log: Any = None,
        retriever: Any = None,
        extraction_agent: Any = None,
        trace_store: TraceStore | None = None,
        skill_registry: Any = None,
    ) -> None:
        if config.agents is None or config.agents.primary is None:
            raise ConfigError(
                "Primary agent not configured — add agents.primary to config.json"
            )
        self._config = config
        self._core_memory = core_memory
        self._event_log = event_log
        self._retriever = retriever
        self._extraction_agent = extraction_agent
        self._store = trace_store
        self._skill_registry = skill_registry

        self._primary = build_primary(
            primary_config=config.agents.primary,
            subagents=config.agents.subagents,
            skill_registry=skill_registry,
            kore_config=config,
        )

    async def _emit(self, event: dict) -> None:
        """Persist a trace event if a TraceStore is configured."""
        if self._store is not None:
            event.setdefault("ts", datetime.now(timezone.utc).isoformat())
            await self._store.add(event)

    async def run(self, message: str, session_id: str) -> AgentResponse:
        """Run one turn through the primary agent and emit span-shaped trace events."""
        session_span = new_span_id()
        primary_span: str | None = None

        await self._emit(
            span_event(
                type_=EventType.SESSION_START,
                kind=EventKind.SESSION,
                session_id=session_id,
                parent_span_id=None,
                span_id=session_span,
                extra={"message": message},
            )
        )

        try:
            buffer = SessionBuffer.load(session_id)

            # Prepend core memory (Layer 1) but never auto-invoke the retriever —
            # the primary calls memory_search itself when it decides it's useful.
            context_prefix = self._build_core_memory_prefix()
            primary_message = f"{context_prefix}{message}" if context_prefix else message

            primary_cfg = self._config.agents.primary  # type: ignore[union-attr]
            allowed_skills = (
                list(primary_cfg.skills) if primary_cfg.skills else None
            )
            deps = KoreDeps(
                config=self._config,
                core_memory=self._core_memory,
                event_log=self._event_log,
                retriever=self._retriever,
                skill_registry=self._skill_registry,
                shell_allowlist=list(primary_cfg.shell_allowlist),
                allowed_skill_names=allowed_skills,
            )

            primary_span = new_span_id()
            model_string = getattr(self._primary, "_kore_model_string", primary_cfg.model)
            skills_loaded = list(getattr(self._primary, "_kore_skills_loaded", []) or [])
            usage_limits = getattr(self._primary, "_kore_usage_limits", None)

            await self._emit(
                span_event(
                    type_=EventType.PRIMARY_START,
                    kind=EventKind.PRIMARY,
                    session_id=session_id,
                    parent_span_id=session_span,
                    span_id=primary_span,
                    extra={
                        "model": model_string,
                        "skills_loaded": skills_loaded,
                    },
                )
            )

            run_kwargs: dict[str, Any] = {
                "deps": deps,
                "message_history": _to_pydantic_history(buffer.history(), model_string),
            }
            if usage_limits is not None:
                run_kwargs["usage_limits"] = usage_limits

            result = await self._primary.run(primary_message, **run_kwargs)

            content = str(result.output)
            all_msgs = list(result.all_messages())
            tool_calls = await self._extract_tool_calls_with_spans(
                all_msgs,
                session_id=session_id,
                parent_span_id=primary_span,
            )
            reasoning = _extract_reasoning(all_msgs)

            response = AgentResponse(
                content=content,
                tool_calls=tool_calls,
                model_used=model_string,
                reasoning_steps=reasoning,
            )

            await self._emit(
                span_event(
                    type_=EventType.PRIMARY_DONE,
                    kind=EventKind.PRIMARY,
                    session_id=session_id,
                    parent_span_id=session_span,
                    span_id=new_span_id(),
                    extra={
                        "content_preview": content[:200],
                        "reasoning_steps": reasoning,
                    },
                )
            )

            # Persist turn and compact if needed
            buffer.append(role="user", content=message)
            buffer.append(role="assistant", content=content)
            await buffer.compact_if_needed(self._config)
            buffer.save()

            # Post-conversation extraction (best-effort)
            if self._extraction_agent is not None:
                try:
                    await self._extraction_agent.extract_and_store(buffer.history())
                except Exception as exc:
                    logger.warning("Post-conversation extraction failed: %s", exc)

            await self._emit(
                span_event(
                    type_=EventType.SESSION_DONE,
                    kind=EventKind.SESSION,
                    session_id=session_id,
                    parent_span_id=session_span,
                    span_id=new_span_id(),
                    extra={"response": content},
                )
            )
            return response

        except Exception as exc:
            await self._emit(
                span_event(
                    type_=EventType.SESSION_ERROR,
                    kind=EventKind.SESSION,
                    session_id=session_id,
                    parent_span_id=primary_span or session_span,
                    span_id=new_span_id(),
                    extra={"error": str(exc)},
                )
            )
            raise

    def _build_core_memory_prefix(self) -> str:
        """Return the core-memory-only context prefix (no event retrieval)."""
        if self._core_memory is None:
            return ""
        formatted = self._core_memory.format_for_prompt()
        if not formatted or formatted == "(core memory is empty)":
            return ""
        return f"## Core Memory\n{formatted}\n\n"

    async def _extract_tool_calls_with_spans(
        self,
        messages: list[ModelMessage],
        *,
        session_id: str,
        parent_span_id: str,
    ) -> list[ToolCall]:
        """Extract tool calls from pydantic-ai messages and emit span-shaped events.

        Every tool_call gets its own span_id; the matching tool_result event
        uses the same span_id so the UI can pair them up.
        """
        pending: dict[str, ToolCall] = {}
        call_spans: dict[str, str] = {}
        ordered: list[ToolCall] = []

        for msg in messages:
            if isinstance(msg, ModelResponse):
                for part in msg.parts:
                    if isinstance(part, ToolCallPart):
                        args = part.args_as_dict()
                        call_id = part.tool_call_id or part.tool_name
                        tc = ToolCall(
                            tool_call_id=call_id,
                            name=part.tool_name,
                            args=args,
                        )
                        pending[call_id] = tc
                        ordered.append(tc)
                        span_id = new_span_id()
                        call_spans[call_id] = span_id

                        # Detect Level 3 on-demand skill reads (read_file on a SKILL.md path)
                        skill_read: str | None = None
                        if part.tool_name == "read_file":
                            path_arg = str(args.get("path", ""))
                            if "SKILL.md" in path_arg:
                                skill_read = path_arg

                        extra: dict[str, Any] = {
                            "tool_name": part.tool_name,
                            "args": args,
                        }
                        if skill_read:
                            extra["skill_read"] = skill_read

                        await self._emit(
                            span_event(
                                type_=EventType.TOOL_CALL,
                                kind=EventKind.TOOL,
                                session_id=session_id,
                                parent_span_id=parent_span_id,
                                span_id=span_id,
                                extra=extra,
                            )
                        )
            elif isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart):
                        call_id = part.tool_call_id or part.tool_name
                        if call_id in pending:
                            pending[call_id].result = part.content
                        span_id = call_spans.get(call_id, new_span_id())
                        result_str = (
                            str(part.content) if part.content is not None else ""
                        )
                        await self._emit(
                            span_event(
                                type_=EventType.TOOL_RESULT,
                                kind=EventKind.TOOL,
                                session_id=session_id,
                                parent_span_id=parent_span_id,
                                span_id=span_id,
                                extra={
                                    "tool_name": part.tool_name,
                                    "result": result_str[:500],
                                },
                            )
                        )

        return ordered


def _to_pydantic_history(
    history: list[KoreMessage],
    model_name: str,
) -> list[ModelMessage] | None:
    """Convert KoreMessage objects to pydantic-ai ModelMessage format."""
    if not history:
        return None
    messages: list[ModelMessage] = []
    for msg in history:
        if msg.role == "user":
            messages.append(ModelRequest(parts=[UserPromptPart(content=msg.content)]))
        else:
            messages.append(
                ModelResponse(
                    parts=[TextPart(content=msg.content)],
                    model_name=model_name,
                )
            )
    return messages


def _extract_reasoning(messages: list[ModelMessage]) -> list[str]:
    """Extract non-empty text parts from ModelResponse messages."""
    texts: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, TextPart) and part.content.strip():
                    texts.append(part.content.strip())
    return texts
