"""Конфигурация приложения — читаем переменные окружения."""
import os
from dotenv import load_dotenv

load_dotenv()

# URL исходящего вебхука Битрикс24 для отправки сообщений (например: https://your.bitrix24.ru/rest/1/abc123xyz/)
BITRIX_WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL", "").rstrip("/") + "/"

# ID группового чата курьеров, который слушаем
BITRIX_CHAT_ID = os.getenv("BITRIX_CHAT_ID", "")

# ID пользователя — заведующего складом
MANAGER_USER_ID = os.getenv("MANAGER_USER_ID", "")

# ID зарегистрированного чат-бота (заполняется автоматически после установки приложения)
BITRIX_BOT_ID = os.getenv("BITRIX_BOT_ID", "")

# OAuth credentials локального приложения Битрикс24
BITRIX_CLIENT_ID = os.getenv("BITRIX_CLIENT_ID", "")
BITRIX_CLIENT_SECRET = os.getenv("BITRIX_CLIENT_SECRET", "")

# Куда сохраняем актуальные OAuth-токены (access_token, refresh_token)
AUTH_STORE_PATH = os.getenv("AUTH_STORE_PATH", "./auth.json")

# Секретный токен — Битрикс24 присылает его вместе с событием, проверяем подлинность запроса
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "")

# Путь к CSV-файлу с записями о доставках
CSV_PATH = os.getenv("CSV_PATH", "./deliveries.csv")

# Часовой пояс Астаны
TIMEZONE = "Asia/Almaty"  # UTC+5, эквивалент Астаны

# Время ежедневного отчёта
REPORT_HOUR = 17
REPORT_MINUTE = 30
