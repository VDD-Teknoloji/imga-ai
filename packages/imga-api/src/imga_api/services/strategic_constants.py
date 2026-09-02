"""Sprint 8.3.6 — strategic-report shared constants.

Industry + company-size enum-to-Türkçe-label maps. Used by the SWOT/OKR
prompt renderer and (Sprint 8.3.6.6) the /settings/profile dropdowns.
The migration 0019 ``tenants.industry`` column stores the enum *code*;
the human label only ever surfaces in prompt text + UI.

The "other" branch is deliberately a sentinel value: when ``industry =
"other"``, ``industry_other_text`` carries the user-typed label and the
prompt renderer prefers it over the generic "Diğer" rendering.

2026-09-02 (TASK B2) — ``_CATEGORY_PLAYBOOK`` / ``playbook_directive``:
kök neden analizine giren kategori-bazlı "kurucu CX pratiği" notları.
Bu dosyada yaşıyor çünkü ``language_directive``/``terminology_directive``
ile aynı "system prompt'un sonuna eklenen dil-üstü katman" ailesinin
üyesi — root_cause_service dördünü de aynı yerde birleştiriyor.
"""

from __future__ import annotations

from typing import Any, Final

INDUSTRY_LABELS: Final[dict[str, str]] = {
    "e_commerce": "E-ticaret",
    "retail": "Perakende",
    "telecom": "Telekomünikasyon",
    "banking": "Bankacılık",
    "insurance": "Sigortacılık",
    "services": "Hizmet sektörü",
    "healthcare": "Sağlık",
    "education": "Eğitim",
    "manufacturing": "Üretim",
    "food_beverage": "Yiyecek-içecek",
    "logistics": "Lojistik-kargo",
    "other": "Diğer",
}

COMPANY_SIZE_LABELS: Final[dict[str, str]] = {
    "solo": "Tek kişi (1)",
    "small": "Küçük (2-10)",
    "medium": "Orta (11-50)",
    "large": "Büyük (51-250)",
    "enterprise": "Kurumsal (251+)",
}


def industry_label(code: str | None, other_text: str | None = None) -> str:
    """Resolve an industry enum code to its Türkçe label.

    Order of precedence:
      1. ``code is None`` → ``"belirsiz"`` (tenant hasn't filled out
         /settings/profile yet — prompt should still render).
      2. ``code == "other"`` AND ``other_text`` is non-empty → return
         the user-typed label verbatim. This is the whole point of
         the sentinel branch.
      3. Known code → mapped label.
      4. Unknown code → return the code itself so an enum drift
         shows up in prompt text instead of silently being mapped to
         ``"Diğer"``.
    """
    if code is None:
        return "belirsiz"
    if code == "other" and other_text:
        return other_text
    return INDUSTRY_LABELS.get(code, code)


def company_size_label(code: str | None) -> str:
    if code is None:
        return "belirsiz"
    return COMPANY_SIZE_LABELS.get(code, code)


def language_directive(language: str | None) -> str:
    """AI çıktı dili yönergesi — system prompt'un SONUNA eklenir (Sprint 12 i18n).

    Kurum dili 'en' ise güçlü bir "yalnız İngilizce" talimatı döndürür; 'tr' veya
    None ise boş (promptlar zaten Türkçe). System prompt'un içeriğini yeniden
    yazmadan, dil-üstü bir katman olarak çalışır — DB-override promptlar dahil."""
    if language == "en":
        return (
            "\n\nIMPORTANT — OUTPUT LANGUAGE: Respond ONLY in English. Every "
            "narrative field, title, summary, analysis, recommendation and label "
            "in your output MUST be written in fluent, professional English, "
            "regardless of the language of the input data or these instructions."
        )
    return ""


