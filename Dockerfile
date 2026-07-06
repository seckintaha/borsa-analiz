# Telegram botunu 7/24 bulutta çalıştırmak için hafif imaj.
# Panel (streamlit) DAHİL DEĞİL — sadece bot + analiz motoru.
FROM python:3.11-slim

# Bot içi zamanlayıcı yerel saate göre çalışır (hafta içi 10:00/18:00, ayın 1'i).
# Bulut sunucusu genelde UTC'dir; Türkiye saatine sabitle.
ENV TZ=Europe/Istanbul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

COPY requirements-bot.txt .
RUN pip install --no-cache-dir -r requirements-bot.txt

COPY . .

# borsa.db ve raporlar/ için kalıcı volume önerilir (aşağıdaki DEPLOY.md'ye bak).
# Secrets (TELEGRAM_BOT_TOKEN vb.) imaja GÖMÜLMEZ — platform env değişkeni olarak verilir.
CMD ["python", "-m", "automation.bot"]
