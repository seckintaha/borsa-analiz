"""
Sinyal Edge Testi — sistemin AL sinyalinin GERÇEK değeri var mı?

Bir hissenin geçmişinde, sistemin "AL" koşulları oluştuğu günleri bulur ve
o günlerden sonraki N günlük getiriyi, rastgele/ortalama günle KIYASLAR.
Sinyal günleri ortalamadan iyiyse "edge var", değilse "edge yok" der.

DÜRÜSTLÜK: Bu, sinyalin işe yarayıp yaramadığını dürüstçe ölçer — pazarlamaz.
Gerçek fiyat verisine dayanır; veri yetersizse açıkça belirtir.
"""

from __future__ import annotations
import numpy as np
import pandas as pd

from data.access import veri_getir
from analysis.indicators import add_indicators


def _al_kosulu(df_i: pd.DataFrame) -> pd.Series:
    """Her bar için sistemin AL koşulu (boğa dizilimi) sağlanıyor mu (bool seri)."""
    ema20 = df_i["Close"].ewm(span=20, adjust=False).mean()
    ema50 = df_i["Close"].ewm(span=50, adjust=False).mean()
    kosul = (
        (ema20 > ema50) &
        (df_i["MACD"] > df_i["MACD_sinyal"]) &
        (df_i["RSI"] >= 40) & (df_i["RSI"] <= 70) &
        (df_i["Close"] > df_i["SMA20"])
    )
    return kosul.fillna(False)


def sinyal_edge_testi(db_path: str, sembol: str, ileri_gun: int = 20) -> str:
    sem = (sembol or "").strip().upper()
    # BIST kısa kodu ise .IS ekle; global sembol (AAPL, nokta içerenler) bozulmaz.
    if not sem.endswith(".IS") and sem.isalpha() and len(sem) <= 5:
        sem += ".IS"
    kod = sem.replace(".IS", "")
    fr = veri_getir(db_path, sem, period="2y", interval="1d")
    if not fr.ok or fr.data is None or len(fr.data) < 120:
        return (f"❌ {kod}: edge testi için yeterli geçmiş veri yok "
                f"(en az ~120 gün gerekir).")

    df_i = add_indicators(fr.data)
    close = df_i["Close"].astype(float)
    # N gün ileri getiri
    ileri_getiri = close.shift(-ileri_gun) / close - 1.0

    kosul = _al_kosulu(df_i)
    # Son ileri_gun bar'ın ileri getirisi yok → at
    gecerli = ileri_getiri.notna()
    kosul = kosul & gecerli

    sinyal_getiriler = ileri_getiri[kosul].dropna()
    tum_getiriler = ileri_getiri[gecerli].dropna()

    if len(sinyal_getiriler) < 5:
        return (f"📊 {kod} — SİNYAL EDGE TESTİ\n\n"
                f"Son 2 yılda yeterli AL sinyali oluşmamış ({len(sinyal_getiriler)} kez). "
                "İstatistiksel sonuç için az. Daha uzun geçmişi olan/likit hisse dene.")

    sinyal_ort = float(sinyal_getiriler.mean()) * 100
    baz_ort = float(tum_getiriler.mean()) * 100
    sinyal_kazanma = float((sinyal_getiriler > 0).mean()) * 100
    baz_kazanma = float((tum_getiriler > 0).mean()) * 100
    fark = sinyal_ort - baz_ort

    if fark > 1.5:
        huk = "✅ EDGE VAR: AL sinyali ortalamadan belirgin iyi performans göstermiş."
    elif fark > 0:
        huk = "🟡 ZAYIF EDGE: AL sinyali ortalamadan biraz iyi (küçük fark)."
    else:
        huk = ("🔴 EDGE YOK: Bu hissede AL sinyali ortalamayı GEÇEMEMİŞ. "
               "Sinyale bu hissede temkinli yaklaş.")

    return "\n".join([
        f"📊 {kod} — SİNYAL EDGE TESTİ (son 2 yıl, {ileri_gun} gün ileri)",
        "",
        f"AL sinyali oluşan gün sayısı: {len(sinyal_getiriler)}",
        "",
        f"📈 Sinyal sonrası ort. getiri: %{sinyal_ort:+.2f}  (kazanma %{sinyal_kazanma:.0f})",
        f"➖ Rastgele gün ort. getiri:   %{baz_ort:+.2f}  (kazanma %{baz_kazanma:.0f})",
        f"🔼 Fark (edge): %{fark:+.2f}",
        "",
        huk,
        "",
        "⚠️ Geçmiş performans geleceği garanti etmez — bu sadece sinyalin geçmişteki "
        "istatistiksel davranışıdır. Yatırım tavsiyesi değildir.",
    ])
