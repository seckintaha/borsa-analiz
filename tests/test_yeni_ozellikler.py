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

# ── faktör motoru (çok-faktör kesitsel sıralama — saf matematik) ──────────────

def test_persentil_temel_siralama():
    from analysis.faktor import persentil_sirala
    # Artan değerler → yüksek iyi: en büyük ~100, en küçük ~0
    p = persentil_sirala([10, 20, 30, 40, 50], yuksek_iyi=True)
    assert p[0] == 0.0 and p[-1] == 100.0
    assert p[2] == 50.0                       # orta eleman
    # yuksek_iyi=False → ters (düşük değer yüksek persentil)
    pt = persentil_sirala([10, 20, 30, 40, 50], yuksek_iyi=False)
    assert pt[0] == 100.0 and pt[-1] == 0.0


def test_persentil_none_ve_esitlik():
    from analysis.faktor import persentil_sirala
    # None sıralamaya girmez, None kalır
    p = persentil_sirala([5, None, 10, None, 15])
    assert p[1] is None and p[3] is None
    assert p[0] == 0.0 and p[4] == 100.0
    # Tek geçerli eleman → nötr 50
    assert persentil_sirala([None, 7, None])[1] == 50.0
    # Eşit değerler aynı persentili alır
    pe = persentil_sirala([10, 10, 20])
    assert pe[0] == pe[1]


def test_kopuk_cezasi_tavan_kirpar():
    from analysis.faktor import kopuk_cezasi
    assert kopuk_cezasi(45, 5) == 1.0                 # normal → ceza yok
    assert kopuk_cezasi(85, None) < 0.2               # aşırı RSI → ağır ceza
    assert kopuk_cezasi(None, 50) < 0.3               # aşırı aylık getiri → ceza
    # Ceza monoton: daha uçmuş = daha düşük çarpan
    assert kopuk_cezasi(75, None) < kopuk_cezasi(66, None)
    assert kopuk_cezasi(None, 35) < kopuk_cezasi(None, 22)


def test_piotroski_sentetik_puan():
    from analysis.faktor import piotroski_fscore
    from data.tv_scanner import TVKalite
    # Neredeyse mükemmel bilanço → yüksek F-Score
    saglam = TVKalite("A.IS", "A", 10, "Tech", fk=10, pddd=1.0, roe=25, roic=18,
                      net_marj=20, fcf_marj=22, borc_ozkaynak=0.4, cari_oran=2.0,
                      gelir_buyume=30, net_kar_buyume=25, temettu=2,
                      piyasa_degeri=1e9, perf_1m=5)
    skor, n, _ = piotroski_fscore(saglam)
    assert n == 9 and skor >= 8               # neredeyse tüm testler geçer
    # Bozuk bilanço → düşük F-Score
    bozuk = TVKalite("B.IS", "B", 10, "Steel", fk=-3, pddd=0.5, roe=-5, roic=-2,
                     net_marj=-8, fcf_marj=-10, borc_ozkaynak=4, cari_oran=0.5,
                     gelir_buyume=-15, net_kar_buyume=-40, temettu=0,
                     piyasa_degeri=1e9, perf_1m=-5)
    skor2, n2, _ = piotroski_fscore(bozuk)
    assert skor2 <= 1 and skor > skor2


def test_piotroski_finans_kaldirac_atlar():
    from analysis.faktor import piotroski_fscore
    from data.tv_scanner import TVKalite
    banka = TVKalite("G.IS", "G", 10, "Finance", fk=6, pddd=0.9, roe=22, roic=None,
                     net_marj=25, fcf_marj=None, borc_ozkaynak=6, cari_oran=0.3,
                     gelir_buyume=20, net_kar_buyume=18, temettu=5,
                     piyasa_degeri=1e10, perf_1m=2)
    _, n, g = piotroski_fscore(banka)
    # Finans: kaldıraç + cari oran testleri atlanır → toplam test < 9
    assert n <= 7
    assert not any("kaldıraç" in x for x in g)


