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


def _kirp(metin: str, limit: int = 4000) -> str:
    """Mesajı Telegram sınırına kırpar; kesildiyse açıkça belirtir (sessiz kesme yok)."""
    if len(metin) <= limit:
        return metin
    not_ = "\n\n…(mesaj uzunluğu nedeniyle kısaltıldı)"
    return metin[:limit - len(not_)] + not_


def gonder(token: str, chat_id: str, metin: str) -> bool:
    sonuc = _post(token, "sendMessage", {
        "chat_id": chat_id,
        "text": _kirp(metin),
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
        "/aylik     Aylık özet (portföy + piyasa)\n"
        "/oneriler  Ayın hisse önerileri (çok-faktörlü)\n"
        "/performans Geçmiş önerilerim endeksi geçti mi\n"
        "/modeltest Faktörler geçmişte işe yaramış mı (kanıt)\n"
        "/deger     Değer yatırımı taraması (ucuz+kârlı)\n"
        "/sektorler Sektör analizi (aylık performans)\n"
        "/global    Küresel piyasa & makro nabzı (top-down)\n"
        "/duyarlilik Korku/açgözlülük endeksi\n"
        "/fikirler  Günün 5 işlem fikri (giriş/hedef/stop)\n\n"
        "🔍 HİSSE\n"
        "/analiz SEMBOL    Derin teknik analiz + AL/TUT/SAT\n"
        "/temel SEMBOL     Temel analiz (F/K, ROE, marj)\n"
        "/kalite SEMBOL    Finansal kalite skoru + tuzak kontrolü\n"
        "/sinyaltest SEMBOL Sinyal geçmişte işe yaramış mı (edge)\n"
        "/buyume SEMBOL    Büyüme mi temettü hissesi mi\n"
        "/sektor <ad>      Bir sektördeki hisseler\n"
        "/haberetki SEMBOL Haberin işlem etkisi\n"
        "/haberyorum SEMBOL LLM haber yorumu (anahtar gerekir)\n"
        "   (örn: /analiz THYAO)\n\n"
        "💼 PORTFÖY (Telegram'dan yönet)\n"
        "/portfoyum  Pozisyonların + canlı kâr/zarar\n"
        "/ekle SEMBOL ADET [FIYAT]   örn: /ekle THYAO 100 280\n"
        "/sat SEMBOL [ADET]          örn: /sat THYAO 50\n"
        "/alarmlar    Stop/hedef/zarar alarmları\n"
        "/olaylar     Yaklaşan bilanço/temettü takvimi\n"
        "/optimize    Risk-optimal portföy ağırlığı\n"
        "/portfoy     Zayıflık/korelasyon/hedge analizi\n"
        "/cesitlendir Çeşitlendirme önerisi (eksik sektör)\n"
        "/aliskanlik  İşlem alışkanlık analizi + 3 kural\n"
        "/portfoysil  Portföyü sıfırla\n\n"
        "📚 EĞİTİM\n"
        "/riskyonetim Risk yönetimi (stop/pozisyon/çeşit)\n"
        "/ekonomi     Ekonomik göstergeler → borsa\n"
        "/kuresel     Küresel olaylar + korunma\n\n"
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


def cmd_aylik() -> str:
    """Aylık özet raporu."""
    try:
        import config
        from analysis.aylik_ozet import aylik_ozet_metni
        return aylik_ozet_metni(config.DB_PATH, config.MACRO)
    except Exception as exc:
        return f"❌ Aylık özet hatası: {exc}"


def cmd_performans() -> str:
    """Sistemin geçmiş önerilerinin gerçek performansı (endeksle kıyas)."""
    try:
        import config
        from analysis.performans import performans_metni
        return performans_metni(config.DB_PATH, min_gun=15)
    except Exception as exc:
        return f"❌ Performans raporu hatası: {exc}"


def cmd_ayinonerileri() -> str:
    """Ayın hisse önerileri — teknik + temel birleşik."""
    try:
        import config
        from analysis.ayin_onerileri import ayin_onerileri, ayin_onerileri_metni
        ok, hata, oneriler = ayin_onerileri(config.DB_PATH, n=10)
        return ayin_onerileri_metni(oneriler, hata)
    except Exception as exc:
        return f"❌ Ayın önerileri hatası: {exc}"


def cmd_temel(sembol: str) -> str:
    """Tek hisse temel analiz (F/K, PD/DD, ROE...)."""
    try:
        from analysis.temel import tek_hisse_temel
        if not sembol:
            return "Kullanım: /temel THYAO"
        return tek_hisse_temel(sembol)
    except Exception as exc:
        return f"❌ Temel analiz hatası: {exc}"


def cmd_deger() -> str:
    """Değer yatırımı taraması (ucuz + kârlı hisseler)."""
    try:
        from analysis.temel import deger_taramasi
        return deger_taramasi(n=10)
    except Exception as exc:
        return f"❌ Değer taraması hatası: {exc}"


def cmd_buyume(sembol: str) -> str:
    """Büyüme mi temettü hissesi mi sınıflandırması."""
    try:
        from analysis.temel import buyume_temettu
        if not sembol:
            return "Kullanım: /buyume THYAO"
        return buyume_temettu(sembol)
    except Exception as exc:
        return f"❌ Büyüme analizi hatası: {exc}"


def cmd_kalite(sembol: str) -> str:
    """Finansal kalite skoru + değer tuzağı kontrolü."""
    try:
        from analysis.kalite import kalite_tek
        if not sembol:
            return "Kullanım: /kalite THYAO"
        return kalite_tek(sembol)
    except Exception as exc:
        return f"❌ Kalite analizi hatası: {exc}"


def cmd_sinyaltest(sembol: str) -> str:
    """Sinyal edge testi — AL sinyali bu hissede geçmişte işe yaramış mı."""
    try:
        import config
        from analysis.sinyal_test import sinyal_edge_testi
        if not sembol:
            return "Kullanım: /sinyaltest THYAO"
        return sinyal_edge_testi(config.DB_PATH, sembol)
    except Exception as exc:
        return f"❌ Sinyal testi hatası: {exc}"


def cmd_sektorler() -> str:
    """Tüm sektörlerin aylık performans özeti (#1)."""
    try:
        from analysis.sektor import sektor_genel
        return sektor_genel()
    except Exception as exc:
        return f"❌ Sektör analizi hatası: {exc}"


def cmd_sektor(arama: str) -> str:
    """Bir sektördeki hisseler (#1)."""
    try:
        from analysis.sektor import sektor_detay
        if not arama:
            return "Kullanım: /sektor <ad>  (örn: /sektor banka, /sektor enerji)"
        return sektor_detay(arama)
    except Exception as exc:
        return f"❌ Sektör hatası: {exc}"


def cmd_cesitlendir() -> str:
    """Portföy çeşitlendirme önerisi (#2)."""
    try:
        import config
        from analysis.sektor import cesitlendirme_onerisi
        return cesitlendirme_onerisi(config.DB_PATH)
    except Exception as exc:
        return f"❌ Çeşitlendirme hatası: {exc}"


def cmd_global() -> str:
    """Küresel piyasa & makro nabzı (top-down bağlam)."""
    try:
        from analysis.kuresel_piyasa import kuresel_metni
        return kuresel_metni()
    except Exception as exc:
        return f"❌ Küresel nabız hatası: {exc}"


def cmd_optimize() -> str:
    """Portföy optimizasyonu — risk-optimal ağırlık önerisi (gerçek pozisyonlar)."""
    try:
        import config
        from analysis.optimize import optimize_metni
        return optimize_metni(config.DB_PATH)
    except Exception as exc:
        return f"❌ Optimizasyon hatası: {exc}"


def cmd_modeltest() -> str:
    """Faktör kanıtı — modelin fiyat-temelli faktörleri geçmişte işe yaramış mı."""
    try:
        import config
        from analysis.faktor_backtest import faktor_kanit_metni
        return faktor_kanit_metni(config.DB_PATH)
    except Exception as exc:
        return f"❌ Faktör kanıtı hatası: {exc}"


def cmd_olaylar() -> str:
    """Portföydeki hisselerin yaklaşan bilanço/temettü olayları."""
    try:
        import config
        from analysis.olaylar import olaylar_metni
        return olaylar_metni(config.DB_PATH)
    except Exception as exc:
        return f"❌ Olay takvimi hatası: {exc}"


def cmd_duyarlilik() -> str:
    """Piyasa duyarlılığı / korku-açgözlülük (#7)."""
    try:
        import config
        from analysis.duyarlilik import piyasa_duyarliligi
        return piyasa_duyarliligi(config.DB_PATH, config.MACRO)
    except Exception as exc:
        return f"❌ Duyarlılık hatası: {exc}"


def cmd_riskyonetim() -> str:
    """Risk yönetimi rehberi + senin sermayenle örnek (#3)."""
    try:
        import config
        from analysis.egitim import risk_yonetimi
        return risk_yonetimi(config.DB_PATH)
    except Exception as exc:
        return f"❌ Risk yönetimi hatası: {exc}"


def cmd_ekonomi() -> str:
    """Ekonomik göstergeler → borsa etkisi (#5)."""
    try:
        from analysis.egitim import ekonomik_gostergeler
        return ekonomik_gostergeler()
    except Exception as exc:
        return f"❌ Ekonomi hatası: {exc}"


def cmd_kuresel() -> str:
    """Küresel olaylar + korunma stratejileri (#10)."""
    try:
        from analysis.egitim import kuresel_olaylar
        return kuresel_olaylar()
    except Exception as exc:
        return f"❌ Küresel hatası: {exc}"


def cmd_alarmlar() -> str:
    """Portföy stop/hedef/zarar alarmları (Öneri #2+#3)."""
    try:
        import config
        from portfolio.ozet import acik_pozisyonlar
        from analysis.alarm import portfoy_alarmlari, alarm_metni
        if not acik_pozisyonlar(config.DB_PATH):
            return ("📭 Portföyün boş — alarm için önce hisse ekle:\n/ekle THYAO 100 280")
        return alarm_metni(portfoy_alarmlari(config.DB_PATH, config.RISK))
    except Exception as exc:
        return f"❌ Alarm hatası: {exc}"


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


def cmd_haberyorum(sembol: str) -> str:
    """
    LLM haber yorumu (opsiyonel katman). GERÇEK haber başlıklarını Claude'a
    yorumlatır. Anahtar/paket yoksa deterministik haber sinyaline TEMİZCE düşer
    (yarı-bozuk hâl yok). LLM çıktısı 'yorum' katmanıdır — sayısal motora karışmaz.
    """
    try:
        import config
        from analysis.kap import yfinance_haberleri, haber_sinyali, haber_sinyali_metni
        from analysis import llm
        if not sembol:
            return "Kullanım: /haberyorum THYAO"
        sem = sembol.upper()
        if not sem.endswith(".IS") and sem.isalpha() and len(sem) <= 5:
            sem += ".IS"
        kod = sem.replace(".IS", "")

        kayitlar = yfinance_haberleri([sem], limit_per_hisse=8)
        try:
            hr = haber_sinyali(sem, config.DB_PATH, config.HABER.get("rss_feeds"))
        except Exception:
            hr = None
        basliklar = [f"- {k.baslik} ({k.kaynak})" for k in kayitlar[:10]]
        if hr and hr.ok:
            basliklar += [f"- {b}" for _, b, _ in getattr(hr, "basliklar", [])[:6]]
        if not basliklar:
            return (f"📭 {kod} için taze haber bulunamadı. LLM yorumu için haber "
                    "gerekir; şimdilik teknik/temel komutları kullan (/analiz, /temel).")

        sistem = ("Sen dikkatli, temkinli bir Türk borsa analistisin. SANA VERİLEN "
                  "GERÇEK haber başlıklarını yorumla — başlıklarda olmayan hiçbir şeyi "
                  "UYDURMA, veri yoksa 'başlıklardan çıkmıyor' de. Şunları kısa ve net "
                  "Türkçe ver: 1) genel duygu (pozitif/negatif/nötr), 2) kısa vade olası "
                  "etki, 3) uzun vade, 4) dikkat edilecek riskler. AL/SAT tavsiyesi verme.")
        kullanici = f"{kod} hissesi için son haber başlıkları:\n" + "\n".join(basliklar[:14])
        sonuc = llm.cevapla(sistem, kullanici,
                            model=config.LLM.get("model", "claude-opus-4-8"),
                            max_tokens=config.LLM.get("max_tokens", 1200))
        if sonuc.ok:
            return (f"🤖 {kod} — LLM HABER YORUMU (yorum katmanı)\n\n{sonuc.metin}\n\n"
                    "⚠️ Bu bir LLM yorumudur; verilen başlıklara dayanır, sayısal "
                    "faktör skoruna dahil DEĞİLDİR ve yatırım tavsiyesi değildir.")
        # Anahtar/paket yok → deterministik analize temiz düşüş
        det = haber_sinyali_metni(hr) if (hr and hasattr(hr, "sembol")) else "Deterministik analiz yok."
        return (f"ℹ️ LLM yorumu aktif değil ({sonuc.not_}).\n"
                "Aktifleştirmek için: `pip install anthropic` + .env'e ANTHROPIC_API_KEY.\n"
                "Şimdilik deterministik haber analizi:\n\n" + det)
    except Exception as exc:
        return f"❌ Haber yorumu hatası: {exc}"


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


def _coz_sembol(ham: str):
    """
    (guncel_fiyat, cozulen_sembol) — sembolü verildiği gibi, olmazsa .IS ekleyerek dener.
    'THYAO' → THYAO.IS bulur; 'AAPL' bozulmaz. Veri yoksa (None, normalize) döner.
    """
    import config
    from data.access import veri_getir
    s = (ham or "").strip().upper()
    if not s:
        return None, s
    adaylar = [s] + ([s + ".IS"] if "." not in s else [])
    for aday in adaylar:
        fr = veri_getir(config.DB_PATH, aday, period="5d", interval="1d")
        if fr.ok and fr.data is not None and len(fr.data):
            return float(fr.data["Close"].iloc[-1]), aday
    return None, (adaylar[-1])


def cmd_ekle(arglar: list[str]) -> str:
    """/ekle SEMBOL ADET [FIYAT] [gerekçe] — portföye pozisyon ekler."""
    try:
        import config
        from data.storage import save_islem
        from datetime import datetime
        if len(arglar) < 2:
            return ("Kullanım: /ekle SEMBOL ADET [FIYAT] [gerekçe]\n"
                    "Örnek: /ekle THYAO 100 280\n"
                    "Fiyat yazmazsan güncel piyasa fiyatı kullanılır.")
        ham_sembol = arglar[0]
        try:
            adet = float(arglar[1].replace(",", "."))
        except ValueError:
            return f"❌ Adet sayı olmalı: '{arglar[1]}'"
        if adet <= 0:
            return "❌ Adet pozitif olmalı."

        canli, sembol = _coz_sembol(ham_sembol)
        # Fiyat verilmişse onu kullan, yoksa canlı fiyat
        fiyat = None
        gerekce_parcalar = arglar[2:]
        if len(arglar) >= 3:
            try:
                fiyat = float(arglar[2].replace(",", "."))
                gerekce_parcalar = arglar[3:]
            except ValueError:
                fiyat = None  # 3. arg fiyat değil, gerekçenin parçası
        if fiyat is None:
            if canli is None:
                return (f"❌ '{ham_sembol}' için canlı fiyat bulunamadı. "
                        f"Fiyatı elle yaz: /ekle {ham_sembol} {arglar[1]} <fiyat>")
            fiyat = round(canli, 2)

        gerekce = " ".join(gerekce_parcalar).strip()
        tarih = datetime.now().date().isoformat()
        tutar = adet * fiyat
        save_islem(config.DB_PATH, sembol, "AL", tarih, fiyat, adet, tutar, gerekce)

        kod = sembol.replace(".IS", "")
        canli_not = ""
        if canli:
            canli_not = f" · güncel {canli:,.2f}"
        return (f"✅ Eklendi: {adet:g} adet {kod} @ {fiyat:,.2f} ₺"
                f" (toplam {tutar:,.0f} ₺{canli_not})\n"
                f"Portföyü gör: /portfoyum")
    except Exception as exc:
        return f"❌ Ekleme hatası: {exc}"


def cmd_sat(arglar: list[str]) -> str:
    """/sat SEMBOL [ADET] [FIYAT] — pozisyon azaltır/kapatır."""
    try:
        import config
        from data.storage import save_islem
        from portfolio.ozet import acik_pozisyonlar
        from datetime import datetime
        if len(arglar) < 1:
            return ("Kullanım: /sat SEMBOL [ADET] [FIYAT]\n"
                    "Örnek: /sat THYAO 50   (50 adet sat)\n"
                    "Adet yazmazsan tüm pozisyon satılır.")
        canli, sembol = _coz_sembol(arglar[0])
        pos = acik_pozisyonlar(config.DB_PATH)
        if sembol not in pos:
            kod = sembol.replace(".IS", "")
            return f"❌ Portföyünde {kod} yok. /portfoyum ile kontrol et."

        mevcut = pos[sembol]["adet"]
        adet = mevcut
        if len(arglar) >= 2:
            try:
                adet = float(arglar[1].replace(",", "."))
            except ValueError:
                return f"❌ Adet sayı olmalı: '{arglar[1]}'"
        adet = min(adet, mevcut)
        if adet <= 0:
            return "❌ Satılacak adet pozitif olmalı."

        fiyat = None
        if len(arglar) >= 3:
            try:
                fiyat = float(arglar[2].replace(",", "."))
            except ValueError:
                fiyat = None
        if fiyat is None:
            if canli is None:
                return f"❌ '{arglar[0]}' güncel fiyatı yok. Fiyatı elle yaz."
            fiyat = round(canli, 2)

        tarih = datetime.now().date().isoformat()
        tutar = adet * fiyat
        save_islem(config.DB_PATH, sembol, "SAT", tarih, fiyat, adet, tutar, "telegram /sat")

        kod = sembol.replace(".IS", "")
        kalan = mevcut - adet
        return (f"✅ Satıldı: {adet:g} adet {kod} @ {fiyat:,.2f} ₺ "
                f"(toplam {tutar:,.0f} ₺)\n"
                f"Kalan: {kalan:g} adet\n/portfoyum")
    except Exception as exc:
        return f"❌ Satış hatası: {exc}"


def cmd_portfoyum() -> str:
    """/portfoyum — açık pozisyonlar + canlı kâr/zarar."""
    try:
        import config
        from portfolio.ozet import acik_pozisyonlar
        from data.access import veri_getir

        pos = acik_pozisyonlar(config.DB_PATH)
        if not pos:
            return ("📭 Portföyün boş.\n\n"
                    "Hisse eklemek için:\n/ekle THYAO 100 280\n"
                    "(100 adet THYAO, 280 ₺'den)")

        sat = [f"💼 PORTFÖYÜM ({len(pos)} hisse)", ""]
        toplam_maliyet = 0.0
        toplam_deger = 0.0
        satir_veriler = []
        for sembol, p in pos.items():
            kod = sembol.replace(".IS", "")
            adet, maliyet = p["adet"], p["maliyet"]
            fr = veri_getir(config.DB_PATH, sembol, period="5d", interval="1d")
            guncel = float(fr.data["Close"].iloc[-1]) if (fr.ok and fr.data is not None and len(fr.data)) else None
            mal_tutar = adet * maliyet
            toplam_maliyet += mal_tutar
            if guncel:
                deger = adet * guncel
                toplam_deger += deger
                kz_pct = (guncel - maliyet) / maliyet * 100 if maliyet else 0
                kz_tl = (guncel - maliyet) * adet
                isaret = "🟢" if kz_pct >= 0 else "🔴"
                satir_veriler.append(
                    f"{isaret} {kod}: {adet:g} ad · maliyet {maliyet:,.2f} → "
                    f"güncel {guncel:,.2f}\n"
                    f"     K/Z: %{kz_pct:+.1f} ({kz_tl:+,.0f} ₺)")
            else:
                toplam_deger += mal_tutar
                satir_veriler.append(
                    f"⚪ {kod}: {adet:g} ad · maliyet {maliyet:,.2f} (güncel fiyat yok)")

        sat += satir_veriler
        toplam_kz = toplam_deger - toplam_maliyet
        toplam_kz_pct = (toplam_kz / toplam_maliyet * 100) if toplam_maliyet else 0
        isaret_t = "🟢" if toplam_kz >= 0 else "🔴"
        sat += [
            "",
            "━━━━━━━━━━━━━━",
            f"💰 Maliyet: {toplam_maliyet:,.0f} ₺",
            f"📊 Güncel değer: {toplam_deger:,.0f} ₺",
            f"{isaret_t} Toplam K/Z: %{toplam_kz_pct:+.1f} ({toplam_kz:+,.0f} ₺)",
            "",
            "Analiz: /portfoy (risk)  ·  /aliskanlik",
            "Düzenle: /ekle  ·  /sat  ·  /portfoysil",
        ]
        return "\n".join(sat)
    except Exception as exc:
        return f"❌ Portföy görüntüleme hatası: {exc}"


def cmd_portfoysil(arg: str = "") -> str:
    """/portfoysil [onay] — tüm portföyü siler (onay gerekir)."""
    try:
        import config
        from data.storage import temizle_portfolio
        if arg.strip().lower() not in ("onay", "evet", "sil"):
            return ("⚠️ Tüm portföyünü silmek üzeresin (geri alınamaz).\n"
                    "Onaylamak için: /portfoysil onay")
        temizle_portfolio(config.DB_PATH)
        return "🗑️ Portföy tamamen silindi. /ekle ile yeniden oluşturabilirsin."
    except Exception as exc:
        return f"❌ Silme hatası: {exc}"


def cmd_portfoy() -> str:
    """Portföyden zayıflık/korelasyon/hedge analizi (Özellik #3)."""
    try:
        import config
        import pandas as pd
        from portfolio.ozet import acik_pozisyonlar
        from data.access import veri_getir
        from analysis.risk import portfoy_zayiflik, portfoy_zayiflik_metni

        pos = acik_pozisyonlar(config.DB_PATH)
        if not pos:
            return ("📭 Portföyün boş. Önce hisse ekle:\n"
                    "/ekle THYAO 100 280\nSonra /portfoy ile analiz et.")
        # Güncel fiyatlarla değer → dağılım %
        kapanis = {}
        degerler = {}
        for sembol, p in pos.items():
            kod = sembol.replace(".IS", "")
            fr = veri_getir(config.DB_PATH, sembol, period="6mo", interval="1d")
            if fr.ok and fr.data is not None:
                kapanis[kod] = fr.data["Close"]
                degerler[kod] = p["adet"] * float(fr.data["Close"].iloc[-1])
        if not degerler:
            return "❌ Pozisyon fiyatları alınamadı."
        fiyat_df = pd.DataFrame(kapanis).dropna() if len(kapanis) >= 2 else None
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
    arglar = parcalar[1:]   # komuttan sonraki tüm argümanlar

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
    elif komut == "/aylik":
        gonder(token, chat_id, "⏳ Aylık özet hazırlanıyor (biraz sürebilir)...")
        yanit = cmd_aylik()
    elif komut in ("/alarmlar", "/alarm"):
        gonder(token, chat_id, "⏳ Portföy alarmları kontrol ediliyor...")
        yanit = cmd_alarmlar()
    elif komut in ("/ayinonerileri", "/ayinhisseleri", "/oneriler"):
        gonder(token, chat_id, "⏳ Ayın önerileri: 607 hisse çok-faktörlü analizden geçiyor (1-2 dk)...")
        yanit = cmd_ayinonerileri()
    elif komut in ("/performans", "/performance"):
        gonder(token, chat_id, "⏳ Geçmiş önerilerin performansı ölçülüyor...")
        yanit = cmd_performans()
    elif komut == "/temel":
        gonder(token, chat_id, f"⏳ {arg or 'hisse'} temel analizi...")
        yanit = cmd_temel(arg)
    elif komut == "/deger":
        gonder(token, chat_id, "⏳ Değer yatırımı taraması...")
        yanit = cmd_deger()
    elif komut == "/buyume":
        gonder(token, chat_id, f"⏳ {arg or 'hisse'} büyüme/temettü analizi...")
        yanit = cmd_buyume(arg)
    elif komut == "/kalite":
        gonder(token, chat_id, f"⏳ {arg or 'hisse'} finansal kalite analizi...")
        yanit = cmd_kalite(arg)
    elif komut in ("/sinyaltest", "/edge"):
        gonder(token, chat_id, f"⏳ {arg or 'hisse'} sinyal edge testi (geçmiş analizi)...")
        yanit = cmd_sinyaltest(arg)
    elif komut in ("/sektorler", "/sektörler"):
        gonder(token, chat_id, "⏳ Sektör analizi hazırlanıyor...")
        yanit = cmd_sektorler()
    elif komut in ("/sektor", "/sektör"):
        gonder(token, chat_id, "⏳ Sektör inceleniyor...")
        yanit = cmd_sektor(arg)
    elif komut in ("/cesitlendir", "/çeşitlendir"):
        gonder(token, chat_id, "⏳ Çeşitlendirme önerisi hazırlanıyor...")
        yanit = cmd_cesitlendir()
    elif komut in ("/global", "/dunya", "/dünya"):
        gonder(token, chat_id, "⏳ Küresel piyasa nabzı çekiliyor...")
        yanit = cmd_global()
    elif komut in ("/olaylar", "/takvim"):
        gonder(token, chat_id, "⏳ Bilanço/temettü takvimi kontrol ediliyor...")
        yanit = cmd_olaylar()
    elif komut in ("/modeltest", "/faktortest"):
        gonder(token, chat_id, "⏳ Faktör kanıtı: likit sepet geçmişi analiz ediliyor (1-2 dk)...")
        yanit = cmd_modeltest()
    elif komut in ("/optimize", "/optimizasyon"):
        gonder(token, chat_id, "⏳ Portföy risk-optimizasyonu hesaplanıyor...")
        yanit = cmd_optimize()
    elif komut in ("/duyarlilik", "/duyarlılık"):
        gonder(token, chat_id, "⏳ Piyasa duyarlılığı hesaplanıyor...")
        yanit = cmd_duyarlilik()
    elif komut in ("/riskyonetim", "/risk"):
        yanit = cmd_riskyonetim()
    elif komut == "/ekonomi":
        yanit = cmd_ekonomi()
    elif komut in ("/kuresel", "/küresel"):
        yanit = cmd_kuresel()
    elif komut == "/fikirler":
        gonder(token, chat_id, "⏳ Günün 5 fikri analiz ediliyor (biraz sürebilir)...")
        yanit = cmd_fikirler()
    elif komut == "/analiz":
        gonder(token, chat_id, f"⏳ {arg or 'hisse'} analiz ediliyor...")
        yanit = cmd_analiz(arg)
    elif komut == "/haberetki":
        gonder(token, chat_id, f"⏳ {arg or 'hisse'} haberleri taranıyor...")
        yanit = cmd_haberetki(arg)
    elif komut in ("/haberyorum", "/llmhaber"):
        gonder(token, chat_id, f"⏳ {arg or 'hisse'} haberleri LLM ile yorumlanıyor...")
        yanit = cmd_haberyorum(arg)
    elif komut == "/aliskanlik":
        yanit = cmd_aliskanlik()
    elif komut == "/ekle":
        yanit = cmd_ekle(arglar)
    elif komut == "/sat":
        yanit = cmd_sat(arglar)
    elif komut in ("/portfoyum", "/portfoy_um"):
        gonder(token, chat_id, "⏳ Portföyün güncel fiyatlarla hesaplanıyor...")
        yanit = cmd_portfoyum()
    elif komut == "/portfoysil":
        yanit = cmd_portfoysil(arg)
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


# ── Zamanlı bildirim (launchd'siz — bot içi zamanlayıcı) ──────────────────────
# macOS'ta launchd venv Python'u çalıştırırken "Resource deadlock avoided" ile
# çöküyor. Bu yüzden günlük/aylık bildirimleri, zaten 7/24 çalışan bot süreci
# gönderir. Bot çalıştığı sürece (Mac açıkken) bildirimler zamanında gider.
# Mac kapalıysa, açıldığında aynı gün içindeki pencerede telafi eder.

_DURUM_DOSYA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "raporlar", "zamanli_durum.json")


def _durum_oku() -> dict:
    try:
        with open(_DURUM_DOSYA, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"gonderilen": []}


def _durum_yaz(d: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_DURUM_DOSYA), exist_ok=True)
        with open(_DURUM_DOSYA, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception as exc:
        print(f"[zamanli] durum yazılamadı: {exc}")


def _gunici_bildirim_gonder() -> None:
    import config
    from automation.notify import tam_bist_bildirim
    tam_bist_bildirim(
        db_path=config.DB_PATH, macro_cfg=config.MACRO,
        tg_cfg=config.TELEGRAM, screen_cfg=config.SCREEN,
        haber_cfg=getattr(config, "HABER", None), mod="gunici")


def _aylik_bildirim_gonder() -> None:
    import config
    from automation.notify import telegram_gonder
    from analysis.aylik_ozet import aylik_ozet_metni
    from analysis.ayin_onerileri import ayin_onerileri, ayin_onerileri_metni
    telegram_gonder(aylik_ozet_metni(config.DB_PATH, config.MACRO))
    ok, hata, oneriler = ayin_onerileri(config.DB_PATH, n=10)
    telegram_gonder(ayin_onerileri_metni(oneriler, hata))
    # Performans takibi: bu ayın önerilerini kaydet (sonra kendini ölçer)
    try:
        from analysis.performans import oneri_kaydet
        oneri_kaydet(config.DB_PATH, oneriler, kaynak="aylik")
    except Exception as exc:
        print(f"[aylik] öneri takip kaydı hatası: {exc}")
    # Geçmiş önerilerin performansını da gönder (varsa)
    try:
        from analysis.performans import performans_metni, performans_raporu
        sonuclar, _ = performans_raporu(config.DB_PATH, min_gun=15)
        if sonuclar:
            telegram_gonder(performans_metni(config.DB_PATH, min_gun=15))
    except Exception as exc:
        print(f"[aylik] performans raporu hatası: {exc}")


_son_zamanli_kontrol = 0.0   # epoch — çok sık dosya okumamak için throttle


def _zamanli_gonderim() -> None:
    """
    Her döngüde çağrılır; zamanı gelen bildirimleri (bir kez) gönderir.
    En fazla dakikada bir gerçek kontrol yapar (gereksiz dosya I/O'yu önler).
    Uzun süren gönderimler bot yanıt döngüsünü geçici bloklar; bu kabul edilir
    çünkü gönderim günde yalnızca birkaç kez ve tek seferlik tetiklenir.
    """
    global _son_zamanli_kontrol
    simdi = time.monotonic()
    if simdi - _son_zamanli_kontrol < 60:
        return
    _son_zamanli_kontrol = simdi

    now = datetime.now()
    durum = _durum_oku()
    gonderilen = set(durum.get("gonderilen", []))
    bugun = now.strftime("%Y-%m-%d")
    ay = now.strftime("%Y-%m")
    degisti = False

    islenecek = []
    # Günlük — hafta içi (Pzt-Cum). Sabah penceresi 10:00-14:00, akşam 18:00-23:00.
    # Pencere: Mac o saatte kapalıysa açılınca aynı gün telafi eder.
    if now.weekday() < 5:
        if 10 <= now.hour < 14:
            islenecek.append((f"gunici-sabah-{bugun}", _gunici_bildirim_gonder))
        if 18 <= now.hour < 23:
            islenecek.append((f"gunici-aksam-{bugun}", _gunici_bildirim_gonder))
    # Aylık — ayın 1'i, 10:30 sonrası (23:00'a kadar telafi penceresi)
    if now.day == 1 and (now.hour > 10 or (now.hour == 10 and now.minute >= 30)) and now.hour < 23:
        islenecek.append((f"aylik-{ay}", _aylik_bildirim_gonder))

    for anahtar, fn in islenecek:
        if anahtar in gonderilen:
            continue
        try:
            print(f"[{now:%H:%M:%S}] Zamanlı bildirim gönderiliyor: {anahtar}")
            fn()
            gonderilen.add(anahtar)
            degisti = True
        except Exception as exc:
            print(f"[zamanli] {anahtar} gönderilemedi: {exc}")

    if degisti:
        durum["gonderilen"] = sorted(gonderilen)[-60:]   # eski kayıtları buda
        _durum_yaz(durum)


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
            else:
                for guncelleme in veri.get("result", []):
                    offset = guncelleme["update_id"] + 1
                    mesaj = guncelleme.get("message")
                    if mesaj:
                        _isle(token, chat_id, mesaj)

            # Zamanlı bildirimleri kontrol et (launchd'siz). getUpdates ağ hatası
            # verse bile çalışır — geçici bir polling sorunu planlı gönderimi
            # sonsuza dek engellemesin. Kendi içinde dakikada bir throttle'lıdır.
            _zamanli_gonderim()

        except KeyboardInterrupt:
            print("\nBot durduruldu.")
            break
        except Exception as exc:
            print(f"[{datetime.now():%H:%M:%S}] Hata: {exc}")
            time.sleep(_POLL_INTERVAL)


if __name__ == "__main__":
    calistir()
