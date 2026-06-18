"""
Sektör analizi (#1) + Portföy çeşitlendirme önerisi (#2).

Gerçek veri: TradingView sektör + temel (tv_temel_tara) ve teknik (bist_tara).
Veri eksikse o hisse/sektör atlanır — uydurulmaz.
"""

from __future__ import annotations

# TradingView İngilizce sektör adları → Türkçe gösterim
_SEKTOR_TR = {
    "Finance": "Finans/Bankacılık",
    "Transportation": "Ulaşım",
    "Electronic Technology": "Elektronik/Teknoloji",
    "Technology Services": "Teknoloji Hizmetleri",
    "Process Industries": "Süreç Sanayi (kimya/gıda)",
    "Producer Manufacturing": "İmalat Sanayi",
    "Retail Trade": "Perakende",
    "Consumer Non-Durables": "Tüketim (gıda/içecek)",
    "Consumer Durables": "Dayanıklı Tüketim",
    "Consumer Services": "Tüketici Hizmetleri",
    "Energy Minerals": "Enerji/Petrol",
    "Non-Energy Minerals": "Madencilik/Metal",
    "Utilities": "Kamu Hizmetleri (elektrik)",
    "Health Technology": "Sağlık",
    "Health Services": "Sağlık Hizmetleri",
    "Communications": "İletişim",
    "Industrial Services": "Sanayi Hizmetleri",
    "Distribution Services": "Dağıtım",
    "Commercial Services": "Ticari Hizmetler",
    "Miscellaneous": "Diğer",
}


def _tr(sektor: str) -> str:
    return _SEKTOR_TR.get(sektor, sektor)


def _veri_birlestir():
    """bist_tara (teknik) + tv_temel_tara (temel) verisini sembol bazında birleştirir."""
    from analysis.bist_tarama import bist_tara
    from data.tv_scanner import tv_temel_tara

    tek_ok, tek_hata, tek = bist_tara(limit=1000)
    if not tek_ok:
        return None, f"Teknik tarama hatası: {tek_hata}"
    tem_ok, tem_hata, tem = tv_temel_tara(limit=1000)
    if not tem_ok:
        return None, f"Temel veri hatası: {tem_hata}"

    temel_map = {t.sembol: t for t in tem}
    birlesik = []
    for r in tek:
        t = temel_map.get(r.sembol)
        if t is None or not t.sektor or t.sektor == "—":
            continue
        birlesik.append((r, t))
    return birlesik, ""


# ── Sektör geneli (#1) ────────────────────────────────────────────────────────

def sektor_genel() -> str:
    """Tüm sektörleri aylık performans + AL adayı yoğunluğuna göre özetler."""
    birlesik, hata = _veri_birlestir()
    if birlesik is None:
        return f"❌ {hata}"

    gruplar: dict[str, list] = {}
    for r, t in birlesik:
        gruplar.setdefault(t.sektor, []).append((r, t))

    satirlar = []
    for sektor, uyeler in gruplar.items():
        if len(uyeler) < 2:
            continue
        perflar = [r.perf_ay for r, _ in uyeler if r.perf_ay is not None]
        fklar = [t.fk for _, t in uyeler if t.fk is not None and 0 < t.fk < 100]
        n_al = sum(1 for r, _ in uyeler if r.aksiyon in ("Güçlü AL adayı", "AL adayı"))
        ort_perf = sum(perflar) / len(perflar) if perflar else None
        ort_fk = sum(fklar) / len(fklar) if fklar else None
        satirlar.append({
            "sektor": sektor, "adet": len(uyeler), "ort_perf": ort_perf,
            "ort_fk": ort_fk, "n_al": n_al,
        })

    # Aylık performansa göre sırala
    satirlar.sort(key=lambda x: (x["ort_perf"] is None, -(x["ort_perf"] or 0)))

    sat = ["🏭 SEKTÖR ANALİZİ — Aylık Performans", ""]
    for s in satirlar:
        perf = f"%{s['ort_perf']:+.1f}" if s["ort_perf"] is not None else "—"
        fk = f"F/K~{s['ort_fk']:.1f}" if s["ort_fk"] is not None else ""
        sat.append(f"• {_tr(s['sektor'])} ({s['adet']} hisse)")
        sat.append(f"   Aylık ort {perf} · AL adayı {s['n_al']} · {fk}")
    sat += ["", "Detay için: /sektor <ad>  (örn: /sektor banka, /sektor enerji)",
            "⚠️ Gerçek verilere dayanır; yatırım tavsiyesi değildir."]
    return "\n".join(sat)


