"""
Tarihsel temel oranlar & mevsimsellik (Aşama 5).

İlke (yol haritası): "kesin artar" denmez. Geçmişte benzer durumların sonraki
N gündeki dağılımı; her zaman **örnek sayısı (n) ve aralıkla** sunulur. Az örnek
varsa bu açıkça belirtilir (veri madenciliği tuzağına düşmemek için).

Canlı veri gerektirmez; verilen geçmiş df üzerinde çalışır.
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class OlayDagilim:
    ufuk_gun: int
    n: int                      # ornek sayisi
    medyan_pct: float | None
    ortalama_pct: float | None
    min_pct: float | None
    max_pct: float | None
    pozitif_orani: float | None # ileri getirinin pozitif oldugu vaka orani
    guvenilir: bool             # n yeterli mi
    not_: str = ""


def olay_calismasi(df: pd.DataFrame, esik_pct: float, ileri_gun: list[int],
                   min_ornek: int = 10) -> dict[int, OlayDagilim]:
    """
    Gunluk degisimin esik_pct'i astigi gunleri bulur; her ileri ufuk icin
    sonraki getirilerin dagilimini cikarir.
    """
    close = df["Close"].astype(float).reset_index(drop=True)
    gunluk = close.pct_change() * 100
    olay_idx = gunluk[gunluk >= esik_pct].index.tolist()

    out: dict[int, OlayDagilim] = {}
    for ufuk in ileri_gun:
        getiriler = []
        for i in olay_idx:
            hedef = i + ufuk
            if hedef < len(close):
                getiriler.append((close.iloc[hedef] - close.iloc[i]) / close.iloc[i] * 100)
        n = len(getiriler)
        if n == 0:
            out[ufuk] = OlayDagilim(ufuk, 0, None, None, None, None, None,
                                    guvenilir=False, not_="hiç örnek yok")
            continue
        arr = np.array(getiriler)
        out[ufuk] = OlayDagilim(
            ufuk_gun=ufuk, n=n,
            medyan_pct=round(float(np.median(arr)), 2),
            ortalama_pct=round(float(arr.mean()), 2),
            min_pct=round(float(arr.min()), 2),
            max_pct=round(float(arr.max()), 2),
            pozitif_orani=round(float((arr > 0).mean()), 2),
            guvenilir=(n >= min_ornek),
            not_="" if n >= min_ornek else f"az örnek (n={n}); güvenilmez, sadece fikir verir",
        )
    return out


def mevsimsellik_aylik(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aylara gore ortalama/medyan aylik getiri + ornek sayisi.
    Cikti yine 'egilim', kesin kural degil.
    """
    close = df["Close"].astype(float).copy()
    close.index = pd.to_datetime(df.index)
    aylik = close.resample("ME").last().pct_change() * 100
    tablo = aylik.groupby(aylik.index.month).agg(
        ortalama_pct=lambda s: round(s.mean(), 2),
        medyan_pct=lambda s: round(s.median(), 2),
        n="count",
        pozitif_orani=lambda s: round((s > 0).mean(), 2),
    )
    aylar = ["Oca", "Şub", "Mar", "Nis", "May", "Haz",
             "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
    tablo.index = [aylar[m - 1] for m in tablo.index]
    return tablo


def ozetle(dagilim: OlayDagilim) -> str:
    """İnsan-okur özet (dürüst dille)."""
    if dagilim.n == 0:
        return f"{dagilim.ufuk_gun} gün: örnek yok."
    s = (f"{dagilim.ufuk_gun} gün sonra: medyan {dagilim.medyan_pct:+.1f}%, "
         f"aralık {dagilim.min_pct:+.1f}% / {dagilim.max_pct:+.1f}%, "
         f"pozitif oranı {dagilim.pozitif_orani:.0%}, n={dagilim.n}")
    if not dagilim.guvenilir:
        s += " — DİKKAT: az örnek, güvenilmez"
    return s
