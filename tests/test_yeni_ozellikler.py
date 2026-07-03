"""
Bu oturumda eklenen özelliklerin deterministik testleri (ağ gerektirmez):
  teknik_derin, fikirler(saf kısım), islem_aliskanlik, risk.portfoy_zayiflik,
  backtest stratejileri, kap duygu analizi, portfolio.ozet, tv_scanner.sinyal_puan
"""

import os
import tempfile
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest


# ── Yardımcı: sentetik OHLCV üretici ──────────────────────────────────────────

def _ohlcv(n=250, baslangic=100.0, egim=0.5, oynaklik=1.0, seed=0):
    """Yükselen (egim>0) ya da düşen trendli sentetik OHLCV df üretir."""
    rng = np.random.default_rng(seed)
    tarihler = pd.date_range(end=datetime.now().date(), periods=n, freq="B")
    kapanis = baslangic + egim * np.arange(n) + rng.normal(0, oynaklik, n)
    kapanis = np.maximum(kapanis, 1.0)
    df = pd.DataFrame({
        "Open": kapanis - rng.normal(0, 0.3, n),
        "High": kapanis + np.abs(rng.normal(0.5, 0.3, n)),
        "Low": kapanis - np.abs(rng.normal(0.5, 0.3, n)),
        "Close": kapanis,
        "Volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
    }, index=tarihler)
    return df


# ── teknik_derin ──────────────────────────────────────────────────────────────

def test_teknik_derin_yukselis_al_verir():
    from analysis.teknik_derin import analiz_et
    df = _ohlcv(n=250, egim=0.8, oynaklik=0.5)   # güçlü yükseliş
    k = analiz_et(df, "TEST.IS")
    assert k.ok
    assert k.karar in ("AL", "TUT", "SAT")
    assert k.karar == "AL"                        # net yükselişte AL beklenir
    assert k.giris is not None
    assert k.kar_al is not None and k.zarar_kes is not None


def test_teknik_derin_yetersiz_veri():
    from analysis.teknik_derin import analiz_et
    df = _ohlcv(n=10)
    k = analiz_et(df, "TEST.IS")
    assert not k.ok                               # 30 bardan az → ok=False


def test_teknik_derin_risk_odul_makul_sinirda():
    """Stop çok yakın olsa bile R/R absürt (ör. 1:8.93) çıkmamalı; ≤5.0 sınırlı."""
    from analysis.teknik_derin import analiz_et
    # Farklı oynaklık/seed'lerde AL sinyali üretip R/R'ı hep 5.0 altında bekle
    for seed in range(8):
        df = _ohlcv(n=250, egim=0.8, oynaklik=0.4, seed=seed)
        k = analiz_et(df, "TEST.IS")
        if k.ok and k.risk_odul is not None:
            assert k.risk_odul <= 5.0            # üst sınır uygulanmış
            assert k.risk_odul > 0
            # Stop gerçekten fiyata çok yakın olmamalı (mikro risk yasak)
            assert k.giris - k.zarar_kes > 0


def test_destek_direnc_fiyatin_iki_tarafinda():
    from analysis.teknik_derin import destek_direnc
    df = _ohlcv(n=200, egim=0.3)
    fiyat = float(df["Close"].iloc[-1])
    destekler, direncler = destek_direnc(df, fiyat, n=3)
    assert all(d.fiyat < fiyat for d in destekler)   # destek fiyatın altında
    assert all(d.fiyat > fiyat for d in direncler)   # direnç fiyatın üstünde


# ── islem_aliskanlik ──────────────────────────────────────────────────────────

@pytest.fixture
def gecici_db():
    from data.storage import init_db
    yol = tempfile.mktemp(suffix=".db")
    init_db(yol)
    yield yol
    if os.path.exists(yol):
        os.remove(yol)


def test_aliskanlik_bos_db_durust(gecici_db):
    from analysis.islem_aliskanlik import analiz_et
    a = analiz_et(gecici_db, n=20)
    assert not a.ok                               # işlem yok → dürüstçe boş


def test_aliskanlik_revenge_ve_kural(gecici_db):
    from analysis.islem_aliskanlik import analiz_et
    from data.storage import save_islem
    # erken kâr, geç zarar, revenge, tekrar kayıp deseni
    t = [
        ("AAA", "AL", "2026-01-01", 100, 10, 1000),
        ("AAA", "SAT", "2026-01-02", 103, 10, 1030),
        ("BBB", "AL", "2026-01-02", 50, 20, 1000),
        ("BBB", "SAT", "2026-01-12", 42, 20, 840),
        ("CCC", "AL", "2026-01-12", 30, 30, 900),
        ("CCC", "SAT", "2026-01-13", 31, 30, 930),
    ]
    for kayit in t:
        save_islem(gecici_db, *kayit)
    a = analiz_et(gecici_db, n=20)
    assert a.ok
    assert a.kapali_islem == 3
    assert len(a.kurallar) == 3                   # her zaman 3 kural
    assert any("revenge" in h.lower() or "geri al" in h.lower() for h in a.hatalar)


