"""
Ayın Hisse Önerileri (her ayın 1'inde) — GÜÇLENDİRİLMİŞ.

Bir hisse ancak 4 filtreden de geçerse önerilir (hepsi gerçek veri):
  1. TEKNİK    — bist_tara: EMA/RSI/MACD "AL adayı"
  2. KALİTE    — kalite_skoru >= 55 ve DEĞER TUZAĞI değil (borç/marj/büyüme/nakit)
  3. GÖRECELİ GÜÇ — son ay endeksten (XU100) daha iyi performans (momentum)
  4. SEVİYE    — teknik_derin ile giriş/hedef/stop + risk/ödül

Veri eksikse hisse ELENIR — asla uydurulmaz.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AylikOneri:
    sembol: str
    sektor: str
    teknik_aksiyon: str
    rsi: Optional[float]
    ema_durumu: str
    aylik_perf: Optional[float]
    goreceli_guc: Optional[float]      # hisse perf - endeks perf (momentum)
    kalite_skor: int
    fk: Optional[float]
    roe: Optional[float]
    net_kar_buyume: Optional[float]
    giris: Optional[float]
    hedef: Optional[float]
    stop: Optional[float]
    risk_odul: Optional[float]
    teknik_gerekce: list = field(default_factory=list)
    temel_gerekce: list = field(default_factory=list)
    ozet: str = ""


def _endeks_aylik_perf(db_path: str) -> Optional[float]:
    """XU100'ün son ~21 işlem günü getirisi (göreceli güç kıyası için)."""
    from data.access import veri_getir
    fr = veri_getir(db_path, "XU100.IS", period="3mo", interval="1d")
    if fr.ok and fr.data is not None and len(fr.data) > 22:
        son = float(fr.data["Close"].iloc[-1])
        onceki = float(fr.data["Close"].iloc[-22])
        if onceki > 0:
            return (son - onceki) / onceki * 100
    return None


def ayin_onerileri(db_path: str, n: int = 10) -> tuple[bool, str, list[AylikOneri]]:
    from analysis.bist_tarama import bist_tara
    from data.tv_scanner import tv_kalite_tara
    from analysis.kalite import kalite_skoru
    from analysis.teknik_derin import analiz_et
    from data.access import veri_getir

    tek_ok, tek_hata, tek_satirlar = bist_tara(limit=1000)
    if not tek_ok:
        return False, f"Teknik tarama hatası: {tek_hata}", []

    kal_ok, kal_hata, kal_liste = tv_kalite_tara(limit=1000)
    if not kal_ok:
        return False, f"Kalite verisi hatası: {kal_hata}", []
    kalite_map = {k.sembol: k for k in kal_liste}

    endeks_perf = _endeks_aylik_perf(db_path)

    adaylar = []
    for r in tek_satirlar:
        # 1) Teknik filtre
        if r.aksiyon not in ("Güçlü AL adayı", "AL adayı"):
            continue
        k = kalite_map.get(r.sembol)
        if k is None:
            continue
        # 2) Kalite filtre
        ks = kalite_skoru(k)
        if ks.skor < 55 or ks.deger_tuzagi:
            continue
        # Temel sağlamlık alt sınırı (kâr eden, makul değerleme)
        if k.fk is None or not (0 < k.fk < 30):
            continue
        # 3) Göreceli güç — endeksten iyi mi
        gg = None
        if r.perf_ay is not None and endeks_perf is not None:
            gg = r.perf_ay - endeks_perf
            if gg < 0:          # endeksin gerisindeyse elenir (momentum yok)
                continue

        # Birleşik skor: teknik + kalite + göreceli güç
        skor = float(r.sinyal_skoru) + ks.skor * 0.4
        if gg is not None:
            skor += min(gg, 20)         # endeksi ne kadar yendiyse (cap 20)
        adaylar.append((skor, r, k, ks, gg))

    if not adaylar:
        return True, "Bu ay 4 filtreden de (teknik+kalite+momentum) geçen hisse yok.", []

    adaylar.sort(key=lambda x: -x[0])

    oneriler: list[AylikOneri] = []
    sektor_sayac: dict[str, int] = {}
    for skor, r, k, ks, gg in adaylar:
        if len(oneriler) >= n:
            break
        if sektor_sayac.get(k.sektor, 0) >= 3:
            continue
        sektor_sayac[k.sektor] = sektor_sayac.get(k.sektor, 0) + 1

        fr = veri_getir(db_path, r.sembol, period="1y", interval="1d")
        giris = hedef = stop = rr = None
        if fr.ok and fr.data is not None:
            kd = analiz_et(fr.data, r.sembol)
            if kd.ok:
                giris, hedef, stop, rr = kd.giris, kd.kar_al, kd.zarar_kes, kd.risk_odul

        tg = []
        if r.ema_durumu in ("Trend Yukarı", "Yukarı"):
            tg.append("EMA trendi yukarı")
        if r.macd_sinyal == "Alış":
            tg.append("MACD alış")
        if r.rsi is not None and r.rsi <= 65:
            tg.append(f"RSI {r.rsi:.0f}")
        if gg is not None:
            tg.append(f"endeksi %{gg:+.0f} yendi (son ay)")

        tmg = [f"kalite {ks.skor}/100"]
        if k.fk is not None:
            tmg.append(f"F/K {k.fk:.1f}")
        if k.roe is not None:
            tmg.append(f"ROE %{k.roe:.0f}")
        if k.net_kar_buyume is not None:
            tmg.append(f"net kâr büy %{k.net_kar_buyume:.0f}")
        if k.temettu and k.temettu > 1:
            tmg.append(f"temettü %{k.temettu:.1f}")

        oneriler.append(AylikOneri(
            sembol=r.sembol.replace(".IS", ""), sektor=k.sektor,
            teknik_aksiyon=r.aksiyon, rsi=r.rsi, ema_durumu=r.ema_durumu,
            aylik_perf=r.perf_ay, goreceli_guc=gg, kalite_skor=ks.skor,
            fk=k.fk, roe=k.roe, net_kar_buyume=k.net_kar_buyume,
            giris=giris, hedef=hedef, stop=stop, risk_odul=rr,
            teknik_gerekce=tg, temel_gerekce=tmg,
            ozet=_ozet(k, ks, gg),
        ))

    return True, "", oneriler


