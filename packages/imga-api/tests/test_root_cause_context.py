"""Kök neden — kurum bağlamı + uzman notu birim testleri (TASK B2).

Saf fonksiyonlar, DB/Redis gerekmez — CI'nin ``api-test`` container'ında
koşar ama lokalde de doğrudan ``pytest tests/test_root_cause_context.py``
ile, Postgres/Redis olmadan çalışır (bkz. test_llm_pricing.py deseni).

Kapsam:
  * render_root_cause_user_prompt — KURUM BAĞLAMI bloğu (Sektör/
    Büyüklük/İş tanımı) yalnız dolu alanlar için basılır, üçü de boşsa
    blok hiç yazılmaz (bkz. root_cause_v1.py'deki ``{% if %}`` deseni).
  * playbook_directive — bilinmeyen kategori kodu için "", bilinen kod
    için UZMAN NOTU bloğu.
  * _validate_and_normalise — expert_note geçerliyse persist edilir,
    yer tutucuysa ("...") anahtar hiç yazılmaz (mevcut headline/
    action_short testleriyle aynı desen — bkz. test_root_cause_overview.py).
"""

from __future__ import annotations

from imga_api.llm.prompts.root_cause_v1 import render_root_cause_user_prompt
from imga_api.services.root_cause_service import _validate_and_normalise
from imga_api.services.strategic_constants import playbook_directive

_BASE_CTX = {
    "primary_category_label": "Kargo",
    "perspective_label": "Statü hatası",
    "date_from": None,
    "date_to": None,
    "bucket_total": 50,
    "bucket_negative": 40,
    "sample_count": 1,
    "reviews": [{"text": "örnek yorum", "sentiment": "negative"}],
    "industry_label": None,
    "company_size_label": None,
    "business_description": None,
}


# --- render_root_cause_user_prompt: KURUM BAĞLAMI ------------------------


def test_user_prompt_omits_kurum_baglami_when_context_absent() -> None:
    """Kurum profili hiç doldurulmamışsa (üçü de None) blok tamamen
    yok — eski davranışla birebir aynı çıktı (regresyon değil)."""
    out = render_root_cause_user_prompt(_BASE_CTX)
    assert "KURUM BAĞLAMI" not in out
    # ANALİZ DÖNEMİ ile KOVA İSTATİSTİĞİ arasında tek boş satır kalmalı.
    assert "Tüm zaman\n\nKOVA İSTATİSTİĞİ:" in out


def test_user_prompt_includes_kurum_baglami_lines_when_present() -> None:
    ctx = dict(
        _BASE_CTX,
        industry_label="Lojistik-kargo",
        company_size_label="Küçük (2-10)",
        business_description="Ev tekstili üreten bir e-ticaret markası.",
    )
    out = render_root_cause_user_prompt(ctx)
    assert "KURUM BAĞLAMI:" in out
    assert "- Sektör: Lojistik-kargo" in out
    assert "- Büyüklük: Küçük (2-10)" in out
    assert "- İş tanımı: Ev tekstili üreten bir e-ticaret markası." in out
    # Blok, ANALİZ DÖNEMİ'nden sonra ve KOVA İSTATİSTİĞİ'nden önce.
    assert out.index("ANALİZ DÖNEMİ") < out.index("KURUM BAĞLAMI") < out.index("KOVA İSTATİSTİĞİ")


def test_user_prompt_includes_only_present_kurum_baglami_fields() -> None:
    """Yalnız iş tanımı doldurulmuşsa Sektör/Büyüklük satırları hiç
    basılmaz — model olmayan bir alanı "belirsiz" ile doldurmaz."""
    ctx = dict(_BASE_CTX, business_description="Ev tekstili markası.")
    out = render_root_cause_user_prompt(ctx)
    assert "KURUM BAĞLAMI:" in out
    assert "- İş tanımı: Ev tekstili markası." in out
    assert "Sektör" not in out
    assert "Büyüklük" not in out


# --- playbook_directive ---------------------------------------------------


def test_playbook_directive_empty_for_unknown_code() -> None:
    assert playbook_directive("bilinmeyen_kategori") == ""
    # "belirsiz" kasıtlı olarak sözlükte yok (bkz. strategic_constants
    # docstring'i) — taksonomik çöp kutusuna CX pratiği oturmaz.
    assert playbook_directive("belirsiz") == ""


def test_playbook_directive_contains_uzman_notu_for_known_code() -> None:
    out = playbook_directive("kargo")
    assert "UZMAN NOTU (kurucu CX pratiği)" in out
    assert "expert_note" in out
    assert out.startswith("\n\n")


# --- _validate_and_normalise: expert_note ----------------------------------


def _payload_with_expert_note(expert_note: object) -> dict[str, object]:
    return {
        "summary": "Bu kovadaki yorumların çoğu kargo gecikmesiyle ilgili.",
        "root_causes": [
            {
                "title": "Kargo takip statüsü güncellenmiyor",
                "description": "Sistem teslim edilmiş gösteriyor ama müşteri paketi almadı.",
                "evidence_quotes": ["paket hala gelmedi ama teslim edildi yazıyor"],
                "affected_surface": "kargo takip ekranı",
                "suggested_action": "Takip statüsü gecikmelerini gözden geçirmek faydalı olabilir.",
                "share_estimate_pct": 60,
                "expert_note": expert_note,
            }
        ],
    }


def test_validate_and_normalise_keeps_valid_expert_note() -> None:
    payload = _payload_with_expert_note(
        "Kanal başına ilk yanıt SLA'sını ayrı ölçmek bu gecikmeyi erken yakalardı."
    )
    out = _validate_and_normalise(payload)
    assert (
        out["root_causes"][0]["expert_note"]
        == "Kanal başına ilk yanıt SLA'sını ayrı ölçmek bu gecikmeyi erken yakalardı."
    )


def test_validate_and_normalise_drops_placeholder_expert_note() -> None:
    payload = _payload_with_expert_note("...")
    out = _validate_and_normalise(payload)
    assert "expert_note" not in out["root_causes"][0]


def test_validate_and_normalise_drops_missing_expert_note() -> None:
    """Model uzman notu vermediyse (alan hiç yok) anahtar eklenmez —
    None ile doldurmuyoruz, routes/tenant_insights.py yokluğu
    ``"expert_note" in cause`` ile ayırt eder."""
    base = _payload_with_expert_note("placeholder")
    del base["root_causes"][0]["expert_note"]
    out = _validate_and_normalise(base)
    assert "expert_note" not in out["root_causes"][0]


def test_validate_and_normalise_trims_long_expert_note() -> None:
    long_note = "Ç" * 250
    payload = _payload_with_expert_note(long_note)
    out = _validate_and_normalise(payload)
    assert len(out["root_causes"][0]["expert_note"]) <= 201  # 200 + "…"
    assert out["root_causes"][0]["expert_note"].endswith("…")