# ── risk.portfoy_zayiflik ─────────────────────────────────────────────────────

def test_portfoy_zayiflik_yogunlasma_ve_sektor():
    from analysis.risk import portfoy_zayiflik
    dagilim = {"GARAN": 40, "AKBNK": 30, "YKBNK": 30}   # %100 bankacılık
    rapor = portfoy_zayiflik(dagilim, fiyat_df=None)
    assert rapor["yogunlasma"]                    # >=25% pozisyonlar var
    assert any("Bankacılık" in s for s in rapor["sektor_uyari"])
    assert rapor["hedge"]                         # hedge önerileri dolu


def test_portfoy_zayiflik_korelasyon():
    from analysis.risk import portfoy_zayiflik
    # İki yüksek korelasyonlu seri (neredeyse aynı)
    n = 100
    base = np.cumsum(np.random.default_rng(1).normal(0, 1, n)) + 100
    fiyat_df = pd.DataFrame({"AAA": base, "BBB": base + np.random.default_rng(2).normal(0, 0.1, n)})
    rapor = portfoy_zayiflik({"AAA": 50, "BBB": 50}, fiyat_df=fiyat_df)
    assert rapor["korelasyon_ciftleri"]           # yüksek korelasyon yakalanmalı


# ── backtest stratejileri ─────────────────────────────────────────────────────

def test_backtest_stratejileri_pozisyon_serisi():
    from backtest.engine import strateji_rsi, strateji_macd, strateji_sma_kesisim
    df = _ohlcv(n=250)
    for fn in (strateji_rsi, strateji_macd, strateji_sma_kesisim):
        poz = fn(df)
        assert set(poz.dropna().unique()).issubset({0, 1})   # sadece 0/1


def test_backtest_oneri_uret():
    from backtest.engine import backtest, strateji_rsi, oneri_uret
    import config
    df = _ohlcv(n=250)
    sonuc = backtest(df, strateji_rsi, costs=config.COSTS)
    oneriler = oneri_uret(sonuc)
    assert isinstance(oneriler, list) and len(oneriler) >= 1


# ── kap duygu analizi ─────────────────────────────────────────────────────────

def test_kap_duygu_pozitif_negatif():
    from analysis.kap import _baslik_duygu
    assert _baslik_duygu("Şirket rekor kâr açıkladı, ihale kazandı") > 0
    assert _baslik_duygu("Şirkete soruşturma, büyük zarar ve dava") < 0
    assert _baslik_duygu("Hava bugün güzel") == 0


def test_kap_benzeri_tespit():
    from analysis.kap import _kap_benzeri_mi
    assert _kap_benzeri_mi("KAP bildirimi: temettü kararı")
    assert not _kap_benzeri_mi("Dolar kuru bugün yatay seyretti")


# ── portfolio.ozet (nakit kısıtsız) ───────────────────────────────────────────

def test_acik_pozisyonlar_net_hesap(gecici_db):
    from portfolio.ozet import acik_pozisyonlar, net_adet
    from data.storage import save_islem
    save_islem(gecici_db, "THYAO.IS", "AL", "2026-01-01", 100, 100, 10000)
    save_islem(gecici_db, "THYAO.IS", "AL", "2026-01-05", 120, 100, 12000)  # ort 110
    save_islem(gecici_db, "THYAO.IS", "SAT", "2026-01-10", 130, 50, 6500)
    pos = acik_pozisyonlar(gecici_db)
    assert "THYAO.IS" in pos
    assert pos["THYAO.IS"]["adet"] == 150         # 100+100-50
    assert abs(pos["THYAO.IS"]["maliyet"] - 110.0) < 0.01
    assert net_adet(gecici_db, "THYAO.IS") == 150


def test_acik_pozisyonlar_kapanan_silinir(gecici_db):
    from portfolio.ozet import acik_pozisyonlar
    from data.storage import save_islem
    save_islem(gecici_db, "AAA.IS", "AL", "2026-01-01", 10, 100, 1000)
    save_islem(gecici_db, "AAA.IS", "SAT", "2026-01-02", 12, 100, 1200)
    assert "AAA.IS" not in acik_pozisyonlar(gecici_db)   # tamamı satıldı


# ── temel analiz (yorum eşikleri — saf) ───────────────────────────────────────

