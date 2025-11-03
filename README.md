# Telegram Score Bot (Paul/Roman)

Считает очки по сообщениям учителя в групповом чате. Поддерживает алиасы имён:
- Paul / Pavlo → Paul
- Roman / Roma → Roman

Формат: `Имя +ЧИСЛО` или `Имя -ЧИСЛО`, в одном сообщении можно несколько строк.

Команды:
- `/score` — показать текущий счёт
- `/clear` — сбросить счёт
- `/start` — подсказка

## Быстрый старт (Render)

1. Создайте бота у BotFather, получите `BOT_TOKEN`.
2. В BotFather отключите Privacy Mode: `/setprivacy` → `Disable`.
3. Залейте эти файлы в новый GitHub репозиторий.
4. На https://dashboard.render.com → New → **Web Service** → подключите репозиторий.
5. **Build Command:** `pip install -r requirements.txt`
6. **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
7. **Environment Variables:** добавьте `BOT_TOKEN=<ваш токен>`
8. Дождитесь деплоя. Возьмите публичный Render URL (например, `https://your-app.onrender.com`).
9. В браузере откройте `https://your-app.onrender.com/set_webhook`
   - Если Render не подставил URL, можно вручную:  
     `https://your-app.onrender.com/set_webhook?url=https://your-app.onrender.com`
10. Добавьте бота в ваш групповой чат.

## UptimeRobot

Добавьте монитор типа `HTTPS` на `https://your-app.onrender.com/healthz` с интервалом 5 минут — чтобы бесплатный Render не «засыпал».

## Проверка

Напишите в группе:
