"""
Piyasa Duyarlılığı / Korku-Açgözlülük (#7).

Gerçek tarama verisinden (bist_tara) deterministik bir duyarlılık endeksi
hesaplar (0 = aşırı korku, 100 = aşırı açgözlülük). Bileşenler:
  - Piyasa genişliği (yükselen/düşen oranı)
  - Ortalama RSI
  - Aşırı alım / aşırı satım dengesi
  - AL adayı yoğunluğu
  - Piyasa rejimi (boğa/ayı)

Tüm girdiler gerçek; veri yoksa o bileşen atlanır. Yatırım tavsiyesi değildir.
"""

from __future__ import annotations


def piyasa_duyarliligi(db_path: str, macro_cfg: dict) -> str:
    from analysis.bist_tarama import bist_tara, ozet_istatistik
    from analysis import macro
    from data.access import veri_getir

    ok, hata, satirlar = bist_tara(limit=1000)
    if not ok:
        return f"❌ Duyarlılık hesaplanamadı: {hata}"
    ist = ozet_istatistik(satirlar)

    bilesenler = []   # (ad, 0-100 puan, açıklama)

    # 1) Piyasa genişliği
    yuk, dus = ist.get("yukselis", 0), ist.get("dusus", 0)
    if yuk + dus > 0:
        genislik = yuk / (yuk + dus) * 100
        bilesenler.append(("Piyasa genişliği", genislik,
                           f"{yuk} yükselen / {dus} düşen"))

    # 2) Ortalama RSI (50=nötr; doğrudan 0-100)
    if ist.get("ort_rsi") is not None:
        bilesenler.append(("Ortalama RSI", ist["ort_rsi"], f"RSI {ist['ort_rsi']}"))

    # 3) Aşırı alım/satım dengesi
    aa = ist.get("asiri_alim_sayisi", 0)
    asat = ist.get("asiri_satim_sayisi", 0)
    if aa + asat > 0:
        denge = aa / (aa + asat) * 100   # çok aşırı alım = açgözlülük
        bilesenler.append(("Aşırı alım/satım", denge,
                           f"{aa} aşırı alım / {asat} aşırı satım"))

    # 4) AL adayı yoğunluğu
    toplam = ist.get("toplam", 0)
    if toplam:
        al_oran = (ist.get("guclu_al", 0) + ist.get("al_adayi", 0)) / toplam * 100
        # %25 AL adayı ~ güçlü iştah; ölçekle
        bilesenler.append(("AL adayı yoğunluğu", min(100, al_oran * 3),
                           f"%{al_oran:.0f} hisse AL adayı"))

    # 5) Rejim
    endeks = macro_cfg.get("rejim_endeksi", "XU100.IS")
    fr = veri_getir(db_path, endeks, period="2y", interval="1d")
    rejim_str = ""
    if fr.ok and fr.data is not None:
        rej = macro.rejim_tespit(fr.data)
        rejim_str = rej.rejim
        rejim_puan = {"Boğa": 75, "Yatay": 50, "Ayı": 25}.get(rej.rejim, 50)
        bilesenler.append(("Piyasa rejimi", rejim_puan, rej.rejim))

    if not bilesenler:
        return "❌ Duyarlılık için yeterli veri yok."

    endeks_puan = sum(b[1] for b in bilesenler) / len(bilesenler)

    if endeks_puan >= 75:
        etiket, emoji = "AŞIRI AÇGÖZLÜLÜK", "🤑"
        yorum = ("Piyasa çok iyimser — tarihsel olarak bu bölgeler temkin gerektirir. "
                 "Yeni alımlarda seçici ol, kâr realizasyonu düşünülebilir.")
    elif endeks_puan >= 60:
        etiket, emoji = "Açgözlülük", "😀"
        yorum = "Risk iştahı yüksek; trend yönünde ama disiplinli kal."
    elif endeks_puan >= 40:
        etiket, emoji = "Nötr", "😐"
        yorum = "Dengeli duyarlılık; net yön yok, seçici olunmalı."
    elif endeks_puan >= 25:
        etiket, emoji = "Korku", "😨"
        yorum = "Temkin hâkim; kaliteli hisseler iskontolu olabilir ama bıçak düşerken dikkat."
    else:
        etiket, emoji = "AŞIRI KORKU", "😱"
        yorum = ("Panik bölgesi — tarihsel olarak bu seviyeler uzun vadeli fırsat "
                 "doğurabilir, ama zamanlama zordur. Kademeli ve seçici ol.")

    # Çubuk
    dolu = int(round(endeks_puan / 10))
    cubuk = "█" * dolu + "░" * (10 - dolu)

    sat = [
        f"{emoji} PİYASA DUYARLILIĞI: {endeks_puan:.0f}/100 — {etiket}",
        f"   [{cubuk}]",
        "   0=Aşırı Korku · 50=Nötr · 100=Aşırı Açgözlülük",
        "",
        "📊 Bileşenler:",
    ]
    for ad, puan, acik in bilesenler:
        sat.append(f"   • {ad}: {puan:.0f}/100 ({acik})")
    sat += ["", f"🧭 {yorum}", "",
            "⚠️ Gerçek tarama verisine dayanır; yatırım tavsiyesi değildir."]
    return "\n".join(sat)
