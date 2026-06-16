"""
Telegram interaktif komut botu (Aşama 13).

Komutlar (yalnızca .env'deki TELEGRAM_CHAT_ID'ye yanıt verir):
    /yardim    — komut listesi
    /durum     — anlık piyasa rejimi + XU100
    /tarama    — izleme listesi AL/Kaçın özeti
    /bist      — tüm BIST TradingView taraması (500 hisse)
    /haberler  — günün önemli haberleri (RSS)
    /arzlar    — son halka arzlar
    /rapor     — bugünün tam analiz raporu
    /watchlist — aktif izleme listesi

Çalıştırma (daemon olarak LaunchAgent yönetir):
    python -m automation.bot

NOT: getUpdates ile 5s polling yapar. Webhook kurmak gerekmez.
"""

from __future__ import annotations
import os
import sys
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # .env'i yükler (TELEGRAM_BOT_TOKEN vs. için gerekli)

_TG_API = "https://api.telegram.org/bot{token}/{method}"
_POLL_INTERVAL = 5       # saniye
_TIMEOUT_UZUN  = 20      # long-poll timeout (API tarafında)


# ── Düşük seviye Telegram ────────────────────────────────────────────────────

def _get(token: str, method: str, params: dict | None = None,
         timeout: float = 30.0) -> dict:
    url = _TG_API.format(token=token, method=method)
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _post(token: str, method: str, veri: dict,
          timeout: float = 15.0) -> dict:
    encoded = urllib.parse.urlencode(veri).encode()
    req = urllib.request.Request(
        _TG_API.format(token=token, method=method), data=encoded)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def gonder(token: str, chat_id: str, metin: str) -> bool:
    sonuc = _post(token, "sendMessage", {
        "chat_id": chat_id,
        "text": metin[:4000],
        "disable_web_page_preview": "true",
    })
    return bool(sonuc.get("ok"))


# ── Komut işleyiciler ────────────────────────────────────────────────────────

def cmd_yardim() -> str:
    return (
        "🤖 Borsa Bot — Komutlar\n\n"
        "📋 PİYASA\n"
        "/durum     Anlık piyasa rejimi\n"
        "/bist      Tüm BIST taraması (607 hisse)\n"
        "/plan      Günlük işlem planı (saat saat)\n"
        "/fikirler  Günün 5 işlem fikri (giriş/hedef/stop)\n\n"
        "🔍 HİSSE\n"
        "/analiz SEMBOL    Derin teknik analiz + AL/TUT/SAT\n"
        "/haberetki SEMBOL Haberin işlem etkisi\n"
        "   (örn: /analiz THYAO)\n\n"
        "🧠 SEN\n"
        "/aliskanlik İşlem alışkanlık analizi + 3 kural\n"
        "/portfoy    Portföy zayıflık/korelasyon (panelden gir)\n\n"
        "📰 DİĞER\n"
        "/haberler  Günün önemli haberleri\n"
        "/arzlar    Son halka arzlar (90 gün)\n"
        "/tarama    İzleme listesi özeti\n"
        "/watchlist Takip ettiğin hisseler\n"
        "/yardim    Bu liste\n\n"
        "⚠️ Teknik taramadır, yatırım tavsiyesi değildir."
    )


def cmd_plan() -> str:
    """Günlük işlem planı (Özellik #1)."""
    try:
        import config
        from analysis.gunluk_plan import gunluk_plan_metni
        return gunluk_plan_metni(config.DB_PATH, config.MACRO,
                                 getattr(config, "HABER", None))
    except Exception as exc:
        return f"❌ Plan hatası: {exc}"


def cmd_fikirler() -> str:
    """Günün 5 işlem fikri (Özellik #7)."""
    try:
        import config
        from analysis.fikirler import gunun_fikirleri, metin_ozet
        ok, hata, fikirler = gunun_fikirleri(config.DB_PATH, n_fikir=5, aday_havuzu=20)
        if not ok:
            return f"❌ Fikir hatası: {hata}"
        return metin_ozet(fikirler)
    except Exception as exc:
        return f"❌ Fikir hatası: {exc}"


