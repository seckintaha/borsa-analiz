"""
Öneri / sıralama (Aşama 11) testleri — offline, ağ/anahtar gerektirmez.
Skorlamanın ve sıralamanın mantığını, AI yorumunun graceful davranışını doğrular.
"""

import os
import numpy as np
import pandas as pd

import config
from analysis.indicators import add_indicators
from analysis import recommender as rec


def _df(egim, n=260, seed=4):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(egim + rng.normal(0, 0.6, n))
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    return add_indicators(pd.DataFrame({
        "Open": close, "High": close + 1, "Low": close - 1,
        "Close": close, "Volume": rng.integers(800_000, 2_000_000, n),
    }, index=idx))


THIN = config.SCREEN["thin_volume"]


def test_skor_yukselen_yuksek():
    skor, ek = rec.skorla(_df(egim=0.5), config.ONERI, THIN, rejim="Boğa")
    assert skor >= config.ONERI["esik_al"]
    assert isinstance(ek["gerekceler"], list)


def test_skor_dusen_dusuk():
    skor, _ = rec.skorla(_df(egim=-0.5), config.ONERI, THIN, rejim="Ayı")
    assert skor < config.ONERI["esik_izle"]


def test_skor_0_100_araliginda():
    for egim in (1.0, -1.0, 0.0):
        skor, _ = rec.skorla(_df(egim=egim), config.ONERI, THIN, rejim="Boğa")
        assert 0 <= skor <= 100


def test_aksiyon_esikleri():
    assert rec._aksiyon(75, config.ONERI) == "Güçlü AL adayı"
    assert rec._aksiyon(60, config.ONERI) == "AL adayı"
    assert rec._aksiyon(50, config.ONERI) == "Nötr / İzle"
    assert rec._aksiyon(20, config.ONERI) == "Zayıf / Kaçın"


def test_guven_kademeleri():
    assert rec._guven(250, 0) == "yüksek"
    assert rec._guven(100, 0) == "orta"
    assert rec._guven(30, 0) == "düşük"
    # Bayrak güveni düşürür
    assert rec._guven(250, 1) == "orta"


def test_rejim_skoru_etkiler():
    boga, _ = rec.skorla(_df(egim=0.3), config.ONERI, THIN, rejim="Boğa")
    ayi, _ = rec.skorla(_df(egim=0.3), config.ONERI, THIN, rejim="Ayı")
    assert boga > ayi  # aynı hisse, Boğa rejiminde daha yüksek skor


def test_yorum_metni_sirali():
    satirlar = [
        rec.OneriSatir("AAA", 80, "Güçlü AL adayı", 100.0, 5.0,
                       gerekceler=["RSI nötr"], guven="yüksek"),
        rec.OneriSatir("BBB", 30, "Zayıf / Kaçın", 50.0, -4.0,
                       bayraklar=["ince hacim"], guven="düşük"),
    ]
    metin = rec._yorum_metni(satirlar, "Boğa", en_iyi_n=6)
    assert "AAA" in metin and "skor 80" in metin
    assert "uydurma" in metin  # talimat metni veri-bloğunu çerçeveler


def test_ai_yorum_anahtarsiz_graceful(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    satirlar = [rec.OneriSatir("AAA", 80, "AL adayı", 100.0, 5.0, guven="orta")]
    y = rec.ai_yorum(satirlar, rejim_ozeti="Boğa")
    assert y.ok is False
    assert y.not_ != ""


# ── Yerel öneri yazarı (ANAHTAR GEREKMEZ) ─────────────────────────────────────

def test_yerel_yorum_adaylari_listeler():
    satirlar = [
        rec.OneriSatir("AAA", 80, "Güçlü AL adayı", 100.0, 5.0,
                       gerekceler=["RSI nötr", "MACD yukarı"],
                       ayi_senaryosu=["beklenti yüksek olabilir"], guven="yüksek"),
        rec.OneriSatir("BBB", 60, "AL adayı", 50.0, 2.0,
                       gerekceler=["trend yukarı"], guven="orta"),
        rec.OneriSatir("CCC", 30, "Zayıf / Kaçın", 20.0, -4.0,
                       bayraklar=["ince hacim"], guven="düşük"),
    ]
    metin = rec.yerel_yorum(satirlar, rejim_ozeti="Boğa", en_iyi_n=6)
    assert "AAA" in metin and "BBB" in metin
    assert "Öne çıkan adaylar" in metin
    assert "uzak durulacaklar" in metin.lower()
    assert "danışmanlığı değildir" in metin
    # Sıralama: AAA (güçlü) BBB'den önce gelmeli
    assert metin.index("AAA") < metin.index("BBB")


def test_yerel_yorum_aday_yok():
    satirlar = [rec.OneriSatir("XXX", 35, "Zayıf / Kaçın", 10.0, -2.0, guven="orta")]
    metin = rec.yerel_yorum(satirlar)
    assert "güçlü bir AL adayı yok" in metin


def test_yerel_yorum_dusuk_guven_uyarisi():
    satirlar = [rec.OneriSatir("AAA", 60, "AL adayı", 100.0, 1.0, guven="düşük")]
    metin = rec.yerel_yorum(satirlar)
    assert "düşük" in metin and ("6 ay" in metin or "pencere" in metin)
