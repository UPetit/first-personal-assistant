from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel as PydanticBaseModel
from pydantic_ai import Agent, UsageLimits, capture_run_messages
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model

from kore.agents.deps import KoreDeps
from kore.llm.types import AgentResponse, KoreMessage, ToolCall

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {529, 503, 529}
_RETRY_DELAYS = [2, 4, 8]  # seconds between attempts


async def _run_with_retry(
    agent: Agent,
    message: str,
    *,
    deps: Any,
    message_history: Any,
    usage_limits: Any,
    model_string: str,
) -> Any:
    """Run agent with exponential backoff on transient API errors (529 overloaded, 503)."""
    last_exc: Exception | None = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            logger.warning(
                "Retrying agent run after %ds (attempt %d, last error: %s)",
                delay,
                attempt,
                last_exc,
                extra={"model": model_string},
            )
            await asyncio.sleep(delay)
        try:
            return await agent.run(
                message,
                deps=deps,
                message_history=message_history,
                usage_limits=usage_limits,
            )
        except ModelHTTPError as exc:
            if exc.status_code in {529, 503}:
                last_exc = exc
                continue
            raise
    raise last_exc  # type: ignore[misc]


class BaseAgent:
    """Thin wrapper over pydantic_ai.Agent — standardises construction and tool registration.

    Tools are passed as plain async callables via Agent(tools=[...]).  Pydantic AI
    generates JSON schemas from their type hints and docstrings automatically.
    This constructor-injection approach is used consistently across all phases.
    """

    def __init__(
        self,
        model: Model,
        model_string: str,
        system_prompt: str,
        tools: list[Callable] | None = None,
        output_type: type | None = None,
        max_retries: int = 3,
        max_tool_calls: int | None = None,
    ) -> None:
        self._model_string = model_string
        self._max_tool_calls = max_tool_calls
        self._agent: Agent[KoreDeps, Any] = Agent(
            model,
            system_prompt=system_prompt,
            tools=tools or [],
            output_type=output_type or str,
            retries=max_retries,
        )

    async def run(
        self,
        message: str,
        deps: KoreDeps | None = None,
        message_history: list[KoreMessage] | None = None,
    ) -> AgentResponse:
        """Run the agent and return a normalised AgentResponse."""
        pydantic_history: list[ModelMessage] | None = None
        if message_history:
            pydantic_history = _to_pydantic_history(message_history, self._model_string)

        usage_limits: UsageLimits | None = None
        if self._max_tool_calls is not None:
            usage_limits = UsageLimits(tool_calls_limit=self._max_tool_calls)

        with capture_run_messages() as messages:
            try:
                result = await _run_with_retry(
                    self._agent,
                    message,
                    deps=deps,
                    message_history=pydantic_history,
                    usage_limits=usage_limits,
                    model_string=self._model_string,
                )
            except UnexpectedModelBehavior as exc:
                logger.error(
                    "Agent run failed — unexpected model behaviour (%d messages captured)",
                    len(messages),
                    extra={"model": self._model_string},
                    exc_info=True,
                )
                raise

        raw_output = result.output

        # Serialise content: Pydantic model results become JSON; plain strings pass through.
        if isinstance(raw_output, PydanticBaseModel):
            content = raw_output.model_dump_json()
            structured: Any = raw_output
        else:
            content = str(raw_output)
            structured = None

        return AgentResponse(
            content=content,
            tool_calls=_extract_tool_calls(result.all_messages()),
            model_used=self._model_string,
            output=structured,
        )


def _to_pydantic_history(
    history: list[KoreMessage],
    model_name: str,
) -> list[ModelMessage]:
    """Convert KoreMessage objects to pydantic-ai ModelMessage format."""
    messages: list[ModelMessage] = []
    for msg in history:
        if msg.role == "user":
            messages.append(ModelRequest(parts=[UserPromptPart(content=msg.content)]))
        else:
            messages.append(
                ModelResponse(
                    parts=[TextPart(content=msg.content)],
                    # model_name is required by pydantic-ai for ModelResponse objects.
                    # For historical messages we don't know the original model, so we
                    # use the current agent's model string as a reasonable default.
                    model_name=model_name,
                )
            )
    return messages


def _extract_tool_calls(messages: list[ModelMessage]) -> list[ToolCall]:
    """Extract tool calls and their results from a Pydantic AI message list.

    Uses tool_call_id for correlation — the same tool can be called multiple times
    in one run, so name-based matching would incorrectly merge separate calls.

    Message structure produced by pydantic-ai:
        ModelResponse([ToolCallPart])  — model requests a tool call
        ModelRequest([ToolReturnPart]) — tool result injected back to model
    """
    pending: dict[str, ToolCall] = {}
    ordered: list[ToolCall] = []

    for msg in messages:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    # args_as_dict() handles both dict and JSON-string arg forms
                    args = part.args_as_dict()
                    call_id = part.tool_call_id or part.tool_name
                    tc = ToolCall(tool_call_id=call_id, name=part.tool_name, args=args)
                    pending[call_id] = tc
                    ordered.append(tc)
        elif isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    call_id = part.tool_call_id or part.tool_name
                    if call_id in pending:
                        pending[call_id].result = part.content

    return ordered