def cmd_analiz(sembol: str) -> str:
    """Derin teknik analiz + net karar (Özellik #6)."""
    try:
        import config
        from data.access import veri_getir
        from analysis.teknik_derin import analiz_et, metin_ozet
        if not sembol:
            return "Kullanım: /analiz THYAO  (sembol gir)"
        sem = sembol.upper()
        if not sem.endswith(".IS") and sem.isalpha() and len(sem) <= 5:
            sem += ".IS"
        fr = veri_getir(config.DB_PATH, sem, period="1y", interval="1d")
        if not fr.ok or fr.data is None:
            return f"❌ {sem} verisi alınamadı: {fr.note}"
        return metin_ozet(analiz_et(fr.data, sem))
    except Exception as exc:
        return f"❌ Analiz hatası: {exc}"


def cmd_haberetki(sembol: str) -> str:
    """Haberin işlem etkisi (Özellik #5)."""
    try:
        import config
        from analysis.kap import haber_sinyali, haber_sinyali_metni
        if not sembol:
            return "Kullanım: /haberetki THYAO  (sembol gir)"
        sem = sembol.upper()
        if not sem.endswith(".IS") and sem.isalpha() and len(sem) <= 5:
            sem += ".IS"
        hs = haber_sinyali(sem, config.DB_PATH, config.HABER.get("rss_feeds"))
        return haber_sinyali_metni(hs)
    except Exception as exc:
        return f"❌ Haber etki hatası: {exc}"


def cmd_aliskanlik() -> str:
    """İşlem alışkanlık analizi (Özellik #2)."""
    try:
        import config
        from analysis.islem_aliskanlik import analiz_et, metin_ozet
        return metin_ozet(analiz_et(config.DB_PATH, n=20))
    except Exception as exc:
        return f"❌ Alışkanlık analizi hatası: {exc}"


def cmd_portfoy() -> str:
    """Sanal portföyden zayıflık analizi (Özellik #3)."""
    try:
        import config
        import pandas as pd
        from data.storage import load_portfolio
        from data.access import veri_getir
        from analysis.risk import portfoy_zayiflik, portfoy_zayiflik_metni

        p = load_portfolio(config.DB_PATH)
        if not p.pozisyonlar:
            return ("📭 Açık pozisyon yok. Panelden Sanal Portföy'e alım yap ya da "
                    "korelasyon/zayıflık analizini panelden manuel dağılımla çalıştır.")
        # Güncel fiyatlarla değer → dağılım %
        kapanis = {}
        for sym in p.pozisyonlar:
            fr = veri_getir(config.DB_PATH, sym, period="6mo", interval="1d")
            if fr.ok:
                kapanis[sym.replace(".IS", "")] = fr.data["Close"]
        degerler = {}
        for sym, poz in p.pozisyonlar.items():
            kod = sym.replace(".IS", "")
            if kod in kapanis:
                degerler[kod] = poz.adet * float(kapanis[kod].iloc[-1])
        if not degerler:
            return "❌ Pozisyon fiyatları alınamadı."
        fiyat_df = pd.DataFrame(kapanis).dropna()
        rapor = portfoy_zayiflik(degerler, fiyat_df)
        return portfoy_zayiflik_metni(rapor)
    except Exception as exc:
        return f"❌ Portföy analizi hatası: {exc}"


def cmd_durum() -> str:
    try:
        import config
        from data.access import veri_getir
        from analysis import macro

        fr = veri_getir(config.DB_PATH, "XU100.IS", period="2y", interval="1d")
        if not fr.ok or fr.data is None:
            return "❌ XU100.IS verisi alınamadı."
        rej = macro.rejim_tespit(fr.data)
        ozet = macro.ozetle(rej)
        kapanis = fr.data["Close"].iloc[-1] if "Close" in fr.data.columns else None
        tarih = fr.meta.get("son_tarih", "?")
        fiyat = f"{kapanis:,.2f}" if kapanis else "?"
        return (
            f"🌐 Piyasa Durumu — {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"📈 XU100.IS: {fiyat} ({tarih})\n"
            f"🔍 Rejim: {ozet}\n\n"
            f"⚠️ Teknik gösterge — yatırım tavsiyesi değildir."
        )
    except Exception as exc:
        return f"❌ Hata: {exc}"


