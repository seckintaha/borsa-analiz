# Borsa Analiz & Takip Sistemi

Global + BIST hisseleri için takip, teknik analiz ve gün sonu tarama sistemi.
Bu depo, projenin **Aşama 0–3, 5, 8, 9** başlangıcını içerir (canlı veri
gerektirmeyen, test edilmiş çekirdek). Tam plan için `borsa_analiz_yol_haritasi.md`.

> **Önemli:** Bu bir karar **destek** aracıdır, kâhin değildir. Hiçbir çıktısı
> yatırım tavsiyesi değildir. Üretilen sinyaller teknik göstergelerin matematiksel
> çıktısıdır ve sık sık yanılır.

## Şu an ne yapıyor

- **Veri:** Global (AAPL) ve BIST (THYAO.IS) için fiyat/OHLCV çeker; her kayıt
  kaynağa + zaman damgasına bağlıdır; veri yoksa açıkça belirtir.
- **Saklama:** SQLite'a yazar (`borsa.db`).
- **Analiz:** RSI, MACD, hareketli ortalamalar, Bollinger; dengeli özet + **ayı
  senaryosu** + **manipülasyon/ince hacim bayrağı**.
- **Panel:** Streamlit ile mum grafik + göstergeler + özet.
- **Tarama (Aşama 1):** İzleme listesini tarar; en çok artan/azalan, anormal hacim,
  RSI uçlarını **gerekçesiyle** listeler.
- **Paper portföy (Aşama 2):** Sanal alım-satım, işlem maliyeti (komisyon+kayma)
  dahil, ayarlanabilir ufukla (kısa/orta/uzun) P&L.
- **Backtest (Aşama 3):** Strateji simülasyonu, **benchmark (al-tut) karşılaştırması**,
  out-of-sample bölme, look-ahead önleme, metrikler (getiri, kazanma oranı, max düşüş,
  Sharpe), işlem maliyeti dahil.
- **Tarihsel temel oranlar (Aşama 5):** "Geçmişte böyle sıçradığında ne oldu" →
  **medyan + aralık + örnek sayısı (n)**; az örnek "güvenilmez" diye işaretlenir.
  Aylık mevsimsellik istatistikleri.
- **Kalibrasyon (Aşama 8):** Tahminleri gerçeğe karşı puanlar; sinyal tipine göre
  isabet oranı + **yazı-tura (0.5) kıyası**.
- **Risk (Aşama 9):** Pozisyon büyüklüğü, yoğunlaşma uyarısı, stop-loss, korelasyon,
  portföy max düşüş.

## Hızlı demo (canlı veri gerektirmez)

Tüm tamamlanmış modülleri sentetik veriyle birlikte çalıştırır:

```bash
python demo.py
```

## Kurulum

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Çalıştırma

```bash
streamlit run app/panel.py
```

Tarayıcı açılır. "Panel" sekmesinde tek hisse analizi, "Tarama" sekmesinde gün sonu
öne çıkanlar.

## Test

```bash
pytest -q
```

Testler internet gerektirmez; gösterge ve sinyal matematiğini sentetik veriyle doğrular.

## Proje yapısı

```
borsa-analiz/
├── config.py              # tüm ayarlar (izleme listesi, ufuklar, eşikler, maliyet, risk)
├── demo.py                # uçtan uca offline demo
├── data/
│   ├── fetcher.py         # veri çekme (hata yakalama, kaynak+zaman)
│   └── storage.py         # SQLite saklama
├── analysis/
│   ├── indicators.py      # teknik göstergeler (saf pandas)
│   ├── signals.py         # sinyal + ayı senaryosu + bayraklar
│   ├── screener.py        # Aşama 1: gün sonu tarama
│   ├── historical.py      # Aşama 5: tarihsel temel oranlar + mevsimsellik
│   ├── calibration.py     # Aşama 8: kendini ölçme
│   └── risk.py            # Aşama 9: risk yönetimi
├── portfolio/
│   └── paper.py           # Aşama 2: paper portföy
├── backtest/
│   └── engine.py          # Aşama 3: backtest motoru
├── app/
│   └── panel.py           # Streamlit arayüz
└── tests/
    ├── test_indicators.py # gösterge/sinyal testleri
    └── test_stages.py     # Aşama 2-3-5-8-9 testleri (22 test toplam)
```

## Ayarlar

Her şey `config.py`'de: izleme listesi, zaman ufukları (kısa/orta/uzun — sabit
değil), tarama eşikleri, başlangıç sermayesi. Sabit değer kodun içine gömülmez.

## Claude Code ile devam

Bu depoyu GitHub'a koyup Claude Code'a bağlayın, sonra sırayla isteyin:

1. "Bu projeyi çalıştır: `pip install -r requirements.txt`, sonra `python demo.py`,
   `pytest` ve `streamlit run app/panel.py` ile her şeyin çalıştığını doğrula."
2. "Paper portföy (Aşama 2), backtest (Aşama 3), tarihsel (Aşama 5), kalibrasyon
   (Aşama 8) ve risk (Aşama 9) modüllerini Streamlit paneline yeni sekmeler olarak
   bağla; şu an bunlar kod olarak hazır ama arayüze takılı değil."
3. "Aşama 4 (KAP & haber) modülünü ekle: kap_sdk ile bildirimler, Finnhub/RSS ile
   haber, hepsi kaynağa+tarihe bağlı."
4. Sonra Aşama 6 (LLM sentez), 7 (makro/rejim), 10 (otomasyon) — yol haritası sırası.

## Sınırlar / bilinen riskler

- Veri kaynakları (yfinance) resmi olmayan yöntemle çalışır; format değişebilir,
  hız limiti olabilir. İlk gerçek çalıştırmada bir yerde takılması olağandır.
- BIST'e özgü düzeltmeler (bedelsiz/temettü), delisting, işlem takvimi henüz tam
  ele alınmadı (yol haritası Bölüm 8.1).
- Sinyaller basit kurallardır; backtest ve kalibrasyon (Aşama 3 ve 8) yapılmadan
  güvenilirliği ölçülemez.
- **Kendini kanıtlamadan gerçek parayla bağlamayın.**
