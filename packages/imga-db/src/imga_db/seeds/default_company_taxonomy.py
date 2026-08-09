"""Default 21-row company-perspective taxonomy.

Sprint 8.3.5. Verbatim port of cx_sentiment_dashboard's
``get_company_perspective`` heuristic (app.py:646-740). ``code`` is a
snake_case ASCII rendering of the Türkçe label; ``priority`` mirrors
the legacy if-elif order so ties resolve identically. Categories #9
and #10 from the original numbering are intentionally absent —
the legacy code itself dropped them with a "Deleted separate 9 and 10"
comment.

A duplicate-but-not-identical copy of this list lives in alembic
migration 0017 for the data-backfill INSERT — the migration runs in a
SQL-only context and shouldn't import from the app code path. Keep
both copies in sync if either is edited (Sprint 8.3.7's edit UI works
off the table, so this static seed is only the platform default).

Sprint 13.1 adds ``primary_category_code`` — the main-category link
that powers the drill-down. Migration 0040 backfills the same code
per ``code`` for every already-existing tenant row; 0017 stays frozen
(applied migrations are immutable).
"""

from __future__ import annotations

from typing import Final, TypedDict


class TaxonomyEntry(TypedDict):
    code: str
    label_tr: str
    keywords: list[str]
    priority: int
    # Sprint 13.1 — bu alt kategorinin bağlı olduğu ana kategori kodu
    # (imga_core.categories GLOBAL_CATEGORY_CODES). Migration 0040
    # aynı eşlemeyi mevcut TÜM kurumların satırlarına backfill eder;
    # ikisi birlikte değişmeli.
    primary_category_code: str