def cmd_tarama() -> str:
    try:
        import config
        from data.storage import load_watchlist
        from analysis import recommender as rec
        from analysis import macro
        from data.access import veri_getir

        watchlist = load_watchlist(config.DB_PATH) or list(config.WATCHLIST)
        fr = veri_getir(config.DB_PATH, "XU100.IS", period="2y", interval="1d")
        rejim = ""
        if fr.ok and fr.data is not None:
            rejim = macro.rejim_tespit(fr.data).rejim

        satirlar = rec.oneri_tara(
            watchlist, config.ONERI,
            thin_volume=config.SCREEN["thin_volume"],
            rejim=rejim, period=config.ONERI["varsayilan_periyot"],
        )

        al  = [r for r in satirlar if r.aksiyon in ("Güçlü AL adayı", "AL adayı")]
        izle = [r for r in satirlar if r.aksiyon == "Nötr / İzle"]
        kacin = [r for r in satirlar if r.aksiyon == "Zayıf / Kaçın"]

        satirlar_out = [
            f"📊 Hızlı Tarama — {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            f"Taranan: {len(satirlar)} hisse\n",
        ]

        if al:
            satirlar_out.append("🟢 AL ADAYLARI")
            for r in al[:5]:
                isaret = "🔥" if r.aksiyon == "Güçlü AL adayı" else "⭐"
                satirlar_out.append(
                    f"  {isaret} {r.symbol} — skor {r.skor}/100 ({r.guven} güven)"
                )
        if izle:
            satirlar_out.append("\n🟡 İZLE")
            for r in izle[:3]:
                satirlar_out.append(f"  • {r.symbol} — skor {r.skor}/100")
        if kacin:
            satirlar_out.append("\n🔴 KAÇIN")
            for r in kacin[:3]:
                satirlar_out.append(f"  • {r.symbol} — skor {r.skor}/100")

        satirlar_out.append(
            "\n⚠️ Teknik taramadır, yatırım tavsiyesi değildir."
        )
        return "\n".join(satirlar_out)
    except Exception as exc:
        return f"❌ Tarama hatası: {exc}"


def cmd_rapor() -> str:
    try:
        import config
        bugun = datetime.now().strftime("%Y-%m-%d")
        yol = os.path.join(
            config.OTOMASYON["rapor_klasoru"],
            f"rapor-{bugun}.md",
        )
        if not os.path.exists(yol):
            return (
                f"📭 Bugünün raporu henüz oluşturulmadı ({bugun}).\n"
                "Rapor her gün 18:30'da otomatik üretilir.\n"
                "Hemen üretmek için: terminalde\n"
                "  python -m automation.run"
            )
        with open(yol, encoding="utf-8") as f:
            icerik = f.read()
        # 4000 karakterle sınırla
        return icerik[:3900] + ("\n\n…(kısaltıldı)" if len(icerik) > 3900 else "")
    except Exception as exc:
        return f"❌ Rapor okunamadı: {exc}"


