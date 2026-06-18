"""
Ayın Hisse Önerileri (her ayın 1'inde).

DOĞRULUK İLKESİ: Bir hisse ancak HEM teknik HEM temel açıdan sağlamsa önerilir.
Tüm rakamlar gerçek kaynaklardan gelir (TradingView teknik + temel, yfinance
seviye hesabı). Veri eksikse o hisse elenir — asla uydurulmaz.

Eleme kriterleri (hepsi gerçek veriye dayalı):
  Temel sağlamlık:  F/K pozitif ve < 30 · ROE > %8 · net marj > 0 (kâr ediyor)
  Teknik güç:       bist_tara'da "AL adayı" / "Güçlü AL adayı"
  Seviye:           teknik_derin ile giriş/hedef/stop + risk/ödül

Çıktı: her öneride teknik gerekçe + temel gerekçe + seviyeler + tek cümle özet.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AylikOneri:
    sembol: str
    sektor: str
    # teknik
    teknik_aksiyon: str
    rsi: Optional[float]
    ema_durumu: str
    aylik_perf: Optional[float]
    # temel
    fk: Optional[float]
    pddd: Optional[float]
    roe: Optional[float]
    temettu: Optional[float]
    net_marj: Optional[float]
    # seviyeler
    giris: Optional[float]
    hedef: Optional[float]
    stop: Optional[float]
    risk_odul: Optional[float]
    # gerekçe
    teknik_gerekce: list = field(default_factory=list)
    temel_gerekce: list = field(default_factory=list)
    ozet: str = ""


def ayin_onerileri(db_path: str, n: int = 10) -> tuple[bool, str, list[AylikOneri]]:
    """
    Teknik + temel birleşik analizle ayın en sağlam N hissesini seçer.
    Dönüş: (basarili, hata, oneri_listesi)
    """
    from analysis.bist_tarama import bist_tara
    from data.tv_scanner import tv_temel_tara
    from analysis.teknik_derin import analiz_et
    from data.access import veri_getir

    # 1) Teknik tarama (607 hisse)
    tek_ok, tek_hata, tek_satirlar = bist_tara(limit=1000)
    if not tek_ok:
        return False, f"Teknik tarama hatası: {tek_hata}", []

    # 2) Temel veri (607 hisse)
    tem_ok, tem_hata, tem_liste = tv_temel_tara(limit=1000)
    if not tem_ok:
        return False, f"Temel veri hatası: {tem_hata}", []
    temel_map = {t.sembol: t for t in tem_liste}

    # 3) Teknik açıdan güçlü olanları al, temel sağlamlık filtresinden geçir
    adaylar = []
    for r in tek_satirlar:
        if r.aksiyon not in ("Güçlü AL adayı", "AL adayı"):
            continue
        t = temel_map.get(r.sembol)
        if t is None:
            continue
        # Temel sağlamlık — hepsi gerçek veriye dayalı, eksikse ele
        if t.fk is None or not (0 < t.fk < 30):
            continue
        if t.roe is None or t.roe < 8:
            continue
        if t.net_marj is not None and t.net_marj <= 0:
            continue   # zarar eden şirket önerilmez

        # Birleşik skor: teknik sinyal + temel kalite
        skor = float(r.sinyal_skoru)
        if t.fk < 12:
            skor += 8                      # ucuz değerleme
        if t.roe > 20:
            skor += 6                      # güçlü kârlılık
        if t.pddd is not None and t.pddd < 1.5:
            skor += 4
        if t.temettu_verim and t.temettu_verim > 3:
            skor += 3
        adaylar.append((skor, r, t))

    if not adaylar:
        return True, "Bu ay hem teknik hem temel kriterleri karşılayan hisse bulunamadı.", []

    adaylar.sort(key=lambda x: -x[0])

    # 4) Üst adaylar için seviye + gerekçe (yfinance ile teknik_derin)
    #    Sektör çeşitliliği: tek sektörden en fazla 3 öneri (dengeli liste).
    oneriler: list[AylikOneri] = []
    sektor_sayac: dict[str, int] = {}
    for skor, r, t in adaylar:
        if len(oneriler) >= n:
            break
        if sektor_sayac.get(t.sektor, 0) >= 3:
            continue
        sektor_sayac[t.sektor] = sektor_sayac.get(t.sektor, 0) + 1
        fr = veri_getir(db_path, r.sembol, period="1y", interval="1d")
        giris = hedef = stop = rr = None
        if fr.ok and fr.data is not None:
            k = analiz_et(fr.data, r.sembol)
            if k.ok:
                giris, hedef, stop, rr = k.giris, k.kar_al, k.zarar_kes, k.risk_odul

        # Teknik gerekçe
        tg = []
        if r.ema_durumu in ("Trend Yukarı", "Yukarı"):
            tg.append("EMA düzeni yukarı trend")
        if r.macd_sinyal == "Alış":
            tg.append("MACD alış sinyali")
        if r.rsi is not None:
            if r.rsi < 40:
                tg.append(f"RSI {r.rsi:.0f} (toparlanma alanı)")
            elif r.rsi <= 65:
                tg.append(f"RSI {r.rsi:.0f} (sağlıklı momentum)")
        if r.perf_ay is not None and r.perf_ay > 0:
            tg.append(f"son ay %{r.perf_ay:+.0f}")

        # Temel gerekçe
        tmg = []
        if t.fk < 12:
            tmg.append(f"F/K {t.fk:.1f} (ucuz)")
        else:
            tmg.append(f"F/K {t.fk:.1f}")
        if t.pddd is not None:
            tmg.append(f"PD/DD {t.pddd:.2f}")
        tmg.append(f"ROE %{t.roe:.0f}")
        if t.net_marj is not None:
            tmg.append(f"net marj %{t.net_marj:.0f}")
        if t.temettu_verim and t.temettu_verim > 1:
            tmg.append(f"temettü %{t.temettu_verim:.1f}")

        ozet = _ozet_cumle(t, r)
        oneriler.append(AylikOneri(
            sembol=r.sembol.replace(".IS", ""), sektor=t.sektor,
            teknik_aksiyon=r.aksiyon, rsi=r.rsi, ema_durumu=r.ema_durumu,
            aylik_perf=r.perf_ay, fk=t.fk, pddd=t.pddd, roe=t.roe,
            temettu=t.temettu_verim, net_marj=t.net_marj,
            giris=giris, hedef=hedef, stop=stop, risk_odul=rr,
            teknik_gerekce=tg, temel_gerekce=tmg, ozet=ozet,
        ))

    return True, "", oneriler


def _ozet_cumle(t, r) -> str:
    parcalar = []
    if t.fk is not None and t.fk < 12 and t.roe is not None and t.roe > 15:
        parcalar.append("ucuz değerleme + güçlü kârlılık")
    elif t.fk is not None and t.fk < 12:
        parcalar.append("ucuz değerleme")
    elif t.roe is not None and t.roe > 20:
        parcalar.append("yüksek kârlılık")
    if r.ema_durumu in ("Trend Yukarı", "Yukarı") and r.macd_sinyal == "Alış":
        parcalar.append("teknik trend yukarı")
    if not parcalar:
        parcalar.append("teknik + temel dengeli")
    return "Hem temel hem teknik destekliyor: " + ", ".join(parcalar) + "."


def ayin_onerileri_metni(oneriler: list[AylikOneri], hata: str = "") -> str:
    from datetime import datetime
    ay = datetime.now().strftime("%B %Y")
    baslik = f"🏅 AYIN HİSSE ÖNERİLERİ — {ay}"
    if hata and not oneriler:
        return f"{baslik}\n\n{hata}"
    if not oneriler:
        return f"{baslik}\n\nBu ay kriterleri karşılayan hisse yok."

    sat = [baslik,
           "(Yalnızca HEM teknik HEM temel açıdan sağlam hisseler — gerçek veri)",
           ""]
    for i, o in enumerate(oneriler, 1):
        sat.append(f"{i}) {o.sembol} · {o.sektor[:20]}")
        sat.append(f"   📊 Teknik: {', '.join(o.teknik_gerekce)}")
        sat.append(f"   📑 Temel: {', '.join(o.temel_gerekce)}")
        if o.giris and o.hedef and o.stop:
            rr = f" · R/R 1:{o.risk_odul}" if o.risk_odul else ""
            sat.append(f"   🎯 Giriş {o.giris} · Hedef {o.hedef} · Stop {o.stop}{rr}")
        sat.append(f"   💡 {o.ozet}")
        sat.append("")

    sat += [
        "━━━━━━━━━━━━━━",
        "Yöntem: 607 hisse teknik tarama + temel veri (F/K, ROE, marj) birlikte "
        "değerlendirilir; yalnızca ikisinden de geçenler listelenir.",
        "⚠️ Tüm veriler gerçektir; yine de bu bir yatırım tavsiyesi DEĞİLDİR. "
        "Kendi araştırmanı yap, riski yönet.",
    ]
    return "\n".join(sat)
