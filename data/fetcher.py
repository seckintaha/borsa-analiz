"""
Veri çekme katmanı (Aşama 0 + dayanıklılık eklentileri).

İlke (yol haritası Bölüm 1 ve 6):
- Hiçbir veri sessizce uydurulmaz. Her sonuç bir kaynağa ve zaman damgasına bağlıdır.
- Veri yoksa/eksikse açıkça belirtilir (FetchResult.ok = False), boşluk doldurulmaz.

Dayanıklılık (bilinen sınırlara karşı):
- yfinance resmi olmayan bir kaynaktır; geçici hata/hız limiti olabilir →
  üstel beklemeli yeniden deneme (retry).
- Veri kalitesi: tümü-NaN satırlar atılır; negatif/sıfır fiyat işaretlenir.
- BIST düzeltmeleri: auto_adjust=True ile temettü/bölünme (bedelsiz dahil)
  geriye dönük düzeltilir; sonuç meta'da "adjusted" olarak işaretlenir.
- Delisting / işlem takvimi: son veri bayatsa ya da uzun boşluk varsa uyarılır.

Dönüş tipi FetchResult: hem veriyi hem de "nereden, ne zaman, sorun var mı"
bilgisini taşır.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd


@dataclass
class FetchResult:
    symbol: str
    data: Optional[pd.DataFrame]      # OHLCV; basarisizsa None
    source: str                       # "yfinance", "cache (DB)" vb.
    fetched_at: str                   # ISO zaman damgasi
    ok: bool                          # veri kullanilabilir mi
    note: str = ""                    # "veri yok", hata mesaji vb.
    bayat: bool = False               # son veri eski mi (delisting/tatil olabilir)
    uyarilar: list = field(default_factory=list)   # veri kalite/güncellik uyarıları
    meta: dict = field(default_factory=dict)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    # yfinance bazen cok katmanli kolon dondurur; tek hisse icin duzlestir
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


# ── Saf yardımcılar (ağ gerektirmez, test edilebilir) ─────────────────────────

def kalite_temizle(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Veri kalitesini kontrol eder ve temizler.
    - Close'u NaN olan satırları atar (kullanılamaz).
    - Negatif/sıfır fiyat ya da negatif hacim varsa uyarı üretir.
    Dönüş: (temiz_df, uyarilar).
    """
    uyarilar: list[str] = []
    df = df.copy()

    onceki = len(df)
    df = df[df["Close"].notna()]
    atilan = onceki - len(df)
    if atilan > 0:
        uyarilar.append(f"{atilan} satır eksik (NaN) fiyat nedeniyle atıldı")

    if (df[["Open", "High", "Low", "Close"]] <= 0).any().any():
        uyarilar.append("sıfır/negatif fiyat içeren satır var — veri şüpheli")
    if "Volume" in df and (df["Volume"] < 0).any():
        uyarilar.append("negatif hacim değeri var — veri şüpheli")

    return df, uyarilar


def bayat_mi(df: pd.DataFrame, bayat_gun: int) -> tuple[bool, str, int]:
    """
    Son veri tarihi bugünden bayat_gun'den fazla eskiyse True döner.
    Delisting, uzun tatil ya da durmuş veri akışının işareti olabilir.
    Dönüş: (bayat, son_tarih_iso, gun_farki).
    """
    if df is None or len(df) == 0:
        return True, "", 9999
    son_ts = pd.to_datetime(df.index[-1])
    if son_ts.tzinfo is not None:
        son_ts = son_ts.tz_localize(None)
    gun_farki = (datetime.now() - son_ts.to_pydatetime()).days
    return (gun_farki > bayat_gun), son_ts.strftime("%Y-%m-%d"), gun_farki


def bosluk_tespit(df: pd.DataFrame, bosluk_gun: int) -> str:
    """En büyük ardışık veri boşluğu bosluk_gun'ü aşıyorsa uyarı metni döner."""
    if df is None or len(df) < 2:
        return ""
    idx = pd.to_datetime(df.index)
    farklar = idx.to_series().diff().dt.days.dropna()
    if len(farklar) == 0:
        return ""
    en_buyuk = int(farklar.max())
    if en_buyuk > bosluk_gun:
        return (f"veride {en_buyuk} günlük boşluk var "
                "(işlem tatili, durma ya da eksik veri olabilir)")
    return ""


