"""
Merkezi ayarlar. Sabit değer kodun içine gömülmez; hepsi buradan ayarlanır.
(Yol haritası Bölüm 5: zaman ufku ve eşikler ayarlanabilir parametredir.)
"""

# --- Veritabanı ---
DB_PATH = "borsa.db"

# --- İzleme listesi (BIST için sona .IS) ---
WATCHLIST = [
    "THYAO.IS", "GARAN.IS", "ASELS.IS", "SASA.IS", "XU100.IS",
    "AAPL", "MSFT", "NVDA",
]

# --- Varsayılan veri çekme ---
DEFAULT_PERIOD = "1y"     # 1mo, 3mo, 6mo, 1y, 2y, 5y
DEFAULT_INTERVAL = "1d"   # 1d, 1wk, 1h

# --- Zaman ufukları (gün) - paper portföy ve tarihsel analiz aynı değerleri kullanır ---
HORIZONS = {
    "kisa": 14,     # 2 hafta
    "orta": 30,     # 1 ay
    "uzun": 180,    # 6 ay
}

# --- Paper portföy ---
INITIAL_CAPITAL = 100_000.0   # TL (Asama 2'de kullanilacak)

# --- Tarama eşikleri (Aşama 1) ---
SCREEN = {
    "gainer_pct": 5.0,      # gunluk %5+ artis "yukselen" sayilir
    "loser_pct": -5.0,      # gunluk %5+ dusus "dusen" sayilir
    "volume_sigma": 3.0,    # hacim, ortalamadan kac std sapunca "anormal"
    "rsi_low": 30,          # asiri satim esigi
    "rsi_high": 70,         # asiri alim esigi
    "thin_volume": 100_000, # bunun altinda gunluk hacim "ince/likit degil" bayragi
}

# --- İşlem maliyetleri (Aşama 2 & 3 - gerçekçi simülasyon için) ---
COSTS = {
    "komisyon_pct": 0.002,   # %0.2 alis+satis komisyonu (orn)
    "kayma_pct": 0.001,      # %0.1 kayma (slippage)
}

# --- Risk yönetimi (Aşama 9) ---
RISK = {
    "pozisyon_pct": 0.10,        # tek pozisyona sermayenin en fazla %10'u
    "yogunlasma_uyari_pct": 0.25, # tek hisse portfoyun %25'ini gecerse uyar
    "stop_loss_pct": -0.08,      # %8 zararda stop onerisi
}

# --- Tarihsel analiz (Aşama 5) ---
HISTORICAL = {
    "sicrama_esigi_pct": 8.0,    # gunluk %8+ "sicrama" sayilir
    "ileri_gun": [5, 10, 20],    # sicrama sonrasi bakilacak gun ufuklari
}

# --- Veri kaynağı sırası (ilki basarisiz olursa digeri denenebilir) ---
# Not: borsapy BIST icin daha saglam; kuruluysa fetcher otomatik dener.
SOURCES = ["yfinance"]
