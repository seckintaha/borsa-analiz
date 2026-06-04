"""
Veri çekme katmanı (Aşama 0).

İlke (yol haritası Bölüm 1 ve 6):
- Hiçbir veri sessizce uydurulmaz. Her sonuç bir kaynağa ve zaman damgasına bağlıdır.
- Veri yoksa/eksikse açıkça belirtilir (FetchResult.ok = False), boşluk doldurulmaz.

Dönüş tipi FetchResult: hem veriyi hem de "nereden, ne zaman, sorun var mı"
bilgisini taşır.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd


@dataclass
class FetchResult:
    symbol: str
    data: Optional[pd.DataFrame]      # OHLCV; basarisizsa None
    source: str                       # "yfinance" vb.
    fetched_at: str                   # ISO zaman damgasi
    ok: bool                          # veri kullanilabilir mi
    note: str = ""                    # "veri yok", hata mesaji vb.
    meta: dict = field(default_factory=dict)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    # yfinance bazen cok katmanli kolon dondurur; tek hisse icin duzlestir
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def fetch_history(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
) -> FetchResult:
    """
    Tek bir sembol icin gecmis OHLCV verisi ceker.
    Once yfinance denenir. Basarisizsa ok=False ve aciklayici not doner.
    """
    symbol = symbol.strip().upper()
    fetched_at = _now_iso()

    try:
        import yfinance as yf
    except ImportError:
        return FetchResult(symbol, None, "yfinance", fetched_at, ok=False,
                           note="yfinance kurulu degil (pip install yfinance)")

    try:
        df = yf.download(symbol, period=period, interval=interval,
                         auto_adjust=True, progress=False)
    except Exception as exc:  # ag/parse hatasi vb.
        return FetchResult(symbol, None, "yfinance", fetched_at, ok=False,
                           note=f"cekme hatasi: {exc}")

    if df is None or df.empty:
        return FetchResult(symbol, None, "yfinance", fetched_at, ok=False,
                           note="veri yok (sembol yanlis olabilir; BIST icin .IS ekleyin)")

    df = _flatten_columns(df)

    # Beklenen kolonlar var mi?
    gerekli = {"Open", "High", "Low", "Close", "Volume"}
    if not gerekli.issubset(set(df.columns)):
        return FetchResult(symbol, None, "yfinance", fetched_at, ok=False,
                           note=f"beklenen kolonlar eksik: {gerekli - set(df.columns)}")

    return FetchResult(
        symbol, df, "yfinance", fetched_at, ok=True,
        note="",
        meta={"period": period, "interval": interval, "satir": len(df)},
    )


def fetch_many(symbols, period="1mo", interval="1d") -> dict[str, FetchResult]:
    """Birden cok sembol icin. Her biri kendi FetchResult'ini alir."""
    out = {}
    for s in symbols:
        out[s.strip().upper()] = fetch_history(s, period=period, interval=interval)
    return out