# ── Canlı çekme ───────────────────────────────────────────────────────────────

# BIST ticker'lari ASCII'dir. Turkce locale/kopyalama bir sembole 'İ' (U+0130,
# noktali buyuk I) ya da baska Turkce harf sokabilir (or. 'GEDİK.IS') → yfinance
# bulamaz. Bu tablo ticker'i ASCII'ye zorlar; boylece cekme bagisik olur.
_TR_ASCII = str.maketrans({
    "İ": "I", "ı": "I", "Ş": "S", "ş": "S", "Ğ": "G", "ğ": "G",
    "Ü": "U", "ü": "U", "Ö": "O", "ö": "O", "Ç": "C", "ç": "C",
})


def normalize_ticker(symbol: str) -> str:
    """Sembolu ASCII-buyuk hale getirir (Turkce harf bozulmalarini duzeltir)."""
    return (symbol or "").strip().translate(_TR_ASCII).upper()


def fetch_history(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    max_deneme: int = 3,
    bekleme_sn: float = 1.5,
    bayat_gun: int = 7,
    bosluk_gun: int = 10,
) -> FetchResult:
    """
    Tek bir sembol icin gecmis OHLCV verisi ceker (auto_adjust=True).
    Gecici hatalarda ustel beklemeyle yeniden dener; veri kalitesini ve
    guncelligini denetler. Basarisizsa ok=False ve aciklayici not doner.
    """
    symbol = normalize_ticker(symbol)
    fetched_at = _now_iso()

    try:
        import yfinance as yf
    except ImportError:
        return FetchResult(symbol, None, "yfinance", fetched_at, ok=False,
                           note="yfinance kurulu degil (pip install yfinance)")

    df = None
    son_hata = ""
    for deneme in range(1, max(1, max_deneme) + 1):
        try:
            df = yf.download(symbol, period=period, interval=interval,
                             auto_adjust=True, progress=False)
        except Exception as exc:  # ag/parse/hiz-limiti hatasi
            son_hata = str(exc)
            df = None

        if df is not None and not df.empty:
            break  # basarili
        # bos sonuc da gecici (hiz limiti) olabilir; son denemeye kadar bekle
        if deneme < max_deneme:
            time.sleep(bekleme_sn * deneme)  # ustel-benzeri artan bekleme

    if df is None:
        return FetchResult(symbol, None, "yfinance", fetched_at, ok=False,
                           note=f"cekme hatasi ({max_deneme} deneme): {son_hata}")
    if df.empty:
        return FetchResult(symbol, None, "yfinance", fetched_at, ok=False,
                           note="veri yok (sembol yanlis olabilir; BIST icin .IS ekleyin)")

    df = _flatten_columns(df)

    # Beklenen kolonlar var mi?
    gerekli = {"Open", "High", "Low", "Close", "Volume"}
    if not gerekli.issubset(set(df.columns)):
        return FetchResult(symbol, None, "yfinance", fetched_at, ok=False,
                           note=f"beklenen kolonlar eksik: {gerekli - set(df.columns)}")

    # Veri kalitesi + güncellik denetimleri
    df, uyarilar = kalite_temizle(df)
    if len(df) == 0:
        return FetchResult(symbol, None, "yfinance", fetched_at, ok=False,
                           note="temizleme sonrası kullanılabilir satır kalmadı")

    bayat, son_tarih, gun_farki = bayat_mi(df, bayat_gun)
    if bayat:
        uyarilar.append(f"son veri {gun_farki} gün önce ({son_tarih}) — "
                        "bayat olabilir (delisting/tatil/durmuş akış)")
    bosluk = bosluk_tespit(df, bosluk_gun)
    if bosluk:
        uyarilar.append(bosluk)

    return FetchResult(
        symbol, df, "yfinance", fetched_at, ok=True,
        note="",
        bayat=bayat,
        uyarilar=uyarilar,
        meta={"period": period, "interval": interval, "satir": len(df),
              "adjusted": True, "son_tarih": son_tarih, "gun_farki": gun_farki},
    )


def fetch_many(symbols, period="1mo", interval="1d", **kwargs) -> dict[str, FetchResult]:
    """Birden cok sembol icin. Her biri kendi FetchResult'ini alir."""
    out = {}
    for s in symbols:
        out[s.strip().upper()] = fetch_history(s, period=period, interval=interval, **kwargs)
    return out
