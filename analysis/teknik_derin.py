"""
Derin teknik analiz + NET KARAR (Özellik #6).

Bir hisse için günlük + haftalık grafiği okur:
  - Destek / direnç seviyeleri (swing tepe/dip + Bollinger + yuvarlak sayı)
  - Trend / EMA dizilimi
  - Momentum: RSI + MACD + ADX
  - NET karar: AL / TUT / SAT (gerekçeli, adım adım)
  - Giriş / kar-al / zarar-kes seviyeleri + risk/ödül oranı (ATR + S/R temelli)

Bu modül NET karar dili kullanır (kullanıcı talebi). Çıktı yine de geçmiş
fiyata dayalıdır; sonunda risk uyarısı eklenir. Veri yoksa açıkça belirtilir.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from analysis.indicators import add_indicators


@dataclass
class Seviye:
    fiyat: float
    tip: str            # "destek" / "direnç"
    kaynak: str         # "swing dip", "Bollinger üst", "SMA200" vb.
    uzaklik_pct: float  # mevcut fiyattan % uzaklık


@dataclass
class TeknikKarar:
    sembol: str
    fiyat: float
    karar: str                 # "AL" / "TUT" / "SAT"
    guven: str                 # "Yüksek" / "Orta" / "Düşük"
    skor: int                  # ham skor
    giris: Optional[float]
    kar_al: Optional[float]
    zarar_kes: Optional[float]
    risk_odul: Optional[float]
    destekler: list = field(default_factory=list)     # list[Seviye]
    direncler: list = field(default_factory=list)
    gerekceler: list = field(default_factory=list)    # adım adım neden
    haftalik_not: str = ""
    uyarilar: list = field(default_factory=list)
    ok: bool = True
    hata: str = ""


# ── Destek / direnç tespiti ───────────────────────────────────────────────────

def _swing_noktalari(df: pd.DataFrame, pencere: int = 5) -> tuple[list[float], list[float]]:
    """
    Yerel tepe (swing high) ve dip (swing low) noktalarını bulur.
    pencere: bir nokta solunda+sağında bu kadar barın hepsinden yüksek/alçaksa pivot.
    """
    high = df["High"].values
    low = df["Low"].values
    n = len(df)
    tepeler, dipler = [], []
    for i in range(pencere, n - pencere):
        pencere_high = high[i - pencere:i + pencere + 1]
        pencere_low = low[i - pencere:i + pencere + 1]
        if high[i] == pencere_high.max():
            tepeler.append(float(high[i]))
        if low[i] == pencere_low.min():
            dipler.append(float(low[i]))
    return tepeler, dipler


def _yakin_kumeleme(seviyeler: list[float], tolerans_pct: float = 1.5) -> list[float]:
    """Birbirine yakın seviyeleri tek seviyede birleştirir (ortalama)."""
    if not seviyeler:
        return []
    seviyeler = sorted(seviyeler)
    kumeler = [[seviyeler[0]]]
    for s in seviyeler[1:]:
        if abs(s - kumeler[-1][-1]) / kumeler[-1][-1] * 100 <= tolerans_pct:
            kumeler[-1].append(s)
        else:
            kumeler.append([s])
    return [round(float(np.mean(k)), 2) for k in kumeler]


def destek_direnc(df: pd.DataFrame, fiyat: float, n: int = 3) -> tuple[list[Seviye], list[Seviye]]:
    """
    Mevcut fiyatın altındaki en yakın N desteği ve üstündeki N direnci döndürür.
    Kaynaklar: swing dip/tepe, Bollinger bantları, SMA50/200, son dönem dip/zirve.
    """
    df_i = add_indicators(df) if "BB_ust" not in df.columns else df
    son = df_i.iloc[-1]

    tepeler, dipler = _swing_noktalari(df, pencere=5)
    tum_destek_ham: list[tuple[float, str]] = [(d, "swing dip") for d in dipler]
    tum_direnc_ham: list[tuple[float, str]] = [(t, "swing tepe") for t in tepeler]

    # Bollinger
    if pd.notna(son.get("BB_alt")):
        tum_destek_ham.append((float(son["BB_alt"]), "Bollinger alt"))
    if pd.notna(son.get("BB_ust")):
        tum_direnc_ham.append((float(son["BB_ust"]), "Bollinger üst"))

    # SMA50 / SMA200 (fiyatın hangi tarafındaysa o rolü oynar)
    for ad, kol in [("SMA50", "SMA50"), ("SMA200", "SMA200")]:
        v = son.get(kol)
        if pd.notna(v):
            v = float(v)
            if v < fiyat:
                tum_destek_ham.append((v, ad))
            else:
                tum_direnc_ham.append((v, ad))

    # Son 60 günün dip ve zirvesi
    if len(df) >= 60:
        son60 = df.iloc[-60:]
        tum_destek_ham.append((float(son60["Low"].min()), "60g dip"))
        tum_direnc_ham.append((float(son60["High"].max()), "60g zirve"))

    # Fiyatın altındakiler destek, üstündekiler direnç
    destek_fiyatlar = _yakin_kumeleme([d for d, _ in tum_destek_ham if d < fiyat])
    direnc_fiyatlar = _yakin_kumeleme([d for d, _ in tum_direnc_ham if d > fiyat])

    # Kaynak etiketini yeniden eşle (en yakın ham seviyeye göre)
    def _kaynak_bul(hedef, ham):
        if not ham:
            return ""
        return min(ham, key=lambda x: abs(x[0] - hedef))[1]

    destekler = [
        Seviye(f, "destek", _kaynak_bul(f, tum_destek_ham),
               round((f - fiyat) / fiyat * 100, 2))
        for f in sorted(destek_fiyatlar, reverse=True)[:n]
    ]
    direncler = [
        Seviye(f, "direnç", _kaynak_bul(f, tum_direnc_ham),
               round((f - fiyat) / fiyat * 100, 2))
        for f in sorted(direnc_fiyatlar)[:n]
    ]
    return destekler, direncler


# ── Haftalık veri (günlükten yeniden örnekle) ─────────────────────────────────

def _haftalik(df: pd.DataFrame) -> pd.DataFrame:
    """Günlük OHLCV'yi haftalığa çevirir (W-FRI)."""
    o = df["Open"].resample("W-FRI").first()
    h = df["High"].resample("W-FRI").max()
    l = df["Low"].resample("W-FRI").min()
    c = df["Close"].resample("W-FRI").last()
    v = df["Volume"].resample("W-FRI").sum()
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}).dropna()


