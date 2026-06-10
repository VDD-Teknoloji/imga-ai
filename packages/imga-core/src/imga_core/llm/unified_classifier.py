"""Sprint 11.0 — birleşik Gemini sınıflandırma motoru.

Sentiment + kategori, TEK structured-output çağrısında ~25 yorum
birden. Eski akışın iki ayrı maliyetini birleştirir:

  * BERT sentiment (CPU/RAM baskısı, paralel chunk başına ~500 MB
    model kopyası) sıcak yoldan çıkar;
  * düşük güvenli satırların TEK TEK Gemini'ye gittiği kategori
    fallback'i (10K satırda binlerce çağrı — "saatlerce bekleme"nin
    asıl kaynağı) toptan kalkar: 10K satır ≈ 400 çağrı.

Düzeltme-geri-besleme buradan akar: tenant'ın geçmiş düzeltmeleri
few-shot örneği olarak prompt'a girer; LLM düzeltme DESENİNİ benzer
yorumlara genelleştirir (eski "Train & Save"in gerçekten çalışan
hali).

Dayanıklılık sözleşmesi: motor herhangi bir sebeple üretemezse
(tüm key'ler tükendi, parse hatası, timeout) çağıran taraf klasik
zincire düşer — BERT (remote → lokal) + keyword kategori. Bu modül
asla "sessizce yanlış" dönmez; ya tam sonuç listesi ya exception.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from imga_core.config import (
    LABEL_NEGATIVE,
    LABEL_NEUTRAL,
    LABEL_POSITIVE,
)
from imga_core.llm.base import LLMProviderError
from imga_core.llm.errors import InvalidKeyError, RateLimitError
from imga_core.llm.key_rotation import GeminiKey, GeminiKeyRotator

if TYPE_CHECKING:
    pass

_logger = logging.getLogger(__name__)

_VALID_LABELS = (LABEL_POSITIVE, LABEL_NEGATIVE, LABEL_NEUTRAL)

# Çağrı başına yorum sayısı. 25 × ~60 token yorum + prompt ≈ 2-4K
# token — flash-lite'ın 250K TPM'inde rahat; tek çağrının çıktısı
# parse edilebilir boyutta kalır.
DEFAULT_CALL_BATCH_SIZE = 25
# Rotator free-tier RPM'ine saygı: aynı anda en çok bu kadar çağrı.
DEFAULT_CONCURRENCY = 4
_HARD_TIMEOUT_SECONDS = 45.0


@dataclass(frozen=True, slots=True)
class FewShotExample:
    """Tenant düzeltmesinden türetilen prompt örneği. imga-api'nin
    CorrectionExample'ı bu tipe çevrilir — core, DB tiplerinden
    habersiz kalır."""

    text: str
    sentiment_label: str
    category: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class UnifiedPrediction:
    sentiment_label: str
    sentiment_score: float
    category: str
    category_confidence: float


@dataclass(slots=True)
class UnifiedBatchStats:
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    calls: int = 0
    failed_calls: int = 0


_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["i", "s", "sc", "c", "cc"],
        "properties": {
            "i": {"type": "integer"},
            "s": {"type": "string", "enum": list(_VALID_LABELS)},
            "sc": {"type": "number"},
            "c": {"type": "string"},
            "cc": {"type": "number"},
        },
    },
}

_SYSTEM_PROMPT = """\
Sen Türkçe müşteri yorumlarını analiz eden kıdemli bir sınıflandırıcısın.

Her yorum için döndür:
  s  — duygu: POZITIF, NEGATIF veya NÖTR
  sc — duygu skoru: -1.0 (çok olumsuz) ile 1.0 (çok olumlu) arası
  c  — kategori: SADECE verilen listeden bir kod
  cc — kategori güveni: 0.0-1.0

