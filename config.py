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

# Секретный токен — Битрикс24 присылает его вместе с событием, проверяем подлинность запроса
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "")

# Путь к CSV-файлу с записями о доставках
CSV_PATH = os.getenv("CSV_PATH", "./deliveries.csv")

# Часовой пояс Астаны
TIMEZONE = "Asia/Almaty"  # UTC+5, эквивалент Астаны

# Время ежедневного отчёта
REPORT_HOUR = 18
REPORT_MINUTE = 0
