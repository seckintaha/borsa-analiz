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
