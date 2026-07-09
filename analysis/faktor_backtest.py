"""
Faktör Kanıtı (backtest) — modelin faktörleri geçmişte GERÇEKTEN işe yaramış mı?

DÜRÜSTLÜK VE KAFA-KARIŞTIRMAMA İLKESİ:
- Bu SADECE bir KANIT/TANI aracıdır. Çekirdek öneri motorunu ASLA değiştirmez,
  ağırlıkları gizlice yeniden ayarlamaz (aşırı-uyum = kafa karışıklığı).
- Yalnızca FİYAT-TEMELLİ faktörler (Trend, Momentum) geçmişe göre test edilir;
  çünkü elimizde nokta-zaman TEMEL veri (F/K, ROE geçmişi) YOK. Temel faktörler
  (Kalite, Değer) ileriye dönük /performans ile doğrulanır — bunu açıkça belirtir.
- Sonuç iyi de olabilir kötü de; olduğu gibi raporlanır, süslenmez.

Yöntem: likit bir sepet üzerinde, "faktör olumlu" günlerdeki ileri getiriyi
"faktör olumsuz" günlerdekiyle kıyaslar (cross-sectional değil, faktör-durumu
temelli — sağlam ve anlaşılır).
"""

from __future__ import annotations
from typing import Optional

# Likit, veri güvenilir BIST sepeti (kanıt örneklemi; tüm evren değil)
_LIKIT_SEPET = [
    "GARAN.IS", "AKBNK.IS", "ISCTR.IS", "YKBNK.IS", "THYAO.IS", "ASELS.IS",
    "KCHOL.IS", "SAHOL.IS", "EREGL.IS", "TUPRS.IS", "BIMAS.IS", "FROTO.IS",
    "SISE.IS", "PGSUS.IS", "TCELL.IS",
]


def faktor_kanit(db_path: str, semboller: Optional[list] = None,
                 ileri_gun: int = 20) -> dict:
    """
    Trend ve Momentum faktörlerinin geçmiş öngörü değerini ölçer.
    Dönüş: {ok, n_hisse, sonuclar:[{ad, olumlu_ort, olumsuz_ort, fark, edge}], not_}
    """
    import numpy as np
    import pandas as pd
    from data.access import veri_getir

    semboller = semboller or _LIKIT_SEPET
    trend_ol, trend_yok = [], []      # ileri getiri: fiyat>SMA200 (uptrend) vs değil
    mom_ol, mom_yok = [], []          # 3-ay momentum pozitif vs negatif
    n_ok = 0

    for s in semboller:
        fr = veri_getir(db_path, s, period="2y", interval="1d")
        if not fr.ok or fr.data is None or len(fr.data) < 220:
            continue
        n_ok += 1
        close = fr.data["Close"].astype(float)
        sma200 = close.rolling(200).mean()
        mom3 = close / close.shift(63) - 1.0
        ileri = close.shift(-ileri_gun) / close - 1.0
        gecerli = ileri.notna()

        trend_ol += ileri[(close > sma200) & gecerli].dropna().tolist()
        trend_yok += ileri[(close <= sma200) & gecerli].dropna().tolist()
        mom_ol += ileri[(mom3 > 0) & gecerli].dropna().tolist()
        mom_yok += ileri[(mom3 <= 0) & gecerli].dropna().tolist()

    if n_ok == 0:
        return {"ok": False, "n_hisse": 0, "sonuclar": [],
                "not_": "Kanıt için yeterli fiyat verisi çekilemedi."}

    def _ozet(ad, ol, yok):
        if len(ol) < 30 or len(yok) < 30:
            return None
        mo = float(np.mean(ol)) * 100
        my = float(np.mean(yok)) * 100
        fark = mo - my
        if fark > 0.7:
            edge = "✅ Edge VAR"
        elif fark > 0:
            edge = "🟡 Zayıf edge"
        else:
            edge = "🔴 Edge YOK"
        return {"ad": ad, "olumlu_ort": round(mo, 2), "olumsuz_ort": round(my, 2),
                "fark": round(fark, 2), "edge": edge,
                "n_ol": len(ol), "n_yok": len(yok)}

    sonuclar = [x for x in (
        _ozet("Trend (fiyat > 200g ort.)", trend_ol, trend_yok),
        _ozet("Momentum (3-ay pozitif)", mom_ol, mom_yok),
    ) if x is not None]

    return {"ok": bool(sonuclar), "n_hisse": n_ok, "sonuclar": sonuclar,
            "not_": ""}


def faktor_kanit_metni(db_path: str, ileri_gun: int = 20) -> str:
    """Faktör kanıtını Telegram/panel metnine çevirir."""
    r = faktor_kanit(db_path, ileri_gun=ileri_gun)
    if not r["ok"]:
        return f"📊 FAKTÖR KANITI (backtest)\n\n{r.get('not_', 'Veri yok.')}"

    sat = [
        "📊 FAKTÖR KANITI — model geçmişte işe yaradı mı?",
        f"(likit {r['n_hisse']} hisse · sinyal sonrası {ileri_gun} gün ileri getiri)",
        "",
        "Fiyat-temelli faktörler (geçmişe göre test edilebilir):",
    ]
    for s in r["sonuclar"]:
        sat.append(f"• {s['ad']}")
        sat.append(f"   Faktör olumluyken: %{s['olumlu_ort']:+.2f}  ·  "
                   f"olumsuzken: %{s['olumsuz_ort']:+.2f}")
        sat.append(f"   Fark (edge): %{s['fark']:+.2f}  →  {s['edge']}")

    sat += [
        "",
        "ℹ️ Kalite ve Değer (temel) faktörleri geçmişe göre test EDİLEMEZ — "
        "elimizde nokta-zaman geçmiş bilanço verisi yok. Onlar ileriye dönük "
        "/performans ile doğrulanır (sistem her önerisini kaydedip endeksle kıyaslar).",
        "",
        "⚠️ Geçmiş performans geleceği garanti etmez. Bu bir kanıt/tanı aracıdır; "
        "öneri motorunu değiştirmez, yatırım tavsiyesi değildir.",
    ]
    return "\n".join(sat)
