"""The only place the pipeline talks to an LLM.

The model gets text in and gives JSON text out: no tools, no code execution. Output is constrained
by a JSON schema on the API side and re-validated with Pydantic here, so nothing it writes is ever
executed or trusted unchecked.
"""

from __future__ import annotations

import json
import logging
import re
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
    """The output broke its contract. `data` holds the parsed JSON, if any, for a repair."""

    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.data = data


@dataclass(frozen=True)
class LLMResult:
    data: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


# models that accept the server-side refusal fallback (`fallbacks: "default"`)
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


class LLMProvider(Protocol):
    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int = 16000,
        model: str | None = None,
        effort: str | None = None,
    ) -> LLMResult: ...


class AnthropicProvider:
    server_fallback = True  # Anthropic's in-call refusal fallback, on the models that accept it

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

    def api_model(self, model: str) -> str:
        """The id this provider's API knows `model` by."""
        return model

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int = 16000,
        model: str | None = None,
        effort: str | None = None,
    ) -> LLMResult:
        """`model` and `effort` override the provider's defaults for this one call."""
        model = model or self.model
        extra: dict[str, Any] = {}
        if self.server_fallback and model in FALLBACK_MODELS:
            # if a safety classifier declines, the API retries on a fallback model in-call
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        resp = self._client.beta.messages.create(
            model=self.api_model(model),
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": effort or self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
            **extra,
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


OPENROUTER_BASE_URL = "https://openrouter.ai/api"


class OpenRouterProvider(AnthropicProvider):
    """Claude through OpenRouter's Anthropic-compatible Messages API.

    Same request, structured output and effort as AnthropicProvider; only the endpoint, the key
    and the model ids differ. The key is sent as a bearer token in a header, never in a URL.
    OpenRouter routes around a failing upstream itself, so Anthropic's fallback beta is off.
    """

    server_fallback = False

    def __init__(
        self,
        api_key: str | None,
        model: str = "claude-opus-5-5",
        effort: str = "medium",
        client: anthropic.Anthropic | None = None,
        base_url: str = OPENROUTER_BASE_URL,
    ) -> None:
        super().__init__(
            None,
            model=model,
            effort=effort,
            client=client
            or anthropic.Anthropic(
                base_url=base_url, api_key=None, auth_token=api_key, max_retries=4
            ),
        )

    def api_model(self, model: str) -> str:
        """claude-opus-5-5 -> anthropic/claude-opus-5.5; an id with a '/' passes through."""
        if "/" in model:
            return model
        return "anthropic/" + re.sub(r"-(\d+)-(\d+)$", r"-\1.\2", model)


def parse_as[M: BaseModel](result: LLMResult, model: type[M]) -> M:
    """Validate an LLM result against its Pydantic contract."""
    try:
        return model.model_validate(result.data)
    except ValidationError as e:
        raise LLMOutputInvalid(str(e), data=result.data) from e


def wrap_untrusted(label: str, text: str) -> str:
    """Fence scraped web text so prompts can tell the model it is data, not instructions."""
    safe = text.replace(f"</{label}>", "")
    return f"<{label}>\n{safe}\n</{label}>"