# ── Karar mantığı (net) ───────────────────────────────────────────────────────

def _skor_hesapla(son, df_i: pd.DataFrame) -> tuple[int, list[str]]:
    """Göstergelerden ham skor + adım adım gerekçe üretir."""
    skor = 0
    g: list[str] = []

    fiyat = float(son["Close"])

    # EMA/SMA dizilimi
    sma20, sma50, sma200 = son.get("SMA20"), son.get("SMA50"), son.get("SMA200")
    if pd.notna(sma50) and pd.notna(sma200):
        if sma50 > sma200:
            skor += 2
            g.append("✅ SMA50 > SMA200: uzun vade trend YUKARI (golden cross bölgesi)")
        else:
            skor -= 2
            g.append("❌ SMA50 < SMA200: uzun vade trend AŞAĞI (death cross bölgesi)")
    if pd.notna(sma20):
        if fiyat > float(sma20):
            skor += 1
            g.append("✅ Fiyat SMA20 üstünde: kısa vade momentum pozitif")
        else:
            skor -= 1
            g.append("❌ Fiyat SMA20 altında: kısa vade momentum negatif")

    # RSI
    rsi = son.get("RSI")
    if pd.notna(rsi):
        rsi = float(rsi)
        if rsi < 30:
            skor += 2
            g.append(f"✅ RSI {rsi:.0f}: aşırı satım — tepki yükselişi potansiyeli")
        elif rsi > 70:
            skor -= 2
            g.append(f"❌ RSI {rsi:.0f}: aşırı alım — geri çekilme riski")
        elif rsi >= 50:
            skor += 1
            g.append(f"✅ RSI {rsi:.0f}: 50 üstü, alıcılar baskın")
        else:
            skor -= 1
            g.append(f"⚠️ RSI {rsi:.0f}: 50 altı, satıcılar baskın")

    # MACD
    macd, macd_sig = son.get("MACD"), son.get("MACD_sinyal")
    if pd.notna(macd) and pd.notna(macd_sig):
        if macd > macd_sig:
            skor += 2
            g.append("✅ MACD sinyal çizgisi üstünde: alış momentumu")
        else:
            skor -= 2
            g.append("❌ MACD sinyal çizgisi altında: satış momentumu")

    # ADX (trend gücü)
    adx = son.get("ADX14")
    di_pos, di_neg = son.get("DI_pos"), son.get("DI_neg")
    if pd.notna(adx):
        adx = float(adx)
        if adx >= 25 and pd.notna(di_pos) and pd.notna(di_neg):
            if di_pos > di_neg:
                skor += 2
                g.append(f"✅ ADX {adx:.0f}: GÜÇLÜ trend, yön yukarı (+DI>-DI)")
            else:
                skor -= 2
                g.append(f"❌ ADX {adx:.0f}: GÜÇLÜ trend, yön aşağı (-DI>+DI)")
        elif adx < 20:
            g.append(f"⚠️ ADX {adx:.0f}: zayıf trend / yatay — kırılım beklenebilir")

    return skor, g


