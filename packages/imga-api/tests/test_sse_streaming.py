"""§7 SSE streaming — sse_stream formatlaması + stream_free_analyze eşleme (mock).

Gerçek Gemini SDK çağrısı MOCK'lanır (google-genai + key yok); bu testler tüm
mantığı doğrular: SSE event şekli (partial/meta/done/error), disconnect erken-durma,
chunk→(text, TokenUsage) eşleme, §5 hata haritalama. Doğrulanmayan tek parça —
gerçek ``generate_content_stream`` SDK çağrı şekli — server-agent canlı-kontrolünde.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from imga_api.v1.envelope import TokenUsage
from imga_api.v1.errors import PartnerApiError
from imga_api.v1.stream import sse_stream


async def _collect(agen: AsyncIterator[str]) -> list[str]:
    return [x async for x in agen]


async def _fake_deltas(
    items: list[tuple[str, TokenUsage | None]],
) -> AsyncIterator[tuple[str, TokenUsage | None]]:
    for text, usage in items:
        yield text, usage


async def _never_disconnected() -> bool:
    return False


def test_sse_stream_partial_meta_done() -> None:
    items: list[tuple[str, TokenUsage | None]] = [
        ("Merhaba", None),
        (" dünya", None),
        ("", TokenUsage(prompt=10, completion=5)),
    ]
    out = asyncio.run(
        _collect(sse_stream(_fake_deltas(items), is_disconnected=_never_disconnected))
    )
    joined = "".join(out)
    assert out[0] == ": ping\n\n"
    assert '"delta": "Merhaba"' in joined and '"delta": " dünya"' in joined
    assert "event: meta" in joined
    assert '"processed_in": "outbound"' in joined
    assert '"prompt": 10' in joined and '"completion": 5' in joined
    assert "event: done" in joined
    assert '"final_length": 13' in joined  # len("Merhaba")=7 + len(" dünya")=6


def test_sse_stream_error_event() -> None:
    async def _raising() -> AsyncIterator[tuple[str, TokenUsage | None]]:
        yield "önce", None
        raise PartnerApiError(status_code=502, code="provider_error", message="boom")

    out = asyncio.run(
        _collect(sse_stream(_raising(), is_disconnected=_never_disconnected))
    )
    joined = "".join(out)
    assert '"delta": "önce"' in joined
    assert "event: error" in joined and '"code": "provider_error"' in joined
    assert "event: done" not in joined  # hata → done yok


def test_sse_stream_disconnect_stops_early() -> None:
    state = {"n": 0}

    async def _disc_after_first() -> bool:
        state["n"] += 1
        return state["n"] >= 2  # 1. delta'da False, 2.'de True

    items: list[tuple[str, TokenUsage | None]] = [("a", None), ("b", None), ("c", None)]
    out = asyncio.run(
        _collect(sse_stream(_fake_deltas(items), is_disconnected=_disc_after_first))
    )
    joined = "".join(out)
    assert '"delta": "a"' in joined
    assert '"delta": "b"' not in joined
    assert "event: meta" not in joined  # disconnect → meta/done yok


def test_stream_free_analyze_maps_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    import imga_api.services.partner_analyze as pa

    class _FakeProvider:
        def __init__(self, **_kw: object) -> None: ...

        async def stream_text(self, **_kw: object) -> AsyncIterator[tuple[str, dict | None]]:
            yield "Selam", None
            yield " çok", None
            yield "", {"input": 20, "output": 7}

    monkeypatch.setattr(pa, "GeminiProvider", _FakeProvider)

    async def _run() -> list[tuple[str, TokenUsage | None]]:
        return [x async for x in pa.stream_free_analyze("soru")]

    out = asyncio.run(_run())
    assert out[0] == ("Selam", None)
    assert out[-1][0] == "" and out[-1][1] == TokenUsage(prompt=20, completion=7)


def test_stream_free_analyze_maps_ratelimit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    import imga_api.services.partner_analyze as pa
    from imga_core.llm.errors import RateLimitError

    class _FakeProvider:
        def __init__(self, **_kw: object) -> None: ...

        async def stream_text(self, **_kw: object) -> AsyncIterator[tuple[str, dict | None]]:
            if False:  # async generator yap; ilk __anext__'te patla
                yield "", None
            raise RateLimitError()

    monkeypatch.setattr(pa, "GeminiProvider", _FakeProvider)

    async def _run() -> list[tuple[str, TokenUsage | None]]:
        return [x async for x in pa.stream_free_analyze("soru")]

    with pytest.raises(PartnerApiError) as ei:
        asyncio.run(_run())
    assert ei.value.code == "rate_limit" and ei.value.status_code == 429
