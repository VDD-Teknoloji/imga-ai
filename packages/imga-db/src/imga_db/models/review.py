"""Review model — analyzed-text archive + auto-ticket bridge log.

Sprint 7.5.5 / Alt-Faz 3. Every call to ``POST /tenants/me/analyze``
writes one row here. The row captures the analyzer output AND the
bridge decision (``create`` or one of the four ``skipped_*`` reasons),
so the historical record explains *why* a complaint did or didn't
become a ticket.

The ``text_hash`` column is a sha256 hex over
``normalize_turkish(text).strip()`` (see ``imga_core.text_utils``).
Identical user submissions collapse to identical hashes; a 24-hour
window on this hash drives the dedup branch.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base
from imga_db.models.mixins import SoftDeleteMixin, TimestampMixin


class ReviewDecision(StrEnum):
    """Outcome of the bridge for a single analyzed review.

    Order = evaluation precedence in ReviewService:

      1. ``skipped_belirsiz`` — primary category is "belirsiz" (unknown);
         no mode auto-creates from this.
      2. ``skipped_mode``     — tenant is in MANUAL automation_mode.
      3. ``skipped_threshold``— SEMI_AUTO confidence/sentiment under
         the threshold, or FULL_AUTO sentiment >= 0.
      4. ``skipped_dedup``    — same text_hash already produced a
         ticket within the last 24h; this row points at that ticket.
      5. ``create``           — all guards passed; new ticket minted.

    ``SKIPPED_QUALITY`` (migration 0042, 2026-08-18) is a newer branch
    for content-quality skips — an empty-text row now gets WRITTEN
    (quality_flag='empty') instead of being dropped, and never reaches
    the ticket bridge. Its exact precedence slot in ReviewService's
    evaluation order is wired in the write path (Dalga 2 scope); this
    enum member and the widened ``ck_reviews_decision`` CHECK only
    make the value legal at the DB layer.
    """

    CREATE = "create"
    SKIPPED_BELIRSIZ = "skipped_belirsiz"
    SKIPPED_MODE = "skipped_mode"
    SKIPPED_THRESHOLD = "skipped_threshold"
    SKIPPED_DEDUP = "skipped_dedup"
    SKIPPED_QUALITY = "skipped_quality"


class Review(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "reviews"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    text: Mapped[str] = mapped_column(Text(), nullable=False)
    # sha256 hex over normalize_turkish(text).strip(). Fixed CHAR(64);
    # the DB CHECK constraint enforces length so a malformed value never
    # lands.
    text_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    sentiment_label: Mapped[str] = mapped_column(String(8), nullable=False)
    sentiment_score: Mapped[float] = mapped_column(Float(), nullable=False)
    primary_category: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_confidence: Mapped[float] = mapped_column(Float(), nullable=False)

    # Snapshot of automation_mode at decision time. Tenant config can
    # flip between calls; this preserves the value that produced the
    # decision below, so audits stay self-explanatory.
    automation_mode: Mapped[str] = mapped_column(String(16), nullable=False)

    decision: Mapped[ReviewDecision] = mapped_column(String(32), nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)

    # Set on `create` (newly minted ticket) AND `skipped_dedup` (pointer
    # to the existing ticket). Other branches leave NULL.
    ticket_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="SET NULL"),
        nullable=True,
    )
    submitted_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Sprint 8.3.1 batch upload back-reference. NULL for /tenants/me/analyze
    # rows; populated for rows the batch worker writes. ``ix_reviews_batch``
    # is a partial index so the dominant non-batch case stays cheap.
    batch_job_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("analyze_batch_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Yorumun kendi tarihi — yükleme dosyasındaki ``tarih`` kolonundan
    # gelir, kolon yoksa/parse edilemezse ingest anına düşer. Analitik
    # pencereleri ve trend bucket'ları bunu kullanır: 3 aylık arşivi tek
    # seferde yükleyen kurum gerçek ay-ay dağılımı görsün. ``analyzed_at``
    # / ``created_at`` "ne zaman bize girdi" anlamını korur.
    review_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Sprint 8.3.4. Pipeline override trace — list of OverrideHit dicts
    # (layer, matched_keywords, score, detail). NULL on rows analyzed
    # before migration 0014; [] when the pipeline ran and nothing fired.
    overrides_applied: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSONB(), nullable=True
    )

    # Sprint 8.3.5. NPS score (0–10), populated when the upload had an
    # NPS column or the manual /analyze caller passed one. NULL is the
    # "not captured" value; check constraint ck_reviews_nps_score_range
    # enforces the 0..10 bound at the DB layer.
    nps_score: Mapped[int | None] = mapped_column(SmallInteger(), nullable=True)

    # Postgres GENERATED ALWAYS STORED — derived from nps_score per the
    # standard NPS bucketing. App must never write this column; the
    # Computed(persisted=True) annotation tells SQLAlchemy to omit it
    # from inserts/updates and just read it back.
    nps_category: Mapped[str | None] = mapped_column(
        String(16),
        Computed(
            "CASE "
            "WHEN nps_score IS NULL THEN NULL "
            "WHEN nps_score <= 6 THEN 'detractor' "
            "WHEN nps_score <= 8 THEN 'passive' "
            "ELSE 'promoter' END",
            persisted=True,
        ),
        nullable=True,
    )

    # Sprint 8.3.5.6. The heuristic reranker's ``CategoryTaxonomy.code``
    # match at analyze time. Plain VARCHAR (no FK) — taxonomy is
    # editable per tenant in 8.3.7, and we don't want a delete to break
    # historical reviews; if the code stops existing, the UI renders
    # the raw code or a "removed category" badge.
    company_perspective_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 2026-08-10 — temas noktası türü ("dijital" | "operasyonel").
    # LLM'in yorum başına verdiği karar; kategoriden TÜRETİLMEZ
    # ("uygulamada kargo statüsü yanlış" → kategori kargo, deneyim
    # dijital). NULL = birleşik yol koşmamış eski satır ya da model
    # geçerli değer üretmemiş; okuma tarafı NULL'ı kategori
    # eşlemesine düşürür. CHECK ck_reviews_experience_type (0041)
    # iki değerden başkasını kabul etmez.
    experience_type: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Sprint 9.3 B — business impact dimensions. All four nullable
    # so existing reviews stay valid; populated at upload time via
    # the tenant's ``tenant_business_dimensions.csv_column_mapping``
    # if configured. Free-text by default; the dimension config row's
    # ``allowed_values`` lets a tenant lock a dimension to an enum
    # for UI cleanliness without a schema migration.
    business_segment: Mapped[str | None] = mapped_column(Text(), nullable=True)
    product_line: Mapped[str | None] = mapped_column(Text(), nullable=True)
    channel: Mapped[str | None] = mapped_column(Text(), nullable=True)
    customer_tier: Mapped[str | None] = mapped_column(Text(), nullable=True)

    # 2026-08-18 (migration 0042) — 5. business dimension: yorumu kuruma
    # giren çalışanın adı, yükleme dosyasından okunur (smart-parser
    # EmployeeNameDetector öneri amaçlı). ck_tenant_business_dimensions_key
    # 'entered_by' değerini de kabul eder. Kalite raporundaki çalışan
    # bazlı kırılımın anahtarı.
    entered_by: Mapped[str | None] = mapped_column(Text(), nullable=True)

    # 2026-08-18 (migration 0042) — şablondaki 'kaynak' kolonu bugüne
    # kadar parse edilip düşürülüyordu; artık kalıcı.
    source: Mapped[str | None] = mapped_column(Text(), nullable=True)

    # 2026-08-26 (migration 0047) — yorumun kaynağındaki kalıcı bağlantı
    # (tweet URL'si, pazar yeri yorum linki). Yükleme dosyasındaki
    # ``bağlantı``/``url`` kolonundan (file_parser otomatik tanır) gelir;
    # arşiv kartı ve detay "Tweeti aç / Kaynağı aç" ile buna gider.
    # NULL = kaynakta bağlantı yok (manuel analiz, şablon yüklemeleri).
    source_url: Mapped[str | None] = mapped_column(Text(), nullable=True)

    # 2026-08-18 (migration 0042) — düşük kaliteli veri işareti. NULL =
    # geçerli satır. 'duplicate' eski satırlar için decision=
    # 'skipped_dedup'tan deterministik backfill edildi; empty/
    # informational/meaningless yalnızca yazım-anında ÇALIŞAN deterministik
    # heuristikten (``imga_api.services.data_quality.classify_data_quality``)
    # gelir — geriye dönük türetilemez. (Bir LLM prompt "q" alanı 2026-08-18
    # "büyük paket" WS2'de denendi ve gold4 kapısında belirsiz oranını
    # kötüleştirdiği ölçüldüğü için TERS ALINDI; saf Python heuristiğine
    # geçildi.) Analitik/rapor/heatmap include_flagged filtresi VARSAYILAN
    # HARİÇ tutar. CHECK ck_reviews_quality_flag bu dört değerden
    # başkasını kabul etmez.
    quality_flag: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # 2026-09-01 (migration 0049) — metnin YAPISAL biçimi ('question' |
    # NULL). Deterministik Türkçe heuristik
    # (``imga_api.services.data_quality.detect_content_type``) yazar,
    # LLM'e hiç dokunmaz. ``quality_flag`` DEĞİLDİR — ORTOGONAL bir
    # boyut: bir NEGATİF şikayetin soru biçiminde yazılması ("Kargom
    # nerede, ilgilenir misiniz?") hâlâ 'question' sayılır VE analitikte
    # kalır; content_type'ı quality_flag'e katmak böyle bir satırı
    # include_flagged=False filtresiyle sessizce gömerdi. Bilinçli olarak
    # genişletilebilir enum (experience_type/0041 deseniyle aynı desen);
    # CHECK ck_reviews_content_type bugün tek değeri kabul eder.
    content_type: Mapped[str | None] = mapped_column(Text(), nullable=True)

    # 2026-09-01 (migration 0049) — açık uçlu kaynak-özel metadata.
    # İlk tüketici: tweet etkileşim sayaçları (like_count/retweet_count/
    # reply_count/view_count — file_parser'ın otomatik tanıdığı CSV
    # kolonlarından ya da twitterapi.io'dan gelir). Şema sabit değil;
    # ileride başka kaynak türleri farklı anahtarlarla aynı kolona yazar.
    source_meta: Mapped[dict[str, object] | None] = mapped_column(JSONB(), nullable=True)
