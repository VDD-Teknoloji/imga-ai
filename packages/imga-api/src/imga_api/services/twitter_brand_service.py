"""Twitter'dan Çek — marka anahtar kelime planı + tweet alaka hakemi.

imga.ai pazarlama sitesindeki trial akışı (site repo'su ``src/lib/
twitter.ts`` → ``extractKeywords``) Gemini'ye şirket adından include/
exclude terimleri + resmi hesap ürettiriyordu; uygulama tarafı bunu
"sorgu deterministik kalsın" diye taşımamıştı. Sonuç: "karaca" araması
Karaca soyadlı herkesin gönderisini getirdi (250'de ~15 marka yorumu).

İki LLM aşaması, ikisi de kurumun kazanan sağlayıcı/modeliyle
(``load_active_llm_keys`` → platform yedeği dahil):

  1. ``plan_brand_search`` — marka + kurum profili (sektör, iş tanımı,
     terminoloji) → include/exclude terimleri, resmi hesap, 1-2 cümlelik
     marka özeti, "çıplak ad belirsiz mi" bayrağı. Kullanıcı formda
     görüp düzenler; ``compose_term`` bunu terim alanının virgül
     sözdizimine çevirir.
  2. ``judge_tweet_relevance`` — çekilen gönderilerin HAM metni (mention
     atılmadan; "@karacaonline ürün bozuk" temizlenince markayı
     kaybeder) 25'lik partilerle hakeme gider: bu marka hakkında mı?
     Parti hatası → o partinin gönderileri TUTULUR (fail-open) ve
     sayılır; aşama-1 alt-dizi filtresi zaten uygulanmıştır.

Onboarding servisiyle aynı ödünç alma deseni: imga-core'a yeni yöntem
eklemek yerine ``generate_root_cause`` ince sarmalayıcısı (hepsi aynı
imzayla ``_generate_structured``a yönlenir) açık temperature/max_tokens
ile kullanılır. Denetim: ``llm_call_audit`` ``twitter_keywords`` /
``twitter_relevance`` (migration 0048). Hakem partileri eşzamanlı koşar;
AsyncSession eşzamanlı kullanılamadığından denetim satırları çağrılar
bittikten SONRA sırayla yazılır (batch yolu ile aynı ``duration_ms``
override deseni).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from imga_core.llm import (
    AllKeysExhaustedError,
    GeminiKeyRotator,
    InvalidKeyError,
    LLMError,
)
from imga_db.models import Tenant
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.llm_audit_service import (
    CALL_TYPE_TWITTER_KEYWORDS,
    CALL_TYPE_TWITTER_RELEVANCE,
    LLMCallAuditor,
    LLMCallContext,
)
from imga_api.services.llm_credentials import (
    LlmKeySelection,
    NoCredentialsError,
    load_active_llm_keys,
    mark_keys_failed,
)
from imga_api.services.llm_provider_factory import (
    StructuredProvider,
    build_structured_provider,
    resolve_model_name,
)
from imga_api.services.smart_parser.base import normalize_header
from imga_api.services.strategic_constants import industry_label

_logger = logging.getLogger(__name__)

MAX_INCLUDE_TERMS = 8
MAX_EXCLUDE_TERMS = 15
MAX_TERM_LENGTH = 60
MIN_TERM_LENGTH = 2
JUDGE_BATCH_SIZE = 25
JUDGE_CONCURRENCY = 4
# Hakeme giden gönderi metni; X'in 280 karakteri + uzun gönderiler için
# üst sınır (prompt şişmesin).
_JUDGE_TEXT_MAX = 600


@dataclass(frozen=True, slots=True)
class BrandSearchPlan:
    brand: str
    brand_summary: str
    include: list[str]
    exclude: list[str]
    handle: str | None
    bare_name_ambiguous: bool
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class RelevanceVerdict:
    """Gönderi başına hakem kararı; ``relevant`` sırası girdiyle aynı.
    ``failed_batches == batches`` ise hakem hiç çalışmadı (fail-open)."""

    relevant: list[bool]
    batches: int
    failed_batches: int
    dropped: int = 0


@dataclass(slots=True)
class _CallOutcome:
    response: dict[str, Any] | None = None
    usage: dict[str, int] | None = None
    duration_ms: int = 0
    error_type: str | None = None
    error_message: str | None = None
    invalid_key_ids: list[UUID] = field(default_factory=list)


PLAN_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "brand_summary": {"type": "string"},
        "include": {"type": "array", "items": {"type": "string"}},
        "exclude": {"type": "array", "items": {"type": "string"}},
        "handle": {"type": "string"},
        "bare_name_ambiguous": {"type": "boolean"},
        "notes": {"type": "string"},
    },
    "required": ["brand_summary", "include", "exclude"],
}

JUDGE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "relevant": {"type": "boolean"},
                },
                "required": ["i", "relevant"],
            },
        }
    },
    "required": ["verdicts"],
}

PLAN_SYSTEM_PROMPT = """\
Sen X/Twitter üzerinde marka izleme sorguları kuran bir uzmansın. Görevin,
bir şirket hakkındaki GERÇEK MÜŞTERİ yorumlarını yakalayacak, aynı adı
taşıyan alakasız içeriği (kişiler, yerler, şarkılar, diziler, başka
şirketler, kelimenin sözlük anlamı) dışarıda bırakacak arama terimleri
üretmektir.