def cmd_bist() -> str:
    """TradingView scanner ile tüm BIST'i tarar."""
    try:
        from analysis.bist_tarama import bist_tara, ozet_istatistik
        ok, hata, satirlar = bist_tara()
        if not ok:
            return f"❌ BIST tarama hatası: {hata}"

        ist = ozet_istatistik(satirlar)
        adaylar = [r for r in satirlar if r.aksiyon in ("Güçlü AL adayı", "AL adayı")]

        satirlar_out = [
            f"📊 BIST Tam Tarama — {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            f"Taranan: {ist['toplam']} hisse",
            f"▲ {ist['yukselis']}  ▼ {ist['dusus']}  ➡ {ist['degismedi']}",
            f"Ort. değişim: %{ist.get('ort_degisim_pct', 0):+.2f}",
            f"Güçlü AL: {ist['guclu_al']}  AL: {ist['al_adayi']}  İzle: {ist['izle']}",
            "",
        ]

        if adaylar:
            satirlar_out.append("🟢 ÖNCÜ AL ADAYLARI (ilk 6):")
            for r in adaylar[:6]:
                isaret = "🔥" if r.aksiyon == "Güçlü AL adayı" else "⭐"
                deg = f"%{r.degisim_pct:+.1f}" if r.degisim_pct is not None else "—"
                rsi = str(r.rsi) if r.rsi else "—"
                satirlar_out.append(
                    f"  {isaret} {r.sembol} · {deg} · RSI {rsi} · {r.ema_durumu}"
                )
        else:
            satirlar_out.append("🟡 Güçlü AL adayı tespit edilmedi.")

        satirlar_out.append("\n⚠️ TradingView verisine dayanır, tavsiye değildir.")
        return "\n".join(satirlar_out)
    except Exception as exc:
        return f"❌ BIST tarama hatası: {exc}"


def cmd_haberler() -> str:
    """RSS akışlarından günün önemli haberlerini getirir."""
    try:
        import config
        from analysis.kap import piyasa_akisi
        haber_cfg = getattr(config, "HABER", {})
        rss = haber_cfg.get("rss_feeds", {})
        if not rss:
            return "❌ RSS akışı tanımlı değil (config.HABER)."
        hr = piyasa_akisi(rss, limit=5)
        if not hr.ok:
            return f"❌ Haber alınamadı: {hr.hata}"

        satirlar_out = [
            f"📰 Günün Haberleri — {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            "",
        ]
        kap_benzeri = [k for k in hr.kayitlar if k.kategori == "kap_benzeri"]
        diger = [k for k in hr.kayitlar if k.kategori != "kap_benzeri"]

        if kap_benzeri:
            satirlar_out.append("🔔 KAP Benzeri / Önemli:")
            for h in kap_benzeri[:4]:
                satirlar_out.append(f"• {h.baslik[:100]}  —{h.kaynak}")
            satirlar_out.append("")

        satirlar_out.append("📰 Genel Haberler:")
        for h in diger[:6]:
            satirlar_out.append(f"• {h.baslik[:100]}  —{h.kaynak}")

        satirlar_out.append("\nKaynak: RSS akışları · kap.org.tr doğrudan erişim değil.")
        return "\n".join(satirlar_out)
    except Exception as exc:
        return f"❌ Haber hatası: {exc}"


def cmd_arzlar() -> str:
    """Son 90 günde halka arz edilen hisseleri listeler."""
    try:
        from data.bist_evren import bist_evren_al
        from analysis.kap import halka_arz_tara

        # Evrenin tamamını değil, yeni hisse tespiti için örneklem al
        evren = bist_evren_al()
        sonuclar = halka_arz_tara(evren[:50], son_gun=90)

        if not sonuclar:
            return "📭 Son 90 günde halka arz tespit edilmedi.\n(yfinance verisi yetersiz olabilir)"

        satirlar_out = [
            f"🆕 Son Halka Arzlar — {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            f"(Son 90 gün, {len(sonuclar)} şirket)",
            "",
        ]
        for h in sonuclar:
            getiri = f"%{h.getiri_pct:+.1f}" if h.getiri_pct is not None else "?"
            fiyat = f"{h.son_fiyat}" if h.son_fiyat else "?"
            satirlar_out.append(
                f"• {h.sembol} — ilk işlem: {h.ilk_islem_tarihi}\n"
                f"  Fiyat: {fiyat} · Halka arza göre getiri: {getiri}"
            )

        satirlar_out.append("\nKaynak: yfinance ilk işlem tarihi.")
        return "\n".join(satirlar_out)
    except Exception as exc:
        return f"❌ Halka arz tarama hatası: {exc}"