def test_temel_fk_yorum():
    from analysis.temel import _fk_yorum, _pddd_yorum, _roe_yorum
    assert "zarar" in _fk_yorum(-5)              # negatif F/K
    assert "düşük" in _fk_yorum(6)               # ucuz
    assert "yüksek" in _fk_yorum(40)             # pahalı
    assert "defter değerinin altında" in _pddd_yorum(0.8)
    assert "güçlü" in _roe_yorum(25)
    assert _fk_yorum(None) == ""                 # veri yoksa boş


def test_ayin_oneri_ozet():
    from analysis.ayin_onerileri import _ozet
    class _K: fk = 8; net_kar_buyume = 20
    class _KS: skor = 80
    class _S: rsi = 44
    cumle = _ozet(_K(), _KS(), 0.3, _S())   # kalite + dip bölge + ucuz + RSI düşük
    assert "kalite" in cumle.lower() and "uçmamış" in cumle


# ── kalite skoru + sinyal edge (saf mantık) ───────────────────────────────────

def test_kalite_yuksek_dusuk():
    from analysis.kalite import kalite_skoru
    from data.tv_scanner import TVKalite
    iyi = TVKalite("X.IS", "X", 100, "Tech", fk=10, pddd=1.2, roe=25, roic=18,
                   net_marj=20, fcf_marj=15, borc_ozkaynak=0.4, cari_oran=2.0,
                   gelir_buyume=30, net_kar_buyume=25, temettu=3, piyasa_degeri=1e9, perf_1m=5)
    kotu = TVKalite("Y.IS", "Y", 10, "Steel", fk=5, pddd=0.5, roe=2, roic=1,
                    net_marj=-5, fcf_marj=-2, borc_ozkaynak=4, cari_oran=0.6,
                    gelir_buyume=-10, net_kar_buyume=-90, temettu=0, piyasa_degeri=1e9, perf_1m=-5)
    s_iyi = kalite_skoru(iyi)
    s_kotu = kalite_skoru(kotu)
    assert s_iyi.skor > s_kotu.skor
    assert s_iyi.skor >= 70
    assert s_kotu.deger_tuzagi      # ucuz + bozuk → değer tuzağı


def test_kalite_finans_sektoru_borc_cezasiz():
    """Banka/finans doğal yüksek borç/düşük cari orandan CEZA GÖRMEMELİ."""
    from analysis.kalite import kalite_skoru
    from data.tv_scanner import TVKalite
    ortak = dict(fiyat=10, fk=6, pddd=0.9, roe=22, roic=None, net_marj=25,
                 fcf_marj=None, cari_oran=0.3, gelir_buyume=20, net_kar_buyume=18,
                 temettu=5, piyasa_degeri=1e10, perf_1m=2)
    banka = TVKalite("GARAN.IS", "Garanti", sektor="Finance", borc_ozkaynak=6, **ortak)
    sanayi = TVKalite("XXXX.IS", "Sanayi", sektor="Steel", borc_ozkaynak=6, **ortak)
    s_banka = kalite_skoru(banka)
    s_sanayi = kalite_skoru(sanayi)
    # Aynı (yüksek) borçla banka, sanayiye göre cezalanmadığı için daha yüksek skorlu
    assert s_banka.skor > s_sanayi.skor
    # Banka yüksek borçla değer tuzağı olarak işaretlenmemeli (finans muafiyeti)
    assert not s_banka.deger_tuzagi


def test_kalite_veri_yoksa():
    from analysis.kalite import kalite_skoru
    from data.tv_scanner import TVKalite
    bos = TVKalite("Z.IS", "Z", None, "—", None, None, None, None, None, None,
                   None, None, None, None, None, None, None)
    assert kalite_skoru(bos).etiket == "veri yok"


def test_rsi_wilder_kesintisiz_yukselis_100():
    """Kesintisiz yükselişte RSI=100 (uydurma değil, matematiksel doğru)."""
    from analysis.indicators import _rsi
    seri = pd.Series(np.arange(100, 160, dtype=float))
    rsi = _rsi(seri, 14).dropna()
    assert abs(rsi.iloc[-1] - 100.0) < 1e-6
    assert (rsi >= 0).all() and (rsi <= 100).all()


def test_kirp_uzun_mesaj_isaretlenir():
    """4000+ karakter mesaj sessizce değil, açık işaretle kırpılmalı."""
    from automation.notify import _kirp
    uzun = "x" * 5000
    k = _kirp(uzun)
    assert len(k) <= 4000
    assert "kısaltıldı" in k
    # Kısa mesaj dokunulmadan geçer
    assert _kirp("kısa") == "kısa"


def test_sinyal_al_kosulu_seri():
    from analysis.sinyal_test import _al_kosulu
    from analysis.indicators import add_indicators
    df = _ohlcv(n=250, egim=0.5, oynaklik=3.0)   # dalgalı trend
    kosul = _al_kosulu(add_indicators(df))
    assert kosul.dtype == bool
    assert len(kosul) == len(df)      # her bar için bool koşul (mantık geçerli)