Bilmen gerekenler:
- X araması bir kelimeyi gönderi metninde VE yazarın adında/kullanıcı
  adında eşler. Yaygın bir soyadı ya da sözlük kelimesi olan marka adları
  (örn. "Karaca") tek başına çok gürültü getirir; böyle durumlarda
  bare_name_ambiguous=true ver ve include listesini marka+ürün/kategori
  birleşimleriyle kur ("karaca tencere", "karaca çaydanlık", "karaca home").
- include: en fazla 8 terim. Marka adı (belirsiz değilse), yaygın yazım
  varyantları, ana ürün/hizmet kategorileriyle birleşimler, resmi hesap
  @kullanıcıadı olarak, bilinen kampanya etiketleri. Her terim 2-4 kelime,
  tırnak ve virgül içermesin.
- exclude: en fazla 15 terim. Aynı adı taşıyan ünlü kişiler (sanatçı,
  sporcu, siyasetçi, gazeteci), yer adları, şarkı/dizi/film adları, aynı
  isimli başka şirketler ve markanın sektörüyle ilgisiz sözlük
  kullanımları. Bilmediğin şeyi uydurma; emin olduklarını yaz.
- handle: resmi X kullanıcı adı (@ olmadan) — kullanıcı verdiyse aynen
  koru, vermediyse ve kesin biliyorsan yaz, bilmiyorsan boş bırak.
- brand_summary: şirketin ne yaptığı, ne sattığı, müşterilerinin kim
  olduğu — 1-2 cümle. Bu özet sonraki adımda gönderilerin alakasını
  değerlendiren hakeme bağlam olarak verilecek.
- notes: kullanıcıya tek cümlelik uyarı/öneri (opsiyonel).
Yalnızca JSON döndür."""

JUDGE_SYSTEM_PROMPT = """\
Sen bir marka izleme hakemisin. Sana bir markanın özeti ve X/Twitter
gönderileri verilecek. Her gönderi için karar ver: gönderi BU şirket/
marka hakkında mı (ürünleri, hizmetleri, mağazaları, müşteri deneyimi,
kampanyaları, resmi hesabına yazılmış şikâyet/teşekkür, hatta markanın
reklamı) — yoksa ALAKASIZ mı (aynı adı taşıyan bir kişi, yer, şarkı,
dizi, başka bir şirket; ya da eşleşme yalnızca yazarın adından
kaynaklanıyor ve metin markayla ilgisiz).

Kurallar:
- Metinde marka adı geçmese bile resmi hesaba (@kullanıcıadı) yazılmış
  ya da ürünlerinden bahseden gönderi alakalıdır.
- Marka adı geçse bile bağlam açıkça başka bir varlıksa (Cem Karaca'nın
  şarkısı, Karacaahmet mezarlığı, futbolcu Efecan Karaca) alakasızdır.