DEFAULT_COMPANY_TAXONOMY: Final[list[TaxonomyEntry]] = [
    {
        "code": "shipment_not_arrived",
        "label_tr": "Kargom ulaşmadı",
        "keywords": [
            "kargom nerede", "gelmedi", "teslim edilmedi",
            "ulaşmadı", "gecikti", "teslimat sorunu",
            # Sprint 8.3.6.1 tense varyantları (Bug 2 patch).
            "gelmiyor", "ulaşamıyorum", "ulaşamadı", "ulaşmıyor",
        ],
        "priority": 1,
        "primary_category_code": "kargo",
    },
    {
        "code": "broken_damaged",
        "label_tr": "Deforme-Kırık Ürün",
        "keywords": [
            "kırık", "deforme", "ezik", "hasarlı",
            "parçalanmış", "yırtık ürün", "defolu", "ayıplı",
            # Sprint 8.3.6.1 tense varyantları.
            "kırılmış", "deforme olmuş",
        ],
        "priority": 2,
        "primary_category_code": "urun_kalitesi",
    },
    {
        "code": "poor_packaging",
        "label_tr": "Özensiz Paketleme",
        "keywords": ["paket", "özensiz", "yırtık paket", "kutu ezik", "ambalaj"],
        "priority": 3,
        "primary_category_code": "kargo",
    },
    {
        "code": "wrong_or_missing_item",
        "label_tr": "Yanlış-Eksik Ürün",
        "keywords": [
            "yanlış ürün", "farklı ürün", "eksik ürün",
            "sipariş ettiğimden farklı", "başka ürün",
        ],
        "priority": 4,
        "primary_category_code": "siparis_sureci",
    },
    {
        "code": "incomplete_set",
        "label_tr": "Ürünümde takım eksik geldi",
        "keywords": ["takım", "parça eksik", "altı yok", "üstü yok", "seti bozuk"],
        "priority": 5,
        "primary_category_code": "siparis_sureci",
    },
    {
        "code": "product_quality_material",
        "label_tr": "Ürün kalite - Ana Malzeme",
        "keywords": [
            "kumaş", "pamuklanma", "tüylenme", "çekme", "solma",
            "kalite", "dikiş", "yırtılma", "ince", "naylon",
        ],
        "priority": 6,
        "primary_category_code": "urun_kalitesi",
    },
    {
        "code": "refund_not_received",
        "label_tr": "İade Ücretim Hesaba Geçmedi",
        "keywords": [
            "ücret iadesi", "param yatmadı", "hesap",
            "geri ödeme", "tutar iadesi", "bakiye",
            # Sprint 8.3.6.1 tense varyantları.
            "param yatmıyor", "iade gelmedi henüz",
        ],
        "priority": 7,
        "primary_category_code": "iade",
    },
    {
        "code": "campaign_issues",
        "label_tr": "Kampanya Sorunları",
        "keywords": [
            "çark", "çevir", "indirim çarkı", "hediye çarkı", "kazanıyorum",
            "puan", "money", "kazanç", "kupon", "indirim kodu",
        ],
        "priority": 8,
        "primary_category_code": "pazarlama",
    },
    # 9, 10 deliberately skipped (legacy "Deleted separate 9 and 10").
    {
        "code": "ebebek_money_transfer",
        "label_tr": "E-bebek Para Aktarımı olmadı",
        "keywords": ["ebebek para", "lcw para", "cüzdan", "aktarım", "yükleme"],
        "priority": 11,
        "primary_category_code": "faturalama",
    },
    {
        "code": "order_status_wrong",
        "label_tr": "Siparişimin statüsü doğru değil",
        "keywords": [
            "statü", "kargoya verildi yazıyor", "hazırlanıyor", "hala", "durum",
        ],
        "priority": 12,
        "primary_category_code": "siparis_sureci",
    },
    {
        "code": "cancel_request",
        "label_tr": "Sipariş iptal talebi",
        "keywords": [
            "iptal etmek istiyorum", "yanlışlıkla verdim",
            "vazgeçtim", "siparişi iptal",
            # Sprint 8.3.6.1 tense varyantları.
            "iptal istiyorum", "iptal edebilir miyim",
        ],
        "priority": 13,
        "primary_category_code": "siparis_sureci",
    },
    {
        "code": "address_change",
        "label_tr": "Teslimat adresini değiştirebilir miyim?",
        "keywords": [
            "adres değişikliği", "yanlış adres", "kargo adresi", "adresi değiştir",
            # Sprint 8.3.6.1 tense varyantları.
            "adresimi değiştirebilir miyim", "yanlış adres yazdım",
        ],
        "priority": 14,
        "primary_category_code": "kargo",
    },
    {
        "code": "store_return_for_online",
        "label_tr": "İnternetten aldığım ürünü mağazadan iade etmek istiyorum",
        "keywords": [
            "mağazadan iade", "şubeden iade", "internetten aldım mağazaya",
        ],
        "priority": 15,
        "primary_category_code": "iade",
    },
    {
        "code": "return_status_inquiry",
        "label_tr": "İnternet satış iadem nerede/sonucu ne oldu",
        "keywords": [
            "iadem ne durumda", "iade sonucu", "inceleniyor", "iade işlemleri",
        ],
        "priority": 16,
        "primary_category_code": "iade",
    },
    {
        "code": "how_to_return",
        "label_tr": "İade nasıl yapılır",
        "keywords": [
            "iade kodu", "nasıl iade ederim", "iade işlemi", "iade etmek istiyorum",
            # Sprint 8.3.6.1 tense varyantları.
            "nasıl iade edeceğim", "iade prosedürü",
        ],
        "priority": 17,
        "primary_category_code": "iade",
    },
    {
        "code": "return_period_exceeded",
        "label_tr": "İade Süresi Aşımı",
        "keywords": [
            "iade süresi", "14 gün", "30 gün", "zamanı geçti", "süre doldu",
        ],
        "priority": 18,
        "primary_category_code": "iade",
    },
    {
        "code": "account_membership",
        "label_tr": "Üyelik ve Hesap Yönetimi",
        "keywords": [
            "üyelik", "giriş yapamıyorum", "şifre", "hesap",
            "güncelleme", "sms", "kod", "login",
        ],
        "priority": 19,
        "primary_category_code": "teknik_destek",
    },
    {
        "code": "invoice_request",
        "label_tr": "Fatura Talebi",
        "keywords": ["fatura", "e-fatura", "kurumsal fatura", "fatura gelmedi"],
        "priority": 20,
        "primary_category_code": "faturalama",
    },
    {
        "code": "store_issues",
        "label_tr": "Mağaza Sorunları",
        "keywords": [
            "mağaza", "personel", "çalışan", "kabin", "kasa",
            "sıra", "reyon", "etiket fiyatı", "güvenlik",
        ],
        "priority": 21,
        "primary_category_code": "musteri_hizmetleri",
    },
    {
        "code": "payment_and_campaign_issues",
        "label_tr": "Ödeme ve Kampanya Sorunları",
        "keywords": ["ödeme", "kredi kartı", "çekim", "taksit", "provizyon"],
        "priority": 22,
        "primary_category_code": "faturalama",
    },
    {
        "code": "general_other",
        "label_tr": "Genel ve Diğer Sorunlar",
        # Legacy fallback had no keywords — empty list keeps the row
        # in the UI but never wins on the heuristic match.
        "keywords": [],
        "priority": 999,
        "primary_category_code": "musteri_hizmetleri",
    },
]
