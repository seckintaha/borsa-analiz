"""
Gün sonu tarama motoru (Aşama 1) — sistemin kalbi.

Verilen sembol listesini tarar, dikkat çekenleri gerekçesiyle döndürür.
Her satırın bir "neden öne çıktı" gerekçesi vardır (Aşama 1 bitti kriteri).

Tespit ettikleri:
- En çok artan / azalan (eşik config.SCREEN'den)
- Anormal hacim (ortalamadan kaç std saptığı)
- RSI uç değerleri (aşırı alım/satım)
- İnce hacim bayrağı
"""

from __future__ import annotations
from dataclasses import dataclass, field

import pandas as pd

from data.fetcher import fetch_many
from analysis.indicators import add_indicators


@dataclass
class ScreenRow:
    symbol: str
    son_fiyat: float | None
    degisim_pct: float | None
    hacim_kat: float | None       # son hacim / ortalama hacim
    rsi: float | None
    gerekceler: list = field(default_factory=list)
    kaynak: str = ""
    zaman: str = ""
    not_: str = ""                # veri yoksa aciklama


def scan(symbols, screen_cfg) -> list[ScreenRow]:
    sonuc: list[ScreenRow] = []
    sonuclar = fetch_many(symbols, period="6mo", interval="1d")

    for sym, fr in sonuclar.items():
        if not fr.ok or fr.data is None or len(fr.data) < 21:
            sonuc.append(ScreenRow(sym, None, None, None, None,
                                   not_=fr.note or "yetersiz veri",
                                   kaynak=fr.source, zaman=fr.fetched_at))
            continue

        df = add_indicators(fr.data)
        son = df.iloc[-1]
        onceki = df["Close"].iloc[-2]
        son_fiyat = float(son["Close"])
        degisim = (son_fiyat - onceki) / onceki * 100 if onceki else 0.0

        ort_hacim = df["Volume"].iloc[-21:-1].mean()
        son_hacim = float(son["Volume"]) if pd.notna(son["Volume"]) else 0.0
        std_hacim = df["Volume"].iloc[-21:-1].std()
        hacim_kat = (son_hacim / ort_hacim) if ort_hacim else None
        rsi = float(son["RSI"]) if pd.notna(son["RSI"]) else None

        gerekceler = []
        if degisim >= screen_cfg["gainer_pct"]:
            gerekceler.append(f"yükseldi +{degisim:.1f}%")
        if degisim <= screen_cfg["loser_pct"]:
            gerekceler.append(f"düştü {degisim:.1f}%")
        if std_hacim and ort_hacim and (son_hacim - ort_hacim) > screen_cfg["volume_sigma"] * std_hacim:
            gerekceler.append(f"anormal hacim ({hacim_kat:.1f}x)")
        if rsi is not None and rsi <= screen_cfg["rsi_low"]:
            gerekceler.append(f"RSI düşük ({rsi:.0f})")
        if rsi is not None and rsi >= screen_cfg["rsi_high"]:
            gerekceler.append(f"RSI yüksek ({rsi:.0f})")
        if ort_hacim and ort_hacim < screen_cfg["thin_volume"]:
            gerekceler.append("ince hacim (dikkat)")

        sonuc.append(ScreenRow(
            symbol=sym, son_fiyat=round(son_fiyat, 2),
            degisim_pct=round(degisim, 2),
            hacim_kat=round(hacim_kat, 1) if hacim_kat else None,
            rsi=round(rsi) if rsi is not None else None,
            gerekceler=gerekceler, kaynak=fr.source, zaman=fr.fetched_at,
        ))

    # Once gerekçesi olanlar (öne çıkanlar), sonra mutlak degisime gore sirala
    sonuc.sort(key=lambda r: (len(r.gerekceler) == 0,
                              -(abs(r.degisim_pct) if r.degisim_pct is not None else -1)))
    return sonuc
