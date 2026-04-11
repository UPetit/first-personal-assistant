from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from kore.agents.base import BaseAgent
from kore.agents.deps import KoreDeps
from kore.agents.executor import create_executor
from kore.agents.planner import PlanResult, create_planner
from kore.config import ConfigError, KoreConfig
from kore.session.buffer import SessionBuffer
from kore.llm.types import AgentResponse

if TYPE_CHECKING:
    from kore.gateway.trace_store import TraceStore

logger = logging.getLogger(__name__)


class Orchestrator:
    """Coordinates the full planner → executor pipeline for a user message.

    Optionally accepts memory components (core_memory, event_log, retriever,
    extraction_agent). When provided:
    - Core memory is injected into the planner's context each turn.
    - Recent relevant memories are retrieved and appended to the context.
    - Post-conversation extraction runs after each turn.

    Memory components are optional for backward compatibility with Phase 2/3 tests.
    """

    def __init__(
        self,
        config: KoreConfig,
        core_memory=None,
        event_log=None,
        retriever=None,
        extraction_agent=None,
        trace_store: TraceStore | None = None,
        skill_registry=None,  # SkillRegistry | None
    ) -> None:
        if config.agents.planner is None:
            raise ConfigError(
                "Planner not configured — add agents.planner to config.json"
            )
        self._config = config
        self._planner = create_planner(config)
        self._executors: dict[str, BaseAgent] = {}
        self._core_memory = core_memory
        self._event_log = event_log
        self._retriever = retriever
        self._extraction_agent = extraction_agent
        self._store = trace_store
        self._skill_registry = skill_registry

    async def _emit(self, event: dict) -> None:
        """Persist a trace event if a TraceStore is configured."""
        if self._store is not None:
            event.setdefault("ts", datetime.now(timezone.utc).isoformat())
            await self._store.add(event)

    async def run(self, message: str, session_id: str) -> AgentResponse:
        """Run the full pipeline: plan → execute steps → extract memories → save session."""
        await self._emit({"type": "session_start", "session_id": session_id, "message": message})

        try:
            buffer = SessionBuffer.load(session_id)

            # Build context prefix with core memory and retrieved events
            context_prefix = await self._build_memory_context(message)
            planner_message = f"{context_prefix}{message}" if context_prefix else message

            kore_deps = KoreDeps(
                config=self._config,
                core_memory=self._core_memory,
                event_log=self._event_log,
                retriever=self._retriever,
                skill_registry=self._skill_registry,
            )

            # 1. Plan — conversation history passed only to planner
            plan_response = await self._planner.run(
                planner_message,
                deps=kore_deps,
                message_history=buffer.history(),
            )
            plan: PlanResult | None = plan_response.output

            # Guard: empty or missing plan
            if not plan or not plan.steps:
                response = AgentResponse(
                    content="I wasn't sure how to handle that. Could you rephrase?",
                    tool_calls=[],
                    model_used=self._config.agents.planner.model,
                )
                await self._emit({"type": "session_done", "session_id": session_id, "response": response.content})
                return response

            # 2. Emit full plan summary before executing any step
            await self._emit({
                "type": "plan_summary",
                "session_id": session_id,
                "intent": plan.intent,
                "reasoning": plan.reasoning,
                "steps": [{"executor": s.executor, "instruction": s.instruction} for s in plan.steps],
            })

            # 3. Execute steps sequentially, feed-forward
            context = message
            last_response: AgentResponse | None = None
            for step_index, step in enumerate(plan.steps):
                executor, safe_instruction = self._resolve_step(step.executor, step.instruction, message)
                executor_name = step.executor if step.executor in self._config.agents.executors else "general"
                executor_cfg = self._config.agents.executors.get(executor_name, self._config.agents.executors.get("general"))

                # Build per-step deps with the executor's shell allowlist
                step_deps = KoreDeps(
                    config=self._config,
                    core_memory=self._core_memory,
                    event_log=self._event_log,
                    retriever=self._retriever,
                    skill_registry=self._skill_registry,
                    shell_allowlist=executor_cfg.shell_allowlist if executor_cfg else [],
                )

                await self._emit({
                    "type": "plan_result",
                    "session_id": session_id,
                    "step_index": step_index,
                    "executor": executor_name,
                    "instruction": safe_instruction,
                    "reasoning": plan.reasoning,
                })
                await self._emit({
                    "type": "executor_start",
                    "session_id": session_id,
                    "step_index": step_index,
                    "executor_name": executor_name,
                    "model": executor_cfg.model if executor_cfg else "unknown",
                    "skills_loaded": executor.skills_loaded,
                })

                instruction = f"{safe_instruction}\n\nContext from previous step:\n{context}"
                last_response = await executor.run(instruction, deps=step_deps)
                context = last_response.content

                # Emit tool calls as a batch (pydantic-ai exposes them post-run)
                for tc in last_response.tool_calls:
                    # Detect Level 3 on-demand skill reads (read_file called on a SKILL.md path)
                    skill_read: str | None = None
                    if tc.name == "read_file":
                        path_arg = str(tc.args.get("path", ""))
                        if "SKILL.md" in path_arg:
                            skill_read = path_arg
                    await self._emit({
                        "type": "tool_call",
                        "session_id": session_id,
                        "step_index": step_index,
                        "tool_name": tc.name,
                        "args": tc.args,
                        **({"skill_read": skill_read} if skill_read else {}),
                    })
                    result_str = str(tc.result) if tc.result is not None else ""
                    await self._emit({
                        "type": "tool_result",
                        "session_id": session_id,
                        "step_index": step_index,
                        "tool_name": tc.name,
                        "result": result_str[:500],
                    })

                await self._emit({
                    "type": "executor_done",
                    "session_id": session_id,
                    "step_index": step_index,
                    "content_preview": last_response.content[:200],
                    "reasoning_steps": last_response.reasoning_steps,
                })

            # 3. Persist turn and compact if needed
            assert last_response is not None
            buffer.append(role="user", content=message)
            buffer.append(role="assistant", content=last_response.content)
            await buffer.compact_if_needed(self._config)
            buffer.save()

            # 4. Post-conversation extraction
            if self._extraction_agent is not None:
                try:
                    await self._extraction_agent.extract_and_store(buffer.history())
                except Exception as exc:
                    logger.warning("Post-conversation extraction failed: %s", exc)

            await self._emit({"type": "session_done", "session_id": session_id, "response": last_response.content})
            return last_response

        except Exception as exc:
            await self._emit({"type": "session_error", "session_id": session_id, "error": str(exc)})
            raise

    async def _build_memory_context(self, message: str) -> str:
        """Build context prefix from core memory and retrieved events."""
        parts: list[str] = []

        if self._core_memory is not None:
            formatted = self._core_memory.format_for_prompt()
            if formatted != "(core memory is empty)":
                parts.append(f"## Core Memory\n{formatted}")

        if self._retriever is not None:
            try:
                results = await self._retriever.search(message)
                if results:
                    lines = [
                        f"- [{r.event.category}] {r.event.content}"
                        for r in results[:5]
                    ]
                    parts.append("## Relevant Memories\n" + "\n".join(lines))
            except Exception as exc:
                logger.warning("Memory retrieval failed: %s", exc)

        return "\n\n".join(parts) + "\n\n" if parts else ""

    def _resolve_step(self, name: str, instruction: str, original_message: str) -> tuple[BaseAgent, str]:
        """Resolve executor, falling back to 'general' for unknown names.

        The planner occasionally hallucinates executor names (e.g. 'assistant',
        'conversational'). When that happens the planner's *instruction* is still
        correct — only the name is wrong — so we keep it and just reroute to
        'general'. We only replace the instruction for truly empty/useless cases.
        """
        if name not in self._config.agents.executors:
            logger.warning("Unknown executor %r — falling back to 'general'", name)
            return self._get_executor("general"), instruction
        return self._get_executor(name), instruction

    def _get_executor(self, name: str) -> BaseAgent:
        if name not in self._executors:
            self._executors[name] = create_executor(
                name, self._config, skill_registry=self._skill_registry
            )
        return self._executors[name]
