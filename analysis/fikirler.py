"""
Günün 5 İşlem Fikri (Özellik #7).

Tüm BIST taramasından (bist_tarama) en yüksek skorlu adayları alır, her biri
için derin teknik analiz (teknik_derin) çalıştırır ve NET seviyelerle
(giriş / kar-al / zarar-kes / risk-ödül) 5 yüksek olasılıklı fikir üretir.

Temel + teknik gerekçe birlikte verilir. Veri yoksa o aday atlanır, uydurulmaz.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from analysis.bist_tarama import bist_tara
from analysis.teknik_derin import analiz_et, TeknikKarar
from data.access import veri_getir


@dataclass
class IslemFikri:
    sembol: str
    ad: str
    karar: str
    guven: str
    giris: Optional[float]
    kar_al: Optional[float]
    zarar_kes: Optional[float]
    risk_odul: Optional[float]
    teknik_gerekce: list = field(default_factory=list)
    temel_gerekce: str = ""        # tarama skoru / hacim / performans bağlamı
    uyarilar: list = field(default_factory=list)


def gunun_fikirleri(
    db_path: str,
    n_fikir: int = 5,
    aday_havuzu: int = 25,
    min_risk_odul: float = 1.5,
) -> tuple[bool, str, list[IslemFikri]]:
    """
    Dönüş: (basarili, hata, fikir_listesi)

    1. bist_tara → en yüksek skorlu `aday_havuzu` hisse
    2. Her biri için yfinance OHLC çek + derin analiz
    3. karar=AL ve risk/ödül >= min_risk_odul olanları seç
    4. Risk/ödül + güvene göre sırala, ilk `n_fikir` döndür
    """
    ok, hata, satirlar = bist_tara(limit=1000)
    if not ok:
        return False, hata, []

    # Skor sıralı (bist_tara zaten sıralı) ilk N aday
    havuz = [r for r in satirlar if r.aksiyon in ("Güçlü AL adayı", "AL adayı")][:aday_havuzu]
    if not havuz:
        return True, "Bugün AL adayı bulunamadı.", []

    fikirler: list[IslemFikri] = []
    for r in havuz:
        fr = veri_getir(db_path, r.sembol, period="1y", interval="1d")
        if not fr.ok or fr.data is None:
            continue
        k: TeknikKarar = analiz_et(fr.data, r.sembol)
        if not k.ok or k.karar != "AL":
            continue
        if k.risk_odul is None or k.risk_odul < min_risk_odul:
            continue

        # Temel/bağlam gerekçesi (tarama verisinden)
        temel = []
        if r.degisim_pct is not None:
            temel.append(f"günlük %{r.degisim_pct:+.1f}")
        if r.hacim_kat and r.hacim_kat >= 1.5:
            temel.append(f"hacim {r.hacim_kat}× ortalama")
        if r.perf_hafta is not None:
            temel.append(f"haftalık %{r.perf_hafta:+.1f}")
        if r.perf_ay is not None:
            temel.append(f"aylık %{r.perf_ay:+.1f}")
        temel_str = ", ".join(temel) if temel else "tarama skoru güçlü"

        fikirler.append(IslemFikri(
            sembol=r.sembol.replace(".IS", ""),
            ad=r.ad,
            karar=k.karar,
            guven=k.guven,
            giris=k.giris,
            kar_al=k.kar_al,
            zarar_kes=k.zarar_kes,
            risk_odul=k.risk_odul,
            teknik_gerekce=[g for g in k.gerekceler if g.startswith("✅")][:3],
            temel_gerekce=temel_str,
            uyarilar=k.uyarilar,
        ))

    # En iyi risk/ödül + yüksek güven önce
    guven_sira = {"Yüksek": 0, "Orta": 1, "Düşük": 2}
    fikirler.sort(key=lambda f: (guven_sira.get(f.guven, 3), -(f.risk_odul or 0)))
    return True, "", fikirler[:n_fikir]


def metin_ozet(fikirler: list[IslemFikri], baslik: str = "💡 GÜNÜN 5 İŞLEM FİKRİ") -> str:
    """Fikir listesini Telegram/panel metnine çevirir."""
    if not fikirler:
        return f"{baslik}\n\nBugün kriterleri karşılayan (R/R ≥ 1.5) AL fikri yok."

    sat = [baslik, ""]
    for i, f in enumerate(fikirler, 1):
        emoji = "🔥" if f.guven == "Yüksek" else "⭐"
        sat += [
            f"{i}) {emoji} {f.sembol} — {f.karar} (güven: {f.guven})",
            f"   Giriş: {f.giris} · 🎯 Hedef: {f.kar_al} · 🛑 Stop: {f.zarar_kes}",
            f"   ⚖️ Risk/Ödül: 1:{f.risk_odul}",
            f"   📊 Teknik: {'; '.join(g[2:] for g in f.teknik_gerekce)}",
            f"   📈 Bağlam: {f.temel_gerekce}",
        ]
        for u in f.uyarilar[:1]:
            sat.append(f"   ⚑ {u}")
        sat.append("")

    sat += ["━━━━━━━━━━━━━━",
            "⚠️ Teknik tarama çıktısıdır, geçmiş fiyata dayanır. Seviyeler kesin "
            "değildir; pozisyon büyüklüğünü ve stop'u kendin yönet."]
    return "\n".join(sat)