- Emin değilsen ve metin markayla bağ kurmuyorsa relevant=false ver.
Her gönderi için tam olarak bir karar döndür; i alanı gönderinin
numarasıdır. Yalnızca JSON döndür."""


# --- terim yardımcıları -------------------------------------------------


def sanitize_term(raw: object) -> str | None:
    """LLM'den ya da kullanıcıdan gelen terimi virgül sözdizimine güvenle
    sokulacak hale getir: tırnak/virgül atılır (virgül terimi ikiye böler,
    baştaki '-' include'u exclude'a çevirir), boşluk sıkıştırılır, uzun
    olan kırpılır. Kısa/boş → None."""
    if raw is None:
        return None
    text = str(raw).replace('"', " ").replace(",", " ").replace("\n", " ")
    text = " ".join(text.split()).strip()
    while text.startswith("-"):
        text = text[1:].strip()
    if len(text) > MAX_TERM_LENGTH:
        text = text[:MAX_TERM_LENGTH].rstrip()
    if len(text) < MIN_TERM_LENGTH:
        return None
    return text


def _dedupe_terms(values: list[object], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = sanitize_term(value)
        if term is None:
            continue
        key = normalize_header(term.lstrip("@#"))
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= limit:
            break
    return out


def compose_term(include: list[str], exclude: list[str]) -> str:
    """Plan → terim alanı sözdizimi (``twitter_import.parse_search_terms``
    ile birebir uyumlu): ``a, b, -x, -y``."""
    parts = [t for t in include if t] + [f"-{t}" for t in exclude if t]
    return ", ".join(parts)


def normalize_handle(raw: object) -> str | None:
    if raw is None:
        return None
    handle = str(raw).strip().lstrip("@").strip()
    if not handle or len(handle) > 50 or " " in handle:
        return None
    return handle


# --- LLM çağrı çekirdeği ------------------------------------------------


class _KeyedProvider:
    """Kurumun kazanan anahtar seçimi + sağlayıcı örneği; bir plan ya da
    bir hakem turu boyunca yeniden kullanılır."""

    def __init__(
        self,
        selection: LlmKeySelection,
        provider: StructuredProvider,
        model_name: str,
    ) -> None:
        self.selection = selection
        self.provider = provider
        self.model_name = model_name
        self.rotator = GeminiKeyRotator(selection.keys)


async def _load_keyed_provider(
    session: AsyncSession,
    tenant_id: UUID,
    provider_override: StructuredProvider | None,
) -> _KeyedProvider:
    selection = await load_active_llm_keys(session, tenant_id)
    if selection is None:
        raise NoCredentialsError("Tenant has no active LLM API keys configured")
    model_name = resolve_model_name(selection.provider, selection.model)
    provider = provider_override or build_structured_provider(selection.provider)
    return _KeyedProvider(selection, provider, model_name)


async def _call_structured(
    keyed: _KeyedProvider,
    *,
    system_prompt: str,
    user_prompt: str,
    response_schema: dict[str, Any],
    temperature: float,
    max_output_tokens: int,
) -> _CallOutcome:
    """Rotasyonlu tek çağrı; istisnayı yutup ``_CallOutcome``a yazar —
    çağıran denetim satırını (sıralı) sonra yazar."""
    outcome = _CallOutcome()
    keys = keyed.selection.keys

    async def _call(api_key: str) -> tuple[dict[str, Any], dict[str, int] | None]:
        try:
            return await keyed.provider.generate_root_cause(
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_schema=response_schema,
                model_name=keyed.model_name,
                temperature=temperature,
                top_p=0.9,
                max_output_tokens=max_output_tokens,
            )
        except InvalidKeyError:
            for k in keys:
                if k.value == api_key:
                    outcome.invalid_key_ids.append(UUID(k.id))
                    break
            raise

    started = time.monotonic()
    try:
        (response, usage), _key_used = await keyed.rotator.call_with_rotation(_call)
        outcome.response = response
        outcome.usage = usage
    except AllKeysExhaustedError as exc:
        outcome.error_type = "all_keys_exhausted"
        outcome.error_message = str(exc.__cause__ or exc)[:1024]
    except LLMError as exc:
        outcome.error_type = "api_error"
        outcome.error_message = str(exc)[:1024]
    except Exception as exc:
        outcome.error_type = "other"
        outcome.error_message = f"{type(exc).__name__}: {exc}"[:1024]
    outcome.duration_ms = int((time.monotonic() - started) * 1000)
    return outcome


async def _record_audit(
    session: AsyncSession,
    keyed: _KeyedProvider,
    outcome: _CallOutcome,
    *,
    tenant_id: UUID,
    call_type: str,
    prompt: str,
    actor_user_id: UUID | None,
) -> None:
    ctx = LLMCallContext(
        tenant_id=tenant_id,
        call_type=call_type,
        model_name=keyed.model_name,
        model_provider=keyed.selection.provider,
        actor_user_id=actor_user_id,
        related_entity_type="tenant",
    )
    auditor = LLMCallAuditor(session, ctx, prompt=prompt)
    async with auditor:
        if outcome.error_type is not None:
            auditor.record_failure(
                error_type=outcome.error_type,
                error_message=outcome.error_message or "",
            )
        else:
            auditor.record_success(
                input_tokens=outcome.usage.get("input") if outcome.usage else None,
                output_tokens=outcome.usage.get("output") if outcome.usage else None,
                duration_ms=outcome.duration_ms,
            )
    if outcome.invalid_key_ids:
        await mark_keys_failed(session, outcome.invalid_key_ids)


# --- 1. plan ----------------------------------------------------------------


def _tenant_context_lines(tenant: Tenant | None) -> list[str]:
    if tenant is None:
        return []
    lines = [f"Kurum adı: {tenant.name}"]
    if tenant.industry:
        lines.append(f"Sektör: {industry_label(tenant.industry, tenant.industry_other_text)}")
    if tenant.business_description:
        lines.append(f"İş tanımı: {tenant.business_description.strip()[:800]}")
    terms = tenant.terminology or []
    names = [str(t.get("term") or t.get("name") or "") for t in terms if isinstance(t, dict)]
    names = [n for n in names if n]
    if names:
        lines.append("Kurum terminolojisi: " + ", ".join(names[:20]))
    return lines


def render_plan_prompt(*, brand: str, handle: str | None, tenant: Tenant | None) -> str:
    lines = [f'Marka / arama adı: "{brand}"']
    if handle:
        lines.append(f"Resmi X hesabı (kullanıcı verdi): @{handle}")
    lines.extend(_tenant_context_lines(tenant))
    lines.append(
        "Türkçe X/Twitter'da bu marka hakkındaki müşteri yorumlarını "
        "yakalayacak include/exclude terimlerini, resmi hesabı ve marka "
        "özetini üret."
    )
    return "\n".join(lines)


def normalize_plan_response(
    data: dict[str, Any], *, brand: str, handle: str | None
) -> BrandSearchPlan:
    include = _dedupe_terms(list(data.get("include") or []), MAX_INCLUDE_TERMS)
    exclude = _dedupe_terms(list(data.get("exclude") or []), MAX_EXCLUDE_TERMS)
    include_keys = {normalize_header(t.lstrip("@#")) for t in include}
    exclude = [t for t in exclude if normalize_header(t.lstrip("@#")) not in include_keys]
    if not include:
        fallback = sanitize_term(brand)
        include = [fallback] if fallback else []
    resolved_handle = normalize_handle(handle) or normalize_handle(data.get("handle"))
    summary = " ".join(str(data.get("brand_summary") or "").split()).strip()[:1000]
    notes_raw = " ".join(str(data.get("notes") or "").split()).strip()[:300]
    return BrandSearchPlan(
        brand=brand,
        brand_summary=summary,
        include=include,
        exclude=exclude,
        handle=resolved_handle,
        bare_name_ambiguous=bool(data.get("bare_name_ambiguous")),
        notes=notes_raw or None,
    )


async def plan_brand_search(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    brand: str,
    handle: str | None,
    actor_user_id: UUID | None,
    provider: StructuredProvider | None = None,
) -> BrandSearchPlan:
    """LLM'den include/exclude/handle/özet planı al. ``session`` kuruma
    bağlı olmalı (denetim satırı + Tenant okuması RLS altında)."""
    tenant = await session.get(Tenant, tenant_id)
    keyed = await _load_keyed_provider(session, tenant_id, provider)
    handle_clean = normalize_handle(handle)
    prompt = render_plan_prompt(brand=brand, handle=handle_clean, tenant=tenant)
    outcome = await _call_structured(
        keyed,
        system_prompt=PLAN_SYSTEM_PROMPT,
        user_prompt=prompt,
        response_schema=PLAN_RESPONSE_SCHEMA,
        temperature=0.2,
        max_output_tokens=2048,
    )
    await _record_audit(
        session,
        keyed,
        outcome,
        tenant_id=tenant_id,
        call_type=CALL_TYPE_TWITTER_KEYWORDS,
        prompt=prompt,
        actor_user_id=actor_user_id,
    )
    if outcome.response is None:
        raise BrandPlanError(outcome.error_type or "other", outcome.error_message or "")
    return normalize_plan_response(outcome.response, brand=brand, handle=handle_clean)


class BrandPlanError(Exception):
    """Plan çağrısı başarısız (anahtarlar tükendi / API hatası)."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


