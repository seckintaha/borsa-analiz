"""
Sinyal değerlendirme (Aşama 0, ileride Aşama 6'da LLM ile zenginleşir).

İlkeler (yol haritası):
- "AL/SAT" hükmü vermez; gostergelerin durumunu ve dengeli bir ozet sunar.
- Her olumlu goruse "ayi senaryosu" (neden ters gidebilir) eklenir.
- Ani fiyat + dusuk hacim birlikteligi manipulasyon/balon bayragi olarak isaretlenir
  (AL degil, DIKKAT).

NOT: Hicbir cikti yatirim tavsiyesi degildir.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class SignalResult:
    ozet: str
    puan: int
    notlar: list = field(default_factory=list)
    ayi_senaryosu: list = field(default_factory=list)
    bayraklar: list = field(default_factory=list)   # dikkat bayraklari


def evaluate(df: pd.DataFrame, thin_volume: float = 100_000) -> SignalResult:
    son = df.iloc[-1]
    notlar, ayi, bayraklar = [], [], []
    puan = 0

    # RSI
    rsi = son.get("RSI")
    if pd.notna(rsi):
        if rsi < 30:
            notlar.append(f"RSI {rsi:.0f}: aşırı satım bölgesi")
            puan += 1
        elif rsi > 70:
            notlar.append(f"RSI {rsi:.0f}: aşırı alım bölgesi")
            puan -= 1
            ayi.append("RSI yüksek; kısa vadede geri çekilme görülebilir")
        else:
            notlar.append(f"RSI {rsi:.0f}: nötr")

    # Uzun vade egilimi
    sma50, sma200 = son.get("SMA50"), son.get("SMA200")
    if pd.notna(sma50) and pd.notna(sma200):
        if sma50 > sma200:
            notlar.append("50 günlük > 200 günlük: uzun vade yukarı eğilimli")
            puan += 1
        else:
            notlar.append("50 günlük < 200 günlük: uzun vade aşağı eğilimli")
            puan -= 1

    # Kisa vade momentum
    macd, macd_sig = son.get("MACD"), son.get("MACD_sinyal")
    if pd.notna(macd) and pd.notna(macd_sig):
        if macd > macd_sig:
            notlar.append("MACD sinyalin üzerinde: kısa vade momentum pozitif")
            puan += 1
        else:
            notlar.append("MACD sinyalin altında: kısa vade momentum negatif")
            puan -= 1

    # --- Manipulasyon / balon bayragi: ani siçrama + dusuk hacim ---
    if len(df) >= 21:
        son_kapanis = df["Close"].iloc[-1]
        onceki = df["Close"].iloc[-2]
        gun_degisim = (son_kapanis - onceki) / onceki * 100 if onceki else 0
        ort_hacim = df["Volume"].iloc[-21:-1].mean()
        son_hacim = df["Volume"].iloc[-1]
        if gun_degisim > 8 and pd.notna(ort_hacim) and son_hacim < ort_hacim:
            bayraklar.append(
                "Dikkat: fiyat sert yükseldi ama hacim ortalamanın altında — "
                "manipülasyon/balon riski olabilir. Bu bir AL sinyali değildir."
            )
        if pd.notna(ort_hacim) and ort_hacim < thin_volume:
            bayraklar.append(
                "Dikkat: ince hacimli hisse — ekrandaki fiyattan gerçekte "
                "alıp satmak zor olabilir."
            )

    # Genel ozet
    if puan >= 2:
        ozet = "Göstergeler ağırlıklı pozitif"
        ayi.append("Pozitif tablo fiyatlanmış olabilir; beklenti zaten yüksekse hayal kırıklığı riski var")
    elif puan <= -2:
        ozet = "Göstergeler ağırlıklı negatif"
    else:
        ozet = "Göstergeler karışık / nötr"

    return SignalResult(ozet=ozet, puan=puan, notlar=notlar,
                        ayi_senaryosu=ayi, bayraklar=bayraklar)