#: 2026-09-02 (TASK B2) — kurucu CX pratiği: her global kategori kodu için
#: (bkz. ``imga_core.categories.taxonomy.DEFAULT_GLOBAL_CATEGORIES``) 2-3
#: cümlelik, gerçek saha bilgisi. Kök neden analizindeki ``expert_note``
#: alanının kaynağı — model bu pratiği kanıta uygulayıp TEK cümleye indirger
#: (bkz. ``playbook_directive``). "belirsiz" kasıtlı olarak yok: o kova
#: taksonomik bir çöp kutusu, üzerine oturacak somut bir CX pratiği yok.
_CATEGORY_PLAYBOOK: dict[str, str] = {
    "kargo": (
        "Proaktif durum bildirimi, reaktif destekten her zaman daha ucuz ve "
        "daha etkilidir: müşteri gecikmeyi kargo firmasını arayarak değil "
        "bir bildirimle öğrenmeli. Kanal başına ilk yanıt SLA'sını (canlı "
        "destek, e-posta, sosyal medya) ayrı ayrı ölçün — ortalama SLA tek "
        "başına yavaş kanalı gizler."
    ),
    "faturalama": (
        "Ücret şikâyetlerinin çoğu tutarın büyüklüğünden değil, ANLAŞILMAZ "
        "olmasından doğar: fatura kalemleri müşterinin önceden gördüğü "
        "tutarla birebir eşleşmeli, farklıysa fark en üstte gerekçeli "
        "gösterilmeli. İade edilen paranın hesaba düşme süresi, algılanan "
        "adaleti tutarın kendisinden daha çok belirler — rakip fiyat "
        "çapası değil, gecikme süresi asıl güven kırıcı."
    ),
    "urun_kalitesi": (
        "Tekil şikâyeti değil KÜMEYİ izleyin: aynı hata SKU/parti/tedarikçi "
        "bazında kümeleniyorsa kalite kontrolde değil üretim/tedarik "
        "zincirinde bir sorun var demektir. Kümelenme tespit edildiğinde "
        "hatanın kaynağına (tek parti mi, sürekli mi) göre iade mi geri "
        "çağırma mı gerektiğine erken karar verin."
    ),
    "musteri_hizmetleri": (
        "Tekrar-temas oranı (repeat-contact rate) memnuniyet anketinden "
        "daha güvenilir bir öncü göstergedir: aynı müşteri aynı konu için "
        "ikinci kez yazıyorsa ilk temasta çözülmemiş demektir. İlk-temas "
        "çözüm oranını (first-contact resolution) ekip performans metriği "
        "yapın, yanıt hızını değil çözüm kalitesini ödüllendirin."
    ),
    "iade": (
        "İade edilen paranın müşteriye ULAŞMA süresi, tek başına en güçlü "
        "yeniden-satın-alma sürücüsüdür — onay hızından çok bu süre "
        "belirleyicidir. Süreç adımlarını (talep → onay → kargo → iade) "
        "ayrı ayrı ölçün; darboğaz genelde onay ile kargoya veriliş "
        "arasındaki bekleme, tek bir 'iade süresi' ortalaması bunu gizler."
    ),
    "teknik_destek": (
        "Hata mesajları müşteriye ne yapması gerektiğini söylemiyorsa "
        "destek yükü kaçınılmaz artar — hata metnini teknik log değil "
        "yönlendirici bir cümle yapın. Kendi kendine çözülen (self-service) "
        "oranı izleyin: aynı hata tekrar tekrar bilet açtırıyorsa arayüzde "
        "düzeltilmesi gereken asıl sorun odur, destek ekibi değil."
    ),
    "siparis_sureci": (
        "Sipariş akışındaki her ekstra adım terk oranını artırır — "
        "şikâyetin kaynağı çoğu zaman tek bir doğrulama/form adımıdır, "
        "akışın tamamı değil. Hatalı/eksik sipariş kayıtlarını gerçek "
        "zamanlı doğrulama ile en başta yakalamak, sonradan düzeltmekten "
        "hem müşteri hem operasyon için çok daha ucuzdur."
    ),
    "pazarlama": (
        "Bildirim yorgunluğu (mesaj sıklığı, kanal, zamanlama şikâyeti) "
        "genelde içerikten değil frekans kontrolünün eksikliğinden "
        "kaynaklanır — kanal ve sıklık tercihini müşteriye bırakan bir "
        "opt-in/opt-out ayrımı bu şikâyetlerin çoğunu önler. Kampanya "
        "mesajı ile işlemsel bildirim (sipariş/teslimat) aynı kanaldan "
        "gidiyorsa müşteri ikisini ayırt edemez ve güveni sarsılır."
    ),
}


def playbook_directive(primary_category_code: str) -> str:
    """Kategoriye özgü kurucu CX pratiğini system prompt'a ekler.

    Bilinmeyen (ya da kasıtlı boş bırakılan, örn. "belirsiz") kod için ""
    döner — prompt'a hiçbir şey eklenmez. Bilinen kod için modele TEK bir
    ``expert_note`` cümlesi üretmesini, bu pratiği eldeki kanıta
    uygulayarak yazmasını (ya da uymuyorsa alanı boş bırakmasını) söyler
    — ``language_directive``/``terminology_directive`` ile aynı desen:
    dil-üstü bir katman, sona eklenir."""
    playbook = _CATEGORY_PLAYBOOK.get(primary_category_code)
    if not playbook:
        return ""
    return (
        "\n\nUZMAN NOTU (kurucu CX pratiği):\n"
        f"{playbook}\n"
        "Her kök neden için expert_note alanına, bu pratiği eldeki "
        "kanıta uygulayan TEK bir cümle yaz (en fazla ~200 karakter). "
        "Pratik bu kök nedene uymuyorsa expert_note alanını HİÇ YAZMA — "
        "zorlama, uydurma bağlantı kurma."
    )


def terminology_directive(terminology: list[dict[str, Any]] | None) -> str:
    """Kurum terim sözlüğü yönergesi — system prompt'un SONUNA eklenir
    (2026-08-18, migration 0042 ``tenants.terminology``).

    ``language_directive`` deseniyle birebir aynı: dil-üstü bir katman,
    prompt içeriğini yeniden yazmadan sona eklenir (DB-override
    promptlar dahil). Sözlük boş/None ise boş döner — mevcut kurumlar
    (henüz sözlük doldurmamış) davranışı hiç değişmez.

    ``terminology`` şekli: ``[{"term": str, "note": str}, ...]``
    (``TenantCreateRequest.terminology`` ile aynı — bkz.
    routes/admin/tenants.py). Boş ``term`` girdileri atlanır; ``note``
    opsiyonel.

    JSONB kolonu şemasız — bu fonksiyon dört stratejik servisin
    (SWOT/OKR/brifing/root-cause) ortak yolunda çalışır, o yüzden
    beklenmeyen bir eleman şekli (dict olmayan girdi) burada 500'e
    değil sessiz atlamaya düşmeli."""
    if not terminology:
        return ""
    lines: list[str] = []
    for entry in terminology:
        if not isinstance(entry, dict):
            continue
        term = str(entry.get("term") or "").strip()
        if not term:
            continue
        note = str(entry.get("note") or "").strip()
        lines.append(f"- {term} — {note}" if note else f"- {term}")
    if not lines:
        return ""
    return (
        "\n\nTERİM SÖZLÜĞÜ (bu terimleri AYNEN kullan, eş anlamlısıyla "
        "değiştirme):\n" + "\n".join(lines)
    )
