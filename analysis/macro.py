"""
Makro & piyasa rejimi (Aşama 7).

İlke (yol haritası): tek hisseden önce piyasanın genel havasını okumak gerekir.
Boğa piyasasında zayıf bir hisse bile taşınabilir; ayı piyasasında güçlü bir
hisse bile satılır. Bu modül "şu an hangi rejimdeyiz" sorusunu **gerekçesiyle**
yanıtlar. Kesin gelecek tahmini yapmaz; mevcut durumu sınıflar.

Saf hesap mantığı; verilen geçmiş df üzerinde çalışır (canlı veri gerektirmez).

NOT: Hiçbir çıktı yatırım tavsiyesi değildir.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd


@dataclass
class RejimSonuc:
    rejim: str                  # "Boğa", "Ayı", "Yatay"
    oynaklik: str               # "düşük", "normal", "yüksek"
    trend_skor: int             # -3..+3, pozitif = yukarı eğilim
    fiyat: float | None
    sma50: float | None
    sma200: float | None
    zirveden_dusus_pct: float | None    # son zirveden güncel düşüş
    yillik_oynaklik_pct: float | None   # yıllıklandırılmış gerçekleşen oynaklık
    notlar: list = field(default_factory=list)
    not_: str = ""              # veri yetersizse açıklama


def rejim_tespit(df: pd.DataFrame, oynaklik_penceresi: int = 20,
                 yatay_band_pct: float = 5.0,
                 yuksek_oynaklik_p: float = 75,
                 dusuk_oynaklik_p: float = 25) -> RejimSonuc:
    """
    Bir endeks/fiyat serisinden piyasa rejimini çıkarır.

    Trend: fiyatın 50/200 gün ortalamalarına göre konumu + 50g eğimi.
    Oynaklık: yıllıklandırılmış gerçekleşen oynaklığın kendi geçmişindeki yeri.
    """
    if df is None or "Close" not in df or len(df) < 60:
        return RejimSonuc("belirsiz", "belirsiz", 0, None, None, None, None, None,
                          not_="rejim için yetersiz veri (en az ~60 gün gerekir)")

    close = df["Close"].astype(float)
    fiyat = float(close.iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    sma200 = (float(close.rolling(200).mean().iloc[-1])
              if len(close) >= 200 else None)

    notlar, skor = [], 0

    # 50g eğimi (son 10 günde 50g ortalama yükseliyor mu)
    sma50_seri = close.rolling(50).mean()
    if len(sma50_seri.dropna()) >= 11:
        egim = sma50_seri.iloc[-1] - sma50_seri.iloc[-11]
        if egim > 0:
            skor += 1
            notlar.append("50 günlük ortalama yükseliyor")
        else:
            skor -= 1
            notlar.append("50 günlük ortalama düşüyor")

    # Fiyat 50g'nin neresinde
    if fiyat > sma50:
        skor += 1
        notlar.append("fiyat 50 günlük ortalamanın üzerinde")
    else:
        skor -= 1
        notlar.append("fiyat 50 günlük ortalamanın altında")

    # Uzun vade: 50g vs 200g
    if sma200 is not None:
        if sma50 > sma200:
            skor += 1
            notlar.append("50 günlük > 200 günlük (uzun vade yukarı)")
        else:
            skor -= 1
            notlar.append("50 günlük < 200 günlük (uzun vade aşağı)")

    # Yatay bandı: fiyat 200g'ye çok yakınsa trend zayıf → yatay
    referans = sma200 if sma200 is not None else sma50
    yakinlik = abs(fiyat - referans) / referans * 100 if referans else 999
    if yakinlik <= yatay_band_pct and -1 <= skor <= 1:
        rejim = "Yatay"
        notlar.append(f"fiyat ortalamaya yakın (%{yakinlik:.1f}) — yön belirsiz")
    elif skor >= 2:
        rejim = "Boğa"
    elif skor <= -2:
        rejim = "Ayı"
    else:
        rejim = "Yatay"

    # Zirveden düşüş (drawdown)
    zirve = close.cummax()
    zirveden_dusus = round(float((fiyat - zirve.iloc[-1]) / zirve.iloc[-1] * 100), 2)

    # Gerçekleşen oynaklık (yıllıklandırılmış) ve geçmişe göre yeri
    getiriler = close.pct_change()
    gunluk_oyn = getiriler.rolling(oynaklik_penceresi).std()
    yillik_oyn = gunluk_oyn * np.sqrt(252) * 100
    son_oyn = yillik_oyn.iloc[-1]
    oynaklik = "belirsiz"
    if pd.notna(son_oyn):
        gecmis = yillik_oyn.dropna()
        ust = np.percentile(gecmis, yuksek_oynaklik_p)
        alt = np.percentile(gecmis, dusuk_oynaklik_p)
        if son_oyn >= ust:
            oynaklik = "yüksek"
            notlar.append(f"oynaklık yüksek (yıllık ~%{son_oyn:.0f}) — sert hareket riski")
        elif son_oyn <= alt:
            oynaklik = "düşük"
            notlar.append(f"oynaklık düşük (yıllık ~%{son_oyn:.0f})")
        else:
            oynaklik = "normal"
            notlar.append(f"oynaklık normal (yıllık ~%{son_oyn:.0f})")

    return RejimSonuc(
        rejim=rejim, oynaklik=oynaklik, trend_skor=skor,
        fiyat=round(fiyat, 2), sma50=round(sma50, 2),
        sma200=round(sma200, 2) if sma200 is not None else None,
        zirveden_dusus_pct=zirveden_dusus,
        yillik_oynaklik_pct=round(float(son_oyn), 1) if pd.notna(son_oyn) else None,
        notlar=notlar,
    )


def piyasa_genisligi(fiyat_tablosu: dict, pencere: int = 50) -> dict:
    """
    Piyasa genişliği (breadth): kaç hisse kendi N günlük ortalamasının üzerinde.

    fiyat_tablosu: {symbol: Close-serisi (pd.Series veya df)}.
    Geniş katılım (çoğu hisse ortalamasının üzerinde) sağlıklı yükseliş işaretidir;
    az hisseyle yükselen piyasa kırılgandır.
    """
    ustte, toplam, detay = 0, 0, {}
    for sym, seri in fiyat_tablosu.items():
        if isinstance(seri, pd.DataFrame):
            seri = seri["Close"] if "Close" in seri else None
        if seri is None:
            continue
        seri = pd.Series(seri).astype(float).dropna()
        if len(seri) < pencere:
            continue
        ort = seri.rolling(pencere).mean().iloc[-1]
        ust_mu = bool(seri.iloc[-1] > ort)
        detay[sym] = ust_mu
        toplam += 1
        ustte += int(ust_mu)

    if toplam == 0:
        return {"oran": None, "ustte": 0, "toplam": 0, "detay": {},
                "not_": "genişlik için yeterli veri yok"}
    oran = round(ustte / toplam, 2)
    return {"oran": oran, "ustte": ustte, "toplam": toplam, "detay": detay,
            "not_": ""}


def ozetle(r: RejimSonuc) -> str:
    """İnsan-okur özet (dürüst dille)."""
    if r.rejim == "belirsiz":
        return r.not_
    s = f"Piyasa rejimi: {r.rejim} | oynaklık: {r.oynaklik}"
    if r.zirveden_dusus_pct is not None and r.zirveden_dusus_pct < -1:
        s += f" | zirveden {r.zirveden_dusus_pct:.1f}%"
    return s
