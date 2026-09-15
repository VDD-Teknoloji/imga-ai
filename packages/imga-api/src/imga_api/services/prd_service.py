"""A revisable interview, not a claim that a universal 16-section PRD exists."""

from __future__ import annotations

from imga_api.services.intelligence_schemas import PrdDocument, PrdSection

PRD_STARTER: tuple[tuple[str, str, str], ...] = (
    (
        "problem",
        "Problem ve kanıt",
        "Kimin hangi sorununu çözüyoruz? Son müşteri görüşmesinden bir kanıt nedir?",
    ),
    (
        "vision",
        "Vizyon ve stratejik uyum",
        "Bu ürün şirketin hangi hedefine hizmet ediyor; neden şimdi?",
    ),
    (
        "personas",
        "Kullanıcılar ve karar vericiler",
        "Kullanan, satın alan ve onaylayan roller kimler?",
    ),
    (
        "markets",
        "Pazar, ülke ve dil",
        "Suudi Arabistan ve Dubai için hangi sektörler, lehçeler ve kanallar kapsamda?",
    ),
    (
        "outcomes",
        "Başarı ölçütleri",
        "Başlangıç değeri, hedef, ölçüm kaynağı ve hedef tarih nedir?",
    ),
    (
        "scope",
        "Kapsam ve kapsam dışı",
        "İlk sürüm neyi yapacak; hangi talepler bilinçli olarak kapsam dışında?",
    ),
    (
        "journeys",
        "Kullanıcı yolculukları",
        "Bir yönetici veri girişinden karar ve takibe kadar hangi adımları izliyor?",
    ),
    (
        "requirements",
        "Fonksiyonel gereksinimler",
        "Gereksinimleri kullanıcı rolü, davranış ve hata durumlarıyla tanımlar mısınız?",
    ),
    (
        "data",
        "Veri ve entegrasyonlar",
        "Müşteri kimliği, olay zamanı ve izinleri hangi sistemlerden alacağız?",
    ),
    (
        "ai",
        "Yapay zeka ve doğrulama",
        "Arapça, Urduca ve Roman Urdu analizini hangi bağımsız etiketli veriyle sınayacağız?",
    ),
    (
        "organization",
        "Organizasyon ve süreçler",
        "Süreç sorumluları, devir noktaları, SLA hedefleri ve eskalasyon yolu nedir?",
    ),
    (
        "retention",
        "Müşteri kaybı ve müdahale",
        "Bu iş modelinde kayıp ne demek; gözlem penceresi ve müdahale sorumlusu kim?",
    ),
    (
        "security",
        "Gizlilik ve yetkiler",
        "Hangi veri hangi ülkede işlenebilir, kim erişebilir ve ne zaman silinir?",
    ),
    ("quality", "Kalite ve işletim", "Gecikme, maliyet, erişilebilirlik ve hata bütçeleri nedir?"),
    (
        "delivery",
        "Yayın ve kabul planı",
        "Pilot, kabul kapıları, geri dönüş planı ve bağımlılıklar nelerdir?",
    ),
    (
        "decisions",
        "Riskler ve açık kararlar",
        "Hangi varsayımlar doğrulanmadı; karar sahibi ve son tarih nedir?",
    ),
)


def starter_document() -> PrdDocument:
    return PrdDocument(
        sections=[
            PrdSection(id=key, title=title, question=question)
            for key, title, question in PRD_STARTER
        ]
    )


def interview(document: PrdDocument) -> dict[str, object]:
    questions: list[dict[str, str]] = []
    confirmed = 0
    excluded = 0
    answered = 0
    for section in document.sections:
        if section.status == "not_applicable":
            excluded += 1
            continue
        if section.answer:
            answered += 1
        if section.status == "confirmed":
            confirmed += 1
            continue
        fields = (
            ("answer", section.question),
            (
                "evidence",
                f"'{section.title}' için bu kararı destekleyen ölçüm, görüşme veya belge nedir?",
            ),
            (
                "acceptance",
                f"'{section.title}' tamamlandığında bunu hangi test veya ölçümle kabul edeceğiz?",
            ),
            ("owner", f"'{section.title}' kararını kim doğrulayacak?"),
        )
        for field, question in fields:
            if not getattr(section, field):
                questions.append({"section_id": section.id, "field": field, "question": question})
                break
        else:
            questions.append(
                {
                    "section_id": section.id,
                    "field": "status",
                    "question": f"'{section.title}' yanıtını, kanıtını ve kabul ölçütünü doğruladınız mı?",
                }
            )
    applicable = len(document.sections) - excluded
    return {
        "questions": questions,
        "confirmed": confirmed,
        "answered": answered,
        "excluded": excluded,
        "total": len(document.sections),
        "maturity_percent": round(100 * confirmed / applicable) if applicable else 0,
        "ready_for_approval": applicable > 0 and confirmed == applicable,
        "template": "imga-starter-v1",
        "is_industry_standard": False,
    }


def export_markdown(document: PrdDocument, revision: int) -> str:
    lines = [f"# {document.title}", "", f"Sürüm: {revision}", ""]
    for i, section in enumerate(document.sections, 1):
        lines.extend(
            [
                f"## {i}. {section.title}",
                "",
                f"Durum: {section.status} | Sorumlu: {section.owner or 'Belirlenmedi'}",
                "",
                section.answer or "Henüz yanıtlanmadı.",
                "",
                "### Kanıt",
                "",
                section.evidence or "Eksik",
                "",
                "### Kabul ölçütü",
                "",
                section.acceptance or "Eksik",
                "",
                "### Açık soru",
                "",
                section.question,
                "",
            ]
        )
    return "\n".join(lines)