def test_birlesik_skor_agirlikli_ve_none_yayar():
    from analysis.faktor import FaktorKayit, birlesik_skor
    yuksek = FaktorKayit("Y", "Tech", deger_p=80, kalite_p=90, momentum_p=60,
                         buyume_p=70, trend_p=100)
    dusuk = FaktorKayit("D", "Tech", deger_p=20, kalite_p=10, momentum_p=40,
                        buyume_p=30, trend_p=0)
    assert birlesik_skor(yuksek) > birlesik_skor(dusuk)
    assert 0 <= birlesik_skor(dusuk) <= 100
    # Eksik faktör (None) skoru sıfırlamaz; kalan faktörler yeniden ağırlıklanır
    kismi = FaktorKayit("K", "Tech", deger_p=None, kalite_p=80, momentum_p=None,
                        buyume_p=None, trend_p=None)
    assert abs(birlesik_skor(kismi) - 80.0) < 1e-6
    # Hiç faktör yoksa 0
    assert birlesik_skor(FaktorKayit("Z", "—")) == 0.0


def test_faktor_evreni_kaliteli_ustte_kopuk_altta():
    """Çok-faktör evren: kaliteli+ucuz+sağlam momentum, uçmuş köpüğü geçmeli."""
    from analysis.faktor import faktor_evreni, EvrenGirdi
    from data.tv_scanner import TVKalite, TVSatir

    def kal(sem, sek, **kw):
        base = dict(fiyat=10, fk=10, pddd=1.0, roe=20, roic=15, net_marj=15,
                    fcf_marj=12, borc_ozkaynak=0.5, cari_oran=2.0, gelir_buyume=20,
                    net_kar_buyume=15, temettu=3, piyasa_degeri=1e9, perf_1m=5)
        base.update(kw)
        return TVKalite(sem, sem, base["fiyat"], sek, base["fk"], base["pddd"],
                        base["roe"], base["roic"], base["net_marj"], base["fcf_marj"],
                        base["borc_ozkaynak"], base["cari_oran"], base["gelir_buyume"],
                        base["net_kar_buyume"], base["temettu"], base["piyasa_degeri"],
                        base["perf_1m"])

    def tek(sem, rsi, perf_ay, fiyat=110, ema50=105, ema200=100):
        return TVSatir(sem, sem, fiyat, 1, 2e6, 1e6, rsi, 1, 0.5, 108, ema50,
                       ema200, 120, 95, 1e9, 115, 95, 2, perf_ay)

    girdiler = [
        # Kaliteli, ucuz, sağlıklı momentum (RSI 50, +8 ay) — ideal aday
        EvrenGirdi("IYI.IS", kal("IYI.IS", "Tech", fk=8, roe=28, roic=22),
                   tek("IYI.IS", 50, 8)),
        # Uçmuş köpük: aynı temeller ama RSI 85, +50 ay → momentum kırpılmalı
        EvrenGirdi("KOPUK.IS", kal("KOPUK.IS", "Tech", fk=8, roe=28, roic=22),
                   tek("KOPUK.IS", 85, 50)),
        # Zayıf temel dolgu
        EvrenGirdi("ZAYIF.IS", kal("ZAYIF.IS", "Steel", fk=25, roe=3, roic=1,
                   net_marj=-2, fcf_marj=-3, borc_ozkaynak=4, net_kar_buyume=-30),
                   tek("ZAYIF.IS", 45, -5, fiyat=90, ema50=95, ema200=100)),
    ]
    kayitlar = faktor_evreni(girdiler)
    m = {r.sembol: r for r in kayitlar}
    # Köpük hissesinin momentum persentili, ceza sonrası ham persentilinden düşük
    assert m["KOPUK"].kopuk_carpan < 0.3
    assert m["KOPUK"].momentum_p < m["KOPUK"].momentum_ham_p
    # İyi hisse köpükten daha yüksek birleşik skor almalı (tavan kovalanmaz)
    assert m["IYI"].birlesik > m["KOPUK"].birlesik
    # Piotroski hesaplanmış olmalı
    assert m["IYI"].piotroski >= 7


def test_magic_formula_ortak_sira():
    from analysis.faktor import faktor_evreni, EvrenGirdi
    from data.tv_scanner import TVKalite

    def kal(sem, fk, roic):
        return TVKalite(sem, sem, 10, "Tech", fk, 1.0, 20, roic, 15, 12, 0.5,
                        2.0, 20, 15, 3, 1e9, 5)

    girdiler = [
        EvrenGirdi("A.IS", kal("A.IS", 5, 30), None),    # ucuz + yüksek ROIC = en iyi
        EvrenGirdi("B.IS", kal("B.IS", 20, 10), None),
        EvrenGirdi("C.IS", kal("C.IS", 12, 18), None),
    ]
    kayitlar = faktor_evreni(girdiler)
    m = {r.sembol: r for r in kayitlar}
    assert m["A"].magic_sira == 1                # en yüksek kazanç verimi + ROIC
    assert m["A"].magic_sira < m["B"].magic_sira


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


