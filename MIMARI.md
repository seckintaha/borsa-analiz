# Mimari & Tasarım Notları

Bu belge projenin **nasıl** çalıştığını ve **neden** böyle tasarlandığını
anlatır. Kod okumadan önce buradan başlayın.

---

## 1. Felsefe (her modülün uyduğu kurallar)

Bu bir karar **destek** aracıdır, kâhin değildir. Tüm kod şu ilkelere uyar:

1. **Veri uydurma yok.** Her sonuç bir kaynağa + zaman damgasına bağlıdır. Veri
   yoksa/eksikse açıkça belirtilir (`ok=False` + açıklama), boşluk doldurulmaz.
2. **AL/SAT hükmü yok.** Sistem göstergelerin durumunu tarif eder; karar vermez.
3. **Ayı senaryosu zorunlu.** Her olumlu göstergeye "neden ters gidebilir"
   eşlik eder.
4. **Dürüst belirsizlik.** Az örnek (düşük `n`), bayat veri, düşük güven açıkça
   işaretlenir. Geriye dönük test/kalibrasyon yapılmadan güvenilirlik iddia edilmez.
5. **Hiçbir çıktı lisanslı yatırım tavsiyesi değildir.**

> **Öneri sekmesi (Aşama 11) hakkında:** Kullanıcı isteğiyle, doğrudan "AL adayı"
> sıralaması veren bir katman eklendi. Bu, felsefeyi **bozmaz**, uygular: öneri
> doğrudandır ama **şeffaftır** — her skor açıklanabilir (sinyal + rejim +
> bayraklar), her adayın **ayı senaryosu ve güven düzeyi** gösterilir ve
> "lisanslı danışmanlık değildir" notu korunur. Gerekçesiz "al" yoktur.

---

## 2. Katmanlar (veri nasıl akar)

```
        Kullanıcı (Streamlit panel / CLI)
                    │
   ┌────────────────┼─────────────────────────────┐
   │                │                              │
 app/panel.py   automation/run.py            demo.py (offline)
   │                │
   └──────┬─────────┘
          ▼
   ANALİZ KATMANI  (analysis/, portfolio/, backtest/)
   indicators · signals · screener · historical · calibration
   risk · macro · news · llm
          │
          ▼
   VERİ ERİŞİM KATMANI
   data/access.py   ──►  canlı çekme + DB önbellek yedeği
        │      │
        ▼      ▼
   data/fetcher.py   data/storage.py
   (yfinance, retry,  (SQLite: fiyat, portföy,
    kalite, bayat)     tahmin, watchlist)
```

**Altın kural:** Analiz katmanı saf hesaptır (çoğu `canlı veri gerektirmez`),
veri katmanı I/O'yu yönetir. Bu ayrım sayesinde testler internet olmadan çalışır.

---

## 3. Modül modül (aşama eşlemesi)

| Dosya | Aşama | Görevi |
|---|---|---|
| `data/fetcher.py` | 0 | yfinance ile OHLCV; retry/backoff, kalite temizliği, bayat/boşluk tespiti, `auto_adjust` (temettü/bölünme) |
| `data/access.py` | 0 | Canlı çekme + başarısızsa DB önbellek yedeği (offline dayanıklılık) |
| `data/storage.py` | 0 | SQLite: `prices`, `portfolio_islemler`, `kalibrasyon_tahminler`, `watchlist`, `events` |
| `analysis/indicators.py` | 0 | RSI, MACD, SMA20/50/200, Bollinger (saf pandas) |
| `analysis/signals.py` | 0 | Dengeli özet + ayı senaryosu + manipülasyon/ince hacim bayrağı |
| `analysis/screener.py` | 1 | Gün sonu tarama — öne çıkanları **gerekçesiyle** listeler |
| `portfolio/paper.py` | 2 | Sanal portföy; komisyon+kayma dahil P&L |
| `backtest/engine.py` | 3 | Strateji vs benchmark, out-of-sample, Sharpe/max düşüş |
| `analysis/news.py` | 4 | Haber & KAP: yfinance hisse haberi + stdlib RSS (güvenli) |
| `analysis/historical.py` | 5 | "Geçmişte böyle olunca ne oldu" — medyan/aralık/n |
| `analysis/llm.py` | 6 | Claude ile dengeli özet; yeni veri uydurmaz, tavsiye vermez |
| `analysis/macro.py` | 7 | Piyasa rejimi (Boğa/Ayı/Yatay) + oynaklık + breadth |
| `analysis/calibration.py` | 8 | Tahminleri gerçeğe karşı puanlar (yazı-tura kıyası) |
| `analysis/risk.py` | 9 | Pozisyon büyüklüğü, yoğunlaşma, stop-loss, korelasyon |
| `automation/scheduler.py` | 10 | Tara → rejim oku → tarihli Markdown rapor |
| `analysis/recommender.py` | 11 | Şeffaf skorlama + sıralama (AL adayları) + AI/yerel yorum |
| `automation/notify.py` | 12 | Telegram bot — borsa günü günlük özet (veri-temelli takvim) |
| `app/panel.py` | — | 14 sekmeli Streamlit arayüzü |

