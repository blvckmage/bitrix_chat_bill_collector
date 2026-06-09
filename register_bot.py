"""Одноразовая регистрация чат-бота в Битрикс24.

Запуск:
    python register_bot.py https://<имя>.onrender.com/bitrix/webhook

После успешной регистрации скрипт напечатает BOT_ID — этого пользователя
нужно вручную добавить в групповой чат курьеров. После этого каждое
сообщение в чате будет триггерить ONIMBOTMESSAGEADD на наш URL.
"""
import sys
import httpx

from config import BITRIX_WEBHOOK_URL


def register(handler_url: str) -> None:
    url = f"{BITRIX_WEBHOOK_URL}imbot.register.json"
    payload = {
        "CODE": "delivery_bot",
        "TYPE": "B",  # B = чат-бот, может быть добавлен в групповые чаты
        "EVENT_MESSAGE_ADD": handler_url,        # сообщение боту/в чат с ботом
        "EVENT_WELCOME_MESSAGE": handler_url,    # приветствие при добавлении
        "EVENT_BOT_DELETE": handler_url,         # удаление бота
        "PROPERTIES": {
            "NAME": "Бот доставок",
            "LAST_NAME": "",
            "COLOR": "AQUA",
            "EMAIL": "delivery-bot@example.local",
            "PERSONAL_BIRTHDAY": "",
            "WORK_POSITION": "Учёт доставок",
        },
    }
    r = httpx.post(url, json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()
    print(data)
    bot_id = data.get("result")
    if bot_id:
        print(f"\n✅ Бот зарегистрирован. BOT_ID = {bot_id}")
        print("Теперь добавьте этого пользователя в групповой чат курьеров.")
    else:
        print("\n❌ Регистрация не удалась — см. ответ выше.")


def unregister(bot_id: int) -> None:
    """Удалить бота по ID (на случай повторной регистрации)."""
    url = f"{BITRIX_WEBHOOK_URL}imbot.unregister.json"
    r = httpx.post(url, json={"BOT_ID": bot_id}, timeout=15)
    print(r.json())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "--unregister":
        unregister(int(sys.argv[2]))
    else:
        register(sys.argv[1])
