"""
Uçtan uca offline demo (canlı veri gerektirmez).

Sentetik veriyle tüm tamamlanmış modülleri birlikte çalıştırır:
Aşama 2 (paper portföy), 3 (backtest), 5 (tarihsel), 8 (kalibrasyon), 9 (risk).

Çalıştırmak için proje kökünde:
    python demo.py

Not: Bu sentetik (uydurma) veridir, sadece sistemin çalıştığını göstermek içindir.
Gerçek piyasa değildir.
"""

import numpy as np
import pandas as pd

import config
from analysis.indicators import add_indicators
from portfolio.paper import PaperPortfolio, cok_ufuklu_getiri
from backtest.engine import backtest, train_test_bol, strateji_sma_kesisim
from analysis.historical import olay_calismasi, ozetle
from analysis.calibration import Tahmin, gercek_ekle, kalibre_et, genel_ozet
from analysis import risk
from analysis import macro, news, llm
from analysis.screener import ScreenRow
from automation.scheduler import rapor_metni


def sentetik(n=500, egim=0.25, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(egim + rng.normal(0, 1.2, n))
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "Open": close, "High": close + 1, "Low": close - 1,
        "Close": close, "Volume": rng.integers(800_000, 2_000_000, n),
    }, index=idx)


def cizgi(b): print("\n" + "=" * 60 + f"\n {b}\n" + "=" * 60)


df = add_indicators(sentetik())

cizgi("AŞAMA 2 — PAPER PORTFÖY")
p = PaperPortfolio(config.INITIAL_CAPITAL, costs=config.COSTS)
giris_tarih = df.index[50]
giris_fiyat = float(df["Close"].iloc[50])
p.al("DEMO.IS", fiyat=giris_fiyat, tarih=str(giris_tarih.date()),
     tutar=config.INITIAL_CAPITAL * config.RISK["pozisyon_pct"], gerekce="SMA kesişim sinyali")
guncel = {"DEMO.IS": float(df["Close"].iloc[-1])}
print("Özet:", p.ozet(guncel))
print("Çok ufuklu getiri (girişten itibaren):")
for ufuk, v in cok_ufuklu_getiri(df["Close"], giris_tarih, config.HORIZONS).items():
    print(f"  {ufuk}: {v}")

cizgi("AŞAMA 3 — BACKTEST (out-of-sample)")
egitim, test = train_test_bol(df, 0.3)
r_egitim = backtest(egitim, strateji_sma_kesisim, costs=config.COSTS)
r_test = backtest(test, strateji_sma_kesisim, costs=config.COSTS)
print("Eğitim dönemi :", r_egitim)
print("Test  dönemi  :", r_test)
print("(Strateji benchmark'ı geçemiyorsa fark negatiftir — dürüst sonuç budur.)")

cizgi("AŞAMA 5 — TARİHSEL TEMEL ORANLAR")
# Gercekci gunluk % hareket icin carpimsal (geometrik) yuksek oynaklikli seri
_rng = np.random.default_rng(11)
_ret = _rng.normal(0.0008, 0.025, 600)   # gunluk ~%2.5 oynaklik
_close = 100 * np.cumprod(1 + _ret)
oynak_df = pd.DataFrame({"Close": _close},
                        index=pd.date_range("2022-01-01", periods=600, freq="D"))
esik = 3.0
dag = olay_calismasi(oynak_df, esik_pct=esik, ileri_gun=config.HISTORICAL["ileri_gun"])
print(f"'%{esik:.0f}+ sıçradığı günlerden sonra ne oldu':")
for ufuk, d in dag.items():
    print("  " + ozetle(d))

cizgi("AŞAMA 8 — KALİBRASYON (kendini ölçme)")
rng = np.random.default_rng(1)
tahminler = []
for _ in range(30):  # %58 isabetli sentetik sinyal
    dogru = rng.random() < 0.58
    tahminler.append(gercek_ekle(Tahmin("DEMO", "2023", "pozitif", "SMA_kesisim", 14),
                                 +3 if dogru else -3))
print(genel_ozet(kalibre_et(tahminler, min_ornek=20)))

cizgi("AŞAMA 9 — RİSK")
pozlar = {"A.IS": 30_000, "B.IS": 8_000, "C.IS": 7_000}
print("Yoğunlaşma:", risk.yogunlasma_kontrol(pozlar, config.RISK["yogunlasma_uyari_pct"]) or "uyarı yok")
print("Stop-loss :", risk.stop_loss_kontrol({"X": {"alis_fiyat": 100}}, {"X": 90},
                                            config.RISK["stop_loss_pct"]) or "uyarı yok")
print("Pozisyon büyüklüğü (250 TL fiyat):",
      risk.pozisyon_buyuklugu(config.INITIAL_CAPITAL, 250, config.RISK["pozisyon_pct"]))

cizgi("AŞAMA 7 — PİYASA REJİMİ")
# Yukselen sentetik seri → Boga beklenir
rej_df = sentetik(n=300, egim=0.4, seed=5)
rej = macro.rejim_tespit(rej_df)
print(macro.ozetle(rej))
for n in rej.notlar:
    print("  •", n)
breadth = macro.piyasa_genisligi({
    "A": sentetik(egim=0.5, seed=1)["Close"],
    "B": sentetik(egim=-0.5, seed=2)["Close"],
    "C": sentetik(egim=0.3, seed=3)["Close"],
}, pencere=50)
print(f"Piyasa genişliği: {breadth['ustte']}/{breadth['toplam']} hisse "
      f"50g ortalamasının üzerinde")

cizgi("AŞAMA 4 — HABER & KAP (offline RSS ayrıştırma)")
RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
  <item><title>Şirket X bilanço açıkladı</title>
    <link>https://ornek.test/1</link>
    <pubDate>Mon, 08 Jun 2026 10:00:00 GMT</pubDate></item>
  <item><title>Piyasa yatay kapattı</title>
    <link>https://ornek.test/2</link>
    <pubDate>Mon, 08 Jun 2026 17:00:00 GMT</pubDate></item>
</channel></rss>"""
for h in news._rss_ayristir(RSS, "Demo Akışı", limit=10):
    print(f"  • {h.baslik}  ({h.kaynak}, {h.zaman[:16]})")
print("(Canlı hisse haberi için: news.hisse_haberleri('AAPL') — yfinance.)")

cizgi("AŞAMA 6 — LLM SENTEZ (deterministik çıktıların özeti)")
baglam = {
    "symbol": "DEMO.IS", "fiyat": 142.5,
    "sinyal_ozet": rej.rejim, "sinyal_notlar": rej.notlar[:2],
    "rejim": macro.ozetle(rej),
}
print("Claude'a gidecek baglam (ozet):")
print("  " + llm.baglam_metni(baglam).splitlines()[0])
sonuc = llm.sentezle(baglam)   # anahtar yoksa uydurmaz, durumu söyler
print("Sentez sonucu:", "üretildi" if sonuc.ok else f"atlandı — {sonuc.not_}")

cizgi("AŞAMA 10 — OTOMASYON (offline rapor kurma)")
rows = [
    ScreenRow("AAA.IS", 100.0, 6.5, 2.0, 72,
              gerekceler=["yükseldi +6.5%", "RSI yüksek (72)"]),
    ScreenRow("BBB.IS", 50.0, 0.2, 1.0, 50, gerekceler=[]),
]
print(rapor_metni(rows, "XU100.IS — " + macro.ozetle(rej), "2026-06-08"))
print("\n(Canlı tarama + dosyaya yazma için: python -m automation.run)")

print("\n[Tüm değerler sentetiktir; yatırım tavsiyesi değildir.]")
