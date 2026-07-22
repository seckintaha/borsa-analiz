"""
Olay / bilanço takvimi farkındalığı (senior analist perspektifi).

Yaklaşan bilanço ve temettü olaylarını yfinance'ten tespit eder. Bilanço
öncesi oynaklık artar; portföydeki hisselerin takvimini bilmek risk yönetimi
açısından kritiktir.

VERİ ASLA UYDURULMAZ: yfinance BIST hisselerinde bilanço tarihini çoğu zaman
VERMEZ. O durumda None döner / "takvim verisi yok" denir — asla tahmini tarih
üretilmez.

API:
  yaklasan_bilanco(sembol)   → Optional[dict]  {tarih, gun_kaldi}
  temettu_bilgisi(sembol)    → Optional[dict]  {tarih, tutar, tur}
  portfoy_olaylari(db_path)  → list[str]       15 gün içi bilanço uyarıları
  olaylar_metni(db_path)     → str             Telegram metni
"""

from __future__ import annotations
from datetime import datetime, date
from typing import Optional


def _normalize(sembol: str) -> str:
    """cmd_analiz'deki kural: büyük harf, nokta yoksa ve harf+≤5 ise .IS ekle."""
    sem = (sembol or "").strip().upper()
    if not sem.endswith(".IS") and sem.isalpha() and len(sem) <= 5:
        sem += ".IS"
    return sem


def _bugun() -> date:
    return datetime.now().date()


def _tarihe_cevir(deger) -> Optional[date]:
    """yfinance'ten gelen çeşitli tarih tiplerini date'e çevirir; olmazsa None."""
    if deger is None:
        return None
    # pandas.Timestamp / datetime
    try:
        if hasattr(deger, "date") and callable(getattr(deger, "date")):
            return deger.date()
    except Exception:
        pass
    if isinstance(deger, datetime):
        return deger.date()
    if isinstance(deger, date):
        return deger
    # string
    if isinstance(deger, str):
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
            try:
                return datetime.strptime(deger[:19], fmt).date()
            except Exception:
                continue
    return None


def _tv_bilanco_tarih(sembol: str) -> Optional[dict]:
    """
    TradingView'dan sonraki bilanço tarihini çeker (BIST'te yfinance'ten çok
    daha güvenilir). Döner: {tarih, gun_kaldi, son_bilanco, eps_qoq, ...} veya None.
    """
    try:
        from data.tv_scanner import tv_bilanco_tara
        kod = _normalize(sembol).replace(".IS", "")
        ok, _h, liste = tv_bilanco_tara(tickers=[f"BIST:{kod}"])
        if not ok or not liste:
            return None
        b = liste[0]
        bugun = _bugun()
        out = {"eps_qoq": b.eps_qoq, "eps_yoy": b.eps_yoy, "gelir_qoq": b.gelir_qoq}
        if b.son_bilanco_ts:
            out["son_bilanco"] = datetime.fromtimestamp(b.son_bilanco_ts).date().isoformat()
        if b.sonraki_bilanco_ts:
            nd = datetime.fromtimestamp(b.sonraki_bilanco_ts).date()
            if nd >= bugun:
                out["tarih"] = nd.isoformat()
                out["gun_kaldi"] = (nd - bugun).days
        return out if (out.get("tarih") or out.get("son_bilanco")) else None
    except Exception:
        return None


def yaklasan_bilanco(sembol: str) -> Optional[dict]:
    """
    Bir sonraki bilanço tarihini bulur. ÖNCE TradingView (BIST'te güvenilir),
    sonra yfinance yedek. Döner: {"tarih","gun_kaldi",...} veya None.
    """
    tv = _tv_bilanco_tarih(sembol)
    if tv and tv.get("tarih"):
        return tv

    try:
        import yfinance as yf
    except ImportError:
        return tv  # TV'den kısmi (son_bilanco/momentum) olabilir

    sem = _normalize(sembol)
    bugun = _bugun()
    adaylar: list[date] = []

    try:
        t = yf.Ticker(sem)
    except Exception:
        return None

    # 1) calendar (dict ya da DataFrame olabilir)
    try:
        cal = t.calendar
    except Exception:
        cal = None
    if cal is not None:
        try:
            deger = None
            if isinstance(cal, dict):
                deger = cal.get("Earnings Date") or cal.get("Earnings Date High")
            else:
                # DataFrame: 'Earnings Date' satırı
                try:
                    if "Earnings Date" in getattr(cal, "index", []):
                        deger = cal.loc["Earnings Date"].iloc[0]
                except Exception:
                    deger = None
            if isinstance(deger, (list, tuple)):
                for d in deger:
                    gd = _tarihe_cevir(d)
                    if gd:
                        adaylar.append(gd)
            else:
                gd = _tarihe_cevir(deger)
                if gd:
                    adaylar.append(gd)
        except Exception:
            pass

    # 2) get_earnings_dates()
    try:
        ed = t.get_earnings_dates(limit=12)
    except Exception:
        ed = None
    if ed is not None:
        try:
            for idx in ed.index:
                gd = _tarihe_cevir(idx)
                if gd:
                    adaylar.append(gd)
        except Exception:
            pass

    # En yakın GELECEK (bugün dahil) tarihi seç
    gelecek = sorted(d for d in adaylar if d >= bugun)
    if not gelecek:
        return None
    hedef = gelecek[0]
    return {"tarih": hedef.isoformat(), "gun_kaldi": (hedef - bugun).days}


