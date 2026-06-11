"""Конфигурация приложения — читаем переменные окружения."""
import os
from dotenv import load_dotenv

load_dotenv()

# URL исходящего вебхука Битрикс24 для отправки сообщений (например: https://your.bitrix24.ru/rest/1/abc123xyz/)
BITRIX_WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL", "").rstrip("/") + "/"

# ID групповых чатов, в которых работает бот. Поддерживаем:
#   - BITRIX_CHAT_IDS=50917,12345,67890   (новая, список через запятую)
#   - BITRIX_CHAT_ID=50917                (старая, один ID)
# Если оба не заданы — бот реагирует на любые чаты, где он участник.
_raw_chat_ids = os.getenv("BITRIX_CHAT_IDS") or os.getenv("BITRIX_CHAT_ID") or ""
BITRIX_CHAT_IDS: list[str] = [s.strip() for s in _raw_chat_ids.split(",") if s.strip()]
# Совместимость со старым кодом — первый ID
BITRIX_CHAT_ID = BITRIX_CHAT_IDS[0] if BITRIX_CHAT_IDS else ""

# ID пользователя — заведующего складом
MANAGER_USER_ID = os.getenv("MANAGER_USER_ID", "")

# ID зарегистрированного чат-бота (заполняется автоматически после установки приложения)
BITRIX_BOT_ID = os.getenv("BITRIX_BOT_ID", "")

# OAuth credentials локального приложения Битрикс24
BITRIX_CLIENT_ID = os.getenv("BITRIX_CLIENT_ID", "")
BITRIX_CLIENT_SECRET = os.getenv("BITRIX_CLIENT_SECRET", "")

# Куда сохраняем актуальные OAuth-токены (access_token, refresh_token)
AUTH_STORE_PATH = os.getenv("AUTH_STORE_PATH", "./auth.json")

# OpenAI — для умного парсера заявок (LLM)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Секретный токен — Битрикс24 присылает его вместе с событием, проверяем подлинность запроса
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "")

# Путь к CSV-файлу с записями о доставках (старый поток /готово)
CSV_PATH = os.getenv("CSV_PATH", "./deliveries.csv")

# Путь к CSV-файлу с заявками (новый поток: зав склада → реакция курьера)
ORDERS_CSV_PATH = os.getenv("ORDERS_CSV_PATH", "./orders.csv")

# Часовой пояс Астаны
TIMEZONE = "Asia/Almaty"  # UTC+5, эквивалент Астаны

# Время ежедневного отчёта
REPORT_HOUR = 17
REPORT_MINUTE = 30