Tüm sabitler `config.py`'de — kodun içine gömülü değer yoktur.

---

## 4. Veri dayanıklılığı (bilinen sınırlara karşı)

`config.VERI` ile ayarlanır:

- **Retry:** geçici hata/hız limitinde üstel beklemeyle 3 deneme.
- **Kalite:** NaN satır atılır; sıfır/negatif fiyat, negatif hacim uyarır.
- **Bayat veri:** son veri çok eskiyse işaretlenir (delisting/tatil sezgisi).
- **Boşluk:** uzun ardışık veri boşluğu uyarılır.
- **Offline yedek:** canlı veri yoksa `data/access.py` son kaydı DB'den gösterir
  (`kaynak = cache (DB)`, `bayat = True`).
- **BIST düzeltmeleri:** `auto_adjust=True` temettü/bölünme/bedelsiz'i düzeltir.

---

## 5. Güvenlik

- **RSS/haber:** yalnızca `http`/`https` (file://, ftp:// engelli — SSRF/yerel
  dosya); indirme 3 MB ile sınırlı (bellek DoS); XML `defusedxml` varsa
  entity-bomb/XXE'ye karşı güvenli ayrıştırılır.
- **Panel linkleri:** yalnızca http/https tıklanabilir (javascript:/data: enjeksiyonu engeli).
- **LLM:** bağlam "veri, talimat değil" olarak çerçevelenir (prompt-injection savunması).
- **SQLite:** tüm sorgular parametreli — SQL enjeksiyonuna kapalı.
- **Sırlar:** `.env`, `*.key`, `secrets.toml`, `*.db` git'e girmez (`.gitignore`).
  API anahtarı yalnızca ortam değişkeninden okunur, asla loglanmaz/commit'lenmez.

---

## 6. Yeni aşama/özellik nasıl eklenir

1. Mantığı `analysis/` (ya da uygun paket) altında **saf, test edilebilir**
   bir modül olarak yaz; felsefe kurallarına uy (kaynak+zaman, ayı senaryosu, dürüst `n`).
2. Sabitleri `config.py`'ye ekle.
3. `tests/` altında **offline** test yaz (ağ/anahtar gerektirmeyen).
4. `app/panel.py`'ye sekme olarak bağla; veri yoksa/anahtar yoksa net mesaj göster.
5. `demo.py`'ye offline bir gösterim ekle.
6. README + bu belgeyi güncelle.

---

## 7. Test & çalıştırma

```bash
pytest -q                      # 47 test, internet gerektirmez
python demo.py                 # tüm modüllerin offline gösterimi
streamlit run app/panel.py     # panel
python -m automation.run       # gün sonu tarama + rapor
```

---

## 8. Kalan sınırlar (dürüstçe)

- yfinance resmi olmayan bir kaynaktır; önlemlere rağmen format değişebilir.
- Tam bir borsa **işlem takvimi** entegre değildir; boşluk/güncellik sezgiseldir.
- Sinyaller basit kurallardır; backtest (Aşama 3) ve kalibrasyon (Aşama 8)
  yapılmadan güvenilirliği ölçülemez.
- **Kendini kanıtlamadan gerçek parayla bağlamayın.**
