# Borsa Analiz & Takip Sistemi

Global + BIST hisseleri için takip, teknik analiz ve gün sonu tarama sistemi.
Bu depo, projenin **Aşama 0–10** modüllerini içerir (Aşama 4 haber/KAP, 6 LLM
sentez, 7 makro/rejim, 10 otomasyon dahil). Çekirdek testlerle doğrulanmıştır.

> **Önemli:** Bu bir karar **destek** aracıdır, kâhin değildir. Hiçbir çıktısı
> yatırım tavsiyesi değildir. Üretilen sinyaller teknik göstergelerin matematiksel
> çıktısıdır ve sık sık yanılır.

📐 **Mimari, tasarım ilkeleri ve güvenlik:** [`MIMARI.md`](MIMARI.md).
🔑 **API anahtarı kurulumu:** [`.env.example`](.env.example).

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
- **Haber & KAP (Aşama 4):** Hisseye özel haberler (yfinance) + config'e eklenen
  RSS/KAP akışları; her haber **kaynağa + yayın zamanına** bağlı, ek anahtar gerekmez.
- **LLM Sentez (Aşama 6):** Yukarıdaki deterministik çıktıları Claude ile dengeli
  bir Türkçe özete çevirir; **yeni veri uydurmaz, AL/SAT tavsiyesi vermez**, her
  olumlu noktaya ayı senaryosu ekler. `ANTHROPIC_API_KEY` yoksa açıkça belirtir.
- **Makro / Rejim (Aşama 7):** Endeksten piyasa rejimini (Boğa/Ayı/Yatay) ve
  oynaklığı **gerekçesiyle** sınıflar; izleme listesinden piyasa genişliği (breadth).
- **Otomasyon (Aşama 10):** İzleme listesini tarar, rejimi okur, `raporlar/` altına
  tarihli Markdown rapor yazar. `python -m automation.run` veya cron ile.

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
│   ├── fetcher.py         # veri çekme (retry, kalite, bayat/boşluk tespiti)
│   ├── access.py          # canlı çekme + DB önbellek yedeği (offline dayanıklılık)
│   └── storage.py         # SQLite saklama
├── analysis/
│   ├── indicators.py      # teknik göstergeler (saf pandas)
│   ├── signals.py         # sinyal + ayı senaryosu + bayraklar
│   ├── screener.py        # Aşama 1: gün sonu tarama
│   ├── historical.py      # Aşama 5: tarihsel temel oranlar + mevsimsellik
│   ├── calibration.py     # Aşama 8: kendini ölçme
│   ├── risk.py            # Aşama 9: risk yönetimi
│   ├── news.py            # Aşama 4: haber & KAP (yfinance + RSS)
│   ├── macro.py           # Aşama 7: makro / piyasa rejimi
│   └── llm.py             # Aşama 6: LLM sentez (Claude)
├── portfolio/
│   └── paper.py           # Aşama 2: paper portföy
├── backtest/
│   └── engine.py          # Aşama 3: backtest motoru
├── automation/
│   ├── scheduler.py       # Aşama 10: tara → rejim → rapor
│   └── run.py             # `python -m automation.run`
├── app/
│   └── panel.py           # Streamlit arayüz (13 sekme)
└── tests/
    ├── test_indicators.py # gösterge/sinyal testleri
    ├── test_stages.py     # Aşama 2-3-5-8-9 testleri
    ├── test_stages2.py    # Aşama 4-6-7-10 testleri
    └── test_data.py       # veri dayanıklılığı testleri (toplam 42 test)
```

## Ayarlar

Her şey `config.py`'de: izleme listesi, zaman ufukları (kısa/orta/uzun — sabit
değil), tarama eşikleri, başlangıç sermayesi. Sabit değer kodun içine gömülmez.

## Otomasyon (Aşama 10)

İzleme listesini tarayıp tarihli rapor üretmek için:

```bash
python -m automation.run        # raporlar/rapor-YYYY-AA-GG.md yazar
```

Her gün otomatik (cron, hafta içi 18:30):

```
30 18 * * 1-5  cd /yol/borsa-analiz && .venv/bin/python -m automation.run
```

## AI Sentez (Aşama 6) için anahtar

"AI Sentez" sekmesi ve `analysis/llm.py` Claude API kullanır. Etkinleştirmek için:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

Anahtar yoksa panel yine çalışır; o sekme "anahtar yok" diye açıkça belirtir
ve **asla veri uydurmaz**.

## Geliştirme notları

- Yeni aşamalar mevcut felsefeye sadıktır: her çıktı kaynağa+zamana bağlı, veri
  yoksa açıkça belirtilir, sinyaller AL/SAT hükmü vermez, her olumlu görüşe ayı
  senaryosu eşlik eder.
- Aşama 4/7/10 ek bağımlılık gerektirmez; Aşama 6 yalnızca opsiyonel `anthropic`.

## Veri dayanıklılığı (bilinen sınırlara karşı alınan önlemler)

- **Hız limiti / geçici hata:** çekme, üstel beklemeyle **3 kez** yeniden denenir
  (`config.VERI`).
- **Offline / çekme başarısız:** canlı veri alınamazsa son bilinen veri **DB
  önbelleğinden** gösterilir; kaynak `cache (DB)` ve "bayat" olarak işaretlenir.
- **Veri kalitesi:** eksik (NaN) satırlar atılır; sıfır/negatif fiyat ve negatif
  hacim uyarı üretir.
- **Temettü/bölünme/bedelsiz:** `auto_adjust=True` ile geriye dönük düzeltilir
  (meta'da `adjusted`).
- **Delisting / işlem takvimi:** son veri çok eskiyse (**bayat**) ve uzun veri
  boşluğu varsa açıkça uyarılır.

## Kalan sınırlar / riskler

- yfinance resmi olmayan bir kaynaktır; üstteki önlemlere rağmen format değişebilir.
- Tam bir borsa **işlem takvimi** entegre değildir; yalnızca boşluk/güncellik
  sezgisel olarak tespit edilir.
- Sinyaller basit kurallardır; backtest ve kalibrasyon (Aşama 3 ve 8) yapılmadan
  güvenilirliği ölçülemez.
- **Kendini kanıtlamadan gerçek parayla bağlamayın.**
