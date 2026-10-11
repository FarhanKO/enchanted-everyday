"""Images and speech through OpenRouter, on the same key as the story agents.

Images: Nano Banana (Gemini image models) through chat completions with image output, the cast's
approved reference images attached so faces and outfits hold. Speech: ElevenLabs voices through
the OpenAI-style speech endpoint. The key goes in a header, never in a URL, and error messages
carry only the status and the start of the body.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

BASE_URL = "https://openrouter.ai/api/v1"

# USD, from openrouter.ai/api/v1/models (2026-10-11). Used when a response carries no cost, and
# to check the daily cap before paying. An unknown model is priced at the dearest known one.
IMAGE_ESTIMATE_USD = {
    "google/gemini-nano-banana-2.1": Decimal("0.040"),
    "google/gemini-3.1-flash-image": Decimal("0.080"),
}
SPEECH_USD_PER_CHAR = {
    "elevenlabs/eleven-v4": Decimal("0.00004"),
    "elevenlabs/eleven-v3": Decimal("0.00004"),
}


def image_estimate(model: str) -> Decimal:
    return IMAGE_ESTIMATE_USD.get(model, max(IMAGE_ESTIMATE_USD.values()))


def speech_cost(model: str, text: str) -> Decimal:
    rate = SPEECH_USD_PER_CHAR.get(model, max(SPEECH_USD_PER_CHAR.values()))
    return rate * len(text)


class MediaError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _retryable(e: BaseException) -> bool:
    return isinstance(e, httpx.TransportError) or (
        isinstance(e, MediaError) and e.status in (408, 429, 500, 502, 503, 504)
    )


_retry = retry(
    retry=retry_if_exception(_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=4, max=30),
    reraise=True,
)


@dataclass(frozen=True)
class Image:
    data: bytes
    mime: str
    model: str
    cost_usd: Decimal


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


class OpenRouterMedia:
    def __init__(self, api_key: str, http: httpx.Client | None = None) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._http = http or httpx.Client(timeout=180)

    def _post(self, path: str, payload: dict) -> httpx.Response:
        resp = self._http.post(f"{BASE_URL}{path}", headers=self._headers, json=payload)
        if resp.status_code != 200:
            raise MediaError(
                f"OpenRouter {path}: HTTP {resp.status_code} {resp.text[:300]}", resp.status_code
            )
        return resp

    @_retry
    def image(
        self,
        prompt: str,
        model: str,
        references: list[Path] = (),
        aspect_ratio: str = "9:16",
        size: str = "1K",
    ) -> Image:
        content: list[dict] = [{"type": "text", "text": prompt}]
        content += [{"type": "image_url", "image_url": {"url": data_uri(p)}} for p in references]
        resp = self._post(
            "/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "modalities": ["image", "text"],
                "image_config": {"aspect_ratio": aspect_ratio, "image_size": size},
                "usage": {"include": True},
            },
        )
        body = resp.json()
        try:
            message = body["choices"][0]["message"]
            url = message["images"][0]["image_url"]["url"]
        except (KeyError, IndexError, TypeError):
            # the model answered in words (a refusal or a question) instead of drawing
            said = ""
            if body.get("choices"):
                said = str(body["choices"][0].get("message", {}).get("content") or "")[:300]
            raise MediaError(f"{model} returned no image: {said or 'empty response'}") from None
        head, _, b64 = url.partition(",")
        mime = head.removeprefix("data:").split(";")[0] or "image/png"
        cost = body.get("usage", {}).get("cost")
        return Image(
            data=base64.b64decode(b64),
            mime=mime,
            model=body.get("model", model),
            cost_usd=Decimal(str(cost)) if cost is not None else image_estimate(model),
        )

    @_retry
    def speech(self, text: str, model: str, voice: str) -> bytes:
        resp = self._post(
            "/audio/speech",
            {"model": model, "input": text, "voice": voice, "response_format": "mp3"},
        )
        if not resp.content:
            raise MediaError(f"{model}/{voice} returned no audio")
        return resp.content

    def close(self) -> None:
        self._http.close()