def temettu_bilgisi(sembol: str) -> Optional[dict]:
    """
    Son / yaklaşan temettü bilgisi. yfinance 'dividends' serisi + 'info'.

    Döner: {"tarih": "YYYY-MM-DD", "tutar": float, "tur": "son"/"yaklasan"}
    veya veri yoksa None.
    """
    try:
        import yfinance as yf
    except ImportError:
        return None

    sem = _normalize(sembol)
    bugun = _bugun()
    try:
        t = yf.Ticker(sem)
    except Exception:
        return None

    # 1) info içinde yaklaşan temettü tarihi olabilir
    try:
        info = t.info or {}
    except Exception:
        info = {}
    for anahtar in ("dividendDate", "exDividendDate"):
        ts = info.get(anahtar)
        if ts:
            try:
                gd = datetime.fromtimestamp(int(ts)).date()
            except Exception:
                gd = _tarihe_cevir(ts)
            if gd and gd >= bugun:
                tutar = info.get("lastDividendValue") or info.get("dividendRate")
                return {"tarih": gd.isoformat(),
                        "tutar": float(tutar) if tutar else None,
                        "tur": "yaklasan"}

    # 2) geçmiş temettü serisi → son ödenen
    try:
        div = t.dividends
    except Exception:
        div = None
    if div is not None:
        try:
            if len(div) > 0:
                son_tarih = _tarihe_cevir(div.index[-1])
                son_tutar = float(div.iloc[-1])
                if son_tarih:
                    return {"tarih": son_tarih.isoformat(),
                            "tutar": son_tutar, "tur": "son"}
        except Exception:
            pass

    return None


def portfoy_olaylari(db_path: str, gun_esigi: int = 15) -> list[str]:
    """
    Portföydeki her açık pozisyon için yaklaşan bilançoyu kontrol eder.
    gun_esigi (varsayılan 15) gün içinde bilanço varsa uyarı üretir.

    Döner: uyarı metni listesi (boş olabilir).
    """
    from portfolio.ozet import acik_pozisyonlar

    uyarilar: list[str] = []
    try:
        pozlar = acik_pozisyonlar(db_path)
    except Exception:
        return []

    for sembol in sorted(pozlar.keys()):
        bil = yaklasan_bilanco(sembol)
        if bil and bil.get("gun_kaldi") is not None and bil["gun_kaldi"] <= gun_esigi:
            kod = sembol.replace(".IS", "")
            uyarilar.append(
                f"⚠️ {kod}: bilanço ~{bil['gun_kaldi']} gün sonra "
                f"({bil['tarih']}) — oynaklık riski"
            )
    return uyarilar


def olaylar_metni(db_path: str) -> str:
    """
    Portföy olaylarını Telegram metnine çevirir: her hisse için yaklaşan
    bilanço tarihi + çeyreklik kâr momentumu (TradingView gerçek verisi).
    Portföy boşsa dürüst mesaj; tarih yoksa uydurmaz.
    """
    from portfolio.ozet import acik_pozisyonlar

    try:
        pozlar = acik_pozisyonlar(db_path)
    except Exception:
        pozlar = {}

    if not pozlar:
        return ("📅 OLAY TAKVİMİ\n\n"
                "Portföyünüzde açık pozisyon yok. Hisse ekleyince yaklaşan "
                "bilanço/temettü olaylarını burada takip edebilirsiniz.")

    sat = [f"📅 OLAY TAKVİMİ ({len(pozlar)} hisse)", ""]
    veri_var = False
    for sembol in sorted(pozlar.keys()):
        kod = sembol.replace(".IS", "")
        bil = yaklasan_bilanco(sembol)   # TV öncelikli
        if not bil:
            sat.append(f"• {kod}: takvim verisi yok")
            continue
        veri_var = True
        parca = [f"• {kod}:"]
        if bil.get("tarih") and bil.get("gun_kaldi") is not None:
            gk = bil["gun_kaldi"]
            uyari = " ⚠️ yakında!" if gk <= 10 else ""
            parca.append(f"sonraki bilanço {bil['tarih']} (~{gk}g){uyari}")
        elif bil.get("son_bilanco"):
            parca.append(f"son bilanço {bil['son_bilanco']}")
        # Çeyrek kâr momentumu — yıllık (YoY) daha stabil; yoksa çeyreklik (QoQ)
        eps = bil.get("eps_yoy")
        etiket_yil = "yıllık"
        if eps is None:
            eps = bil.get("eps_qoq"); etiket_yil = "çeyreklik"
        if eps is not None:
            yon = "📈hızlanıyor" if eps > 5 else ("📉kâr düşüyor" if eps < -5 else "yatay")
            # Uç baz etkisini kırp (küçük bazdan hesaplanan % absürt görünmesin)
            eps_str = ">+200" if eps > 200 else ("<-200" if eps < -200 else f"{eps:+.0f}")
            parca.append(f"· {etiket_yil} kâr %{eps_str} {yon}")
        sat.append(" ".join(parca))

    if not veri_var:
        sat.append("")
        sat.append("ℹ️ Bu hisseler için bilanço tarihi bulunamadı (veri yok "
                   "demektir, olay olmadığı anlamına gelmez).")
    sat += ["", "⚠️ Kaynak: TradingView. Bilgilendirme amaçlıdır; yatırım "
            "tavsiyesi değildir."]
    return "\n".join(sat)
