"""
Aşama 4 (haber), 6 (LLM sentez), 7 (makro/rejim), 10 (otomasyon) testleri.

Hiçbiri internet ya da API anahtarı gerektirmez; mantığı sentetik veriyle ve
graceful-degradation yollarıyla doğrular.
"""

import os
import numpy as np
import pandas as pd

from analysis import macro
from analysis import news
from analysis import llm
from analysis.screener import ScreenRow
from automation import scheduler


def _seri(egim, n=260, seed=3):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(egim + rng.normal(0, 0.6, n))
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    return pd.DataFrame({"Close": close}, index=idx)


# ── Aşama 7: Makro / Rejim ────────────────────────────────────────────────────

def test_rejim_boga_yukselen_trend():
    r = macro.rejim_tespit(_seri(egim=0.4))
    assert r.rejim == "Boğa"
    assert r.trend_skor > 0
    assert r.fiyat is not None


def test_rejim_ayi_dusen_trend():
    r = macro.rejim_tespit(_seri(egim=-0.4))
    assert r.rejim == "Ayı"
    assert r.trend_skor < 0


def test_rejim_yetersiz_veri():
    r = macro.rejim_tespit(_seri(egim=0.3, n=30))
    assert r.rejim == "belirsiz"
    assert "yetersiz" in r.not_


def test_piyasa_genisligi():
    g = macro.piyasa_genisligi({
        "A": _seri(0.5, seed=1)["Close"],
        "B": _seri(-0.5, seed=2)["Close"],
    }, pencere=50)
    assert g["toplam"] == 2
    assert 0.0 <= g["oran"] <= 1.0


# ── Aşama 4: Haber (RSS ayrıştırma, offline) ──────────────────────────────────

RSS_ORNEK = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Test Akışı</title>
  <item>
    <title>Şirket X bilanço açıkladı</title>
    <link>https://ornek.test/1</link>
    <pubDate>Mon, 08 Jun 2026 10:00:00 GMT</pubDate>
    <description>Özet metin.</description>
  </item>
  <item>
    <title>Piyasa günü yatay kapattı</title>
    <link>https://ornek.test/2</link>
    <pubDate>Mon, 08 Jun 2026 17:00:00 GMT</pubDate>
  </item>
</channel></rss>"""


def test_rss_ayristir():
    kayitlar = news._rss_ayristir(RSS_ORNEK, "Test Akışı", limit=10)
    assert len(kayitlar) == 2
    assert kayitlar[0].baslik == "Şirket X bilanço açıkladı"
    assert kayitlar[0].kaynak == "Test Akışı"
    assert kayitlar[0].link == "https://ornek.test/1"
    assert kayitlar[0].saglayici == "rss"


def test_piyasa_akisi_bos_yapilandirma():
    r = news.piyasa_akisi({})
    assert r.ok is False
    assert "yapılandırılmamış" in r.not_


def test_tam_kelime_eslesme():
    # "thy" tam kelime → eşleşir; "timothy" içindeki "thy" → eşleşMEZ
    assert news._tam_kelime_var(news._tr_kucult("THY rekor kırdı"), "thy") is True
    assert news._tam_kelime_var(news._tr_kucult("Timothy Chou hisse"), "thy") is False
    assert news._tam_kelime_var(news._tr_kucult("Türk Hava Yolları"),
                                "türk hava yolları") is True


def test_hisse_haberleri_tr_filtreler(monkeypatch):
    """BIST haberi Türkçe akıştan şirket adıyla süzülür; yanlış pozitif elenir."""
    sahte = news.HaberSonuc(True, kayitlar=[
        news.HaberKaydi("THY yeni uçak siparişi verdi", "AA", "", "https://x/1"),
        news.HaberKaydi("Timothy Cook açıklama yaptı", "X", "", "https://x/2"),
        news.HaberKaydi("Borsa yatay seyretti", "X", "", "https://x/3"),
    ])
    monkeypatch.setattr(news, "piyasa_akisi", lambda *a, **k: sahte)
    r = news.hisse_haberleri_tr("THYAO.IS", {"AA": "http://x"}, limit=5)
    assert r.ok is True
    assert len(r.kayitlar) == 1                       # sadece THY haberi
    assert "THY" in r.kayitlar[0].baslik
    assert r.kayitlar[0].saglayici == "rss-tr"

    # Eşleşme yoksa dürüstçe ok=False
    bos = news.HaberSonuc(True, kayitlar=[
        news.HaberKaydi("Alakasız haber", "X", "", "https://x/9")])
    monkeypatch.setattr(news, "piyasa_akisi", lambda *a, **k: bos)
    r2 = news.hisse_haberleri_tr("GARAN.IS", {"AA": "http://x"}, limit=5)
    assert r2.ok is False
    assert "bulunamadı" in r2.not_


# ── Aşama 6: LLM Sentez (graceful, anahtarsız) ────────────────────────────────

def test_baglam_metni_icerik():
    metin = llm.baglam_metni({
        "symbol": "THYAO.IS", "fiyat": 250.0,
        "sinyal_ozet": "Göstergeler karışık",
        "sinyal_notlar": ["RSI 55: nötr"],
        "rejim": "Boğa",
    })
    assert "THYAO.IS" in metin
    assert "RSI 55" in metin
    assert "Boğa" in metin


def test_sentezle_bos_baglam():
    s = llm.sentezle({})
    assert s.ok is False
    assert "bağlam" in s.not_


def test_sentezle_anahtarsiz_graceful(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    s = llm.sentezle({"symbol": "X", "sinyal_ozet": "nötr"})
    # Anahtar yok (ya da kütüphane yok) → uydurmaz, açıkça başarısız döner
    assert s.ok is False
    assert s.not_ != ""


# ── Aşama 10: Otomasyon (rapor kurma, offline) ────────────────────────────────

def test_rapor_metni_one_cikan():
    rows = [
        ScreenRow("AAA.IS", 100.0, 6.5, 2.0, 72,
                  gerekceler=["yükseldi +6.5%", "RSI yüksek (72)"],
                  kaynak="yfinance", zaman="2026-06-08"),
        ScreenRow("BBB.IS", 50.0, 0.2, 1.0, 50, gerekceler=[],
                  kaynak="yfinance", zaman="2026-06-08"),
    ]
    metin = scheduler.rapor_metni(rows, "XU100.IS — Boğa", "2026-06-08")
    assert "Gün Sonu Raporu" in metin
    assert "AAA.IS" in metin
    assert "yatırım tavsiyesi değildir" in metin


def test_kaydet_rapor(tmp_path):
    yol = scheduler.kaydet_rapor("# Test\nİçerik", klasor=str(tmp_path / "rapor"))
    assert os.path.exists(yol)
    with open(yol, encoding="utf-8") as f:
        assert "Test" in f.read()