def cmd_watchlist() -> str:
    try:
        import config
        from data.storage import load_watchlist
        wl = load_watchlist(config.DB_PATH) or list(config.WATCHLIST)
        bist   = [s for s in wl if s.endswith(".IS")]
        global_ = [s for s in wl if not s.endswith(".IS")]
        satirlar = [
            f"📋 İzleme Listesi ({len(wl)} hisse)\n",
            f"🇹🇷 BIST ({len(bist)}):",
            "  " + "  ".join(bist),
        ]
        if global_:
            satirlar += [
                f"\n🌍 Global ({len(global_)}):",
                "  " + "  ".join(global_),
            ]
        return "\n".join(satirlar)
    except Exception as exc:
        return f"❌ Hata: {exc}"


# ── Polling döngüsü ───────────────────────────────────────────────────────────

def _isle(token: str, chat_id: str, mesaj: dict) -> None:
    """Gelen mesajı işle, yetkili chat'ten geliyorsa yanıtla."""
    sohbet = mesaj.get("chat", {})
    gelen_id = str(sohbet.get("id", ""))
    if gelen_id != str(chat_id):
        return  # Yabancı mesaj — sessizce geç

    ham = (mesaj.get("text") or "").strip()
    if not ham:
        return
    parcalar = ham.split()
    komut = parcalar[0].lower()
    arg = parcalar[1] if len(parcalar) > 1 else ""

    if komut in ("/yardim", "/start", "/help"):
        yanit = cmd_yardim()
    elif komut == "/durum":
        yanit = cmd_durum()
    elif komut == "/tarama":
        yanit = cmd_tarama()
    elif komut == "/bist":
        gonder(token, chat_id, "⏳ Tüm BIST taranıyor (607 hisse)...")
        yanit = cmd_bist()
    elif komut == "/plan":
        gonder(token, chat_id, "⏳ Günlük plan hazırlanıyor...")
        yanit = cmd_plan()
    elif komut == "/fikirler":
        gonder(token, chat_id, "⏳ Günün 5 fikri analiz ediliyor (biraz sürebilir)...")
        yanit = cmd_fikirler()
    elif komut == "/analiz":
        gonder(token, chat_id, f"⏳ {arg or 'hisse'} analiz ediliyor...")
        yanit = cmd_analiz(arg)
    elif komut == "/haberetki":
        gonder(token, chat_id, f"⏳ {arg or 'hisse'} haberleri taranıyor...")
        yanit = cmd_haberetki(arg)
    elif komut == "/aliskanlik":
        yanit = cmd_aliskanlik()
    elif komut == "/portfoy":
        gonder(token, chat_id, "⏳ Portföy analiz ediliyor...")
        yanit = cmd_portfoy()
    elif komut == "/haberler":
        gonder(token, chat_id, "⏳ Haberler çekiliyor...")
        yanit = cmd_haberler()
    elif komut == "/arzlar":
        gonder(token, chat_id, "⏳ Halka arzlar kontrol ediliyor...")
        yanit = cmd_arzlar()
    elif komut == "/rapor":
        yanit = cmd_rapor()
    elif komut == "/watchlist":
        yanit = cmd_watchlist()
    else:
        yanit = "Komut tanınmadı. /yardim ile komut listesine bak."

    gonder(token, chat_id, yanit)


def calistir() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik. .env kontrol et.")
        sys.exit(1)

    print(f"[{datetime.now():%H:%M:%S}] Bot başladı. Chat: {chat_id}")
    offset = 0

    while True:
        try:
            veri = _get(token, "getUpdates", {
                "offset": offset,
                "timeout": _TIMEOUT_UZUN,
                "allowed_updates": '["message"]',
            }, timeout=_TIMEOUT_UZUN + 5)

            if not veri.get("ok"):
                print(f"getUpdates hatası: {veri}")
                time.sleep(_POLL_INTERVAL)
                continue

            for guncelleme in veri.get("result", []):
                offset = guncelleme["update_id"] + 1
                mesaj = guncelleme.get("message")
                if mesaj:
                    _isle(token, chat_id, mesaj)

        except KeyboardInterrupt:
            print("\nBot durduruldu.")
            break
        except Exception as exc:
            print(f"[{datetime.now():%H:%M:%S}] Hata: {exc}")
            time.sleep(_POLL_INTERVAL)


if __name__ == "__main__":
    calistir()
