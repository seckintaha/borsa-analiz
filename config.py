"""
Merkezi ayarlar — tüm sabitler buradan yönetilir.
"""

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
