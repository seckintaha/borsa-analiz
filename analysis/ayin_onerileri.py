"""
Ayın Hisse Önerileri — "İYİ GİRİŞ" felsefesi (tepeden alım DEĞİL).

Kullanıcı geri bildirimi: "zaten çok yükselmiş hisse istemiyorum, iyi giriş
noktasındaki hisse istiyorum." Bu yüzden motor artık momentum KOVALAMAZ.

Bir hisse ancak şu 4 şartı da sağlarsa önerilir (hepsi gerçek veri):
  1. KALİTE      — kalite_skoru >= 60, değer tuzağı DEĞİL (sağlam bilanço)
  2. AŞIRI ALIM DEĞİL — RSI 35-58 (nötr/toparlanma), zaten uçmuş değil
  3. UZUN VADE SAĞLAM — EMA50>EMA200 ya da fiyat>EMA200 (düşen bıçak değil)
  4. İYİ GİRİŞ    — Bollinger alt bölgesinde / geri çekilmiş / desteğe yakın

Böylece: kaliteli ama HENÜZ PAHALANMAMIŞ, geri çekilme/dip bölgesindeki
hisseler öne çıkar. Bu "yükselecek" garantisi DEĞİL — daha iyi giriş noktası.
Veri eksikse hisse elenir; asla uydurulmaz.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AylikOneri:
    sembol: str
    sektor: str
    rsi: Optional[float]
    aylik_perf: Optional[float]
    bollinger_poz: Optional[float]     # 0=alt bant, 1=üst bant
    kalite_skor: int
    fk: Optional[float]
    roe: Optional[float]
    giris: Optional[float]
    hedef: Optional[float]
    stop: Optional[float]
    risk_odul: Optional[float]
    giris_gerekce: list = field(default_factory=list)
    temel_gerekce: list = field(default_factory=list)
    ozet: str = ""


def ayin_onerileri(db_path: str, n: int = 10) -> tuple[bool, str, list["AylikOneri"]]:
    from data.tv_scanner import tv_tara, tv_kalite_tara
    from analysis.kalite import kalite_skoru
    from analysis.teknik_derin import analiz_et
    from data.access import veri_getir

    tv_ok, tv_hata, tv_satirlar = tv_tara(limit=1000)
    if not tv_ok:
        return False, f"Tarama hatası: {tv_hata}", []
    kal_ok, kal_hata, kal_liste = tv_kalite_tara(limit=1000)
    if not kal_ok:
        return False, f"Kalite verisi hatası: {kal_hata}", []
    kal_map = {k.sembol: k for k in kal_liste}

    adaylar = []
    for s in tv_satirlar:
        k = kal_map.get(s.sembol)
        if k is None:
            continue

        # 1) Kalite
        ks = kalite_skoru(k)
        if ks.skor < 60 or ks.deger_tuzagi:
            continue
        if k.fk is None or not (0 < k.fk < 30):
            continue

        # Zorunlu teknik veriler
        if s.rsi is None or s.fiyat is None or s.ema50 is None or s.ema200 is None:
            continue

        # 2) Aşırı alım DEĞİL — zaten uçmuş olanı ele
        if not (35 <= s.rsi <= 58):
            continue
        if s.perf_ay is not None and s.perf_ay > 15:   # son ay %15+ artmışsa "kaçırıldı"
            continue

        # 3) Uzun vade sağlam (düşen bıçak değil)
        if not (s.ema50 > s.ema200 or s.fiyat > s.ema200):
            continue

        # 4) İyi giriş skoru — Bollinger'da alt bölge + RSI tatlı nokta + desteğe yakın
        bpoz = None
        entry = 0.0
        if s.bb_ust and s.bb_alt and s.bb_ust > s.bb_alt:
            bpoz = (s.fiyat - s.bb_alt) / (s.bb_ust - s.bb_alt)
            entry += max(0.0, (0.6 - bpoz)) * 40     # bandın alt yarısı = iyi giriş
        entry += max(0.0, 15 - abs(s.rsi - 45))       # RSI ~45 en iyi (toparlanma)
        if s.fiyat >= s.ema50 and (s.fiyat - s.ema50) / s.ema50 < 0.06:
            entry += 10                                # yükselen 50-ort desteğine yakın

        skor = ks.skor * 0.3 + entry
        adaylar.append((skor, s, k, ks, bpoz))

    if not adaylar:
        return True, ("Bu ay 'kaliteli + aşırı alım değil + iyi giriş' kriterlerine "
                      "uyan hisse yok. (Piyasa geneli pahalı/aşırı alım olabilir.)"), []

    adaylar.sort(key=lambda x: -x[0])

    oneriler: list[AylikOneri] = []
    sektor_sayac: dict[str, int] = {}
    for skor, s, k, ks, bpoz in adaylar:
        if len(oneriler) >= n:
            break
        if sektor_sayac.get(k.sektor, 0) >= 3:
            continue
        sektor_sayac[k.sektor] = sektor_sayac.get(k.sektor, 0) + 1

        fr = veri_getir(db_path, s.sembol, period="1y", interval="1d")
        giris = hedef = stop = rr = None
        if fr.ok and fr.data is not None:
            kd = analiz_et(fr.data, s.sembol)
            if kd.ok:
                giris, hedef, stop, rr = kd.giris, kd.kar_al, kd.zarar_kes, kd.risk_odul

        gg = []
        if bpoz is not None and bpoz < 0.4:
            gg.append("Bollinger ALT bölgesinde (ucuz giriş)")
        elif bpoz is not None and bpoz < 0.6:
            gg.append("Bollinger orta-alt (makul giriş)")
        gg.append(f"RSI {s.rsi:.0f} (aşırı alım değil)")
        if s.perf_ay is not None:
            gg.append(f"son ay %{s.perf_ay:+.0f} (uçmamış)")
        if s.ema50 and s.fiyat >= s.ema50 and (s.fiyat - s.ema50) / s.ema50 < 0.06:
            gg.append("yükselen 50-ort desteğinde")

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
            sembol=s.sembol.replace(".IS", ""), sektor=k.sektor,
            rsi=s.rsi, aylik_perf=s.perf_ay, bollinger_poz=bpoz,
            kalite_skor=ks.skor, fk=k.fk, roe=k.roe,
            giris=giris, hedef=hedef, stop=stop, risk_odul=rr,
            giris_gerekce=gg, temel_gerekce=tmg, ozet=_ozet(k, ks, bpoz, s),
        ))

    return True, "", oneriler


def _ozet(k, ks, bpoz, s) -> str:
    p = []
    if ks.skor >= 75:
        p.append("yüksek kalite")
    else:
        p.append("sağlam temel")
    if bpoz is not None and bpoz < 0.4:
        p.append("dip/geri çekilme bölgesinde")
    if s.rsi is not None and s.rsi < 50:
        p.append("henüz pahalanmamış")
    if k.fk is not None and k.fk < 12:
        p.append("ucuz değerleme")
    return "Kaliteli ama uçmamış — " + ", ".join(p) + "."


def ayin_onerileri_metni(oneriler: list["AylikOneri"], hata: str = "") -> str:
    from datetime import datetime
    ay = datetime.now().strftime("%B %Y")
    baslik = f"🏅 AYIN HİSSE ÖNERİLERİ — {ay}"
    if hata and not oneriler:
        return f"{baslik}\n\n{hata}"
    if not oneriler:
        return f"{baslik}\n\nBu ay kriterleri karşılayan hisse yok."

    sat = [baslik,
           "(Kaliteli + aşırı alım DEĞİL + iyi giriş — 'zaten uçmuş' hisse değil)",
           ""]
    for i, o in enumerate(oneriler, 1):
        sat.append(f"{i}) {o.sembol} · {o.sektor[:20]} · kalite {o.kalite_skor}/100")
        sat.append(f"   🎯 Giriş noktası: {', '.join(o.giris_gerekce)}")
        sat.append(f"   📑 Temel: {', '.join(o.temel_gerekce)}")
        if o.giris and o.hedef and o.stop:
            rr = f" · R/R 1:{o.risk_odul}" if o.risk_odul else ""
            sat.append(f"   📐 Giriş {o.giris} · Hedef {o.hedef} · Stop {o.stop}{rr}")
        sat.append(f"   💡 {o.ozet}")
        sat.append("")

    sat += [
        "━━━━━━━━━━━━━━",
        "Yöntem: kaliteli (borç/marj/büyüme sağlam) + RSI 35-58 (aşırı alım değil) "
        "+ uzun vade trend sağlam + Bollinger alt bölge = daha iyi giriş noktası.",
        "⚠️ 'Yükselecek' garantisi DEĞİL — daha iyi giriş demektir. Riski yönet, "
        "yatırım tavsiyesi değildir.",
    ]
    return "\n".join(sat)
