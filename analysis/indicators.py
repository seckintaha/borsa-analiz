"""
Teknik göstergeler (Aşama 0). Saf pandas ile; TA-Lib gibi kurulumu zor
bağımlılık gerektirmez.
"""

from __future__ import annotations
import pandas as pd
import numpy as np


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

    # ATR / ADX / OBV — High/Low/Volume varsa hesapla (yoksa atla)
    high = df["High"] if "High" in df.columns else None
    low = df["Low"] if "Low" in df.columns else None
    vol = df["Volume"] if "Volume" in df.columns else None

    if high is not None and low is not None:
        df["ATR14"] = _atr(high, low, close, 14)
        adx, di_pos, di_neg = _adx(high, low, close, 14)
        df["ADX14"], df["DI_pos"], df["DI_neg"] = adx, di_pos, di_neg
    if vol is not None:
        df["OBV"] = _obv(close, vol)
        df["OBV_SMA20"] = df["OBV"].rolling(20).mean()

    return df


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI(14) — Wilder yumuşatması (TradingView/standart ile uyumlu)."""
    delta = close.diff()
    kazanc = delta.clip(lower=0)
    kayip = -delta.clip(upper=0)
    # Wilder ortalaması = EWM(alpha=1/period). Basit rolling ortalama DEĞİL;
    # aksi halde TradingView'ın RSI kolonuyla tutarsız değer üretir.
    ort_kazanc = kazanc.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    ort_kayip = kayip.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = ort_kazanc / ort_kayip
    rsi = 100 - (100 / (1 + rs))
    # Tüm kayıplar 0 ise (kesintisiz yükseliş) RSI=100; ort_kayip=0 → rs=inf → 100.
    # Hem kazanç hem kayıp 0 ise (yatay) sonuç NaN kalır (veri yok, uydurma yok).
    return rsi


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    onceki_kapanis = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - onceki_kapanis).abs(),
        (low - onceki_kapanis).abs(),
    ], axis=1).max(axis=1)
    return tr


def _atr(high, low, close, period: int = 14) -> pd.Series:
    """Average True Range — oynaklık ölçüsü (stop/hedef mesafesi için)."""
    return _true_range(high, low, close).ewm(alpha=1 / period, adjust=False).mean()


def _adx(high, low, close, period: int = 14):
    """
    ADX (trend gücü) + yönlü göstergeler (+DI/-DI). Wilder yöntemi.
    ADX > 25 güçlü trend, < 20 zayıf/yatay olarak yorumlanır.
    """
    up = high.diff()
    down = -low.diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    tr = _true_range(high, low, close)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    di_pos = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr
    di_neg = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = 100 * (di_pos - di_neg).abs() / (di_pos + di_neg).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return adx, di_pos, di_neg


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume — hacmin yön ağırlıklı birikimi (para akışı)."""
    yon = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (yon * volume).fillna(0).cumsum()
