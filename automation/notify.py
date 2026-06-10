"""
Telegram bildirim botu (Aşama 12).

Günlük özet (AL adayları + piyasa rejimi) Telegram'a gönderilir. Yalnızca
**borsanın çalıştığı günlerde** çalışır: tam bir işlem takvimi gömmek yerine
veriye bakılır — endeks bugün bar ürettiyse borsa açıktı demektir; hafta
sonu/resmî tatilde veri gelmediği için bot otomatik susar.

Kütüphane gerektirmez (saf stdlib HTTP). Token/chat id ortam değişkeninden
okunur; yoksa sessizce uydurmaz, "ayarlı değil" der.

Kullanım:
    python -m automation.notify

Zamanlama (cron, hafta içi 18:30 — tatiller veri kontrolüyle atlanır):
    30 18 * * 1-5  cd /yol/borsa-analiz && .venv/bin/python -m automation.notify

NOT: Gönderilen mesaj teknik bir taramadır, yatırım tavsiyesi değildir.
"""

from __future__ import annotations
import os
import sys
import json
import urllib.parse
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TG_API = "https://api.telegram.org/bot{token}/sendMessage"


# ── Telegram gönderici ────────────────────────────────────────────────────────

def telegram_ayarli_mi() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN")
               and os.environ.get("TELEGRAM_CHAT_ID"))


