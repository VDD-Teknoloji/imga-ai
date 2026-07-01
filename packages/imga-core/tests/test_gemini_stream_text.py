"""GeminiProvider.stream_text — SDK çağrı şekli + chunk→(text,usage) eşleme (mock).

``_build_client`` mock'lanır → gerçek google-genai çağrısı yapılmaz; stream_text'in
KENDİ mantığı (config kurulumu, generate_content_stream kwargs, iterasyon, usage
extraction, hata haritalama) doğrulanır. Gerçek SDK'nın bu şekle uyduğu ayrıca
canlı doğrulanmalı (bu test mock varsayımını kilitler)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from imga_core.llm import gemini as gmod
from imga_core.llm.errors import RateLimitError
from imga_core.llm.gemini import GeminiProvider


class _Usage:
    def __init__(self, p: int, c: int, t: int) -> None:
        self.prompt_token_count = p
        self.candidates_token_count = c
        self.total_token_count = t


class _Chunk:
    def __init__(self, text: str, usage: _Usage | None = None) -> None:
        self.text = text
        self.usage_metadata = usage


async def _fake_stream(chunks: list[_Chunk]) -> AsyncIterator[_Chunk]:
    for c in chunks:
        yield c


class _FakeAioModels:
    def __init__(self, chunks: list[_Chunk]) -> None:
        self._chunks = chunks
        self.calls: list[tuple[str, str]] = []

    async def generate_content_stream(
        self, *, model: str, contents: str, config: object
    ) -> AsyncIterator[_Chunk]:
        self.calls.append((model, contents))
        return _fake_stream(self._chunks)


class _FakeClient:
    def __init__(self, models: _FakeAioModels) -> None:
        self.aio = type("_Aio", (), {"models": models})()


def _patch_client(monkeypatch: pytest.MonkeyPatch, models: _FakeAioModels) -> None:
    monkeypatch.setattr(
        gmod, "_build_client", lambda api_key, timeout: _FakeClient(models)
    )


def test_stream_text_yields_deltas_then_final_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [_Chunk("Mer"), _Chunk("haba"), _Chunk("", _Usage(12, 4, 16))]
    models = _FakeAioModels(chunks)
    _patch_client(monkeypatch, models)
    prov = GeminiProvider(api_key="x", model_name="m")

    async def _run() -> list[tuple[str, dict | None]]:
        return [
            x
            async for x in prov.stream_text(
                api_key="x", system_prompt="s", user_prompt="soru", model_name="m"
            )
        ]

    out = asyncio.run(_run())
    assert out[0] == ("Mer", None)
    assert out[1] == ("haba", None)
    assert out[2] == ("", {"input": 12, "output": 4, "total": 16})
    # generate_content_stream doğru kwargs ile çağrıldı
    assert models.calls == [("m", "soru")]


def test_stream_text_empty_prompt_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, _FakeAioModels([]))
    prov = GeminiProvider(api_key="x", model_name="m")

    async def _run() -> list[tuple[str, dict | None]]:
        return [
            x
            async for x in prov.stream_text(
                api_key="x", system_prompt="s", user_prompt="  ", model_name="m"
            )
        ]

    with pytest.raises(Exception):  # MalformedResponseError
        asyncio.run(_run())


def test_stream_text_maps_sdk_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingModels(_FakeAioModels):
        async def generate_content_stream(self, **_kw: object) -> AsyncIterator[_Chunk]:
            raise RuntimeError("429 rate limit resource_exhausted")
            if False:
                yield _Chunk("")

    _patch_client(monkeypatch, _FailingModels([]))
    prov = GeminiProvider(api_key="x", model_name="m")

    async def _run() -> list[tuple[str, dict | None]]:
        return [
            x
            async for x in prov.stream_text(
                api_key="x", system_prompt="s", user_prompt="soru", model_name="m"
            )
        ]

    with pytest.raises(RateLimitError):  # _raise_mapped_sdk_error → 429 mesajı
        asyncio.run(_run())
