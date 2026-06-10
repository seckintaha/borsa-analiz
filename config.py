"""
Merkezi ayarlar — tüm sabitler buradan yönetilir.
"""

import os as _os


# ── .env otomatik yükleme (saf stdlib, bağımlılıksız) ────────────────────────
# Proje kökündeki `.env` dosyasını okuyup ortam değişkenlerine aktarır. Böylece
# hem Streamlit hem cron (`python -m automation.notify`) anahtarları kendiliğinden
# bulur; elle `set -a; source .env` yapmak gerekmez.
# İlke: kabukta ZATEN tanımlı bir değişkenin üzerine YAZILMAZ (açık ortam kazanır).
# Boş değerler ("ANAHTAR=") atlanır → yarım doldurulmuş .env yanlış pozitif vermez.
def _env_yukle(yol: str) -> None:
    try:
        with open(yol, "r", encoding="utf-8") as f:
            satirlar = f.readlines()
    except OSError:
        return
    for ham in satirlar:
        s = ham.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        if s.startswith("export "):
            s = s[len("export "):]
        anahtar, _, deger = s.partition("=")
        anahtar = anahtar.strip()
        deger = deger.strip().strip('"').strip("'")
        if anahtar and deger and anahtar not in _os.environ:
            _os.environ[anahtar] = deger


_env_yukle(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".env"))


# ── Veritabanı ───────────────────────────────────────────────────────────────
DB_PATH = "borsa.db"

# ── Varsayılan izleme listesi (DB boşsa kullanılır) ─────────────────────────
WATCHLIST = [
    "THYAO.IS", "GARAN.IS", "ASELS.IS", "SASA.IS", "XU100.IS",
    "AAPL", "MSFT", "NVDA",
]

# ── Popüler hisseler — hisse ekleme ekranında kategori olarak gösterilir ────
POPULER_HISSELER = {
    "BIST — Bankacılık": [
        "GARAN.IS", "AKBNK.IS", "YKBNK.IS", "ISCTR.IS", "HALKB.IS", "VAKBN.IS",
    ],
    "BIST — Sanayi & Enerji": [
        "EREGL.IS", "PETKM.IS", "TUPRS.IS", "AKSEN.IS", "ARCLK.IS", "VESTL.IS",
    ],
    "BIST — Ulaşım & Havacılık": [
        "THYAO.IS", "PGSUS.IS", "TAVHL.IS",
    ],
    "BIST — Otomotiv": [
        "TOASO.IS", "FROTO.IS",
    ],
    "BIST — Savunma & Teknoloji": [
        "ASELS.IS", "TTKOM.IS", "TCELL.IS",
    ],
    "BIST — Perakende & Gıda": [
        "BIMAS.IS", "MGROS.IS", "ULKER.IS", "SOKM.IS",
    ],
    "BIST — Holding & Cam": [
        "KCHOL.IS", "SAHOL.IS", "SISE.IS", "SASA.IS",
    ],
    "BIST — Endeksler": [
        "XU100.IS", "XU030.IS", "XUTEK.IS",
    ],
    "Global — Teknoloji": [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "INTC", "ORCL",
    ],
    "Global — Finans": [
        "JPM", "BAC", "GS", "MS", "BRK-B",
    ],
    "Global — Tüketim & Diğer": [
        "WMT", "KO", "PEP", "MCD", "NKE", "DIS",
    ],
    "ETF & Emtia": [
        "SPY", "QQQ", "GLD", "TLT", "IWM",
    ],
}

# ── Piyasa özeti ekranı için hisse listeleri ─────────────────────────────────
PIYASA_BIST = [
    "THYAO.IS", "GARAN.IS", "AKBNK.IS", "YKBNK.IS", "ISCTR.IS",
    "ASELS.IS", "EREGL.IS", "KCHOL.IS", "TUPRS.IS", "BIMAS.IS",
    "ARCLK.IS", "TOASO.IS", "FROTO.IS", "PETKM.IS", "TTKOM.IS",
    "PGSUS.IS", "SISE.IS", "SASA.IS", "TCELL.IS", "HALKB.IS",
]

PIYASA_GLOBAL = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
    "AMD", "JPM", "BAC", "SPY", "QQQ", "GLD",
]

# ── Varsayılan grafik ayarları ────────────────────────────────────────────────
DEFAULT_PERIOD   = "1y"
DEFAULT_INTERVAL = "1d"

# ── Zaman ufukları (gün) ──────────────────────────────────────────────────────
HORIZONS = {
    "Kısa (2 hafta)": 14,
    "Orta (1 ay)":    30,
    "Uzun (6 ay)":   180,
}

# ── Sanal portföy başlangıç sermayesi ─────────────────────────────────────────
INITIAL_CAPITAL = 100_000.0

# ── Tarama eşikleri ───────────────────────────────────────────────────────────
SCREEN = {
    "gainer_pct":   5.0,      # günlük %5+ artış "yükselen" sayılır
    "loser_pct":   -5.0,      # günlük %5+ düşüş "düşen" sayılır
    "volume_sigma": 3.0,      # hacim ortalamanın kaç std üstündeyse "anormal"
    "rsi_low":     30,        # aşırı satım eşiği
    "rsi_high":    70,        # aşırı alım eşiği
    "thin_volume": 100_000,   # altında günlük hacim "ince/likit değil" bayrağı
}

# ── İşlem maliyetleri ─────────────────────────────────────────────────────────
COSTS = {
    "komisyon_pct": 0.002,    # %0.2 alış+satış komisyonu
    "kayma_pct":    0.001,    # %0.1 kayma (slippage)
}