# ── sektör + eğitim (saf) ─────────────────────────────────────────────────────

def test_sektor_tr_cevirisi():
    from analysis.sektor import _tr
    assert _tr("Finance") == "Finans/Bankacılık"
    assert _tr("Bilinmeyen") == "Bilinmeyen"   # haritada yoksa aynen


def test_egitim_metinleri_dolu():
    from analysis.egitim import ekonomik_gostergeler, kuresel_olaylar, risk_yonetimi
    assert "FAİZ" in ekonomik_gostergeler()
    assert "KORUNMA" in kuresel_olaylar()
    import config
    ry = risk_yonetimi(config.DB_PATH)
    assert "POZİSYON" in ry and "STOP" in ry


# ── alarm (portföy stop/hedef/zarar) ──────────────────────────────────────────

def test_alarm_bos_portfoy(gecici_db):
    from analysis.alarm import portfoy_alarmlari
    import config
    assert portfoy_alarmlari(gecici_db, config.RISK) == []   # pozisyon yok → alarm yok


def test_alarm_sat_kararinda_yanlis_stop_hedef_tetiklenmez(gecici_db, monkeypatch):
    """SAT kararında zarar_kes=direnç, kar_al=destek olduğundan stop/hedef alarmı
    üretilmemeli (aksi halde her düşen hisse için sahte 🛑/🎯 alarmı çıkar)."""
    import analysis.alarm as alarm_mod
    from analysis.teknik_derin import TeknikKarar
    from data.storage import save_islem

    save_islem(gecici_db, "DUSEN.IS", "AL", "2026-01-01", 100, 10, 1000)

    # veri_getir'i sahte düşen fiyatla, analiz_et'i SAT kararıyla değiştir
    class _FR:
        ok = True
        class data:
            @staticmethod
            def __len__(): return 60
        note = ""
    import pandas as pd
    fake_df = pd.DataFrame({"Close": [90.0] * 60})

    def sahte_veri(db, sem, **kw):
        class R:
            ok = True
            data = fake_df
            note = ""
        return R()

    def sahte_analiz(df, sem):
        # SAT: zarar_kes fiyatın üstünde (direnç), kar_al altında (destek)
        return TeknikKarar(sem, 90.0, "SAT", "Orta", -6, giris=90.0,
                           kar_al=80.0, zarar_kes=100.0, risk_odul=None)

    monkeypatch.setattr(alarm_mod, "veri_getir", sahte_veri, raising=False)
    # alarm.py fonksiyon içinde import ettiği için modül düzeyinde de yamalayalım
    import data.access as da
    monkeypatch.setattr(da, "veri_getir", sahte_veri)
    import analysis.teknik_derin as td
    monkeypatch.setattr(td, "analiz_et", sahte_analiz)

    alarmlar = alarm_mod.portfoy_alarmlari(gecici_db, {"stop_loss_pct": -0.08})
    # SAT kararı → teknik stop/hedef alarmı YOK (sadece yüzde-zarar alarmı olabilir)
    assert all(a.tip not in ("stop", "stop_yakin", "hedef") for a in alarmlar)


def test_alarm_metni_bos():
    from analysis.alarm import alarm_metni
    metin = alarm_metni([])
    assert "Aktif alarm yok" in metin


# ── tv_scanner.sinyal_puan (saf) ──────────────────────────────────────────────

def test_tv_sinyal_puan_boga_pozitif():
    from data.tv_scanner import TVSatir, sinyal_puan
    boga = TVSatir(
        sembol="X.IS", ad="X", fiyat=110, degisim_pct=2, hacim=3_000_000,
        ort_hacim_10g=1_000_000, rsi=35, macd=2, macd_sinyal=1,
        ema20=108, ema50=105, ema200=100, bb_ust=115, bb_alt=95,
        piyasa_degeri=1e9, yuksek_1m=112, dusuk_1m=95, perf_hafta=3, perf_ay=8,
    )
    ayi = TVSatir(
        sembol="Y.IS", ad="Y", fiyat=90, degisim_pct=-2, hacim=500_000,
        ort_hacim_10g=1_000_000, rsi=75, macd=1, macd_sinyal=2,
        ema20=92, ema50=95, ema200=100, bb_ust=105, bb_alt=88,
        piyasa_degeri=1e9, yuksek_1m=110, dusuk_1m=89, perf_hafta=-3, perf_ay=-8,
    )
    assert sinyal_puan(boga) > sinyal_puan(ayi)   # boğa > ayı
    assert sinyal_puan(boga) > 0
