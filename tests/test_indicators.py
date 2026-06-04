"""
Gösterge matematiği için birim testler.
İnternet/veri gerektirmez; sentetik veriyle çalışır.

Çalıştırmak için:
    pip install pytest
    pytest -q
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from analysis.indicators import add_indicators, _rsi
from analysis.signals import evaluate


def _sentetik_df(n=300, baslangic=100.0, egim=0.1, seed=0):
    rng = np.random.default_rng(seed)
    kapanis = baslangic + np.cumsum(egim + rng.normal(0, 1, n))
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "Open": kapanis, "High": kapanis + 1, "Low": kapanis - 1,
        "Close": kapanis, "Volume": rng.integers(1_000_000, 2_000_000, n),
    }, index=idx)


def test_rsi_0_100_arasinda():
    s = _sentetik_df()["Close"]
    rsi = _rsi(s, 14).dropna()
    assert (rsi >= 0).all() and (rsi <= 100).all()


def test_sma_dogru_hesaplaniyor():
    df = _sentetik_df()
    out = add_indicators(df)
    # Son SMA20, son 20 kapanisin ortalamasina esit olmali
    beklenen = df["Close"].iloc[-20:].mean()
    assert abs(out["SMA20"].iloc[-1] - beklenen) < 1e-6


def test_gostergeler_eklendi():
    out = add_indicators(_sentetik_df())
    for kol in ["SMA20", "SMA50", "SMA200", "RSI", "MACD", "MACD_sinyal", "BB_ust", "BB_alt"]:
        assert kol in out.columns


def test_yukselen_trendde_puan_pozitif():
    # Guclu yukselen trend -> uzun vade egilimi pozitif olmali
    df = add_indicators(_sentetik_df(egim=0.5))
    res = evaluate(df)
    assert res.puan >= 1


def test_ayi_senaryosu_pozitifte_var():
    df = add_indicators(_sentetik_df(egim=0.5))
    res = evaluate(df)
    if res.puan >= 2:
        assert len(res.ayi_senaryosu) >= 1  # her guclu pozitifte ayi senaryosu olmali
