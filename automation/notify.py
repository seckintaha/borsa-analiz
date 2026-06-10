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


# ── Günlük özet metni ─────────────────────────────────────────────────────────

def gunluk_ozet_metni(satirlar, rejim_satiri: str, zaman: str,
                      aday_sayisi: int = 5) -> str:
    """Skorlanmış adaylardan kısa bir Telegram özeti kurar (saf, ağ gerektirmez)."""
    adaylar = [r for r in satirlar
               if r.aksiyon in ("Güçlü AL adayı", "AL adayı")][:aday_sayisi]
    sat = [f"📊 Borsa Özeti — {zaman[:10]}", "", f"🌐 {rejim_satiri}", ""]
    if adaylar:
        sat.append("🟢 Öne çıkan adaylar:")
        for r in adaylar:
            sat.append(f"• {r.symbol}: skor {r.skor}/100 — {r.aksiyon} "
                       f"(güven {r.guven})")
    else:
        sat.append("🟡 Bugün güçlü AL adayı yok.")
    sat += ["", "⚠️ Teknik taramadır, yatırım tavsiyesi değildir; sık yanılır."]
    return "\n".join(sat)


# ── Uçtan uca günlük bildirim ─────────────────────────────────────────────────

def gunluk_bildirim(db_path: str, watchlist: list[str], oneri_cfg: dict,
                    screen_cfg: dict, macro_cfg: dict, tg_cfg: dict) -> dict:
    """
    Borsa günüyse: tara → rejim oku → AL adaylarını Telegram'a gönder.
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

    if tg_cfg.get("sadece_borsa_gunu", True) and not borsa_gunu_mu(son_tarih):
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
    metin = gunluk_ozet_metni(satirlar, rejim_str, zaman,
                              aday_sayisi=tg_cfg.get("ozet_aday_sayisi", 5))

    ok, hata = telegram_gonder(metin)
    log_event(db_path, zaman, symbol="", kind="telegram_bildirim",
              detail=("gönderildi" if ok else f"başarısız: {hata}"),
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

    watchlist = load_watchlist(config.DB_PATH) or list(config.WATCHLIST)
    sonuc = gunluk_bildirim(
        db_path=config.DB_PATH, watchlist=watchlist,
        oneri_cfg=config.ONERI, screen_cfg=config.SCREEN,
        macro_cfg=config.MACRO, tg_cfg=config.TELEGRAM)

    if sonuc["gonderildi"]:
        print("✅ Telegram bildirimi gönderildi.")
        print(sonuc["rejim"])
    else:
        print(f"ℹ️ Gönderilmedi: {sonuc['neden']}")


if __name__ == "__main__":
    main()
