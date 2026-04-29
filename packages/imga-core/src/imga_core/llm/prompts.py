"""LLM prompts for category classification.

Single-source-of-truth Turkish prompt used by every provider. Categories
are interpolated at call time (since tenants may extend or disable them).
"""

from __future__ import annotations

from typing import Final

CLASSIFICATION_SYSTEM_PROMPT: Final[str] = """Sen Türkçe müşteri şikayetlerini iş birimlerine sınıflandıran bir asistansın.

Aşağıdaki kategorilerden EN UYGUN olanını seç:
{categories}

Şikayet metni:
{text}

Yanıt kuralları:
1. Sadece yukarıdaki kategori kodlarından birini kullan
2. Hiçbiri uymazsa "belirsiz" olarak işaretle
3. Confidence 0.0-1.0 arasında, ne kadar emin olduğunu yansıtsın
4. Reasoning 1-2 cümle, neden bu kategoriyi seçtiğini açıkla

JSON formatında cevap ver:
{{"primary": "kategori_kodu", "confidence": 0.0-1.0, "reasoning": "açıklama"}}
"""


# Structured-output schema enforced via Gemini's response_schema. Provider-
# agnostic JSON Schema dialect; other providers can ignore or translate.
CLASSIFICATION_RESPONSE_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "primary": {"type": "string"},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["primary", "confidence", "reasoning"],
}


def build_classification_prompt(text: str, available_categories: list[str]) -> str:
    """Render the classification prompt with the given category list."""
    categories_block = "\n".join(f"- {c}" for c in available_categories)
    return CLASSIFICATION_SYSTEM_PROMPT.format(
        categories=categories_block,
        text=text,
    )
