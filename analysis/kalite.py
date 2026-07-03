"""
Kalite Skoru — finansal sağlamlık + değer tuzağı filtresi.

"Ucuz" yetmez; ucuz + SAĞLAM olmalı. Bu modül gerçek temel verilerle
(ROE, ROIC, marj, borç, likidite, büyüme) 0-100 kalite skoru üretir ve
"değer tuzağı" (ucuz ama bozulan) hisseleri işaretler.

Tüm metrikler gerçektir (TradingView). Veri eksik bileşen skora katılmaz.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from data.tv_scanner import tv_kalite_tara, TVKalite


@dataclass
class KaliteSonuc:
    sembol: str
    skor: int                 # 0-100
    etiket: str               # "Yüksek kalite" / "Orta" / "Zayıf"
    deger_tuzagi: bool        # ucuz ama temel bozuk mu
    gerekceler: list = field(default_factory=list)   # (+/-) maddeler
    metrikler: dict = field(default_factory=dict)


# Banka/finans/sigorta sektörleri doğal olarak yüksek borç/özkaynak ve düşük
# cari orana sahiptir (iş modeli gereği). Bu metrikleri onlara uygulamak haksız
# cezadır; bu sektörlerde borç ve cari oran bileşenleri atlanır.
_FINANS_SEKTORLERI = (
    "finance", "financial", "bank", "insurance", "banka", "sigorta",
    "finans", "holding", "leasing", "factoring", "gayrimenkul yatırım",
    "real estate investment", "reit",
)


def _finans_sektoru_mu(sektor: Optional[str]) -> bool:
    if not sektor:
        return False
    s = sektor.lower()
    return any(anahtar in s for anahtar in _FINANS_SEKTORLERI)


def kalite_skoru(k: TVKalite) -> KaliteSonuc:
    """Tek bir hissenin kalite skorunu hesaplar."""
    puan = 0.0
    agirlik = 0.0   # toplanan max puan (veri olan bileşenler)
    g = []
    finans = _finans_sektoru_mu(k.sektor)

    def ekle(kosul_puan, max_puan, art_mesaj, eks_mesaj, kosul_iyi):
        nonlocal puan, agirlik
        agirlik += max_puan
        puan += kosul_puan
        g.append(("✅ " if kosul_iyi else "⚠️ ") + (art_mesaj if kosul_iyi else eks_mesaj))

    # Kârlılık — ROE
    if k.roe is not None:
        if k.roe >= 20:
            ekle(20, 20, f"ROE %{k.roe:.0f} (güçlü kârlılık)", "", True)
        elif k.roe >= 10:
            ekle(12, 20, f"ROE %{k.roe:.0f} (makul)", "", True)
        else:
            ekle(3, 20, "", f"ROE %{k.roe:.0f} (zayıf kârlılık)", False)

    # ROIC (sermaye verimliliği)
    if k.roic is not None:
        if k.roic >= 12:
            ekle(12, 12, f"ROIC %{k.roic:.0f} (sermayeyi iyi kullanıyor)", "", True)
        elif k.roic >= 6:
            ekle(7, 12, f"ROIC %{k.roic:.0f}", "", True)
        else:
            ekle(2, 12, "", f"ROIC %{k.roic:.0f} (düşük sermaye verimi)", False)

    # Net marj
    if k.net_marj is not None:
        if k.net_marj >= 15:
            ekle(12, 12, f"net marj %{k.net_marj:.0f} (yüksek)", "", True)
        elif k.net_marj > 0:
            ekle(7, 12, f"net marj %{k.net_marj:.0f}", "", True)
        else:
            ekle(0, 12, "", f"net marj %{k.net_marj:.0f} (zarar ediyor!)", False)

    # Serbest nakit akışı marjı (kâr gerçek nakde dönüyor mu)
    if k.fcf_marj is not None:
        if k.fcf_marj > 5:
            ekle(10, 10, f"FCF marj %{k.fcf_marj:.0f} (kâr nakde dönüyor)", "", True)
        elif k.fcf_marj > 0:
            ekle(6, 10, f"FCF marj %{k.fcf_marj:.0f}", "", True)
        else:
            ekle(1, 10, "", f"FCF marj %{k.fcf_marj:.0f} (nakit üretmiyor)", False)

    # Borç/özkaynak (kaldıraç riski) — banka/finans/sigorta iş modeli gereği doğal
    # olarak yüksek kaldıraçlıdır; bu sektörlerde bileşen atlanır (haksız ceza yok).
    if k.borc_ozkaynak is not None and not finans:
        if k.borc_ozkaynak < 1:
            ekle(15, 15, f"borç/özkaynak {k.borc_ozkaynak:.2f} (düşük borç)", "", True)
        elif k.borc_ozkaynak < 2:
            ekle(9, 15, f"borç/özkaynak {k.borc_ozkaynak:.2f}", "", True)
        else:
            ekle(2, 15, "", f"borç/özkaynak {k.borc_ozkaynak:.2f} (yüksek kaldıraç)", False)
    elif finans and k.borc_ozkaynak is not None:
        g.append("ℹ️ Finans sektörü: yüksek kaldıraç normaldir, borç bileşeni atlandı.")

    # Likidite — cari oran (finans sektörü için anlamsız, atlanır)
    if k.cari_oran is not None and not finans:
        if k.cari_oran >= 1.5:
            ekle(8, 8, f"cari oran {k.cari_oran:.2f} (sağlam likidite)", "", True)
        elif k.cari_oran >= 1:
            ekle(5, 8, f"cari oran {k.cari_oran:.2f}", "", True)
        else:
            ekle(2, 8, "", f"cari oran {k.cari_oran:.2f} (kısa vade baskı)", False)

    # Büyüme — gelir
    if k.gelir_buyume is not None:
        if k.gelir_buyume >= 20:
            ekle(13, 13, f"gelir büyümesi %{k.gelir_buyume:.0f} (hızlı)", "", True)
        elif k.gelir_buyume > 0:
            ekle(8, 13, f"gelir büyümesi %{k.gelir_buyume:.0f}", "", True)
        else:
            ekle(2, 13, "", f"gelir küçülüyor %{k.gelir_buyume:.0f}", False)

    # Büyüme — net kâr (değer tuzağı için kritik)
    if k.net_kar_buyume is not None:
        if k.net_kar_buyume >= 15:
            ekle(10, 10, f"net kâr büyümesi %{k.net_kar_buyume:.0f}", "", True)
        elif k.net_kar_buyume > -10:
            ekle(5, 10, f"net kâr büyümesi %{k.net_kar_buyume:.0f}", "", True)
        else:
            ekle(0, 10, "", f"net kâr ÇÖKÜYOR %{k.net_kar_buyume:.0f}", False)

    if agirlik == 0:
        return KaliteSonuc(k.sembol.replace(".IS", ""), 0, "veri yok", False,
                           ["Yeterli temel veri yok"], {})

    skor = int(round(puan / agirlik * 100))
    etiket = "Yüksek kalite" if skor >= 70 else ("Orta kalite" if skor >= 45 else "Zayıf")

    # Değer tuzağı: ucuz (düşük F/K veya PD/DD) AMA temel bozuk (skor düşük ya da
    # net kâr çöküyor / yüksek borç)
    ucuz = (k.fk is not None and 0 < k.fk < 8) or (k.pddd is not None and k.pddd < 0.8)
    bozuk = (skor < 45 or
             (k.net_kar_buyume is not None and k.net_kar_buyume < -20) or
             # Yüksek borç sinyali sadece finans-dışı sektörler için geçerli.
             (not finans and k.borc_ozkaynak is not None and k.borc_ozkaynak > 3))
    deger_tuzagi = bool(ucuz and bozuk)
    if deger_tuzagi:
        g.insert(0, "🪤 DEĞER TUZAĞI RİSKİ: ucuz görünüyor ama temeller zayıf/bozuluyor")

    return KaliteSonuc(
        sembol=k.sembol.replace(".IS", ""), skor=skor, etiket=etiket,
        deger_tuzagi=deger_tuzagi, gerekceler=g,
        metrikler={"fk": k.fk, "roe": k.roe, "roic": k.roic, "net_marj": k.net_marj,
                   "borc_ozkaynak": k.borc_ozkaynak, "net_kar_buyume": k.net_kar_buyume},
    )


def kalite_tek(sembol: str) -> str:
    """/kalite SEMBOL — tek hissenin finansal sağlamlık raporu."""
    kod = sembol.replace(".IS", "").upper()
    ok, hata, liste = tv_kalite_tara(tickers=[f"BIST:{kod}"])
    if not ok or not liste:
        return f"❌ {kod} için kalite verisi yok: {hata}"
    s = kalite_skoru(liste[0])

    bar = "█" * (s.skor // 10) + "░" * (10 - s.skor // 10)
    sat = [
        f"🏅 {s.sembol} — KALİTE SKORU: {s.skor}/100 ({s.etiket})",
        f"   [{bar}]",
        "",
    ]
    if s.deger_tuzagi:
        sat.append("🪤 DİKKAT: DEĞER TUZAĞI RİSKİ — ucuz ama temeller zayıf.")
        sat.append("")
    sat.append("📋 Değerlendirme:")
    for x in s.gerekceler:
        if not x.startswith("🪤"):
            sat.append(f"   {x}")
    sat += ["", "⚠️ Gerçek temel verilere dayanır; yatırım tavsiyesi değildir."]
    return "\n".join(sat)