def _karar_etiketi(skor: int) -> tuple[str, str]:
    """Ham skoru AL/TUT/SAT + güven düzeyine çevirir."""
    if skor >= 6:
        return "AL", "Yüksek"
    if skor >= 3:
        return "AL", "Orta"
    if skor >= -2:
        return "TUT", "Orta"
    if skor >= -5:
        return "SAT", "Orta"
    return "SAT", "Yüksek"


def analiz_et(df: pd.DataFrame, sembol: str) -> TeknikKarar:
    """
    Tek hisse için derin teknik analiz + net karar üretir.
    df: tarih indeksli OHLCV (en az ~60 bar önerilir).
    """
    if df is None or len(df) < 30:
        return TeknikKarar(sembol, 0.0, "TUT", "Düşük", 0, None, None, None, None,
                           ok=False, hata="yetersiz veri (en az 30 bar gerekli)")

    df_i = add_indicators(df)
    son = df_i.iloc[-1]
    fiyat = float(son["Close"])
    atr = float(son["ATR14"]) if pd.notna(son.get("ATR14")) else fiyat * 0.02

    skor, gerekceler = _skor_hesapla(son, df_i)
    karar, guven = _karar_etiketi(skor)

    destekler, direncler = destek_direnc(df, fiyat, n=3)

    # ── Giriş / hedef / stop (net seviyeler) ──
    giris = kar_al = zarar_kes = risk_odul = None
    # Stop'un fiyata en az bu kadar uzak olması beklenir (aksi halde R/R şişer).
    # ATR'nin yarısı ya da fiyatın %0.5'i — hangisi büyükse taban risk odur.
    min_risk = max(0.5 * atr, fiyat * 0.005)
    if karar == "AL":
        giris = round(fiyat, 2)
        # Stop: en yakın destek altı, ama ATR×2.5'ten uzaksa riski sınırla.
        if destekler and (fiyat - destekler[0].fiyat) <= 2.5 * atr:
            ham_stop = destekler[0].fiyat * 0.995
        else:
            ham_stop = fiyat - 1.5 * atr
        # Stop fiyata çok yakınsa (mikro risk → absürt R/R) taban riske it.
        if giris - ham_stop < min_risk:
            ham_stop = giris - min_risk
        zarar_kes = round(ham_stop, 2)
        risk = giris - zarar_kes
        # Hedef: R/R >= 1.8 verecek ilk direnci seç; yoksa risk×2 üstü ATR hedefi.
        hedef = None
        for d in direncler:
            if risk > 0 and (d.fiyat - giris) / risk >= 1.8:
                hedef = d.fiyat
                break
        if hedef is None:
            hedef = round(giris + max(2.0 * risk, 2.5 * atr), 2)
        kar_al = hedef
    elif karar == "SAT":
        # SAT kararında: elde tutan için çıkış/stop referansı
        giris = round(fiyat, 2)
        zarar_kes = round(direncler[0].fiyat, 2) if direncler else round(fiyat + 1.5 * atr, 2)
        kar_al = round(destekler[0].fiyat, 2) if destekler else round(fiyat - 2.5 * atr, 2)
    else:  # TUT
        giris = round(fiyat, 2)
        if direncler:
            kar_al = direncler[0].fiyat
        if destekler:
            zarar_kes = round(destekler[0].fiyat * 0.995, 2)

    # risk/ödül
    if giris and kar_al and zarar_kes and karar == "AL":
        risk = giris - zarar_kes
        odul = kar_al - giris
        if risk > 0 and odul > 0:
            # R/R'ı makul bir üst sınıra çek: çok yüksek R/R genelde stop'un
            # gerçekçi olmayacak kadar yakın olmasından doğar ve yanıltıcıdır.
            risk_odul = round(min(odul / risk, 5.0), 2)

    # ── Haftalık teyit ──
    haftalik_not = ""
    try:
        hf = _haftalik(df)
        if len(hf) >= 30:
            hf_i = add_indicators(hf)
            h_son = hf_i.iloc[-1]
            h_sma50 = h_son.get("SMA50")  # haftalıkta ~1 yıl
            if pd.notna(h_son.get("SMA20")) and pd.notna(h_son.get("Close")):
                if float(h_son["Close"]) > float(h_son["SMA20"]):
                    haftalik_not = "Haftalık grafik de YUKARI eğilimli (günlükle uyumlu)."
                else:
                    haftalik_not = "Haftalık grafik AŞAĞI eğilimli — günlük sinyale temkinli yaklaş."
    except Exception:
        haftalik_not = ""

    # ── Uyarılar ──
    uyarilar = []
    if pd.notna(son.get("Volume")):
        ort_hacim = df["Volume"].iloc[-21:-1].mean()
        if pd.notna(ort_hacim) and ort_hacim < 500_000:
            uyarilar.append("İnce hacim — ekrandaki fiyattan işlem zor olabilir.")
    if risk_odul is not None and risk_odul < 1.5 and karar == "AL":
        uyarilar.append(f"Risk/ödül {risk_odul} — 1.5 altı, getiri riski karşılamıyor olabilir.")

    return TeknikKarar(
        sembol=sembol, fiyat=round(fiyat, 2), karar=karar, guven=guven, skor=skor,
        giris=giris, kar_al=kar_al, zarar_kes=zarar_kes, risk_odul=risk_odul,
        destekler=destekler, direncler=direncler, gerekceler=gerekceler,
        haftalik_not=haftalik_not, uyarilar=uyarilar, ok=True,
    )