# --- 2. hakem ---------------------------------------------------------------


def render_judge_prompt(
    *,
    brand: str,
    brand_summary: str | None,
    include: list[str],
    exclude: list[str],
    handle: str | None,
    tenant: Tenant | None,
    tweets: list[str],
    start_index: int,
) -> str:
    lines = [f'Marka: "{brand}"']
    if brand_summary:
        lines.append(f"Marka özeti: {brand_summary}")
    lines.extend(_tenant_context_lines(tenant))
    if handle:
        lines.append(f"Resmi X hesabı: @{handle}")
    if include:
        lines.append("Markayı tanımlayan terimler: " + ", ".join(include))
    if exclude:
        lines.append("Alakasız olduğu bilinen adlar/anlamlar: " + ", ".join(exclude))
    lines.append("")
    lines.append("Gönderiler:")
    for offset, text in enumerate(tweets):
        cleaned = " ".join(text.split())[:_JUDGE_TEXT_MAX]
        lines.append(f"{start_index + offset}. {cleaned}")
    lines.append("")
    lines.append('Her gönderi için {"i": numara, "relevant": true/false} kararı ver.')
    return "\n".join(lines)


def parse_judge_response(data: dict[str, Any] | None, *, start_index: int, size: int) -> list[bool]:
    """Kararları indekse göre eşle; eksik/bozuk giriş → TUTULUR (fail-open).
    Dizi uzunluğuna asla güvenilmez."""
    verdicts = [True] * size
    if not data:
        return verdicts
    raw = data.get("verdicts")
    if not isinstance(raw, list):
        return verdicts
    for item in raw:
        if not isinstance(item, dict):
            continue
        idx = item.get("i")
        rel = item.get("relevant")
        if not isinstance(idx, int) or isinstance(idx, bool) or not isinstance(rel, bool):
            continue
        pos = idx - start_index
        if 0 <= pos < size:
            verdicts[pos] = rel
    return verdicts