# ── performans takibi (ağsız) ─────────────────────────────────────────────────

def test_oneri_takip_dedup_ve_bos_rapor(gecici_db):
    from data.storage import save_oneri_takip, load_oneri_takip
    from analysis.performans import performans_metni
    # Aynı dönem+sembol+kaynak iki kez → tek kayıt (UNIQUE)
    save_oneri_takip(gecici_db, "2026-06", "2026-06-01", "THYAO.IS", 300, 360, 285, 80, "aylik")
    save_oneri_takip(gecici_db, "2026-06", "2026-06-01", "THYAO.IS", 300, 360, 285, 80, "aylik")
    save_oneri_takip(gecici_db, "2026-06", "2026-06-01", "GARAN.IS", 130, 155, 122, 78, "aylik")
    assert len(load_oneri_takip(gecici_db)) == 2          # çift engellendi
    # Olgunlaşmamış (bugün) öneri → ölçüm boş, dürüst mesaj (ağ gerektirmez)
    from datetime import datetime
    bugun = datetime.now().strftime("%Y-%m-%d")
    save_oneri_takip(gecici_db, "2099-01", bugun, "AAA.IS", 10, 12, 9, 70, "aylik")
    # min_gun çok yüksek → hiçbiri olgun değil → boş rapor mesajı
    metin = performans_metni(gecici_db, min_gun=9999)
    assert "Henüz ölçülecek olgun öneri yok" in metin


def test_oneri_kaydet_liste(gecici_db):
    from analysis.performans import oneri_kaydet
    from data.storage import load_oneri_takip
    class _O:
        def __init__(s, sembol, giris):
            s.sembol = sembol; s.giris = giris; s.hedef = giris*1.2
            s.stop = giris*0.95; s.birlesik = 75.0
    n = oneri_kaydet(gecici_db, [_O("THYAO", 300), _O("GARAN", 130)], kaynak="aylik")
    assert n == 2
    assert len(load_oneri_takip(gecici_db, kaynak="aylik")) == 2


# ── XXE / RSS güvenlik sertleştirmesi (ağsız) ─────────────────────────────────

_NORMAL_RSS = ('<rss><channel><item><title>Test Haber</title>'
               '<link>http://ornek.com/a</link>'
               '<description>ozet</description></item></channel></rss>')

_BILLION_LAUGHS = (
    '<?xml version="1.0"?>\n'
    '<!DOCTYPE lolz [ <!ENTITY lol "lol">'
    ' <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
    ' <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;"> ]>'
    '<rss><channel><item><title>&lol3;</title></item></channel></rss>')

