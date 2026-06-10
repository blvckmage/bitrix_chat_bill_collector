"""Клиент REST API Битрикс24.

Два режима работы:
1. Через входящий вебхук (BITRIX_WEBHOOK_URL) — от имени владельца вебхука.
2. Через OAuth-токен бота (auth_context из события) — от имени бота.
"""
import httpx

from config import BITRIX_WEBHOOK_URL, BITRIX_BOT_ID


async def call_method(method: str, payload: dict) -> dict:
    """Вызов метода через входящий вебхук (от имени владельца вебхука)."""
    url = f"{BITRIX_WEBHOOK_URL}{method}.json"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


async def call_method_as_bot(method: str, payload: dict, auth_context: dict) -> dict:
    """Вызов метода REST с OAuth-токеном бота (для отправки от имени бота).

    auth_context должен содержать ключи: 'access_token' и 'client_endpoint'.
    """
    client_endpoint = auth_context["client_endpoint"].rstrip("/") + "/"
    url = f"{client_endpoint}{method}.json"
    body = {**payload, "auth": auth_context["access_token"]}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=body)
        response.raise_for_status()
        return response.json()


async def send_message_to_chat(
    chat_id: str | int,
    text: str,
    auth_context: dict | None = None,  # пока не используется (см. примечание в README)
) -> dict:
    """Отправить сообщение в групповой чат от имени владельца вебхука."""
    dialog_id = f"chat{chat_id}" if str(chat_id).isdigit() else str(chat_id)
    return await call_method("im.message.add", {"DIALOG_ID": dialog_id, "MESSAGE": text})


async def send_message_to_user(
    user_id: str | int,
    text: str,
    auth_context: dict | None = None,
) -> dict:
    """Отправить личное сообщение пользователю от имени владельца вебхука."""
    return await call_method("im.message.add", {"DIALOG_ID": str(user_id), "MESSAGE": text})


async def get_user_name(user_id: str | int) -> str:
    """Получить ФИО пользователя по ID."""
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
