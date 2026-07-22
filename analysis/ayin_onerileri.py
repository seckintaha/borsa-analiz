"""
Ayın Hisse Önerileri — ÇOK-FAKTÖRLÜ QUANT MOTORU (profesyonel seviye).

Basit eşik filtresinden, tüm BIST evrenini kesitsel (cross-section) sıralayan
çok-faktörlü bir modele geçildi. Motor (analysis/faktor.py) kanıtlanmış
yöntemleri uygular:

  • ÇOK-FAKTÖR (Fama-French/AQR): Kalite %30, Değer %25, Momentum %20,
    Büyüme %15, Trend/giriş %10 — her faktör evren içinde persentil (0-100).
  • PIOTROSKI F-Score (0-9): bilanço sağlamlığının ayrık kontrolü.
  • GREENBLATT MAGIC FORMULA: kazanç verimi + ROIC ortak sırası.

Kullanıcı felsefesi KORUNUR: "tavan yapmış/uçmuş" hisse KOVALANMAZ. Momentum
faktörü RSI>65 ve aşırı aylık getiride köpük cezasıyla kırpılır; ayrıca
RSI>70 / aşırı performans / değer tuzağı / düşük likidite olan hisseler
tamamen elenir. Böylece kaliteli + faktörsel güçlü + makul giriş sunan
hisseler öne çıkar.

Veri gerçektir (TradingView + yfinance). Eksik veri UYDURULMAZ — hisse elenir.
Fonksiyon imzaları (ayin_onerileri, ayin_onerileri_metni) bot & notify için
KORUNMUŞTUR.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# Filtre eşikleri (evren daraltma — köpük/tuzak/likidite/oynaklık eleme)
_MIN_PIYASA_DEGERI = 5e8      # ~500M TL altı: likidite riski, ele (300M'den sıkılaştırıldı)
_RSI_KOPUK = 70              # RSI>70: aşırı alım köpüğü, tamamen ele
_PERF_AY_KOPUK = 35         # son ay %35+: parabolik/tavan, ele
_MIN_BIRLESIK = 55          # birleşik faktör skoru bu altındaysa önerilmez
_MAX_YILLIK_OYNAKLIK = 65.0  # son 6 ay yıllık vol %65 üstü: aşırı oynak, ele
                             # — tutarsızlığı azaltır (kazan/kaybet uçları biner)


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
    # Profesyonel faktör kırılımı (yeni)
    deger_p: Optional[float] = None
    kalite_p: Optional[float] = None
    momentum_p: Optional[float] = None
    buyume_p: Optional[float] = None
    trend_p: Optional[float] = None
    birlesik: float = 0.0
    piotroski: int = 0
    piotroski_n: int = 0
    magic_sira: Optional[int] = None
    rejim_notu: str = ""              # rejim-duyarlı ağırlık açıklaması


def _getiri_yuzde(fr, gun: int) -> Optional[float]:
    """yfinance geçmişinden ~gun gün önceki kapanışa göre getiri %; veri yoksa None."""
    try:
        if not fr.ok or fr.data is None:
            return None
        kapanis = fr.data["Close"].dropna()
        if len(kapanis) < gun + 1:
            return None
        son = float(kapanis.iloc[-1])
        onceki = float(kapanis.iloc[-(gun + 1)])
        if onceki <= 0:
            return None
        return (son / onceki - 1.0) * 100.0
    except Exception:
        return None


def ayin_onerileri(db_path: str, n: int = 10) -> tuple[bool, str, list["AylikOneri"]]:
    from data.tv_scanner import tv_tara, tv_kalite_tara
    from analysis.kalite import kalite_skoru
    from analysis.teknik_derin import analiz_et
    from analysis.faktor import faktor_evreni, EvrenGirdi, rejim_agirliklari
    from data.access import veri_getir

    tv_ok, tv_hata, tv_satirlar = tv_tara(limit=1000)
    if not tv_ok:
        return False, f"Tarama hatası: {tv_hata}", []
    kal_ok, kal_hata, kal_liste = tv_kalite_tara(limit=1000)
    if not kal_ok:
        return False, f"Kalite verisi hatası: {kal_hata}", []

    tv_map = {s.sembol: s for s in tv_satirlar}

    # ── Rejim-duyarlı faktör ağırlıkları (top-down): küresel risk + BIST rejimi ──
    risk_skoru = 0
    bist_rejim = ""
    try:
        from analysis.kuresel_piyasa import kuresel_nabiz
        kn = kuresel_nabiz()
        risk_skoru = kn.risk_skoru if kn.ok else 0
    except Exception:
        pass
    try:
        import config
        from analysis import macro
        fr_x = veri_getir(db_path, config.MACRO.get("rejim_endeksi", "XU100.IS"),
                          period="2y", interval="1d")
        if fr_x.ok and fr_x.data is not None:
            bist_rejim = macro.rejim_tespit(fr_x.data).rejim
    except Exception:
        pass
    agirliklar, rejim_notu = rejim_agirliklari(risk_skoru, bist_rejim)

    # ── 1) Evreni oluştur (min likidite filtresi; teknik veri eşleştir) ──
    girdiler: list[EvrenGirdi] = []
    for k in kal_liste:
        if k.piyasa_degeri is not None and k.piyasa_degeri < _MIN_PIYASA_DEGERI:
            continue
        t = tv_map.get(k.sembol)
        girdiler.append(EvrenGirdi(sembol=k.sembol, kalite=k, teknik=t))

    if not girdiler:
        return True, "Evrende yeterli veri yok.", []

    # ── 2) Kesitsel faktör motorunu REJİM-DUYARLI ağırlıkla çalıştır ──
    kayitlar = faktor_evreni(girdiler, agirliklar=agirliklar)
    kayit_map = {r.sembol: r for r in kayitlar}

    # Bilanço momentum haritası (çeyreklik kâr çöküşü = gizli değer tuzağı).
    # Tek istekte tüm evren; veri yoksa boş → eleme yapılmaz (güvenli).
    bilanco_map = {}
    try:
        from data.tv_scanner import tv_bilanco_tara
        okb, _hb, blist = tv_bilanco_tara(limit=1000)
        if okb:
            bilanco_map = {b.sembol: b for b in blist}
    except Exception:
        bilanco_map = {}

    # ── 3) Köpük/tuzak/likidite eleme + faktör eşiği ──
    adaylar = []
    for k in kal_liste:
        kod = k.sembol.replace(".IS", "")
        r = kayit_map.get(kod)
        if r is None:
            continue
        t = tv_map.get(k.sembol)

        ks = kalite_skoru(k)
        if ks.etiket == "veri yok" or ks.deger_tuzagi:
            continue                                    # değer tuzağı ele

        # Çeyreklik kâr çöküşü = gizli değer tuzağı (ucuz F/K'ya kanma).
        # Yıllık çeyrek EPS büyümesi çok negatifse (kâr yapısal düşüyor) ele.
        b = bilanco_map.get(k.sembol)
        if b is not None and b.eps_yoy is not None and b.eps_yoy < -30:
            continue

        # Köpük/tavan eleme (kullanıcı: uçmuş hisse istemiyorum)
        rsi = t.rsi if t is not None else None
        perf_ay = (t.perf_ay if t is not None else k.perf_1m)
        if rsi is not None and rsi > _RSI_KOPUK:
            continue
        if perf_ay is not None and perf_ay > _PERF_AY_KOPUK:
            continue

        # Faktörsel güç eşiği
        if r.birlesik < _MIN_BIRLESIK:
            continue
        # Trend: düşen bıçağı ele (uzun vade tümüyle aşağı ise geç)
        if r.trend_p is not None and r.trend_p == 0.0:
            continue

        adaylar.append((r, k, ks, t))

    if not adaylar:
        return True, ("Bu ay faktörsel olarak güçlü + köpük olmayan + tuzak olmayan "
                      "hisse yok. (Piyasa geneli pahalı/aşırı alım olabilir.)"), []

    adaylar.sort(key=lambda x: -x[0].birlesik)

    # ── 4) Sektör çeşitliliği + OYNAKLIK filtresi + teknik giriş/hedef/stop ──
    oneriler: list[AylikOneri] = []
    sektor_sayac: dict[str, int] = {}
    for r, k, ks, t in adaylar:
        if len(oneriler) >= n:
            break
        if sektor_sayac.get(k.sektor, 0) >= 3:
            continue

        # yfinance ile giriş/hedef/stop + oynaklık
        fr = veri_getir(db_path, k.sembol, period="1y", interval="1d")
        giris = hedef = stop = rr = None
        if fr.ok and fr.data is not None:
            # OYNAKLIK FİLTRESİ: aşırı oynak (yıllık vol > eşik) hisse tutarsızlık
            # kaynağıdır — kaliteli de olsa elenir (kazan-kaybet kumarhanesi olmasın).
            try:
                import numpy as _np
                # Son ~6 ay (126 işlem günü) — güncel oynaklık, eski sakin
                # dönem aşırı oynak hisseyi maskelemesin.
                _ret = fr.data["Close"].pct_change().dropna().iloc[-126:]
                if len(_ret) > 30:
                    _vol = float(_ret.std() * _np.sqrt(252) * 100)
                    if _vol > _MAX_YILLIK_OYNAKLIK:
                        continue
            except Exception:
                pass
            kd = analiz_et(fr.data, k.sembol)
            if kd.ok:
                giris, hedef, stop, rr = kd.giris, kd.kar_al, kd.zarar_kes, kd.risk_odul

        sektor_sayac[k.sektor] = sektor_sayac.get(k.sektor, 0) + 1

        # Bollinger giriş konumu (varsa)
        bpoz = None
        if t is not None and t.bb_ust and t.bb_alt and t.fiyat and t.bb_ust > t.bb_alt:
            bpoz = (t.fiyat - t.bb_alt) / (t.bb_ust - t.bb_alt)

        gg = _giris_gerekce(r, t, bpoz)
        tmg = _temel_gerekce(r, k, ks)

        oneriler.append(AylikOneri(
            sembol=r.sembol, sektor=k.sektor,
            rsi=r.rsi, aylik_perf=r.perf_ay, bollinger_poz=bpoz,
            kalite_skor=ks.skor, fk=k.fk, roe=k.roe,
            giris=giris, hedef=hedef, stop=stop, risk_odul=rr,
            giris_gerekce=gg, temel_gerekce=tmg, ozet=_ozet_faktor(r, ks),
            deger_p=r.deger_p, kalite_p=r.kalite_p, momentum_p=r.momentum_p,
            buyume_p=r.buyume_p, trend_p=r.trend_p, birlesik=r.birlesik,
            piotroski=r.piotroski, piotroski_n=r.piotroski_n,
            magic_sira=r.magic_sira, rejim_notu=rejim_notu,
        ))

    return True, "", oneriler


def _p(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.0f}"


def _giris_gerekce(r, t, bpoz) -> list:
    gg = []
    if bpoz is not None and bpoz < 0.4:
        gg.append("Bollinger ALT bölgesinde (ucuz giriş)")
    elif bpoz is not None and bpoz < 0.6:
        gg.append("Bollinger orta-alt (makul giriş)")
    if r.rsi is not None:
        gg.append(f"RSI {r.rsi:.0f} (aşırı alım değil)")
    if r.perf_ay is not None:
        gg.append(f"son ay %{r.perf_ay:+.0f} (uçmamış)")
    if r.kopuk_carpan < 0.95:
        gg.append("momentum köpük-cezalı (tavan riski kırpıldı)")
    return gg or ["makul giriş bölgesi"]


def _temel_gerekce(r, k, ks) -> list:
    tmg = [f"kalite {ks.skor}/100"]
    if k.fk is not None:
        tmg.append(f"F/K {k.fk:.1f}")
    if k.roe is not None:
        tmg.append(f"ROE %{k.roe:.0f}")
    if k.net_kar_buyume is not None:
        tmg.append(f"net kâr büy %{k.net_kar_buyume:.0f}")
    if k.temettu and k.temettu > 1:
        tmg.append(f"temettü %{k.temettu:.1f}")
    return tmg


def _ozet_faktor(r, ks) -> str:
    p = []
    if r.kalite_p is not None and r.kalite_p >= 70:
        p.append("kalite lideri")
    elif ks.skor >= 60:
        p.append("sağlam temel")
    if r.deger_p is not None and r.deger_p >= 65:
        p.append("ucuz değerleme")
    if r.momentum_p is not None and r.momentum_p >= 45 and r.kopuk_carpan >= 0.9:
        p.append("sağlıklı momentum (uçmamış)")
    if r.piotroski_n >= 5 and r.piotroski >= 7:
        p.append(f"Piotroski {r.piotroski}/{r.piotroski_n} güçlü")
    if r.magic_sira is not None and r.magic_sira <= 30:
        p.append(f"Magic Formula #{r.magic_sira}")
    if not p:
        p.append("faktörsel dengeli")
    return "Faktörsel güçlü + makul giriş — " + ", ".join(p) + "."


def _ozet(k, ks, bpoz, s) -> str:
    """Geriye dönük uyumluluk (eski test/çağrı için korundu)."""
    p = []
    if getattr(ks, "skor", 0) >= 75:
        p.append("yüksek kalite")
    else:
        p.append("sağlam temel")
    if bpoz is not None and bpoz < 0.4:
        p.append("dip/geri çekilme bölgesinde")
    if getattr(s, "rsi", None) is not None and s.rsi < 50:
        p.append("henüz pahalanmamış")
    if getattr(k, "fk", None) is not None and k.fk < 12:
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

    rejim_notu = getattr(oneriler[0], "rejim_notu", "") if oneriler else ""
    sat = [baslik,
           "(Çok-faktör: Kalite+Değer+Momentum+Büyüme+Trend · köpük/tavan elenir)"]
    if rejim_notu:
        sat.append(rejim_notu)     # rejim-duyarlı ağırlık (top-down)
    sat.append("")
    for i, o in enumerate(oneriler, 1):
        sat.append(f"{i}) {o.sembol} · {o.sektor[:20]} · faktör skor {o.birlesik:.0f}/100")
        # Profesyonel faktör kırılımı
        pio = f"Piotroski {o.piotroski}/{o.piotroski_n}" if o.piotroski_n else "Piotroski —"
        mf = f" · Magic Formula #{o.magic_sira}" if o.magic_sira else ""
        sat.append(
            f"   📊 Değer {_p(o.deger_p)} · Kalite {_p(o.kalite_p)} · "
            f"Momentum {_p(o.momentum_p)} · Büyüme {_p(o.buyume_p)} · Trend {_p(o.trend_p)} (persentil)"
        )
        sat.append(f"   🧮 {pio}{mf} · kalite {o.kalite_skor}/100")
        sat.append(f"   🎯 Giriş noktası: {', '.join(o.giris_gerekce)}")
        sat.append(f"   📑 Temel: {', '.join(o.temel_gerekce)}")
        if o.giris and o.hedef and o.stop:
            rr = f" · R/R 1:{o.risk_odul}" if o.risk_odul else ""
            sat.append(f"   📐 Giriş {o.giris} · Hedef {o.hedef} · Stop {o.stop}{rr}")
        sat.append(f"   💡 {o.ozet}")
        sat.append("")

    sat += [
        "━━━━━━━━━━━━━━",
        "Yöntem: tüm BIST evreni kesitsel sıralanır (persentil). Çok-faktör harman "
        "(Kalite %30, Değer %25, Momentum %20, Büyüme %15, Trend %10) + Piotroski "
        "F-Score + Greenblatt Magic Formula. RSI>65/aşırı getiri momentum'u kırpar, "
        "RSI>70 / aşırı performans / değer tuzağı elenir.",
        "⚠️ 'Yükselecek' garantisi DEĞİL — faktörsel olarak güçlü + makul giriş "
        "demektir. Riski yönet, yatırım tavsiyesi değildir.",
    ]
    return "\n".join(sat)