# ── Risk yönetimi eşikleri ────────────────────────────────────────────────────
RISK = {
    "pozisyon_pct":          0.10,   # tek pozisyona sermayenin en fazla %10'u
    "yogunlasma_uyari_pct":  0.25,   # tek hisse portföyün %25'ini geçerse uyar
    "stop_loss_pct":        -0.08,   # %8 zararda çıkış önerisi
}

# ── Tarihsel analiz ───────────────────────────────────────────────────────────
HISTORICAL = {
    "sicrama_esigi_pct": 8.0,
    "ileri_gun":         [5, 10, 20],
}

# ── Veri kaynağı ──────────────────────────────────────────────────────────────
SOURCES = ["yfinance"]

# ── Aşama 4: KAP & Haber ──────────────────────────────────────────────────────
# Hisse haberleri yfinance üzerinden çekilir (ek anahtar gerekmez).
# Genel piyasa/KAP akışı için aşağıya RSS adresi ekleyin (ad: URL). Boşsa atlanır.
# Her haber kaynağa + yayın zamanına bağlıdır; veri yoksa açıkça belirtilir.
HABER = {
    "hisse_basina_limit": 8,
    "rss_feeds": {
        # "Investing TR": "https://tr.investing.com/rss/news.rss",
        # "KAP Bildirimleri": "https://www.kap.org.tr/tr/rss/...",
    },
    "rss_basina_limit": 10,
}

# ── Aşama 7: Makro / Piyasa Rejimi ────────────────────────────────────────────
MACRO = {
    "rejim_endeksi":      "XU100.IS",  # rejim bu endeksten okunur
    "oynaklik_penceresi": 20,          # gün — gerçekleşen oynaklık penceresi
    "yatay_band_pct":     5.0,         # fiyat 200g ort.'a bu kadar yakınsa "yatay"
    "yuksek_oynaklik_p":  75,          # yıllık oynaklık bu persentilin üstündeyse "yüksek"
    "dusuk_oynaklik_p":   25,          # altındaysa "düşük"
}

# ── Aşama 6: LLM Sentez (Claude) ──────────────────────────────────────────────
# Deterministik modüllerin (sinyal/tarihsel/rejim/kalibrasyon) çıktısını
# dengeli bir Türkçe özete çevirir. Yeni veri UYDURMAZ, AL/SAT tavsiyesi VERMEZ.
# Çalışması için ortam değişkeni: ANTHROPIC_API_KEY. Yoksa açıkça belirtilir.
LLM = {
    "model":      "claude-opus-4-8",
    "max_tokens": 2000,
    "etkin":      True,
}

# ── Aşama 10: Otomasyon ───────────────────────────────────────────────────────
OTOMASYON = {
    "rapor_klasoru": "raporlar",
}

# ── Aşama 12: Telegram bildirim botu ──────────────────────────────────────────
# Günlük özet (AL adayları + rejim) Telegram'a gönderilir.
# Anahtarlar ortam değişkeninden okunur (yoksa "ayarlı değil" der):
#   TELEGRAM_BOT_TOKEN  — @BotFather'dan alınır
#   TELEGRAM_CHAT_ID    — bota mesaj atıp öğrenilir
# "sadece_borsa_gunu": endeks bugün veri ürettiyse (borsa açıksa) gönderir;
# hafta sonu/resmî tatilde veri gelmediği için bot otomatik susar.
TELEGRAM = {
    "sadece_borsa_gunu": True,
    "ozet_aday_sayisi":  5,    # bildirimde en fazla kaç AL adayı listelensin
}

# ── Aşama 11: Öneri / Tarama Sıralaması ───────────────────────────────────────
# İzleme listesini skorlar ve "AL adayı / İzle / Kaçın" olarak SIRALAR.
# Skor şeffaftır: sinyal puanı + piyasa rejimi + dikkat bayrakları.
# Doğrudan öneri verir; her öneri gerekçe + ayı senaryosu + güven düzeyiyle gelir.
ONERI = {
    "varsayilan_periyot": "1mo",   # tarama periyodu (panelden değiştirilebilir)
    "sinyal_agirlik":     8,       # her sinyal puanının skora etkisi
    "rejim_boga":        10,       # Boğa rejiminde skor bonusu
    "rejim_ayi":        -12,       # Ayı rejiminde skor cezası
    "bayrak_cezasi":    -10,       # her dikkat bayrağı (manipülasyon/ince hacim)
    "esik_guclu_al":     70,       # >= bu skor → "Güçlü AL adayı"
    "esik_al":           58,       # >= bu skor → "AL adayı"
    "esik_izle":         43,       # >= bu skor → "Nötr / İzle"; altı "Zayıf / Kaçın"
    "ai_yorum_aday":      6,       # AI yorumuna gönderilecek en iyi N aday
}

# ── Veri dayanıklılığı (yfinance sınırları + BIST düzeltmeleri) ────────────────
VERI = {
    "max_deneme":      3,      # geçici hata/hız limitinde kaç kez yeniden denensin
    "bekleme_sn":      1.5,    # denemeler arası taban bekleme (üstel artar)
    "bayat_gun":       7,      # son veri bu kadar günden eskiyse "bayat" (delisting/tatil)
    "bosluk_gun":      10,     # ardışık veri boşluğu bu kadar günü aşarsa uyar
    "db_yedek":        True,   # canlı veri başarısızsa DB önbelleğinden devam et
}
