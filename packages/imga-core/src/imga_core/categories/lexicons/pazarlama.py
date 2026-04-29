"""Keywords for the 'Pazarlama / İletişim' category.

Covers: ad accuracy, campaigns, coupons, spam comms, subscription
deception, KVKK / consent issues. Stripped of bare 'aldatıcı' / 'yanıltıcı'
which were too generic — phrase forms ('yanıltıcı reklam', 'yanıltıcı bilgi')
are kept.
"""

from __future__ import annotations

PAZARLAMA_KEYWORDS: frozenset[str] = frozenset({
    # Ads
    "reklam",
    "reklamda",
    "reklamı yanlış",
    "yanıltıcı reklam",
    "yalan reklam",
    "yanıltıcı bilgi",
    "tanıtımda farklı",
    "reklamda göründüğü gibi değil",
    # Promised vs delivered
    "vaad edilen",
    "söz verildi",
    "kandırıldım",
    "aldatıldım",
    # Campaigns / discounts
    "kampanya",
    "kampanya hilesi",
    "kampanya geçerli değil",
    "sahte kampanya",
    "indirim",
    "indirim kodu çalışmadı",
    "kupon",
    "kupon geçersiz",
    "promosyon",
    # Influencer ads
    "instagram reklamı",
    "tiktok reklamı",
    "youtuber önerdi",
    "influencer",
    "influencer önerdi",
    # Spam / consent
    "sms spam",
    "sürekli sms",
    "mail spam",
    "bültenden çıkamıyorum",
    "üyelik iptali",
    "abonelik iptali",
    "otomatik yenilendi",
    "abone yaptılar",
    "izinsiz abonelik",
    "email izni vermedim",
    "kvkk",
})
