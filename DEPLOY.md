# 7/24 Bulut Kurulumu (bot Mac kapalıyken de çalışsın)

Bot şu an Mac'te çalışıyor → Mac kapalıysa bildirim gelmez. Bulutta çalıştırınca
bilgisayardan bağımsız, hep açık olur. Kod bulut için hazır (`Dockerfile`).

## Önce: gerekli 3 secret (asla repoya yazma)
Platform panelinde **Environment Variables** olarak gireceksin:
- `TELEGRAM_BOT_TOKEN` — @BotFather'dan
- `TELEGRAM_CHAT_ID` — senin kişisel chat id'in
- `TELEGRAM_KANAL_ID` — kanal id'in (opsiyonel)

## ⚠️ İki önemli nokta
1. **Zaman dilimi:** Dockerfile `TZ=Europe/Istanbul` ile ayarlı → 10:00/18:00
   bildirimleri Türkiye saatiyle çalışır. (Ayarlanmazsa UTC olur, 3 saat kayar.)
2. **Kalıcı veri:** `borsa.db` (portföyün + öneri takibi) container yeniden
   başlayınca SİLİNMESİN diye **volume** bağla (aşağıda). Bağlamazsan her
   redeploy'da portföyün sıfırlanır.

---

## Seçenek A — Railway (en kolay, önerilen)
1. https://railway.app → GitHub ile giriş
2. **New Project → Deploy from GitHub repo** → `seckintaha/borsa-analiz`
3. Railway `Dockerfile`'ı otomatik bulur ve derler.
4. **Variables** sekmesi → yukarıdaki 3 secret'ı ekle.
5. **Volumes** → yeni volume, mount path: `/app` (borsa.db kalıcı olur).
6. Deploy. Loglarda "Bot başladı" görünce hazır.

Maliyet: aylık ~5$ kredi (küçük bot için genelde yeterli/ucuz).

## Seçenek B — Oracle Cloud (kalıcı ÜCRETSİZ, biraz daha teknik)
1. Oracle Cloud hesabı aç → "Always Free" ARM VM (VM.Standard.A1) oluştur.
2. VM'e SSH ile bağlan, Docker kur.
3. Repoyu çek: `git clone https://github.com/seckintaha/borsa-analiz.git`
4. `.env` dosyasını VM'de oluştur (3 secret) — repoya girmez.
5. Çalıştır:
   ```
   docker build -t borsabot .
   docker run -d --restart=always --env-file .env \
     -v $(pwd)/data:/app/data borsabot
   ```
Maliyet: 0₺ (kalıcı ücretsiz katman).

## Seçenek C — Fly.io
`fly launch` → Dockerfile'ı algılar → `fly secrets set TELEGRAM_BOT_TOKEN=...`
→ volume ekle → `fly deploy`.

---

## Deploy sonrası
- Mac'teki botu durdurabilirsin (çift bot Telegram'da çakışır — **aynı anda
  ikisi çalışmasın**; getUpdates çakışır). Bulut açılınca Mac'teki `pkill -f automation.bot`.
- Bildirimler bulut sunucusundan gelir; bilgisayar kapalı olsa da çalışır.
- Komutların (`/portfoyum`, `/oneriler`, `/performans`) her an cevap verir.

> Not: Panel (Streamlit) buluta dahil edilmedi — Telegram öncelikli kullanımda
> gerek yok. İstersen ayrıca Streamlit Cloud'a koyulabilir.
