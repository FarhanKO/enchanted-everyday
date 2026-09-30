"""The only place the pipeline talks to an LLM.

The model gets text in and gives JSON text out: no tools, no code execution. Output is constrained
by a JSON schema on the API side and re-validated with Pydantic here, so nothing it writes is ever
executed or trusted unchecked.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

import anthropic
from pydantic import BaseModel, ValidationError

from engine.llm.pricing import cost_usd

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LLMRefusal(LLMError):
    pass


class LLMOutputInvalid(LLMError):
    pass


@dataclass(frozen=True)
class LLMResult:
    data: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


class LLMProvider(Protocol):
    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 16000
    ) -> LLMResult: ...


class AnthropicProvider:
    def __init__(
        self,
        api_key: str | None,
        model: str = "claude-opus-5-5",
        effort: str = "medium",
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self._client = client or anthropic.Anthropic(api_key=api_key, max_retries=4)

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 16000
    ) -> LLMResult:
        resp = self._client.beta.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
            # if a safety classifier declines, the API retries on a fallback model in-call
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        cost = cost_usd(resp.model, resp.usage.input_tokens, resp.usage.output_tokens)
        log.info(
            "llm call",
            extra={
                "model": resp.model,
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
                "cost_usd": str(cost),
                "stop_reason": resp.stop_reason,
            },
        )

        if resp.stop_reason == "refusal":
            raise LLMRefusal(f"model declined: {getattr(resp.stop_details, 'category', None)}")
        if resp.stop_reason == "max_tokens":
            raise LLMOutputInvalid("output hit max_tokens; JSON is truncated")

        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise LLMOutputInvalid("no text block in response")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMOutputInvalid(f"invalid JSON: {e}") from e

        return LLMResult(
            data=data,
            model=resp.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cost_usd=cost,
        )


def parse_as[M: BaseModel](result: LLMResult, model: type[M]) -> M:
    """Validate an LLM result against its Pydantic contract."""
    try:
        return model.model_validate(result.data)
    except ValidationError as e:
        raise LLMOutputInvalid(str(e)) from e


def wrap_untrusted(label: str, text: str) -> str:
    """Fence scraped web text so prompts can tell the model it is data, not instructions."""
    safe = text.replace(f"</{label}>", "")
    return f"<{label}>\n{safe}\n</{label}>"
