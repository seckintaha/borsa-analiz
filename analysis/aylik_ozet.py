"""
Aylık Özet Raporu.

Her ayın 1'inde (veya /aylik komutuyla) üretilir:
  - Piyasa rejimi + endeksin aylık getirisi
  - Portföyünün aylık performansı (her hissenin son ~21 işlem günü getirisi)
  - En iyi / en kötü hissen
  - Uzun vade trend durumu (SMA50/200 golden/death cross)
  - Her pozisyon için güncel AL/TUT/SAT
  - Piyasadaki aylık öne çıkanlar (en iyi aylık performanslı AL adayları)

Tüm rakamlar geçmiş fiyat verisine dayanır; veri yoksa "veri yok" der.
"""

from __future__ import annotations
from datetime import datetime

import pandas as pd

from data.access import veri_getir
from analysis.indicators import add_indicators
from analysis import macro
from portfolio.ozet import acik_pozisyonlar


def _aylik_getiri(df: pd.DataFrame, n_gun: int = 21):
    """Son n işlem günü getirisi (%). Yetersiz veride None."""
    if df is None or len(df) < n_gun + 1:
        return None
    son = float(df["Close"].iloc[-1])
    onceki = float(df["Close"].iloc[-1 - n_gun])
    if onceki <= 0:
        return None
    return (son - onceki) / onceki * 100


def _trend_durumu(df_i: pd.DataFrame) -> str:
    """SMA50/200 ilişkisinden uzun vade trend etiketi."""
    son = df_i.iloc[-1]
    sma50, sma200 = son.get("SMA50"), son.get("SMA200")
    if pd.isna(sma50) or pd.isna(sma200):
        return "trend belirsiz (yetersiz veri)"
    if sma50 > sma200:
        return "Yukarı (SMA50>SMA200, golden cross bölgesi)"
    return "Aşağı (SMA50<SMA200, death cross bölgesi)"


def aylik_ozet_metni(db_path: str, macro_cfg: dict, n_gun: int = 21) -> str:
    """Aylık özet raporunu metin olarak üretir."""
    ay = datetime.now().strftime("%B %Y")
    bugun = datetime.now().strftime("%d.%m.%Y")

    sat = [f"📅 AYLIK ÖZET — {ay}", f"(rapor: {bugun}, son ~{n_gun} işlem günü baz alınır)", ""]

    # ── 1) Piyasa rejimi + endeks aylık ──
    endeks = macro_cfg.get("rejim_endeksi", "XU100.IS")
    fr = veri_getir(db_path, endeks, period="2y", interval="1d")
    if fr.ok and fr.data is not None:
        rej = macro.rejim_tespit(fr.data)
        endeks_aylik = _aylik_getiri(fr.data, n_gun)
        aylik_str = f"%{endeks_aylik:+.1f}" if endeks_aylik is not None else "—"
        sat += [
            "🌐 PİYASA",
            f"   Rejim: {macro.ozetle(rej)}",
            f"   {endeks} aylık getiri: {aylik_str}",
            "",
        ]

    # ── 2) Portföy aylık performansı ──
    pos = acik_pozisyonlar(db_path)
    if not pos:
        sat += ["💼 PORTFÖY", "   Boş — /ekle ile hisse ekleyince aylık performansın burada çıkar.", ""]
    else:
        perf_list = []   # (kod, aylik_getiri, trend, karar, guncel)
        toplam_deger = 0.0
        agirlikli_getiri = 0.0
        for sembol, p in pos.items():
            kod = sembol.replace(".IS", "")
            frh = veri_getir(db_path, sembol, period="1y", interval="1d")
            if not frh.ok or frh.data is None:
                perf_list.append((kod, None, "veri yok", "—", None))
                continue
            df_i = add_indicators(frh.data)
            getiri = _aylik_getiri(frh.data, n_gun)
            trend = _trend_durumu(df_i)
            guncel = float(frh.data["Close"].iloc[-1])
            # güncel AL/TUT/SAT
            try:
                from analysis.teknik_derin import analiz_et
                karar = analiz_et(frh.data, sembol).karar
            except Exception:
                karar = "—"
            perf_list.append((kod, getiri, trend, karar, guncel))
            deger = p["adet"] * guncel
            toplam_deger += deger
            if getiri is not None:
                agirlikli_getiri += deger * getiri

        portfoy_aylik = (agirlikli_getiri / toplam_deger) if toplam_deger else None

        sat.append("💼 PORTFÖYÜN — AYLIK")
        if portfoy_aylik is not None:
            isaret = "🟢" if portfoy_aylik >= 0 else "🔴"
            sat.append(f"   {isaret} Ağırlıklı aylık getiri: %{portfoy_aylik:+.1f}")
        sat.append("")

        # Her hisse
        for kod, getiri, trend, karar, guncel in perf_list:
            g_str = f"%{getiri:+.1f}" if getiri is not None else "veri yok"
            kemoji = {"AL": "🟢", "TUT": "🟡", "SAT": "🔴"}.get(karar, "⚪")
            sat.append(f"   • {kod}: aylık {g_str} · {kemoji} {karar} · trend: {trend}")

        # En iyi / en kötü
        gecerli = [(k, g) for k, g, *_ in perf_list if g is not None]
        if gecerli:
            en_iyi = max(gecerli, key=lambda x: x[1])
            en_kotu = min(gecerli, key=lambda x: x[1])
            sat += [
                "",
                f"   🏆 Ayın en iyisi: {en_iyi[0]} (%{en_iyi[1]:+.1f})",
                f"   🔻 Ayın en kötüsü: {en_kotu[0]} (%{en_kotu[1]:+.1f})",
            ]
        sat.append("")

    # ── 3) Piyasada aylık öne çıkanlar ──
    try:
        from analysis.bist_tarama import bist_tara
        ok, _, satirlar = bist_tara(limit=1000)
        if ok:
            adaylar = [r for r in satirlar
                       if r.aksiyon in ("Güçlü AL adayı", "AL adayı")
                       and r.perf_ay is not None]
            adaylar.sort(key=lambda r: r.perf_ay, reverse=True)
            if adaylar:
                sat.append("🚀 PİYASADA AYLIK ÖNE ÇIKAN AL ADAYLARI")
                for r in adaylar[:5]:
                    sat.append(f"   • {r.sembol.replace('.IS','')}: aylık %{r.perf_ay:+.1f} "
                               f"· RSI {r.rsi} · {r.ema_durumu}")
                sat.append("")
    except Exception:
        pass

    sat += [
        "━━━━━━━━━━━━━━",
        "⚠️ Aylık özet geçmiş fiyat verisine dayanır; yatırım tavsiyesi değildir. "
        "Detaylı tek hisse için /analiz SEMBOL.",
    ]
    return "\n".join(sat)