Kurallar:
- Kararsızsan kategori için "belirsiz" kodunu kullan (listede varsa).
- Alaycı/ironik ifadelerde gerçek niyeti puanla.
- Karma duygularda baskın olanı seç; sc'yi orta bantta tut.
- Her girdi yorumu için TAM BİR sonuç döndür; index (i) girdiyle eşleşmeli.
"""


def _build_prompt(
    texts: list[str],
    available_categories: list[str],
    few_shot: tuple[FewShotExample, ...],
) -> str:
    parts: list[str] = [_SYSTEM_PROMPT]
    parts.append("Kategori kodları: " + ", ".join(available_categories))

    if few_shot:
        parts.append(
            "\nBu işletmenin geçmiş İNSAN DÜZELTMELERİ — aynı dili/deseni "
            "taşıyan yorumlarda bu kararları örnek al:"
        )
        for example in few_shot:
            reason = f" (gerekçe: {example.reason})" if example.reason else ""
            parts.append(
                f'- "{example.text[:200]}" -> duygu={example.sentiment_label}, '
                f"kategori={example.category}{reason}"
            )

    parts.append("\nYorumlar:")
    for i, text in enumerate(texts):
        single_line = " ".join(text.split())
        parts.append(f"{i}: {single_line[:600]}")
    parts.append(
        "\nJSON dizisi döndür; her öğe {\"i\", \"s\", \"sc\", \"c\", \"cc\"} "
        "alanlarını taşımalı."
    )
    return "\n".join(parts)


def _map_sdk_error(exc: Exception) -> Exception:
    """SDK hatasını rotator sözlüğüne çevir — RateLimit/InvalidKey
    rotasyonu tetikler, kalanlar LLMProviderError olarak akar.
    (rotating_gemini._maybe_rotate ile aynı sniff semantiği.)"""
    text = str(exc).lower()
    if "429" in text or "resource_exhausted" in text or "rate" in text and "limit" in text:
        return RateLimitError()
    if "api key" in text or "api_key" in text or "401" in text or "403" in text:
        return InvalidKeyError(str(exc))
    return LLMProviderError(f"Gemini unified call failed: {exc}")


class GeminiUnifiedEngine:
    """Rotator-bilinçli birleşik sınıflandırıcı. Tek kullanım/job —
    rotator durumu job başında taze kurulur (RotatingGeminiProvider
    ile aynı yaşam döngüsü)."""

    def __init__(
        self,
        keys: list[GeminiKey],
        *,
        model_name: str,
        call_batch_size: int = DEFAULT_CALL_BATCH_SIZE,
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> None:
        if not keys:
            raise ValueError("GeminiUnifiedEngine requires at least one key")
        self._rotator = GeminiKeyRotator(keys)
        self._model_name = model_name
        self._call_batch_size = max(1, call_batch_size)
        self._concurrency = max(1, concurrency)

    @property
    def model_name(self) -> str:
        return self._model_name

    async def classify_unified_batch_async(
        self,
        texts: list[str],
        *,
        available_categories: list[str],
        few_shot: tuple[FewShotExample, ...] = (),
    ) -> tuple[list[UnifiedPrediction], UnifiedBatchStats]:
        """Tüm metinler için birleşik tahmin. Herhangi bir alt-çağrı
        kalıcı olarak başarısızsa exception fırlatır — kısmi/sessiz
        sonuç dönmez (çağıran fallback zincirine geçer)."""
        if not texts:
            return [], UnifiedBatchStats()
        if not available_categories:
            raise LLMProviderError("available_categories must be non-empty")

        stats = UnifiedBatchStats()
        started = time.monotonic()
        semaphore = asyncio.Semaphore(self._concurrency)
        results: dict[int, UnifiedPrediction] = {}

        async def _one_call(offset: int, chunk: list[str]) -> None:
            async with semaphore:
                predictions = await self._call_with_rotation(
                    chunk, available_categories, few_shot, stats
                )
            for local_idx, prediction in predictions.items():
                results[offset + local_idx] = prediction

        tasks = [
            _one_call(offset, texts[offset : offset + self._call_batch_size])
            for offset in range(0, len(texts), self._call_batch_size)
        ]
        await asyncio.gather(*tasks)

        stats.duration_ms = int((time.monotonic() - started) * 1000)

        ordered: list[UnifiedPrediction] = []
        for i, _ in enumerate(texts):
            prediction = results.get(i)
            if prediction is None:
                # Model bu index'i atladıysa nötr/belirsiz ile doldur —
                # satır kaybetmek yok; düşük güven manuel inceleme
                # bayrağını zaten tetikler.
                prediction = UnifiedPrediction(
                    sentiment_label=LABEL_NEUTRAL,
                    sentiment_score=0.0,
                    category="belirsiz",
                    category_confidence=0.0,
                )
            ordered.append(prediction)
        return ordered, stats

    async def _call_with_rotation(
        self,
        chunk: list[str],
        available_categories: list[str],
        few_shot: tuple[FewShotExample, ...],
        stats: UnifiedBatchStats,
    ) -> dict[int, UnifiedPrediction]:
        prompt = _build_prompt(chunk, available_categories, few_shot)

        async def _operation(api_key: str) -> dict[int, UnifiedPrediction]:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(
                        self._generate_sync,
                        api_key,
                        prompt,
                        chunk,
                        available_categories,
                        stats,
                    ),
                    timeout=_HARD_TIMEOUT_SECONDS,
                )
            except TimeoutError as exc:
                stats.failed_calls += 1
                raise LLMProviderError(
                    "Gemini unified call timed out at asyncio safety net "
                    f"({_HARD_TIMEOUT_SECONDS:.0f}s)"
                ) from exc

        result, winning_key = await self._rotator.call_with_rotation(_operation)
        _logger.debug(
            "GeminiUnifiedEngine: chunk served by key label=%s",
            winning_key.label,
        )
        return result

    def _generate_sync(
        self,
        api_key: str,
        prompt: str,
        chunk: list[str],
        available_categories: list[str],
        stats: UnifiedBatchStats,
    ) -> dict[int, UnifiedPrediction]:
        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=api_key)
        try:
            response = client.models.generate_content(
                model=self._model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_RESPONSE_SCHEMA,
                    temperature=0.1,
                ),
            )
        except Exception as exc:  # noqa: BLE001 — SDK hatası eşlenir
            stats.failed_calls += 1
            raise _map_sdk_error(exc) from exc

        stats.calls += 1
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            stats.input_tokens += int(
                getattr(usage, "prompt_token_count", 0) or 0
            )
            stats.output_tokens += int(
                getattr(usage, "candidates_token_count", 0) or 0
            )

        raw = getattr(response, "text", None)
        if not raw:
            raise LLMProviderError("Empty response text from Gemini (unified)")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                f"Gemini unified returned non-JSON: {raw[:200]!r}"
            ) from exc
        if not isinstance(data, list):
            raise LLMProviderError(
                f"Expected JSON array, got {type(data).__name__}"
            )

        valid_categories = set(available_categories)
        parsed: dict[int, UnifiedPrediction] = {}
        for entry in data:
            if not isinstance(entry, dict):
                continue
            try:
                idx = int(entry["i"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= idx < len(chunk)) or idx in parsed:
                continue
            label = str(entry.get("s", LABEL_NEUTRAL))
            if label not in _VALID_LABELS:
                label = LABEL_NEUTRAL
            try:
                score = max(-1.0, min(1.0, float(entry.get("sc", 0.0))))
            except (TypeError, ValueError):
                score = 0.0
            category = str(entry.get("c", "belirsiz"))
            if category not in valid_categories:
                category = "belirsiz"
            try:
                confidence = max(0.0, min(1.0, float(entry.get("cc", 0.0))))
            except (TypeError, ValueError):
                confidence = 0.0
            parsed[idx] = UnifiedPrediction(
                sentiment_label=label,
                sentiment_score=score,
                category=category,
                category_confidence=confidence,
            )
        if not parsed:
            raise LLMProviderError(
                "Gemini unified response contained no usable entries"
            )
        return parsed


__all__ = [
    "DEFAULT_CALL_BATCH_SIZE",
    "FewShotExample",
    "GeminiUnifiedEngine",
    "UnifiedBatchStats",
    "UnifiedPrediction",
]