async def judge_tweet_relevance(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    brand: str,
    brand_summary: str | None,
    include: list[str],
    exclude: list[str],
    handle: str | None,
    tweets: list[str],
    actor_user_id: UUID | None,
    provider: StructuredProvider | None = None,
    batch_size: int = JUDGE_BATCH_SIZE,
    concurrency: int = JUDGE_CONCURRENCY,
) -> RelevanceVerdict:
    """Ham gönderi metinlerini partiler halinde hakeme sor. Partiler
    eşzamanlı (``concurrency``) koşar; denetim satırları sonra sırayla
    yazılır. Hatalı parti fail-open: gönderiler tutulur, ``failed_batches``
    artar. Anahtar yoksa ``NoCredentialsError`` yükselir — çağıran
    (route) bunu "AI kontrolü atlandı" olarak raporlar."""
    if not tweets:
        return RelevanceVerdict(relevant=[], batches=0, failed_batches=0)
    tenant = await session.get(Tenant, tenant_id)
    keyed = await _load_keyed_provider(session, tenant_id, provider)

    batches = [tweets[i : i + batch_size] for i in range(0, len(tweets), batch_size)]
    prompts = [
        render_judge_prompt(
            brand=brand,
            brand_summary=brand_summary,
            include=include,
            exclude=exclude,
            handle=handle,
            tenant=tenant,
            tweets=batch,
            start_index=i * batch_size + 1,
        )
        for i, batch in enumerate(batches)
    ]
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _run(prompt: str) -> _CallOutcome:
        async with semaphore:
            return await _call_structured(
                keyed,
                system_prompt=JUDGE_SYSTEM_PROMPT,
                user_prompt=prompt,
                response_schema=JUDGE_RESPONSE_SCHEMA,
                temperature=0.0,
                max_output_tokens=2048,
            )

    outcomes = await asyncio.gather(*(_run(p) for p in prompts))

    relevant: list[bool] = []
    failed = 0
    for i, (batch, outcome, prompt) in enumerate(zip(batches, outcomes, prompts, strict=True)):
        await _record_audit(
            session,
            keyed,
            outcome,
            tenant_id=tenant_id,
            call_type=CALL_TYPE_TWITTER_RELEVANCE,
            prompt=prompt,
            actor_user_id=actor_user_id,
        )
        if outcome.response is None:
            failed += 1
            _logger.warning(
                "twitter relevance batch %d failed (%s): %s",
                i + 1,
                outcome.error_type,
                outcome.error_message,
            )
        relevant.extend(
            parse_judge_response(outcome.response, start_index=i * batch_size + 1, size=len(batch))
        )
    dropped = sum(1 for ok in relevant if not ok)
    return RelevanceVerdict(
        relevant=relevant, batches=len(batches), failed_batches=failed, dropped=dropped
    )
