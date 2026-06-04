"""
Teknik göstergeler (Aşama 0). Saf pandas ile; TA-Lib gibi kurulumu zor
bağımlılık gerektirmez.
"""

from __future__ import annotations
import pandas as pd


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Close kolonu olan bir OHLCV df alir, gostergeleri ekleyip dondurur."""
    df = df.copy()
    close = df["Close"] if "Close" in df.columns else df["close"]

    # Hareketli ortalamalar
    df["SMA20"] = close.rolling(20).mean()
    df["SMA50"] = close.rolling(50).mean()
    df["SMA200"] = close.rolling(200).mean()

    # RSI (14)
    df["RSI"] = _rsi(close, 14)

    # MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_sinyal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    # Bollinger (20, 2 std)
    orta = close.rolling(20).mean()
    std = close.rolling(20).std()
    df["BB_ust"] = orta + 2 * std
    df["BB_alt"] = orta - 2 * std

    return df


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    kazanc = delta.clip(lower=0).rolling(period).mean()
    kayip = (-delta.clip(upper=0)).rolling(period).mean()
    rs = kazanc / kayip
    return 100 - (100 / (1 + rs))
