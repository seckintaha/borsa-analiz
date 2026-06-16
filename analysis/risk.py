"""
Risk yönetimi (Aşama 9).

İlke (yol haritası): hayatta kalmayı belirleyen şey hisse seçimi değil risk
yönetimidir. Bu modül "ne kadar ve ne riskle" sorusunu yanıtlar.

Saf hesap mantığı; canlı veri gerektirmez.
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


def pozisyon_buyuklugu(sermaye: float, fiyat: float, pozisyon_pct: float) -> dict:
    """Sermayenin belirli yuzdesiyle kac adet alinir."""
    tahsis = sermaye * pozisyon_pct
    adet = int(tahsis // fiyat) if fiyat > 0 else 0
    return {"tahsis_tutar": round(tahsis, 2), "adet": adet,
            "gercek_tutar": round(adet * fiyat, 2)}


def yogunlasma_kontrol(pozisyon_degerleri: dict[str, float], uyari_pct: float) -> list[str]:
    """Tek hisse portfoyun belirli oranini geciyorsa uyari uretir."""
    toplam = sum(pozisyon_degerleri.values())
    uyarilar = []
    if toplam <= 0:
        return uyarilar
    for sym, deger in pozisyon_degerleri.items():
        oran = deger / toplam
        if oran > uyari_pct:
            uyarilar.append(f"{sym} portföyün %{oran*100:.0f}'i — yoğunlaşma riski "
                            f"(eşik %{uyari_pct*100:.0f})")
    return uyarilar


def stop_loss_kontrol(pozisyonlar: dict, fiyatlar: dict, stop_pct: float) -> list[str]:
    """
    pozisyonlar: {symbol: {"alis_fiyat": x}}; fiyatlar: {symbol: guncel}.
    Zarar stop esigini gectiyse uyarir.
    """
    uyarilar = []
    for sym, p in pozisyonlar.items():
        guncel = fiyatlar.get(sym)
        alis = p.get("alis_fiyat")
        if guncel is None or not alis:
            continue
        getiri = (guncel - alis) / alis
        if getiri <= stop_pct:
            uyarilar.append(f"{sym} %{getiri*100:.1f} zararda — stop-loss seviyesi "
                            f"(%{stop_pct*100:.0f}) aşıldı")
    return uyarilar


def korelasyon_matrisi(fiyat_df: pd.DataFrame) -> pd.DataFrame:
    """
    fiyat_df: kolonlari semboller, satirlari tarih olan Close tablosu.
    Gunluk getiriler uzerinden korelasyon. Yuksek korelasyon = cesitlendirme yok.
    """
    getiriler = fiyat_df.pct_change().dropna()
    return getiriler.corr().round(2)


def portfoy_max_dusus(deger_serisi: pd.Series) -> float:
    """Portfoy deger serisinin maksimum dususu (drawdown), yuzde."""
    s = pd.Series(deger_serisi).astype(float)
    zirve = s.cummax()
    dusus = (s - zirve) / zirve
    return round(float(dusus.min() * 100), 2)


# ── Portföy Zayıflık Analizi (Özellik #3) ─────────────────────────────────────

# Kaba sektör eşlemesi (BIST kodları). Bilinmeyen → "Diğer".
_SEKTOR = {
    "GARAN": "Bankacılık", "AKBNK": "Bankacılık", "YKBNK": "Bankacılık",
    "ISCTR": "Bankacılık", "HALKB": "Bankacılık", "VAKBN": "Bankacılık",
    "TSKB": "Bankacılık", "SKBNK": "Bankacılık", "ALBRK": "Bankacılık",
    "THYAO": "Ulaşım", "PGSUS": "Ulaşım", "TAVHL": "Ulaşım", "CLEBI": "Ulaşım",
    "EREGL": "Demir-Çelik", "KRDMD": "Demir-Çelik", "ISDMR": "Demir-Çelik",
    "TUPRS": "Enerji", "PETKM": "Enerji", "AKSEN": "Enerji", "ZOREN": "Enerji",
    "ENJSA": "Enerji", "AYGAZ": "Enerji", "ODAS": "Enerji",
    "ASELS": "Savunma/Tek", "OTKAR": "Savunma/Tek", "TTKOM": "Telekom",
    "TCELL": "Telekom", "LOGO": "Teknoloji", "ARCLK": "Sanayi", "VESTL": "Sanayi",
    "TOASO": "Otomotiv", "FROTO": "Otomotiv", "TTRAK": "Otomotiv",
    "BIMAS": "Perakende", "MGROS": "Perakende", "SOKM": "Perakende", "ULKER": "Gıda",
    "CCOLA": "Gıda", "AEFES": "Gıda", "TATGD": "Gıda",
    "KCHOL": "Holding", "SAHOL": "Holding", "DOHOL": "Holding", "ALARK": "Holding",
    "SISE": "Cam/Kimya", "SASA": "Cam/Kimya", "HEKTS": "Kimya", "GUBRF": "Kimya",
    "EKGYO": "GYO", "ISGYO": "GYO", "TRGYO": "GYO", "DZGYO": "GYO", "PSGYO": "GYO",
    "DGGYO": "GYO", "SNGYO": "GYO", "NUGYO": "GYO", "OZKGY": "GYO",
}


def _sektor(kod: str) -> str:
    return _SEKTOR.get(kod.replace(".IS", "").upper(), "Diğer")


def portfoy_zayiflik(dagilim: dict[str, float], fiyat_df: pd.DataFrame | None = None,
                     yuksek_korelasyon: float = 0.7) -> dict:
    """
    Portföyün gizli risklerini çıkarır.
    dagilim: {kod: yuzde}  (örn. {"GARAN": 40, "AKBNK": 30, "THYAO": 30})
    fiyat_df: kolonlari kod olan Close tablosu (korelasyon için; yoksa atlanır).

    Döner: {yogunlasma, sektor_dagilim, sektor_uyari, korelasyon_ciftleri,
            birlikte_dusme_uyari, oneriler, hedge}
    """
    toplam = sum(dagilim.values()) or 1
    normal = {k: v / toplam * 100 for k, v in dagilim.items()}

    # ── Tek hisse yoğunlaşması ──
    yogunlasma = []
    for kod, pct in sorted(normal.items(), key=lambda x: -x[1]):
        if pct >= 25:
            yogunlasma.append(f"{kod}: portföyün %{pct:.0f}'i — tek hisse yoğunlaşma riski")

    # ── Sektör yoğunlaşması ──
    sektor_dagilim: dict[str, float] = {}
    for kod, pct in normal.items():
        s = _sektor(kod)
        sektor_dagilim[s] = sektor_dagilim.get(s, 0) + pct
    sektor_uyari = []
    for s, pct in sorted(sektor_dagilim.items(), key=lambda x: -x[1]):
        if pct >= 40 and s != "Diğer":
            sektor_uyari.append(f"{s} sektörü portföyün %{pct:.0f}'i — sektör yoğunlaşması "
                                "(sektörel şokta hep birlikte düşersin)")

    # ── Korelasyon / birlikte düşme ──
    korelasyon_ciftleri = []
    birlikte_dusme_uyari = []
    if fiyat_df is not None and fiyat_df.shape[1] >= 2:
        try:
            corr = korelasyon_matrisi(fiyat_df)
            kodlar = list(corr.columns)
            for i in range(len(kodlar)):
                for j in range(i + 1, len(kodlar)):
                    c = corr.iloc[i, j]
                    if pd.notna(c) and c >= yuksek_korelasyon:
                        korelasyon_ciftleri.append((kodlar[i], kodlar[j], round(float(c), 2)))
            if korelasyon_ciftleri:
                en_yuksek = sorted(korelasyon_ciftleri, key=lambda x: -x[2])[:3]
                for a, b, c in en_yuksek:
                    birlikte_dusme_uyari.append(
                        f"{a} ↔ {b}: korelasyon {c} — neredeyse birlikte hareket ederler, "
                        "ikisi de aynı anda düşer (çeşitlendirme yanılsaması)")
        except Exception:
            pass

    # ── Öneriler ──
    oneriler = []
    if yogunlasma:
        oneriler.append("Tek hisse ağırlığını %25 altına çek; en büyük pozisyonu kısmen sat.")
    if sektor_uyari:
        oneriler.append("Farklı sektör ekle (örn. ağırlık bankacılıksa savunma/gıda/teknoloji).")
    if korelasyon_ciftleri:
        oneriler.append("Yüksek korelasyonlu çiftlerden birini, düşük korelasyonlu bir "
                        "varlıkla değiştir — gerçek çeşitlendirme sağla.")
    if not oneriler:
        oneriler.append("Dağılım makul görünüyor; yine de düzenli olarak gözden geçir.")
    oneriler.append("Nakit/likit bir tampon tut (%10-20) — düşüşte fırsat ve güvenlik sağlar.")

    # ── Hedge stratejileri ──
    hedge = [
        "Endeks short/ters ETF: büyük düşüş beklentisinde XU100'e karşı korunma "
        "(BIST'te ters ETF sınırlı; nakde geçiş çoğu zaman en pratik hedge).",
        "Nakit oranını artırmak: en basit ve maliyetsiz hedge — riskini doğrudan azaltır.",
        "Altın/döviz: TL bazlı portföyde sistemik şoka karşı kısmi tampon (GLD, gram altın).",
        "Pozisyon küçültme: ralli sonrası kâr realize edip ağırlığı düşürmek de bir hedge'dir.",
    ]

    return {
        "normal_dagilim": {k: round(v, 1) for k, v in normal.items()},
        "yogunlasma": yogunlasma,
        "sektor_dagilim": {k: round(v, 1) for k, v in sektor_dagilim.items()},
        "sektor_uyari": sektor_uyari,
        "korelasyon_ciftleri": korelasyon_ciftleri,
        "birlikte_dusme_uyari": birlikte_dusme_uyari,
        "oneriler": oneriler,
        "hedge": hedge,
    }


def portfoy_zayiflik_metni(rapor: dict) -> str:
    """portfoy_zayiflik çıktısını Telegram/panel metnine çevirir."""
    sat = ["⚠️ PORTFÖY ZAYIFLIK ANALİZİ", ""]

    sat.append("📊 Dağılım:")
    for k, v in sorted(rapor["normal_dagilim"].items(), key=lambda x: -x[1]):
        sat.append(f"   {k}: %{v}")

    if rapor["yogunlasma"]:
        sat += ["", "🔴 Tek hisse yoğunlaşma:"]
        for y in rapor["yogunlasma"]:
            sat.append(f"   • {y}")

    if rapor["sektor_uyari"]:
        sat += ["", "🟠 Sektör yoğunlaşma:"]
        for s in rapor["sektor_uyari"]:
            sat.append(f"   • {s}")

    if rapor["birlikte_dusme_uyari"]:
        sat += ["", "🔗 Gizli korelasyon (birlikte düşme) riski:"]
        for b in rapor["birlikte_dusme_uyari"]:
            sat.append(f"   • {b}")

    sat += ["", "✅ Riski azaltma önerileri:"]
    for o in rapor["oneriler"]:
        sat.append(f"   • {o}")

    sat += ["", "🛡️ Hedge (düşüşe karşı korunma) stratejileri:"]
    for h in rapor["hedge"]:
        sat.append(f"   • {h}")

    sat += ["", "⚠️ Analiz geçmiş fiyat/dağılıma dayanır; yatırım tavsiyesi değildir."]
    return "\n".join(sat)
