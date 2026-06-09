"""
Veri katmanı dayanıklılık testleri (Aşama 0 eklentileri):
kalite temizliği, bayat/boşluk tespiti, DB önbellek yedeği.

Hiçbiri internet gerektirmez; ağ çağrıları monkeypatch ile taklit edilir.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from data import fetcher
from data.fetcher import FetchResult, kalite_temizle, bayat_mi, bosluk_tespit
from data import access
from data.storage import init_db, save_prices, get_prices_fetchresult


def _ohlcv(n=30, son_tarih=None):
    son = son_tarih or datetime.now()
    idx = pd.date_range(end=son, periods=n, freq="D")
    close = np.linspace(100, 110, n)
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1,
                         "Close": close, "Volume": np.full(n, 1_000_000)},
                        index=idx)


# ── Kalite temizliği ──────────────────────────────────────────────────────────

def test_kalite_nan_satir_atilir():
    df = _ohlcv(10)
    df.loc[df.index[3], "Close"] = np.nan
    temiz, uyarilar = kalite_temizle(df)
    assert len(temiz) == 9
    assert any("NaN" in u or "eksik" in u for u in uyarilar)


def test_kalite_negatif_fiyat_uyarir():
    df = _ohlcv(10)
    df.loc[df.index[2], "Close"] = -5
    _, uyarilar = kalite_temizle(df)
    assert any("negatif" in u for u in uyarilar)


# ── Bayat / boşluk tespiti ────────────────────────────────────────────────────

def test_bayat_guncel_veri():
    df = _ohlcv(30, son_tarih=datetime.now())
    bayat, son_tarih, gun = bayat_mi(df, bayat_gun=7)
    assert bayat is False
    assert gun <= 7


def test_bayat_eski_veri():
    df = _ohlcv(30, son_tarih=datetime(2020, 1, 1))
    bayat, son_tarih, gun = bayat_mi(df, bayat_gun=7)
    assert bayat is True
    assert gun > 7


def test_bosluk_tespit():
    df = _ohlcv(10)
    # 40 günlük boşluk yarat
    yeni_idx = list(df.index)
    yeni_idx[-1] = yeni_idx[-2] + timedelta(days=40)
    df.index = pd.DatetimeIndex(yeni_idx)
    uyari = bosluk_tespit(df, bosluk_gun=10)
    assert "boşluk" in uyari


def test_bosluk_yok():
    assert bosluk_tespit(_ohlcv(20), bosluk_gun=10) == ""


# ── DB önbellek yedeği ────────────────────────────────────────────────────────

def _seed_db(db_path):
    init_db(db_path)
    fr = FetchResult("TEST.IS", _ohlcv(20), "yfinance",
                     datetime.now().isoformat(), ok=True)
    save_prices(db_path, fr)


def test_get_prices_fetchresult(tmp_path):
    db = str(tmp_path / "t.db")
    _seed_db(db)
    r = get_prices_fetchresult(db, "TEST.IS")
    assert r.ok is True
    assert r.source == "cache (DB)"
    assert "Close" in r.data.columns
    assert r.bayat is True  # önbellek her zaman "güncel değil" işaretli


def test_veri_getir_canli_basarisizsa_dbden(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    _seed_db(db)

    def sahte_basarisiz(*a, **k):
        return FetchResult("TEST.IS", None, "yfinance",
                           datetime.now().isoformat(), ok=False,
                           note="ağ yok (test)")
    monkeypatch.setattr(access, "fetch_history", sahte_basarisiz)

    r = access.veri_getir(db, "TEST.IS", db_yedek=True)
    assert r.ok is True
    assert r.source == "cache (DB)"
    assert any("canlı çekme başarısız" in u for u in r.uyarilar)


def test_veri_getir_dbde_de_yoksa_durust_hata(tmp_path, monkeypatch):
    db = str(tmp_path / "bos.db")
    init_db(db)

    def sahte_basarisiz(*a, **k):
        return FetchResult("YOK.IS", None, "yfinance",
                           datetime.now().isoformat(), ok=False, note="ağ yok")
    monkeypatch.setattr(access, "fetch_history", sahte_basarisiz)

    r = access.veri_getir(db, "YOK.IS", db_yedek=True)
    assert r.ok is False
