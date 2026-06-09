"""
Otomasyon (Aşama 10) — gün sonu tarama + rapor.

İlke (yol haritası): sistem her gün elle çalıştırılmak zorunda kalmamalı.
Bu modül izleme listesini tarar, piyasa rejimini okur ve tarihli bir
Markdown rapor üretir. Rapor metni kaynağa + zamana bağlıdır.

Burada gerçek bir arka plan servisi (daemon) yoktur — bu işletim sistemine
özgüdür. Bunun yerine tek seferlik çalışan bir komut sunulur; cron / launchd
ile zamanlamak kullanıcıya bırakılır (aşağıdaki nasıl-yapılır'a bakın).

NOT: Üretilen rapor karar destek amaçlıdır, yatırım tavsiyesi değildir.
"""

from __future__ import annotations
import os
from datetime import datetime, timezone

from analysis.screener import scan, ScreenRow
from analysis.macro import rejim_tespit, ozetle as rejim_ozetle
from data.fetcher import fetch_history
from data.storage import init_db, log_event


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rapor_metni(rows: list[ScreenRow], rejim_satiri: str, zaman: str) -> str:
    """Tarama sonuçları + rejimden Markdown rapor kurar (saf, ağ gerektirmez)."""
    one_cikan = [r for r in rows if r.gerekceler]
    satirlar = [
        f"# Gün Sonu Raporu — {zaman}",
        "",
        f"**Piyasa rejimi:** {rejim_satiri}",
        "",
        f"Taranan: {len(rows)} hisse | öne çıkan: {len(one_cikan)}",
        "",
        "## Öne çıkanlar",
    ]
    if not one_cikan:
        satirlar.append("_Bugün eşikleri aşan hisse yok._")
    else:
        satirlar.append("| Sembol | Fiyat | Değişim % | RSI | Neden öne çıktı |")
        satirlar.append("|---|---|---|---|---|")
        for r in one_cikan:
            satirlar.append(
                f"| {r.symbol} | {r.son_fiyat if r.son_fiyat is not None else '—'} "
                f"| {r.degisim_pct if r.degisim_pct is not None else '—'} "
                f"| {r.rsi if r.rsi is not None else '—'} "
                f"| {', '.join(r.gerekceler)} |"
            )

    veri_yok = [r for r in rows if r.not_]
    if veri_yok:
        satirlar += ["", "## Veri alınamayanlar"]
        for r in veri_yok:
            satirlar.append(f"- {r.symbol}: {r.not_}")

    satirlar += ["", "---",
                 "_Bu rapor teknik göstergelerin matematiksel çıktısıdır; "
                 "yatırım tavsiyesi değildir ve sık sık yanılır._"]
    return "\n".join(satirlar)


def kaydet_rapor(metin: str, klasor: str = "raporlar") -> str:
    """Raporu tarihli bir .md dosyasına yazar, yolu döndürür."""
    os.makedirs(klasor, exist_ok=True)
    ad = f"rapor-{datetime.now().strftime('%Y-%m-%d')}.md"
    yol = os.path.join(klasor, ad)
    with open(yol, "w", encoding="utf-8") as f:
        f.write(metin)
    return yol


def calistir(db_path: str, watchlist: list[str], screen_cfg: dict,
             macro_cfg: dict, rapor_klasoru: str = "raporlar") -> dict:
    """
    Uçtan uca otomasyon: tara → rejim oku → rapor yaz → olay günlüğüne işle.
    Canlı veri çeker; dönüş bir özet sözlüğüdür.
    """
    zaman = _now_iso()
    init_db(db_path)

    rows = scan(watchlist, screen_cfg)

    # Piyasa rejimi (rejim endeksinden)
    endeks = macro_cfg.get("rejim_endeksi", "XU100.IS")
    fr = fetch_history(endeks, period="2y", interval="1d")
    if fr.ok and fr.data is not None:
        rej = rejim_tespit(
            fr.data,
            oynaklik_penceresi=macro_cfg.get("oynaklik_penceresi", 20),
            yatay_band_pct=macro_cfg.get("yatay_band_pct", 5.0),
            yuksek_oynaklik_p=macro_cfg.get("yuksek_oynaklik_p", 75),
            dusuk_oynaklik_p=macro_cfg.get("dusuk_oynaklik_p", 25),
        )
        rejim_satiri = f"{endeks} — {rejim_ozetle(rej)}"
    else:
        rejim_satiri = f"{endeks} — rejim okunamadı ({fr.note})"

    metin = rapor_metni(rows, rejim_satiri, zaman)
    yol = kaydet_rapor(metin, rapor_klasoru)

    one_cikan = sum(1 for r in rows if r.gerekceler)
    log_event(db_path, zaman, symbol="", kind="gun_sonu_rapor",
              detail=f"{len(rows)} tarandı, {one_cikan} öne çıkan, rapor: {yol}",
              source="otomasyon")

    return {"zaman": zaman, "rapor_yolu": yol, "taranan": len(rows),
            "one_cikan": one_cikan, "rejim": rejim_satiri}