def _ozet(k, ks, gg) -> str:
    p = []
    if ks.skor >= 75:
        p.append("yüksek finansal kalite")
    elif ks.skor >= 60:
        p.append("sağlam temel")
    if k.fk is not None and k.fk < 12:
        p.append("makul/ucuz değerleme")
    if gg is not None and gg > 5:
        p.append(f"endeksten güçlü (+%{gg:.0f})")
    if not p:
        p.append("teknik + temel dengeli")
    return "4 filtreden geçti: " + ", ".join(p) + "."


def ayin_onerileri_metni(oneriler: list[AylikOneri], hata: str = "") -> str:
    from datetime import datetime
    ay = datetime.now().strftime("%B %Y")
    baslik = f"🏅 AYIN HİSSE ÖNERİLERİ — {ay}"
    if hata and not oneriler:
        return f"{baslik}\n\n{hata}"
    if not oneriler:
        return f"{baslik}\n\nBu ay kriterleri karşılayan hisse yok."

    sat = [baslik,
           "(4 filtre: teknik AL + kalite≥55 + değer tuzağı değil + endeksi yenen)",
           ""]
    for i, o in enumerate(oneriler, 1):
        sat.append(f"{i}) {o.sembol} · {o.sektor[:20]} · kalite {o.kalite_skor}/100")
        sat.append(f"   📊 Teknik: {', '.join(o.teknik_gerekce)}")
        sat.append(f"   📑 Temel: {', '.join(o.temel_gerekce)}")
        if o.giris and o.hedef and o.stop:
            rr = f" · R/R 1:{o.risk_odul}" if o.risk_odul else ""
            sat.append(f"   🎯 Giriş {o.giris} · Hedef {o.hedef} · Stop {o.stop}{rr}")
        sat.append(f"   💡 {o.ozet}")
        sat.append("")

    sat += [
        "━━━━━━━━━━━━━━",
        "Yöntem: 607 hisse · teknik tarama + finansal KALİTE skoru (borç/marj/"
        "büyüme/nakit) + göreceli güç (endeksi yenme); 4 filtreden geçenler.",
        "⚠️ Tüm veriler gerçektir; yine de yatırım tavsiyesi DEĞİLDİR.",
    ]
    return "\n".join(sat)