def telegram_gonder(metin: str, token: str | None = None,
                    chat_id: str | None = None, timeout: float = 10.0) -> tuple[bool, str]:
    """
    Telegram'a düz metin mesaj gönderir. Token/chat id yoksa (False, açıklama).
    Token URL'de taşınır (Telegram'ın yöntemi) — asla loglanmaz.
    """
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return (False, "Telegram ayarlı değil (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")

    veri = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": metin[:4000],              # Telegram sınırı ~4096
        "disable_web_page_preview": "true",
    }).encode()
    try:
        istek = urllib.request.Request(_TG_API.format(token=token), data=veri)
        with urllib.request.urlopen(istek, timeout=timeout) as yanit:
            sonuc = json.loads(yanit.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return (False, f"Telegram gönderim hatası: {exc}")

    if sonuc.get("ok"):
        return (True, "")
    return (False, f"Telegram reddetti: {sonuc.get('description', 'bilinmeyen hata')}")


# ── Borsa günü tespiti (veri-temelli, takvim gömülmeden) ──────────────────────

def borsa_gunu_mu(son_veri_tarihi: str) -> bool:
    """
    Endeksin en yeni barı BUGÜNE aitse borsa bugün çalıştı demektir.
    Hafta sonu/resmî tatilde veri gelmez → False (bot susar).
    son_veri_tarihi: "YYYY-MM-DD".
    """
    if not son_veri_tarihi:
        return False
    return son_veri_tarihi == datetime.now().strftime("%Y-%m-%d")


def veri_taze_mi(son_veri_tarihi: str, max_gun: int = 4) -> bool:
    """
    Gün-içi mod için: en yeni bar son `max_gun` gün içindeyse veri 'taze' sayılır.
    Hafta sonu/uzun tatilde bar eskir → False (bot susar). EOD modundaki katı
    'tam bugün' kuralı yerine, gün içinde (bugünün barı henüz kapanmamışken)
    da çalışabilmek için gevşek kontrol.
    """
    if not son_veri_tarihi:
        return False
    try:
        d = datetime.strptime(son_veri_tarihi[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    fark = (datetime.now().date() - d).days
    return 0 <= fark <= max_gun


# ── Günlük özet metni ─────────────────────────────────────────────────────────

def gunluk_ozet_metni(satirlar, rejim_satiri: str, zaman: str,
                      aday_sayisi: int = 5, son_veri_tarihi: str = "",
                      basliklar=None, baslik: str = "📊 Borsa Günlük Analiz") -> str:
    """
    Skorlanmış adaylardan DETAYLI bir Telegram raporu kurar (saf, ağ gerektirmez).
    Her aday için: aksiyon, skor, güven, fiyat, dönem getirisi, gerekçeler (RSI/MACD/
    rejim), varsa ayı senaryosu ve dikkat bayrakları. Üstte tarama istatistiği +
    veri tazeliği; altta (verilirse) günün öne çıkan haber başlıkları.

    son_veri_tarihi: kullanılan en yeni fiyat barının tarihi (şeffaflık için).
    basliklar: (kaynak, başlık) çiftleri — günün haber başlıkları (opsiyonel).
    """
    adaylar = [r for r in satirlar
               if r.aksiyon in ("Güçlü AL adayı", "AL adayı")][:aday_sayisi]
    n_al = sum(1 for r in satirlar if r.aksiyon in ("Güçlü AL adayı", "AL adayı"))
    n_izle = sum(1 for r in satirlar if r.aksiyon == "Nötr / İzle")
    n_kacin = sum(1 for r in satirlar if r.aksiyon == "Zayıf / Kaçın")
    n_veriyok = sum(1 for r in satirlar if getattr(r, "not_", ""))

    def _fmt_fiyat(v):
        return "—" if v is None else (f"{v:,.2f}" if abs(v) >= 1 else f"{v:.4f}")

    zaman_etiket = zaman[:16].replace("T", " ")
    sat = [
        f"{baslik} — {zaman_etiket}",
        "",
        f"🌐 Piyasa: {rejim_satiri}",
    ]
    if son_veri_tarihi:
        taze = " (bugün ✅)" if son_veri_tarihi == datetime.now().strftime("%Y-%m-%d") \
               else " ⚠️ bugünün barı henüz yok"
        sat.append(f"📅 Kullanılan veri: {son_veri_tarihi}{taze}")
    sat += [
        f"📋 Taranan: {len(satirlar)} hisse · AL adayı: {n_al} · "
        f"İzle: {n_izle} · Kaçın: {n_kacin}"
        + (f" · veri yok: {n_veriyok}" if n_veriyok else ""),
        "",
    ]

    if adaylar:
        sat.append("🟢 AL ADAYLARI")
        for i, r in enumerate(adaylar, 1):
            isaret = "🔥" if r.aksiyon == "Güçlü AL adayı" else "⭐"
            getiri = ("—" if r.degisim_pct is None
                      else f"%{r.degisim_pct:+.2f}")
            sat += [
                "",
                f"{i}) {isaret} {r.symbol} — {r.aksiyon}",
                f"   📈 skor {r.skor}/100 · güven {r.guven}",
                f"   💰 fiyat {_fmt_fiyat(r.son_fiyat)} · dönem getirisi {getiri}",
            ]
            for g in (r.gerekceler or []):
                sat.append(f"   ✓ {g}")
            for a in (getattr(r, "ayi_senaryosu", None) or []):
                sat.append(f"   🔻 ayı senaryosu: {a}")
            for b in (getattr(r, "bayraklar", None) or []):
                sat.append(f"   ⚑ dikkat: {b}")
    else:
        sat.append("🟡 Bugün güçlü AL adayı yok — sistem temkinli.")

    if basliklar:
        sat += ["", "📰 Günün başlıkları:"]
        for kaynak, bas in basliklar[:5]:
            sat.append(f"• {bas[:90]}  —{kaynak}")

    sat += [
        "",
        "━━━━━━━━━━━━━━",
        "⚠️ Otomatik teknik taramadır, yatırım tavsiyesi DEĞİLDİR. "
        "Skorlar geçmiş fiyat/momentuma dayanır, sık yanılır; kendi araştırmanı yap.",
    ]

    metin = "\n".join(sat)
    return metin[:4000]            # Telegram tek mesaj sınırı (~4096)


# ── Uçtan uca günlük bildirim ─────────────────────────────────────────────────

def gunluk_bildirim(db_path: str, watchlist: list[str], oneri_cfg: dict,
                    screen_cfg: dict, macro_cfg: dict, tg_cfg: dict,
                    mod: str = "eod", haber_cfg: dict | None = None) -> dict:
    """
    Borsa günüyse: tara → rejim oku → haber çek → AL adaylarını Telegram'a gönder.
    mod="eod": gün sonu (18:30), bugünün barı oluşmuş olmalı (katı).
    mod="gunici": gün içi (örn. 13:00), veri son birkaç gün içindeyse gönderir.
    Dönüş: durum sözlüğü (gonderildi, neden, ...).
    """
    from data.access import veri_getir
    from analysis import macro
    from analysis import recommender as rec
    from data.storage import init_db, log_event

    zaman = datetime.now().isoformat(timespec="seconds")
    init_db(db_path)

    # Rejim endeksi (hem rejim hem borsa-günü kontrolü buradan)
    endeks = macro_cfg.get("rejim_endeksi", "XU100.IS")
    fr = veri_getir(db_path, endeks, period="2y", interval="1d")
    son_tarih = fr.meta.get("son_tarih", "") if fr.ok else ""

    if tg_cfg.get("sadece_borsa_gunu", True):
        taze = veri_taze_mi(son_tarih) if mod == "gunici" else borsa_gunu_mu(son_tarih)
        if not taze:
            return {"gonderildi": False,
                    "neden": f"borsa günü değil / veri taze değil (son veri: {son_tarih or 'yok'})"}

    rejim_str = ""
    if fr.ok and fr.data is not None:
        rej = macro.rejim_tespit(fr.data)
        rejim_str = f"{endeks} — {macro.ozetle(rej)}"
        rejim = rej.rejim
    else:
        rejim_str = f"{endeks} — rejim okunamadı"
        rejim = ""

    satirlar = rec.oneri_tara(watchlist, oneri_cfg,
                              thin_volume=screen_cfg["thin_volume"],
                              rejim=rejim, period=oneri_cfg["varsayilan_periyot"])

    # Günün haber başlıkları (opsiyonel; akış yoksa sessizce atlanır)
    basliklar = []
    if haber_cfg and haber_cfg.get("rss_feeds"):
        try:
            from analysis import news
            hr = news.piyasa_akisi(dict(haber_cfg["rss_feeds"]),
                                   limit=haber_cfg.get("rss_basina_limit", 10))
            if hr.ok:
                basliklar = [(k.kaynak, k.baslik) for k in hr.kayitlar[:5]]
        except Exception:
            basliklar = []

    baslik = "📊 Borsa Günlük Analiz" if mod == "eod" else "⏱️ Borsa Gün-İçi Analiz"
    metin = gunluk_ozet_metni(satirlar, rejim_str, zaman,
                              aday_sayisi=tg_cfg.get("ozet_aday_sayisi", 5),
                              son_veri_tarihi=son_tarih, basliklar=basliklar,
                              baslik=baslik)

    ok, hata = telegram_gonder(metin)
    log_event(db_path, zaman, symbol="", kind="telegram_bildirim",
              detail=(f"{mod} gönderildi" if ok else f"{mod} başarısız: {hata}"),
              source="telegram")
    return {"gonderildi": ok, "neden": hata if not ok else "",
            "rejim": rejim_str, "metin": metin}


def chat_id_bul(token: str | None = None, timeout: float = 10.0) -> tuple[bool, str]:
    """
    getUpdates ile bota mesaj atmış sohbetlerin chat id'lerini bulur. Token
    verince kullanıcının URL'yi elle açmasına gerek kalmaz: botuna bir mesaj at,
    sonra `python -m automation.notify --chat-id` çalıştır.
    """
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return (False, "Token yok. Önce TELEGRAM_BOT_TOKEN ayarla (.env).")
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as yanit:
            sonuc = json.loads(yanit.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return (False, f"getUpdates hatası: {exc}")
    if not sonuc.get("ok"):
        return (False, f"Telegram reddetti: {sonuc.get('description', 'bilinmeyen')}")
    bulunan = {}
    for upd in sonuc.get("result", []):
        sohbet = (upd.get("message") or upd.get("channel_post") or {}).get("chat", {})
        if sohbet.get("id") is not None:
            ad = sohbet.get("title") or sohbet.get("username") or \
                 (f"{sohbet.get('first_name','')} {sohbet.get('last_name','')}".strip())
            bulunan[str(sohbet["id"])] = ad or "(isimsiz)"
    if not bulunan:
        return (False, "Hiç mesaj görünmüyor. Botuna Telegram'dan bir mesaj atıp "
                       "tekrar dene (eski mesajlar ~24 saat sonra düşer).")
    satir = "\n".join(f"  TELEGRAM_CHAT_ID={cid}   # {ad}"
                      for cid, ad in bulunan.items())
    return (True, satir)


def main() -> None:
    import config
    from data.storage import load_watchlist

    if "--chat-id" in sys.argv:
        ok, mesaj = chat_id_bul()
        if ok:
            print("Bulunan chat id'ler (.env'e yapıştır):")
        print(mesaj)
        return

    if not telegram_ayarli_mi():
        print("Telegram ayarlı değil. Ortam değişkenlerini ayarlayın:")
        print("  export TELEGRAM_BOT_TOKEN=...")
        print("  export TELEGRAM_CHAT_ID=...")
        print("(@BotFather'dan token alın; chat id için botuna mesaj atıp")
        print(" `python -m automation.notify --chat-id` çalıştırın.)")
        return

    mod = "gunici" if "--gunici" in sys.argv else "eod"
    watchlist = load_watchlist(config.DB_PATH) or list(config.WATCHLIST)
    sonuc = gunluk_bildirim(
        db_path=config.DB_PATH, watchlist=watchlist,
        oneri_cfg=config.ONERI, screen_cfg=config.SCREEN,
        macro_cfg=config.MACRO, tg_cfg=config.TELEGRAM,
        mod=mod, haber_cfg=getattr(config, "HABER", None))

    if sonuc["gonderildi"]:
        print(f"✅ Telegram bildirimi gönderildi ({mod}).")
        print(sonuc["rejim"])
    else:
        print(f"ℹ️ Gönderilmedi: {sonuc['neden']}")


if __name__ == "__main__":
    main()
