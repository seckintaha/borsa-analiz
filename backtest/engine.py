"""
Backtest motoru (Aşama 3).

İlkeler (yol haritası Bölüm 8.2):
- İşlem maliyeti (komisyon + kayma) dahil edilir.
- Mutlaka bir kıyas (benchmark = al-tut) ile karşılaştırılır.
- Look-ahead'i önlemek için sinyal t günündeki kapanışla üretilir, işlem t+1'de
  uygulanır (gecikme).
- Out-of-sample bölme yardımcı fonksiyonu sağlanır.

Strateji arayüzü: bir fonksiyon (df) -> pozisyon serisi (1 = tam long, 0 = nakit).
Basit ve test edilebilir tutuldu.
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class BacktestSonuc:
    getiri_pct: float
    benchmark_pct: float
    fark_pct: float            # strateji - benchmark
    kazanma_orani: float       # pozitif gunlerin orani (pozisyondayken)
    max_dusus_pct: float       # maksimum drawdown
    sharpe: float
    islem_sayisi: int
    gun_sayisi: int

    def __str__(self):
        return (f"Strateji {self.getiri_pct:+.1f}% | Benchmark {self.benchmark_pct:+.1f}% | "
                f"Fark {self.fark_pct:+.1f}% | Max düşüş {self.max_dusus_pct:.1f}% | "
                f"Sharpe {self.sharpe:.2f} | {self.islem_sayisi} işlem")


def _max_drawdown(deger_serisi: pd.Series) -> float:
    zirve = deger_serisi.cummax()
    dusus = (deger_serisi - zirve) / zirve
    return float(dusus.min() * 100)


def backtest(df: pd.DataFrame, strateji_fn, costs: dict | None = None,
             yillik_gun: int = 252) -> BacktestSonuc:
    """
    df: Close kolonu olan, tarih indeksli OHLCV.
    strateji_fn(df) -> pandas Series (1/0), her gun icin hedef pozisyon.
    """
    costs = costs or {"komisyon_pct": 0.0, "kayma_pct": 0.0}
    islem_maliyet = costs["komisyon_pct"] + costs["kayma_pct"]

    close = df["Close"].astype(float)
    gunluk_getiri = close.pct_change().fillna(0)

    pozisyon = strateji_fn(df).reindex(close.index).fillna(0).clip(0, 1)
    # Look-ahead onleme: bugunku sinyal yarin uygulanir
    uygulanan = pozisyon.shift(1).fillna(0)

    # Pozisyon degisince islem maliyeti dus
    pozisyon_degisim = uygulanan.diff().abs().fillna(uygulanan.abs())
    maliyet = pozisyon_degisim * islem_maliyet

    strateji_getiri = uygulanan * gunluk_getiri - maliyet
    strateji_deger = (1 + strateji_getiri).cumprod()
    benchmark_deger = (1 + gunluk_getiri).cumprod()

    getiri_pct = (strateji_deger.iloc[-1] - 1) * 100
    benchmark_pct = (benchmark_deger.iloc[-1] - 1) * 100

    pozisyondaki = strateji_getiri[uygulanan > 0]
    kazanma = float((pozisyondaki > 0).mean()) if len(pozisyondaki) else 0.0

    std = strateji_getiri.std()
    sharpe = float(strateji_getiri.mean() / std * np.sqrt(yillik_gun)) if std > 0 else 0.0
    islem_sayisi = int((pozisyon_degisim > 0).sum())

    return BacktestSonuc(
        getiri_pct=round(float(getiri_pct), 2),
        benchmark_pct=round(float(benchmark_pct), 2),
        fark_pct=round(float(getiri_pct - benchmark_pct), 2),
        kazanma_orani=round(kazanma, 3),
        max_dusus_pct=round(_max_drawdown(strateji_deger), 2),
        sharpe=round(sharpe, 2),
        islem_sayisi=islem_sayisi,
        gun_sayisi=len(close),
    )


def train_test_bol(df: pd.DataFrame, test_orani: float = 0.3):
    """Out-of-sample: ilk kisim parametre/gelistirme, son kisim degerlendirme."""
    n = len(df)
    kesim = int(n * (1 - test_orani))
    return df.iloc[:kesim].copy(), df.iloc[kesim:].copy()


# --- Örnek strateji (test ve demo için) ---
def strateji_sma_kesisim(df: pd.DataFrame) -> pd.Series:
    """50 günlük ortalama 200'ün üzerindeyse long, değilse nakit."""
    close = df["Close"].astype(float)
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    return (sma50 > sma200).astype(int)
