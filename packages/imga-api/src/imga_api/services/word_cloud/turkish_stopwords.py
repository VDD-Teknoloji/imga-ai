"""Türkçe stop-word list for the word cloud tokenizer.

Sprint 8.3.9. Hard-coded ~200-word frozenset. Sourced from the
public NLTK Türkçe stopword corpus + manual additions:

  * Enclitic forms ("de", "da", "ki", "mi", "mı", "mu") which the
    naive whitespace tokenizer leaves as separate tokens.
  * Common verb stems that surface as standalone words after
    inflection drop ("etmek", "etti", "olur", "var", "yok").
  * Generic intensifiers / fillers ("çok", "biraz", "şey").
  * Survey-specific noise ("yorum", "merhaba", "teşekkür") that
    dominate every customer-feedback word cloud without conveying
    signal.

The list is intentionally aggressive on the noise side; a tenant
who wants to surface "teşekkür" specifically can override at the
UI / SQL level later (Sprint 9.x roadmap, custom-stopword tab).
"""

from __future__ import annotations

from typing import Final

TURKISH_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        # NLTK Türkçe corpus core — pronouns + auxiliaries.
        "acaba", "altı", "ama", "ancak", "arada", "artık", "aslında",
        "az", "bana", "bazen", "bazı", "bazıları", "bazısı", "belki",
        "ben", "benden", "beni", "benim", "beri", "beş", "bile", "bilhassa",
        "bin", "bir", "biraz", "birçoğu", "birçok", "biri", "birisi",
        "birkaç", "birkez", "birşey", "biz", "bizden", "bize", "bizi",
        "bizim", "bu", "buna", "bunda", "bundan", "bunlar", "bunları",
        "bunların", "bunu", "bunun", "burada", "böyle", "böylece",
        "büyük", "çoğu", "çoğuna", "çoğunu", "çok", "çünkü",
        "da", "daha", "de", "defa", "değil", "diğer", "diğeri",
        "diğerleri", "diye", "doksan", "dokuz", "dolayı", "dolayısıyla",
        "dört", "edecek", "eden", "ederek", "edilecek", "ediliyor",
        "edilmesi", "ediyor", "elli", "en", "etmesi", "etti", "ettiği",
        "ettiğini", "fakat", "gibi", "göre", "halen", "hangi", "hangisi",
        "hani", "hatta", "hem", "henüz", "hep", "hepsi", "her", "herhangi",
        "herkes", "herkese", "herkesi", "herkesin", "hiç", "hiçbir",
        "için", "iki", "ile", "ilgili", "ise", "işte", "itibaren",
        "itibariyle", "kaç", "kadar", "karşı", "kendi", "kendilerine",
        "kendine", "kendini", "kendisi", "kendisine", "kendisini",
        "kez", "ki", "kim", "kimden", "kime", "kimi", "kimin", "kimisi",
        "kırk", "milyar", "milyon", "mu", "mü", "mı", "mi", "nasıl",
        "ne", "neden", "nedenle", "nerde", "nerede", "nereye", "niçin",
        "niye", "o", "olan", "olarak", "oldu", "olduğu", "olduğunu",
        "olduklarını", "olmadı", "olmadığı", "olmak", "olması", "olmayan",
        "olmaz", "olsa", "olsun", "olup", "olur", "olursa", "oluyor",
        "on", "ona", "ondan", "onlar", "onlardan", "onları", "onların",
        "onu", "onun", "orada", "öbür", "önce", "ön", "öyle", "rağmen",
        "sana", "sanki", "sayın", "sekiz", "seksen", "sen", "senden",
        "seni", "senin", "siz", "sizden", "size", "sizi", "sizin",
        "son", "sonra", "tabii", "tam", "tamam", "tamamen", "tarafından",
        "trilyon", "tüm", "üç", "üzere", "var", "vardı", "ve", "veya",
        "ya", "yani", "yapacak", "yapılan", "yapılması", "yapıyor",
        "yapmak", "yaptı", "yaptığı", "yaptığını", "yaptıkları", "yedi",
        "yerine", "yetmiş", "yine", "yirmi", "yoksa", "yok", "yüz",
        "zaten", "zira",
        # Manual additions — survey/feedback noise.
        "merhaba", "selam", "teşekkür", "teşekkürler", "lütfen",
        "yorum", "iyi", "kötü", "güzel", "şey", "şeyler", "evet", "hayır", "tabi", "hala",
    }
)


__all__ = ["TURKISH_STOPWORDS"]
