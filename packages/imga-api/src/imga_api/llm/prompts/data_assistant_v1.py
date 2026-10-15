"""Veri asistanı istemi (v1, 2026-10-15).

Model yalnız ``evidence`` içindeki rakamları yorumlar; sayı üretmez,
alıntı uydurmaz. Kanıt paketi SQL'den gelir (bkz.
``services/data_assistant_service.py``), model o paketi Türkçe (ya da
kurum rapor dilinde) kısa bir yanıta çevirir. Çıktı JSON şema ile
zorlanır ki arayüz "öne çıkanlar" ve "veri boşlukları"nı ayrı çizebilsin.
"""

from __future__ import annotations

import json
from typing import Any

DATA_ASSISTANT_SYSTEM_PROMPT = """Sen İmga'nın veri asistanısın: bir kurumun müşteri yorumu analizleri üzerinde çalışan, rakamlara sadık bir analistsin.

KURALLAR
- YALNIZ verilen kanıt paketindeki sayılara, oranlara ve alıntılara dayan. Pakette olmayan hiçbir sayı, yüzde, müşteri adı ya da alıntı üretme.
- Kanıt yetersizse ("insufficient" / küçük örneklem) bunu açıkça söyle; kesin neden iddia etme, "veriye göre en olası" de.
- Soru "neden" soruyorsa: önce ne değişti (sayı + yüzde), sonra hangi alt konular/aşamalar/kanallar arttı, sonra alıntılarla örnekle, en sonda yapılacak 1-2 somut adım.
- Kısa yaz: en fazla 6 cümle ya da 5 madde. Alıntıya referans verirken [#n] numarasını kullan.
- Dönemleri okurken: "current" sorulan dönem, "previous" ondan hemen önceki eşit uzunluktaki dönemdir.
- Yorumları yazanların kimliği bilinmez; isim ya da kişisel veri üretme.

ÇIKTI: Yalnızca JSON; alanlar: answer (metin), highlights (en çok 4 kısa madde), follow_ups (kullanıcının sorabileceği en çok 3 soru), data_gaps (yanıtı sınırlayan veri eksikleri, yoksa boş liste).
"""

DATA_ASSISTANT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "highlights": {"type": "array", "items": {"type": "string"}},
        "follow_ups": {"type": "array", "items": {"type": "string"}},
        "data_gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "highlights", "follow_ups", "data_gaps"],
}


def render_data_assistant_user_prompt(ctx: dict[str, Any]) -> str:
    history = ctx.get("history") or []
    lines: list[str] = []
    if history:
        lines.append("ÖNCEKİ KONUŞMA (en yeni en altta):")
        for turn in history:
            role = "Kullanıcı" if turn.get("role") == "user" else "Asistan"
            lines.append(f"- {role}: {str(turn.get('content', ''))[:600]}")
        lines.append("")
    lines.append(f"SORU: {ctx['question']}")
    lines.append("")
    lines.append("KAPSAM: " + json.dumps(ctx["scope"], ensure_ascii=False))
    lines.append("")
    lines.append("KANIT PAKETİ (JSON):")
    lines.append(json.dumps(ctx["evidence"], ensure_ascii=False, default=str))
    return "\n".join(lines)
