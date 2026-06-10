"""
Telegram bildirim botu (Aşama 12) testleri — offline, ağ/token gerektirmez.
"""

from datetime import datetime

from automation import notify
from analysis.recommender import OneriSatir


def test_telegram_ayarsiz_graceful(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notify.telegram_ayarli_mi() is False
    ok, hata = notify.telegram_gonder("merhaba")
    assert ok is False
    assert "ayarlı değil" in hata


def test_borsa_gunu_bugun():
    bugun = datetime.now().strftime("%Y-%m-%d")
    assert notify.borsa_gunu_mu(bugun) is True


def test_borsa_gunu_eski_tarih():
    assert notify.borsa_gunu_mu("2020-01-01") is False
    assert notify.borsa_gunu_mu("") is False


def test_gunluk_ozet_metni():
    satirlar = [
        OneriSatir("AAA.IS", 75, "Güçlü AL adayı", 100.0, 5.0, guven="yüksek"),
        OneriSatir("BBB.IS", 60, "AL adayı", 50.0, 2.0, guven="orta"),
        OneriSatir("CCC.IS", 30, "Zayıf / Kaçın", 20.0, -3.0, guven="düşük"),
    ]
    metin = notify.gunluk_ozet_metni(satirlar, "XU100.IS — Boğa",
                                     "2026-06-10T18:30:00", aday_sayisi=5)
    assert "AAA.IS" in metin and "BBB.IS" in metin
    assert "CCC.IS" not in metin            # sadece AL adayları listelenir
    assert "Boğa" in metin
    assert "tavsiyesi değildir" in metin


def test_gunluk_ozet_aday_yoksa():
    satirlar = [OneriSatir("CCC.IS", 30, "Zayıf / Kaçın", 20.0, -3.0, guven="düşük")]
    metin = notify.gunluk_ozet_metni(satirlar, "XU100.IS — Ayı", "2026-06-10T18:30:00")
    assert "güçlü AL adayı yok" in metin
