from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_embedding_model_returns_list_of_floats(tmp_path, monkeypatch):
    """Local model path returns a list of floats."""
    from kore.memory.embeddings import EmbeddingModel

    mock_st = MagicMock()
    mock_st.encode.return_value = [0.1] * 384

    with patch("kore.memory.embeddings._load_sentence_transformer", return_value=mock_st):
        model = EmbeddingModel(model_name="all-MiniLM-L6-v2")
        result = model.embed_sync("hello world")

    assert isinstance(result, list)
    assert len(result) == 384
    assert all(isinstance(x, float) for x in result)


def test_embedding_model_returns_none_when_local_fails_and_no_api(monkeypatch):
    """Returns None when local model raises and no API key is configured."""
    from kore.memory.embeddings import EmbeddingModel

    with patch("kore.memory.embeddings._load_sentence_transformer", side_effect=ImportError("no ST")):
        model = EmbeddingModel(model_name="all-MiniLM-L6-v2", openai_api_key=None)
        result = model.embed_sync("hello world")

    assert result is None


@pytest.mark.asyncio
async def test_embedding_model_async_returns_list(monkeypatch):
    """Async embed wraps the sync call."""
    from kore.memory.embeddings import EmbeddingModel

    mock_st = MagicMock()
    mock_st.encode.return_value = [0.5] * 384

    with patch("kore.memory.embeddings._load_sentence_transformer", return_value=mock_st):
        model = EmbeddingModel(model_name="all-MiniLM-L6-v2")
        result = await model.embed("test text")

    assert result is not None
    assert len(result) == 384


@pytest.mark.asyncio
async def test_embedding_model_falls_back_to_none_on_all_failures(monkeypatch):
    """Returns None when both local and API fail."""
    from kore.memory.embeddings import EmbeddingModel

    with patch("kore.memory.embeddings._load_sentence_transformer", side_effect=Exception("fail")):
        model = EmbeddingModel(model_name="all-MiniLM-L6-v2", openai_api_key=None)
        result = await model.embed("test")

    assert result is None


def test_serialize_deserialize_roundtrip():
    """Vector survives serialization → bytes → deserialization."""
    from kore.memory.embeddings import deserialize_vector, serialize_vector

    original = [0.1, 0.2, 0.3, -0.5, 1.0]
    b = serialize_vector(original)
    recovered = deserialize_vector(b)

    assert len(recovered) == len(original)
    for a, r in zip(original, recovered):
        assert abs(a - r) < 1e-6