def sektor_detay(arama: str) -> str:
    """Bir sektördeki hisseleri teknik+temel özetiyle listeler (ad ile arama)."""
    birlesik, hata = _veri_birlestir()
    if birlesik is None:
        return f"❌ {hata}"

    arama_l = arama.strip().lower()
    # Türkçe ya da İngilizce ada göre eşle
    def _eslesir(sektor_en: str) -> bool:
        tr = _tr(sektor_en).lower()
        return arama_l in tr or arama_l in sektor_en.lower()

    uyeler = [(r, t) for r, t in birlesik if _eslesir(t.sektor)]
    if not uyeler:
        mevcut = sorted(set(_tr(t.sektor) for _, t in birlesik))
        return ("🔍 '%s' sektörü bulunamadı.\n\nMevcut sektörler:\n  %s" %
                (arama, "\n  ".join(mevcut)))

    sektor_adi = _tr(uyeler[0][1].sektor)
    # Sinyal skoruna göre sırala
    uyeler.sort(key=lambda x: -x[0].sinyal_skoru)

    sat = [f"🏭 {sektor_adi} — {len(uyeler)} hisse", ""]
    for r, t in uyeler[:12]:
        kod = r.sembol.replace(".IS", "")
        perf = f"%{r.perf_ay:+.0f}" if r.perf_ay is not None else "—"
        fk = f"F/K {t.fk:.1f}" if t.fk is not None else "F/K —"
        roe = f"ROE %{t.roe:.0f}" if t.roe is not None else ""
        aksiyon_iks = {"Güçlü AL adayı": "🟢", "AL adayı": "🟢",
                       "Nötr / İzle": "🟡", "Zayıf / Kaçın": "🔴"}.get(r.aksiyon, "⚪")
        sat.append(f"{aksiyon_iks} {kod}: aylık {perf} · {fk} · {roe}")
    sat += ["", "⚠️ Gerçek verilere dayanır; yatırım tavsiyesi değildir."]
    return "\n".join(sat)


# ── Portföy çeşitlendirme önerisi (#2) ────────────────────────────────────────

# Önemli sektörler — çeşitlendirmede "eksik mi" diye bakılacaklar
_ANA_SEKTORLER = [
    "Finance", "Transportation", "Energy Minerals", "Retail Trade",
    "Process Industries", "Non-Energy Minerals", "Consumer Non-Durables",
    "Utilities", "Producer Manufacturing", "Technology Services",
]


def cesitlendirme_onerisi(db_path: str) -> str:
    """
    Portföyünün sektör dağılımını çıkarır, eksik sektörleri bulur ve o
    sektörlerden SPESİFİK kaliteli hisse önerir (değer + teknik filtreli).
    """
    from portfolio.ozet import acik_pozisyonlar

    pos = acik_pozisyonlar(db_path)
    if not pos:
        return ("📭 Portföyün boş. Önce /ekle ile hisse ekle, sonra /cesitlendir "
                "ile çeşitlendirme önerisi al.")

    birlesik, hata = _veri_birlestir()
    if birlesik is None:
        return f"❌ {hata}"
    temel_map = {t.sembol: t for _, t in birlesik}

    # Portföyün sektörleri
    portfoy_sektor: dict[str, list[str]] = {}
    for sembol in pos:
        t = temel_map.get(sembol)
        sek = t.sektor if t else "Bilinmiyor"
        portfoy_sektor.setdefault(sek, []).append(sembol.replace(".IS", ""))

    sat = ["🧭 PORTFÖY ÇEŞİTLENDİRME ÖNERİSİ", "", "📊 Mevcut sektör dağılımın:"]
    for sek, kodlar in portfoy_sektor.items():
        sat.append(f"   • {_tr(sek)}: {', '.join(kodlar)}")

    # Yoğunlaşma uyarısı
    en_buyuk = max(portfoy_sektor.items(), key=lambda x: len(x[1]))
    if len(en_buyuk[1]) >= max(2, len(pos) * 0.5):
        sat += ["", f"⚠️ Ağırlık {_tr(en_buyuk[0])}'da yoğunlaşmış "
                f"({len(en_buyuk[1])}/{len(pos)} hisse). Farklı sektör eklemek riski azaltır."]

    # Eksik ana sektörler
    sahip_sektorler = set(portfoy_sektor.keys())
    eksikler = [s for s in _ANA_SEKTORLER if s not in sahip_sektorler]

    if not eksikler:
        sat += ["", "✅ Ana sektörlerin çoğunda pozisyonun var — iyi çeşitlenmişsin."]
    else:
        sat += ["", "🆕 Girmediğin sektörler + kaliteli aday hisseler:"]
        # Her eksik sektör için en iyi değer+teknik hisseyi bul
        for sek in eksikler[:5]:
            adaylar = []
            for r, t in birlesik:
                if t.sektor != sek:
                    continue
                if t.fk is None or not (0 < t.fk < 25):
                    continue
                if t.roe is None or t.roe < 8:
                    continue
                skor = float(r.sinyal_skoru) + (10 - t.fk if t.fk < 10 else 0) + t.roe / 5
                adaylar.append((skor, r, t))
            if not adaylar:
                continue
            adaylar.sort(key=lambda x: -x[0])
            _, r, t = adaylar[0]
            kod = r.sembol.replace(".IS", "")
            sat.append(f"   • {_tr(sek)} → {kod} "
                       f"(F/K {t.fk:.1f} · ROE %{t.roe:.0f} · {r.aksiyon})")

    sat += ["", "💡 Çeşitlendirme: farklı sektörler aynı anda düşmez; "
            "biri kötüyken diğeri portföyü dengeler.",
            "⚠️ Öneriler gerçek veriye dayanır; yatırım tavsiyesi değildir."]
    return "\n".join(sat)
