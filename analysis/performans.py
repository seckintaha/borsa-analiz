"""
Öneri Performans Takibi — sistem kendini ölçer.

Sistem her aylık öneri verdiğinde bunları kaydeder (giriş fiyatı + tarih).
Zaman geçince gerçek getiriyi hesaplar ve ENDEKSLE (XU100) kıyaslar:
"Geçen ay önerdiklerim endeksi geçti mi? Hedeflere ulaştı mı?"

DÜRÜSTLÜK: Bu, faktör modelinin GERÇEKTEN işe yarayıp yaramadığını zamanla
kanıtlar. Sonuç iyi de olabilir kötü de — olduğu gibi raporlanır, süslenmez.
Getiriler gerçek fiyat verisine dayanır; veri yoksa o öneri atlanır.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


def oneri_kaydet(db_path: str, oneriler, kaynak: str = "aylik") -> int:
    """
    AylikOneri listesini takip tablosuna kaydeder. Dönem = bu ay (YYYY-MM).
    Aynı dönemde aynı sembol tekrar kaydedilmez. Kaç yeni kayıt eklendiğini döner.
    """
    from data.storage import save_oneri_takip, load_oneri_takip
    if not oneriler:
        return 0
    bugun = datetime.now()
    donem = bugun.strftime("%Y-%m")
    tarih = bugun.strftime("%Y-%m-%d")

    onceki = {(o["donem"], o["symbol"], o["kaynak"])
              for o in load_oneri_takip(db_path, kaynak=kaynak)}
    eklenen = 0
    for o in oneriler:
        sembol = (o.sembol if hasattr(o, "sembol") else o.get("sembol", "")).upper()
        if not sembol:
            continue
        if (donem, sembol, kaynak) in onceki:
            continue
        giris = getattr(o, "giris", None)
        hedef = getattr(o, "hedef", None)
        stop = getattr(o, "stop", None)
        skor = getattr(o, "birlesik", None)
        save_oneri_takip(db_path, donem, tarih, sembol, giris, hedef, stop,
                         skor, kaynak)
        eklenen += 1
    return eklenen


@dataclass
class OneriSonuc:
    symbol: str
    donem: str
    tarih: str
    giris: Optional[float]
    guncel: Optional[float]
    getiri_pct: Optional[float]
    endeks_getiri_pct: Optional[float]
    fark_pct: Optional[float]          # öneri - endeks (pozitif = endeksi geçti)
    hedef_vuruldu: bool
    stop_vuruldu: bool
    gun: int


def _endeks_getiri(db_path: str, tarih: str) -> Optional[float]:
    """XU100'ün öneri tarihinden bugüne getirisi %."""
    from data.access import veri_getir
    import pandas as pd
    fr = veri_getir(db_path, "XU100.IS", period="1y", interval="1d")
    if not fr.ok or fr.data is None or len(fr.data) < 2:
        return None
    try:
        idx = pd.to_datetime(fr.data.index)
        hedef_ts = pd.to_datetime(tarih)
        konum = idx.get_indexer([hedef_ts], method="nearest")[0]
        baslangic = float(fr.data["Close"].iloc[konum])
        son = float(fr.data["Close"].iloc[-1])
        if baslangic > 0:
            return (son - baslangic) / baslangic * 100
    except Exception:
        return None
    return None


