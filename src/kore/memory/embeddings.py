from __future__ import annotations

import asyncio
import struct
from typing import Any


def _load_sentence_transformer(model_name: str) -> Any:
    """Load a SentenceTransformer model. Separated for easy mocking in tests."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(model_name)


def serialize_vector(v: list[float]) -> bytes:
    """Serialize a float list to 32-bit float bytes (sqlite-vec format)."""
    return struct.pack(f"{len(v)}f", *v)


def deserialize_vector(b: bytes) -> list[float]:
    """Deserialize 32-bit float bytes back to a list of floats."""
    n = len(b) // 4
    return list(struct.unpack(f"{n}f", b))


class EmbeddingModel:
    """Embedding cascade: local sentence-transformers → OpenAI API → None (BM25-only).

    The model is lazy-loaded on first use to avoid startup delay.
    Falls back gracefully at each step — callers treat ``None`` as
    "embedding unavailable; use BM25-only retrieval."
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        openai_api_key: str | None = None,
        openai_base_url: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._openai_api_key = openai_api_key
        self._openai_base_url = openai_base_url
        self._local_model: Any = None
        self._local_failed = False

    def embed_sync(self, text: str) -> list[float] | None:
        """Synchronous embedding — tries local model only (no async API call)."""
        if not self._local_failed:
            try:
                if self._local_model is None:
                    self._local_model = _load_sentence_transformer(self._model_name)
                result = self._local_model.encode(text)
                # sentence-transformers may return numpy array or list
                return [float(x) for x in result]
            except Exception:
                self._local_failed = True
        return None

    async def embed(self, text: str) -> list[float] | None:
        """Async embedding — tries local model, then OpenAI API, then returns None."""
        # Try local (run in thread pool to avoid blocking event loop)
        if not self._local_failed:
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, self.embed_sync, text)
                if result is not None:
                    return result
            except Exception:
                self._local_failed = True

        # Try OpenAI-compatible API
        if self._openai_api_key:
            try:
                return await self._openai_embed(text)
            except Exception:
                pass

        return None

    async def _openai_embed(self, text: str) -> list[float]:
        """Embed via OpenAI-compatible API (also works with OpenRouter)."""
        import httpx

        headers = {"Authorization": f"Bearer {self._openai_api_key}"}
        base = self._openai_base_url or "https://api.openai.com/v1"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{base}/embeddings",
                headers=headers,
                json={"input": text, "model": "text-embedding-3-small"},
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