def metin_ozet(k: TeknikKarar) -> str:
    """TeknikKarar'ı okunabilir metne çevirir (Telegram/panel için)."""
    if not k.ok:
        return f"❌ {k.sembol}: {k.hata}"

    emoji = {"AL": "🟢", "TUT": "🟡", "SAT": "🔴"}.get(k.karar, "⚪")
    sat = [
        f"{emoji} {k.sembol} — KARAR: {k.karar} (güven: {k.guven})",
        f"💰 Güncel fiyat: {k.fiyat}",
        "",
        "📐 SEVİYELER:",
    ]
    if k.giris:
        sat.append(f"   Giriş: {k.giris}")
    if k.kar_al:
        sat.append(f"   🎯 Kar-al: {k.kar_al}")
    if k.zarar_kes:
        sat.append(f"   🛑 Zarar-kes: {k.zarar_kes}")
    if k.risk_odul:
        sat.append(f"   ⚖️ Risk/Ödül: 1:{k.risk_odul}")

    if k.direncler:
        sat.append("")
        sat.append("🔺 Dirençler: " + " · ".join(
            f"{d.fiyat} ({d.kaynak}, %{d.uzaklik_pct:+.1f})" for d in k.direncler))
    if k.destekler:
        sat.append("🔻 Destekler: " + " · ".join(
            f"{d.fiyat} ({d.kaynak}, %{d.uzaklik_pct:+.1f})" for d in k.destekler))

    sat += ["", "📊 GEREKÇELER (adım adım):"]
    for g in k.gerekceler:
        sat.append(f"   {g}")

    if k.haftalik_not:
        sat += ["", f"🗓️ {k.haftalik_not}"]

    if k.uyarilar:
        sat += ["", "⚑ UYARILAR:"]
        for u in k.uyarilar:
            sat.append(f"   {u}")

    sat += ["", "━━━━━━━━━━━━━━",
            "⚠️ Teknik analiz çıktısıdır, geçmiş fiyata dayanır. Kesin sonuç "
            "garantisi değildir; riski yönet, kendi kararını ver."]
    return "\n".join(sat)