def performans_raporu(db_path: str, min_gun: int = 15,
                      kaynak: str = "aylik") -> tuple[list[OneriSonuc], dict]:
    """
    Kaydedilmiş önerilerden en az `min_gun` gün geçmiş olanları ölçer.
    Dönüş: (sonuc_listesi, ozet_istatistik).
    """
    from data.storage import load_oneri_takip
    from data.access import veri_getir

    kayitlar = load_oneri_takip(db_path, kaynak=kaynak)
    bugun = datetime.now()
    sonuclar: list[OneriSonuc] = []

    for kyt in kayitlar:
        try:
            t = datetime.strptime(kyt["tarih"][:10], "%Y-%m-%d")
        except Exception:
            continue
        gun = (bugun - t).days
        if gun < min_gun:
            continue   # daha çok yeni, ölçmek için erken

        sembol = kyt["symbol"]
        giris = kyt.get("giris_fiyat")
        fr = veri_getir(db_path, sembol, period="1y", interval="1d")
        if not fr.ok or fr.data is None or len(fr.data) < 2:
            continue

        import pandas as pd
        df = fr.data
        # Öneri tarihinden bugüne olan dilim
        try:
            idx = pd.to_datetime(df.index)
            konum = idx.get_indexer([pd.to_datetime(kyt["tarih"])], method="nearest")[0]
            dilim = df.iloc[konum:]
        except Exception:
            dilim = df

        guncel = float(df["Close"].iloc[-1])
        if not giris or giris <= 0:
            giris = float(dilim["Close"].iloc[0])
        getiri = (guncel - giris) / giris * 100 if giris else None

        hedef = kyt.get("hedef")
        stop = kyt.get("stop")
        hedef_vuruldu = bool(hedef and (dilim["High"] >= hedef).any())
        stop_vuruldu = bool(stop and (dilim["Low"] <= stop).any())

        endeks = _endeks_getiri(db_path, kyt["tarih"])
        fark = (getiri - endeks) if (getiri is not None and endeks is not None) else None

        sonuclar.append(OneriSonuc(
            symbol=sembol.replace(".IS", ""), donem=kyt["donem"], tarih=kyt["tarih"],
            giris=round(giris, 2) if giris else None,
            guncel=round(guncel, 2), getiri_pct=round(getiri, 2) if getiri is not None else None,
            endeks_getiri_pct=round(endeks, 2) if endeks is not None else None,
            fark_pct=round(fark, 2) if fark is not None else None,
            hedef_vuruldu=hedef_vuruldu, stop_vuruldu=stop_vuruldu, gun=gun,
        ))

    # Özet istatistik
    gecerli = [s for s in sonuclar if s.getiri_pct is not None]
    ozet = {"toplam": len(gecerli)}
    if gecerli:
        getiriler = [s.getiri_pct for s in gecerli]
        farklar = [s.fark_pct for s in gecerli if s.fark_pct is not None]
        ozet.update({
            "ort_getiri": round(sum(getiriler) / len(getiriler), 2),
            "pozitif_oran": round(sum(1 for g in getiriler if g > 0) / len(getiriler) * 100),
            "endeksi_gecen": round(sum(1 for f in farklar if f > 0) / len(farklar) * 100) if farklar else None,
            "ort_fark": round(sum(farklar) / len(farklar), 2) if farklar else None,
            "hedef_vuran": sum(1 for s in gecerli if s.hedef_vuruldu),
            "stop_vuran": sum(1 for s in gecerli if s.stop_vuruldu),
        })
    return sonuclar, ozet


def performans_metni(db_path: str, min_gun: int = 15) -> str:
    """Performans raporunu Telegram/panel metnine çevirir."""
    sonuclar, ozet = performans_raporu(db_path, min_gun=min_gun)

    if not sonuclar:
        return ("📊 ÖNERİ PERFORMANS TAKİBİ\n\n"
                "Henüz ölçülecek olgun öneri yok. Sistem her ay önerdiği hisseleri "
                "kaydeder; ~15 gün geçince buradan gerçek getirilerini endeksle "
                "kıyaslar. İlk aylık öneriden sonra dolmaya başlar.")

    sat = ["📊 ÖNERİ PERFORMANS TAKİBİ", "(sistemin geçmiş önerileri gerçekte ne yaptı)", ""]

    if ozet.get("toplam"):
        og = ozet["ort_getiri"]
        isaret = "🟢" if og >= 0 else "🔴"
        sat += [
            f"{isaret} Ortalama getiri: %{og:+.1f}",
            f"📈 Pozitif çıkan: %{ozet['pozitif_oran']} ({ozet['toplam']} öneri)",
        ]
        if ozet.get("endeksi_gecen") is not None:
            sat.append(f"🏆 Endeksi geçen: %{ozet['endeksi_gecen']} · ort. fark %{ozet['ort_fark']:+.1f}")
        sat.append(f"🎯 Hedefe ulaşan: {ozet['hedef_vuran']} · 🛑 stop vuran: {ozet['stop_vuran']}")
        sat.append("")

    # Dönem dönem detay (en yeni önce)
    sat.append("📋 Öneri bazında:")
    for s in sorted(sonuclar, key=lambda x: x.tarih, reverse=True)[:15]:
        g = f"%{s.getiri_pct:+.1f}" if s.getiri_pct is not None else "—"
        e = f"(endeks %{s.endeks_getiri_pct:+.1f})" if s.endeks_getiri_pct is not None else ""
        durum = ""
        if s.hedef_vuruldu:
            durum = " 🎯hedef"
        elif s.stop_vuruldu:
            durum = " 🛑stop"
        isaret = "🟢" if (s.getiri_pct or 0) >= 0 else "🔴"
        sat.append(f"  {isaret} {s.symbol} ({s.donem}): {g} {e}{durum} · {s.gun}g")

    sat += ["", "⚠️ Geçmiş performans geleceği garanti etmez; bu sistemin dürüst "
            "öz-değerlendirmesidir, yatırım tavsiyesi değildir."]
    return "\n".join(sat)