_XXE = ('<?xml version="1.0"?>'
        '<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        '<rss><channel><item><title>&x;</title></item></channel></rss>')


@pytest.mark.parametrize("modul_ad", ["analysis.news", "analysis.kap"])
def test_xml_normal_rss_ayristirilir(modul_ad):
    import importlib
    mod = importlib.import_module(modul_ad)
    kok = mod._xml_fromstring(_NORMAL_RSS)
    assert kok.find(".//title").text == "Test Haber"


@pytest.mark.parametrize("modul_ad", ["analysis.news", "analysis.kap"])
@pytest.mark.parametrize("payload_ad", ["billion", "xxe"])
def test_xml_dtd_saldirilari_reddedilir(modul_ad, payload_ad):
    """Billion-laughs ve harici entity (XXE) DTD içerdiği için reddedilmeli."""
    import importlib
    mod = importlib.import_module(modul_ad)
    payload = _BILLION_LAUGHS if payload_ad == "billion" else _XXE
    with pytest.raises(Exception):
        mod._xml_fromstring(payload)


def test_kap_rss_yerel_dosya_semasi_reddedilir():
    """file:// gibi http olmayan şemalar için ağa çıkmadan boş dönmeli (SSRF)."""
    from analysis import kap
    assert kap._rss_cek("file:///etc/passwd") == []
    assert kap._http_url_mu("http://x.com") is True
    assert kap._http_url_mu("file:///etc/passwd") is False


# ── Panel yardımcıları: tek satırlık veri sekmeyi kırmamalı ───────────────────

def test_liste_ozet_tek_satir_veri_cokmez(monkeypatch):
    """_liste_ozet, tek satırlık (iloc[-2] olmayan) veri gelse de çökmemeli."""
    from data.fetcher import FetchResult
    import analysis.screener  # noqa
    tek = pd.DataFrame({"Open": [10.0], "High": [10.0], "Low": [10.0],
                        "Close": [10.0], "Volume": [1000.0]},
                       index=pd.date_range(end=datetime.now().date(), periods=1, freq="B"))
    fr = FetchResult("AAA", tek, "test", "", ok=True)

    import app.panel as panel
    monkeypatch.setattr(panel, "fetch_many", lambda syms, period="3mo": {"AAA": fr})
    # cache'li fonksiyonun sarmalanmamış halini çağır
    rows = panel._liste_ozet.__wrapped__("AAA")
    assert rows and rows[0]["Sembol"] == "AAA"
    assert rows[0]["Durum"] == "⚠️ Yetersiz veri"


# ── küresel piyasa nabzı (ağsız — metin/mantık) ───────────────────────────────

def test_kuresel_metni_veri_yok():
    from analysis.kuresel_piyasa import kuresel_metni, KureselNabiz
    # ok=False (hiç veri yok) → dürüst mesaj, çökme yok
    bos = KureselNabiz(varliklar=[], risk_skoru=0, risk_etiket="Nötr", bist_etkileri=[], ok=False)
    assert "Veri alınamadı" in kuresel_metni(bos)


def test_kuresel_metni_render():
    from analysis.kuresel_piyasa import kuresel_metni, KureselNabiz, VarlikVeri
    v = [
        VarlikVeri("^GSPC","S&P 500 (ABD)","abd","deg",5000.0,-0.4),
        VarlikVeri("^VIX","VIX (korku endeksi)","risk","seviye",26.0,3.6),
        VarlikVeri("TRY=X","USD/TRY","kur","deg",34.0,0.8),
        VarlikVeri("BZ=F","Brent petrol","emtia","deg",76.0,5.7),
    ]
    kn = KureselNabiz(varliklar=v, risk_skoru=-2, risk_etiket="Risk-OFF 🔴",
                      bist_etkileri=["⚠️ VIX 26 yüksek", "⚠️ USD/TRY %+0.8"], ok=True)
    m = kuresel_metni(kn)
    assert "KÜRESEL" in m and "Risk-OFF" in m and "Brent" in m


# ── olay / bilanço takvimi (ağsız — DB + metin mantığı) ───────────────────────

def test_olaylar_metni_bos_portfoy_durust(gecici_db):
    # Boş portföyde ağ ÇAĞRILMAZ; dürüst mesaj döner.
    from analysis.olaylar import olaylar_metni
    m = olaylar_metni(gecici_db)
    assert "OLAY TAKVİMİ" in m
    assert "açık pozisyon yok" in m


def test_olaylar_metni_takvim_yok_uydurmaz(gecici_db, monkeypatch):
    # Portföyde hisse var ama yfinance bilanço tarihi vermiyor (None) →
    # "takvim verisi yok" der, tarih UYDURMAZ.
    from data.storage import save_islem
    import analysis.olaylar as olaylar
    save_islem(gecici_db, "THYAO.IS", "AL", "2026-01-01", 100, 10, 1000)
    monkeypatch.setattr(olaylar, "yaklasan_bilanco", lambda s: None)
    m = olaylar.olaylar_metni(gecici_db)
    assert "1 hisse" in m
    assert "bulunamadı" in m and "takvim verisi yok" in m


def test_portfoy_olaylari_15gun_ici_uyari(gecici_db, monkeypatch):
    from data.storage import save_islem
    import analysis.olaylar as olaylar
    save_islem(gecici_db, "ASELS.IS", "AL", "2026-01-01", 50, 20, 1000)
    save_islem(gecici_db, "THYAO.IS", "AL", "2026-01-01", 100, 10, 1000)

    def sahte_bilanco(sembol):
        if sembol.startswith("ASELS"):
            return {"tarih": "2026-07-15", "gun_kaldi": 5}   # 15 gün içi → uyarı
        return {"tarih": "2026-09-01", "gun_kaldi": 60}       # uzak → uyarı yok

    monkeypatch.setattr(olaylar, "yaklasan_bilanco", sahte_bilanco)
    uyarilar = olaylar.portfoy_olaylari(gecici_db)
    assert len(uyarilar) == 1
    assert "ASELS" in uyarilar[0] and "oynaklık riski" in uyarilar[0]
    assert not any("THYAO" in u for u in uyarilar)


def test_olaylar_normalize_is_eki():
    from analysis.olaylar import _normalize
    assert _normalize("thyao") == "THYAO.IS"
    assert _normalize("AAPL") == "AAPL.IS"        # harf + ≤5 → .IS
    assert _normalize("XU100.IS") == "XU100.IS"   # zaten .IS
    assert _normalize("BRENT.OIL") == "BRENT.OIL" # nokta var → dokunma


# ── enflasyon farkındalığı notu (ağsız — scanner stub'lanır) ──────────────────

def _stub_temel():
    from data.tv_scanner import TVTemel
    return TVTemel(
        sembol="THYAO.IS", ad="THY", fiyat=300.0, degisim_pct=1.0,
        fk=4.0, pddd=1.2, temettu_verim=2.0, roe=25.0, eps=70.0,
        net_marj=12.0, gelir_buyume=30.0, piyasa_degeri=4e11, sektor="Ulaştırma")


def test_temel_enflasyon_notu_gecer(monkeypatch):
    import analysis.temel as temel
    monkeypatch.setattr(temel, "tv_temel_tara",
                        lambda tickers=None, **kw: (True, "", [_stub_temel()]))
    m = temel.tek_hisse_temel("THYAO")
    assert "NOMİNAL" in m and "enflasyon muhasebesi" in m
    assert "F/K" in m   # mevcut çıktı bozulmadı


def test_buyume_temettu_enflasyon_notu_gecer(monkeypatch):
    import analysis.temel as temel
    monkeypatch.setattr(temel, "tv_temel_tara",
                        lambda tickers=None, **kw: (True, "", [_stub_temel()]))
    m = temel.buyume_temettu("THYAO")
    assert "NOMİNAL" in m and "sektör ortalamasıyla göreli" in m


def test_kalite_enflasyon_notu_gecer(monkeypatch):
    from data.tv_scanner import TVKalite
    import analysis.kalite as kalite
    k = TVKalite(
        sembol="THYAO.IS", ad="THY", fiyat=300.0, sektor="Ulaştırma",
        fk=4.0, pddd=1.2, roe=25.0, roic=15.0, net_marj=12.0, fcf_marj=8.0,
        borc_ozkaynak=0.5, cari_oran=1.6, gelir_buyume=30.0,
        net_kar_buyume=20.0, temettu=2.0, piyasa_degeri=4e11, perf_1m=5.0)
    monkeypatch.setattr(kalite, "tv_kalite_tara",
                        lambda tickers=None, **kw: (True, "", [k]))
    m = kalite.kalite_tek("THYAO")
    assert "NOMİNAL" in m and "enflasyon" in m
    assert "KALİTE SKORU" in m   # mevcut çıktı bozulmadı


# ── portföy optimizasyonu (ağsız — saf matematik + boş DB) ────────────────────

def test_optimize_bos_portfoy_durust(gecici_db):
    """Boş portföyde ağ ÇAĞRILMAZ; dürüst mesaj döner, çökme yok."""
    from analysis.optimize import portfoy_optimizasyon, optimize_metni
    r = portfoy_optimizasyon(gecici_db)
    assert r["ok"] is False
    assert r["mesaj"] == "portföy boş"
    m = optimize_metni(gecici_db)
    assert "PORTFÖY OPTİMİZASYONU" in m
    assert "boş" in m
    # Metinde yatırım tavsiyesi uyarısı boş portföyde bile çökmeden üretilebilmeli
    assert "OPTİMİZASYONU" in m


def test_optimize_agirlik_semalari_toplam_bir():
    """Üç şema da uzun-only ve toplamı ~1.0 olmalı."""
    from analysis.optimize import _esit_agirlik, _ters_vol_agirlik, _min_varyans_agirlik
    vol = np.array([0.2, 0.4, 0.1, 0.3])
    # Pozitif tanımlı kovaryans (rastgele ama simetrik + köşegen baskın)
    rng = np.random.default_rng(3)
    a = rng.normal(0, 1, (4, 4))
    cov = a @ a.T + np.eye(4) * 0.5
    for w in (_esit_agirlik(4), _ters_vol_agirlik(vol), _min_varyans_agirlik(cov, vol)):
        assert abs(w.sum() - 1.0) < 1e-9
        assert (w >= -1e-12).all()           # uzun-only (negatif yok)


def test_optimize_ters_vol_yuksek_vol_dusuk_agirlik():
    """Ters-volatilite: yüksek oynaklıklı hisse daha DÜŞÜK ağırlık almalı."""
    from analysis.optimize import _ters_vol_agirlik
    vol = np.array([0.10, 0.20, 0.40])       # artan oynaklık
    w = _ters_vol_agirlik(vol)
    assert w[0] > w[1] > w[2]                 # düşük vol → yüksek ağırlık
    assert abs(w.sum() - 1.0) < 1e-9
    # Sıfır volatilite sıfıra bölmeyle çökmemeli
    w2 = _ters_vol_agirlik(np.array([0.0, 0.2]))
    assert np.isfinite(w2).all() and abs(w2.sum() - 1.0) < 1e-9


def test_optimize_ters_vol_sentetik_getiri_matrisi():
    """Sentetik getiri matrisinden yıllık vol + ters-vol ağırlığı: sakin hisse ağır basar."""
    from analysis.optimize import _yillik_vol, _ters_vol_agirlik
    rng = np.random.default_rng(7)
    n = 300
    # A: düşük oynaklık (std 0.005), B: yüksek oynaklık (std 0.03)
    getiri_df = pd.DataFrame({
        "SAKIN": rng.normal(0, 0.005, n),
        "OYNAK": rng.normal(0, 0.030, n),
    })
    vol = _yillik_vol(getiri_df)
    assert vol[0] < vol[1]                    # sakin hisse daha düşük yıllık vol
    w = _ters_vol_agirlik(vol)
    assert w[0] > w[1]                        # ters-vol → sakin hisseye daha çok ağırlık


def test_optimize_min_varyans_tekil_matris_ters_vole_duser():
    """Tekil (ters alınamaz) kovaryansta min-varyans ters-volatiliteye düşmeli, çökmemeli."""
    from analysis.optimize import _min_varyans_agirlik, _ters_vol_agirlik
    # İki özdeş satır → tekil matris
    tekil = np.array([[1.0, 1.0], [1.0, 1.0]])
    vol = np.array([0.1, 0.4])
    w = _min_varyans_agirlik(tekil, vol)
    beklenen = _ters_vol_agirlik(vol)
    assert np.allclose(w, beklenen)
    assert abs(w.sum() - 1.0) < 1e-9


def test_optimize_portfoy_vol_ve_normalize_kenar_durum():
    """Portföy vol ve normalize None/sıfır/tek-hisse kenar durumlarında çökmemeli."""
    from analysis.optimize import _portfoy_vol, _normalize, _min_varyans_agirlik
    # Tek hisse: min-varyans = %100
    assert np.allclose(_min_varyans_agirlik(np.array([[0.04]]), np.array([0.2])), [1.0])
    # Sıfır ağırlık toplamı → eşit dağıtım
    assert np.allclose(_normalize(np.array([0.0, 0.0, 0.0])), [1/3, 1/3, 1/3])
    # Boş girdi
    assert _portfoy_vol(np.array([]), np.zeros((0, 0))) == 0.0


# ── rejim-duyarlı faktör ağırlıkları (ağsız) ──────────────────────────────────

def test_rejim_agirliklari_rotasyon():
    from analysis.faktor import rejim_agirliklari
    # Risk-off + ayı → savunmacı (kalite yüksek, momentum düşük)
    a_def, n_def = rejim_agirliklari(-2, "Ayı")
    assert a_def["kalite"] > a_def["momentum"]
    assert "SAVUNMACI" in n_def
    # Risk-on + boğa → atak (momentum artar)
    a_atk, n_atk = rejim_agirliklari(2, "Boğa")
    assert a_atk["momentum"] > a_def["momentum"]
    assert "ATAK" in n_atk
    # Her profil toplam ~1.0
    for a in (a_def, a_atk, rejim_agirliklari(0, "Yatay")[0]):
        assert abs(sum(a.values()) - 1.0) < 0.001
