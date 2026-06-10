"""Sprint 11.0 — review_corrections + pgvector

Revision ID: 0031
Revises: 0030
Create Date: 2026-06-10 00:00:00

Düzeltme-geri-besleme altyapısının veri katmanı. Eski sistemin
"Train & Save"i düzeltmeleri lokal bir CSV'ye yazıp birebir metin
eşleşmesiyle override ediyordu (model hiç eğitilmiyordu). Yeni
mekanizma üç katman ve hepsi bu tablodan beslenir:

  1. Birebir override — ``text_hash`` (normalize SHA-256, reviews
     ile aynı üretim) eşleşen yeni yorumlar düzeltilmiş kararı alır.
  2. Few-shot besleme — tenant'ın güncel düzeltmeleri Gemini batch
     sınıflandırma prompt'una örnek olarak girer; LLM düzeltme
     DESENİNİ benzer yorumlara genelleştirir.
  3. RAG — ``embedding`` (pgvector, 768 boyut: gemini-embedding-001
     output_dimensionality=768) ile anlamsal komşu düzeltmeler
     bulunur; cosine benzerliği yüksek olanlar few-shot'a öncelikli
     girer. Embedding best-effort'tur: API erişilemezse NULL kalır,
     katman 1-2 çalışmaya devam eder (NULL satırlar vector
     sorgusunda zaten elenmiş olur).

Tasarım kararları:

  * ``review_text`` denormalize tutulur — review soft-delete olsa da
    düzeltme örneği few-shot'ta yaşamaya devam eder; ayrıca few-shot
    derlemek için reviews JOIN'i gerekmez.
  * Aynı text_hash birden çok kez düzeltilebilir (fikir değişikliği);
    okuma tarafı ORDER BY created_at DESC LIMIT 1 ile son kararı
    alır. UNIQUE yok.
  * Vector index HNSW (cosine) — tablo küçükken de zararsız, büyürken
    sorgu planı hazır. pgvector >= 0.5 'trusted' olduğundan CREATE
    EXTENSION owner rolüyle çalışır (superuser gerekmez); compose
    imajları pgvector/pgvector:pgXX'e geçirildi.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

EMBEDDING_DIM = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "review_corrections",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "review_id",
            UUID(as_uuid=True),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text_hash", sa.CHAR(64), nullable=False),
        sa.Column("review_text", sa.Text(), nullable=False),
        sa.Column("old_sentiment_label", sa.String(8), nullable=False),
        sa.Column("new_sentiment_label", sa.String(8), nullable=False),
        sa.Column("old_category", sa.String(64), nullable=False),
        sa.Column("new_category", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "corrected_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Birebir override sorgusu: (tenant, hash) -> son düzeltme.
    op.create_index(
        "ix_review_corrections_tenant_hash",
        "review_corrections",
        ["tenant_id", "text_hash"],
    )
    # Few-shot "son N düzeltme" taraması.
    op.create_index(
        "ix_review_corrections_tenant_created",
        "review_corrections",
        ["tenant_id", "created_at"],
    )
    # RAG komşu araması — cosine HNSW. NULL embedding'ler indekste
    # yer almaz; backfill edilmemiş satırlar sorguyu etkilemez.
    op.execute(
        """
        CREATE INDEX ix_review_corrections_embedding
            ON review_corrections
            USING hnsw (embedding vector_cosine_ops)
        """
    )

    op.execute("ALTER TABLE review_corrections ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE review_corrections FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON review_corrections
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON review_corrections")
    op.drop_table("review_corrections")
    # Extension bilinçli bırakılır — başka tablolar kullanıyor
    # olabilir; idempotent upgrade zaten IF NOT EXISTS.
