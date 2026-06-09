"""Тонкий клиент над REST API Битрикс24 (через исходящий вебхук)."""
import httpx

from config import BITRIX_WEBHOOK_URL


async def call_method(method: str, payload: dict) -> dict:
    """Вызвать произвольный метод REST API Битрикс24."""
    url = f"{BITRIX_WEBHOOK_URL}{method}.json"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


async def send_message_to_chat(chat_id: str | int, text: str) -> dict:
    """Отправить сообщение в групповой чат по его ID."""
    # Метод im.message.add принимает DIALOG_ID — для группового чата это 'chatNNN'
    dialog_id = f"chat{chat_id}" if str(chat_id).isdigit() else str(chat_id)
    return await call_method("im.message.add", {"DIALOG_ID": dialog_id, "MESSAGE": text})


async def send_message_to_user(user_id: str | int, text: str) -> dict:
    """Отправить личное сообщение пользователю по его ID."""
    return await call_method("im.message.add", {"DIALOG_ID": str(user_id), "MESSAGE": text})


async def get_user_name(user_id: str | int) -> str:
    """Получить ФИО пользователя по ID. Возвращает строку 'Имя Фамилия'."""
    try:
        data = await call_method("user.get", {"ID": str(user_id)})
        result = data.get("result") or []
        if result:
            u = result[0]
            name = " ".join(filter(None, [u.get("NAME"), u.get("LAST_NAME")])).strip()
            return name or u.get("EMAIL") or f"User#{user_id}"
    except Exception:
        pass
    return f"User#{user_id}"
