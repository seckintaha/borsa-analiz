"""
Otomatik Günlük İşlem Planı (Özellik #1).

Sabah açılış öncesinden kapanış sonrasına, BIST seansına (10:00–18:00) göre
zaman damgalı bir kontrol listesi üretir:
  - 09:30 Açılış öncesi kontrol listesi (rejim, gece kapanışı, haberler, izleme)
  - 10:00 Açılış stratejisi (gap, ilk 15 dk volatilite)
  - 12:00 / 14:00 / 16:00 gün içi düzeltme noktaları
  - 17:45 Kapanış öncesi hareketler

Plan, o anki tarama (bist_tarama) + rejim (macro) + haber (kap) verisine dayanır.
Veri yoksa ilgili madde "veri yok" der.
"""

from __future__ import annotations
from datetime import datetime

from analysis.bist_tarama import bist_tara, ozet_istatistik
from analysis.kap import piyasa_akisi
from analysis import macro
from data.access import veri_getir


def gunluk_plan_metni(db_path: str, macro_cfg: dict, haber_cfg: dict | None = None) -> str:
    """Zaman damgalı günlük işlem planı (checklist) üretir."""
    bugun = datetime.now().strftime("%d.%m.%Y")

    # ── Rejim ──
    endeks = macro_cfg.get("rejim_endeksi", "XU100.IS")
    fr = veri_getir(db_path, endeks, period="2y", interval="1d")
    rejim_str = "veri yok"
    rejim = ""
    if fr.ok and fr.data is not None:
        rej = macro.rejim_tespit(fr.data)
        rejim_str = macro.ozetle(rej)
        rejim = rej.rejim

    # ── Tarama (en güçlü/zayıf) ──
    ok, _, satirlar = bist_tara(limit=1000)
    ist = ozet_istatistik(satirlar) if ok else {}
    adaylar = [r for r in satirlar if r.aksiyon in ("Güçlü AL adayı", "AL adayı")][:5] if ok else []
    zayiflar = [r for r in satirlar if r.aksiyon == "Zayıf / Kaçın"][-3:] if ok else []

    # ── Haberler ──
    kap_haber = []
    if haber_cfg and haber_cfg.get("rss_feeds"):
        try:
            hr = piyasa_akisi(dict(haber_cfg["rss_feeds"]), limit=4)
            if hr.ok:
                kap_haber = [k for k in hr.kayitlar if k.kategori == "kap_benzeri"][:3] \
                            or hr.kayitlar[:3]
        except Exception:
            pass

    # ── Plan kur ──
    sat = [
        f"🗓️ GÜNLÜK İŞLEM PLANI — {bugun}",
        f"🌐 Piyasa rejimi: {rejim_str}",
        "",
        "━━━ 09:30 · AÇILIŞ ÖNCESİ KONTROL ━━━",
    ]

    # Rejime göre genel duruş
    if "Boğa" in rejim:
        sat.append("☑️ Rejim BOĞA — alım fikirlerine açık ol, trend yönünde işlem önceliği.")
    elif "Ayı" in rejim:
        sat.append("☑️ Rejim AYI — temkinli ol, pozisyon küçült, stop'ları sıkı tut.")
    else:
        sat.append("☑️ Rejim YATAY — kırılım bekle, bant alt/üstünde işlem; ortada bekle.")

    sat.append("☑️ Gece ABD/Asya kapanışını kontrol et (genel risk iştahı).")
    if kap_haber:
        sat.append("☑️ Öne çıkan haber başlıkları:")
        for h in kap_haber:
            sat.append(f"     • {h.baslik[:80]} —{h.kaynak}")
    else:
        sat.append("☑️ Önemli haber akışı: veri yok / sakin.")

    if adaylar:
        izlenecek = ", ".join(r.sembol.replace(".IS", "") for r in adaylar)
        sat.append(f"☑️ Bugün izlenecek güçlü adaylar: {izlenecek}")
    else:
        sat.append("☑️ Güçlü aday yok — bugün seçici ol, zorlama.")

    sat += [
        "",
        "━━━ 10:00 · AÇILIŞ STRATEJİSİ ━━━",
        "☑️ İlk 15 dk (10:00–10:15) volatildir — acele girme, yönü gözle.",
        "☑️ Gap (boşluk) açan hisselerde: gap dolar mı, devam mı? teyit bekle.",
    ]
    if adaylar:
        en_iyi = adaylar[0]
        sat.append(f"☑️ Öncelikli izlenen: {en_iyi.sembol.replace('.IS','')} "
                   f"(RSI {en_iyi.rsi}, {en_iyi.ema_durumu}) — destek üstü tutuşu izle.")

    sat += [
        "",
        "━━━ 12:00 · GÜN İÇİ DÜZELTME #1 ━━━",
        "☑️ Sabah açılan pozisyonların stop'unu güncelle (kâr varsa stop'u girişe çek).",
        "☑️ Hacim anomalisi olan hisseleri kontrol et (ani giriş/çıkış).",
    ]
    if ist:
        sat.append(f"☑️ Piyasa nabzı: {ist.get('yukselis',0)} yükseliş / "
                   f"{ist.get('dusus',0)} düşüş, ort %{ist.get('ort_degisim_pct',0):+.2f}")

    sat += [
        "",
        "━━━ 14:00 · GÜN İÇİ DÜZELTME #2 ━━━",
        "☑️ Öğleden sonra trend teyidi: sabahki yön korunuyor mu?",
        "☑️ Zarardaki pozisyonlarda stop'a sadık kal — ortalama AŞAĞI yapma.",
    ]
    if zayiflar:
        zayif_str = ", ".join(r.sembol.replace(".IS", "") for r in zayiflar)
        sat.append(f"☑️ Zayıf/kaçınılacaklar (yeni alım için uzak dur): {zayif_str}")

    sat += [
        "",
        "━━━ 16:00 · GÜN İÇİ DÜZELTME #3 ━━━",
        "☑️ Kapanışa 2 saat — günü kârla kapatacak pozisyonları değerlendir.",
        "☑️ Yeni pozisyon için geç olabilir; ertesi güne taşıma riskini düşün.",
        "",
        "━━━ 17:45 · KAPANIŞ ÖNCESİ ━━━",
        "☑️ Gün içi (intraday) pozisyonları kapat — gece riski taşıma.",
        "☑️ Swing pozisyonlarda kapanış stop seviyesini doğrula.",
        "☑️ Günün notunu al: ne işe yaradı, ne yaramadı (işlem günlüğüne yaz).",
        "",
        "━━━━━━━━━━━━━━",
        "⚠️ Bu plan teknik tarama + rejime dayalı bir kontrol listesidir; "
        "yatırım tavsiyesi değildir. Her maddeyi kendi riskinle uygula.",
    ]
    return "\n".join(sat)
