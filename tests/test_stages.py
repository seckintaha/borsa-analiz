"""
Aşama 2 (paper portföy), 3 (backtest), 5 (tarihsel), 8 (kalibrasyon), 9 (risk)
için birim testler. Sentetik veriyle çalışır; internet/yfinance gerektirmez.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from portfolio.paper import PaperPortfolio, cok_ufuklu_getiri
from backtest.engine import backtest, train_test_bol, strateji_sma_kesisim
from analysis.historical import olay_calismasi, mevsimsellik_aylik
from analysis.calibration import Tahmin, gercek_ekle, kalibre_et
from analysis import risk


def _seri(n=400, egim=0.3, seed=0):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(egim + rng.normal(0, 1, n))
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "Open": close, "High": close + 1, "Low": close - 1,
        "Close": close, "Volume": rng.integers(1_000_000, 2_000_000, n),
    }, index=idx)


# ---------- Aşama 2: paper portföy ----------
def test_alim_nakit_dusuyor():
    p = PaperPortfolio(100_000, costs={"komisyon_pct": 0.0, "kayma_pct": 0.0})
    p.al("THYAO.IS", fiyat=100, tarih="2024-01-01", tutar=10_000, gerekce="test")
    assert abs(p.nakit - 90_000) < 1e-6
    assert "THYAO.IS" in p.pozisyonlar


def test_islem_maliyeti_uygulaniyor():
    p = PaperPortfolio(100_000, costs={"komisyon_pct": 0.002, "kayma_pct": 0.001})
    p.al("AAPL", fiyat=100, tarih="2024-01-01", adet=10)
    # efektif alis 100 * 1.003 = 100.3 -> maliyet 1003
    assert abs((100_000 - p.nakit) - 1003) < 1e-6


def test_satis_kar_zarar():
    p = PaperPortfolio(100_000, costs={"komisyon_pct": 0.0, "kayma_pct": 0.0})
    p.al("X", fiyat=100, tarih="2024-01-01", adet=10)
    p.sat("X", fiyat=120, tarih="2024-02-01")
    # 1000 harcadi, 1200 geri aldi -> nakit 100200
    assert abs(p.nakit - 100_200) < 1e-6
    assert "X" not in p.pozisyonlar


def test_yetersiz_nakit_hata():
    p = PaperPortfolio(1_000)
    try:
        p.al("X", fiyat=100, tarih="2024-01-01", tutar=10_000)
        assert False, "hata bekleniyordu"
    except ValueError:
        pass


def test_cok_ufuklu_getiri():
    s = _seri(egim=0.5)["Close"]
    out = cok_ufuklu_getiri(s, s.index[10], {"kisa": 14, "orta": 30})
    assert "kisa" in out and "orta" in out
    assert out["kisa"]["getiri_pct"] is not None


# ---------- Aşama 3: backtest ----------
def test_backtest_benchmark_uretiyor():
    df = _seri(egim=0.4)
    r = backtest(df, strateji_sma_kesisim, costs={"komisyon_pct": 0.001, "kayma_pct": 0.0})
    assert r.gun_sayisi == len(df)
    assert isinstance(r.benchmark_pct, float)
    assert -100 <= r.max_dusus_pct <= 0


def test_train_test_bol():
    df = _seri()
    tr, te = train_test_bol(df, 0.3)
    assert len(tr) + len(te) == len(df)
    assert len(te) == int(len(df) * 0.3)


def test_maliyet_getiriyi_dusurur():
    df = _seri(egim=0.4)
    maliyetsiz = backtest(df, strateji_sma_kesisim, costs={"komisyon_pct": 0, "kayma_pct": 0})
    maliyetli = backtest(df, strateji_sma_kesisim, costs={"komisyon_pct": 0.01, "kayma_pct": 0.01})
    assert maliyetli.getiri_pct <= maliyetsiz.getiri_pct


# ---------- Aşama 5: tarihsel ----------
def test_olay_calismasi_n_ve_aralik():
    df = _seri(seed=3)
    out = olay_calismasi(df, esik_pct=2.0, ileri_gun=[5, 10])
    for ufuk, d in out.items():
        if d.n > 0:
            assert d.min_pct <= d.medyan_pct <= d.max_pct
            assert 0 <= d.pozitif_orani <= 1


def test_az_ornek_guvenilmez_isaretleniyor():
    df = _seri(seed=4)
    out = olay_calismasi(df, esik_pct=6.0, ileri_gun=[5], min_ornek=1000)
    d = out[5]
    if d.n > 0:
        assert d.guvenilir is False  # 1000 ornek olmadigi icin


def test_mevsimsellik_12_ay():
    df = _seri()
    t = mevsimsellik_aylik(df)
    assert len(t) <= 12 and "n" in t.columns


# ---------- Aşama 8: kalibrasyon ----------
def test_kalibrasyon_isabet():
    tahminler = []
    # 8 dogru, 2 yanlis pozitif tahmin -> isabet 0.8
    for i in range(8):
        tahminler.append(gercek_ekle(Tahmin("X", "2024", "pozitif", "RSI_dusuk", 10), +5))
    for i in range(2):
        tahminler.append(gercek_ekle(Tahmin("X", "2024", "pozitif", "RSI_dusuk", 10), -5))
    sonuc = kalibre_et(tahminler, min_ornek=5)
    assert sonuc[0].isabet_orani == 0.8
    assert sonuc[0].yazitura_farki == 0.3
    assert sonuc[0].guvenilir is True


def test_kalibrasyon_eksik_tahmin_atlaniyor():
    tahminler = [Tahmin("X", "2024", "pozitif", "MACD", 10)]  # gerceklesen yok
    assert kalibre_et(tahminler) == []


# ---------- Aşama 9: risk ----------
def test_pozisyon_buyuklugu():
    r = risk.pozisyon_buyuklugu(100_000, fiyat=250, pozisyon_pct=0.10)
    assert r["adet"] == 40  # 10000 / 250
    assert r["tahsis_tutar"] == 10_000


def test_yogunlasma_uyari():
    uy = risk.yogunlasma_kontrol({"A": 6000, "B": 2000, "C": 2000}, uyari_pct=0.25)
    assert any("A" in u for u in uy)  # A %60


def test_stop_loss():
    poz = {"X": {"alis_fiyat": 100}}
    uy = risk.stop_loss_kontrol(poz, {"X": 90}, stop_pct=-0.08)
    assert len(uy) == 1  # %10 zarar > %8 stop


def test_max_dusus():
    seri = [100, 110, 90, 95, 80, 120]
    d = risk.portfoy_max_dusus(seri)
    assert d < 0  # mutlaka negatif (zirveden dusus var)
