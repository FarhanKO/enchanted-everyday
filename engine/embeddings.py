"""Local sentence embeddings for the near-duplicate story check.

Runs all-MiniLM-L6-v2 through ONNX (fastembed), so there's no torch and no per-call cost. The
model (~90 MB) downloads on first use into EMBEDDING_CACHE_DIR.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from engine.config import Settings
from engine.db.models import EMBEDDING_DIM


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedder:
    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name, cache_dir=cache_dir or None)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = [v.tolist() for v in self._model.embed(texts)]
        if vectors and len(vectors[0]) != EMBEDDING_DIM:
            raise ValueError(f"embedding size {len(vectors[0])}; schema expects {EMBEDDING_DIM}")
        return vectors


@lru_cache
def _cached(model_name: str, cache_dir: str) -> FastEmbedder:
    return FastEmbedder(model_name, cache_dir)


def get_embedder(settings: Settings) -> Embedder:
    return _cached(settings.embedding_model, settings.embedding_cache_dir)
