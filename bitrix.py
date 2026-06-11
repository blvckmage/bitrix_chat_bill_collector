"""Клиент REST API Битрикс24 (через OAuth-токен локального приложения)."""
import httpx

from config import BITRIX_WEBHOOK_URL, BITRIX_BOT_ID
import auth_store


async def call_method(method: str, payload: dict) -> dict:
    """Вызов метода через входящий вебхук (от имени владельца вебхука).
    Используется как fallback, если OAuth-токенов ещё нет.
    """
    url = f"{BITRIX_WEBHOOK_URL}{method}.json"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


async def call_method_as_bot(method: str, payload: dict, auth_context: dict | None = None) -> dict:
    """Вызов метода с OAuth-токеном (от имени бота / приложения).

    auth_context (опционально) — словарь с 'access_token' и 'client_endpoint'.
    Если не задан — берётся из auth_store (для фоновых задач), с автообновлением.
    """
    if auth_context is None:
        auth_context = await auth_store.refresh_if_needed()
        if not auth_context:
            raise RuntimeError("OAuth-токены ещё не получены — установите приложение в Битрикс24")

    import logging
    log = logging.getLogger("bot")
    client_endpoint = auth_context["client_endpoint"].rstrip("/") + "/"
    url = f"{client_endpoint}{method}.json"
    body = {**payload, "auth": auth_context["access_token"]}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=body)
        if response.status_code >= 400:
            log.error("Битрикс %s вернул %s: %s | payload=%s",
                      method, response.status_code, response.text,
                      {k: v for k, v in body.items() if k != "auth"})
        response.raise_for_status()
        return response.json()


async def send_message_to_chat(
    chat_id: str | int,
    text: str,
    auth_context: dict | None = None,
) -> dict:
    """Отправить сообщение в групповой чат от имени бота.
    Возвращает ответ Битрикса целиком — в поле 'result' будет message_id."""
    dialog_id = f"chat{chat_id}" if str(chat_id).isdigit() else str(chat_id)
    if BITRIX_BOT_ID:
        return await call_method_as_bot("imbot.message.add", {
            "BOT_ID": BITRIX_BOT_ID,
            "DIALOG_ID": dialog_id,
            "MESSAGE": text,
        }, auth_context)
    return await call_method("im.message.add", {"DIALOG_ID": dialog_id, "MESSAGE": text})


async def send_message_to_user(
    user_id: str | int,
    text: str,
    auth_context: dict | None = None,
) -> dict:
    """Личное сообщение пользователю от имени бота."""
    if BITRIX_BOT_ID:
        return await call_method_as_bot("imbot.message.add", {
            "BOT_ID": BITRIX_BOT_ID,
            "DIALOG_ID": str(user_id),
            "MESSAGE": text,
        }, auth_context)
    return await call_method("im.message.add", {"DIALOG_ID": str(user_id), "MESSAGE": text})


async def get_user_name(user_id: str | int) -> str:
    """ФИО пользователя по ID — через входящий вебхук (не требует OAuth)."""
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


async def bind_event(auth_context: dict, event_name: str, handler_url: str) -> dict:
    """Подписать приложение на общее событие через event.bind."""
    client_endpoint = auth_context["client_endpoint"].rstrip("/") + "/"
    url = f"{client_endpoint}event.bind.json"
    body = {
        "event": event_name,
        "handler": handler_url,
        "auth": auth_context["access_token"],
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json=body)
        return r.json()


async def register_chatbot(auth_context: dict, handler_url: str) -> int | None:
    """Зарегистрировать чат-бота через imbot.register, используя OAuth-контекст.
    Возвращает BOT_ID или None при неудаче."""
    client_endpoint = auth_context["client_endpoint"].rstrip("/") + "/"
    url = f"{client_endpoint}imbot.register.json"
    body = {
        "CODE": "delivery_bot",
        "TYPE": "B",
        "EVENT_MESSAGE_ADD": handler_url,
        "EVENT_WELCOME_MESSAGE": handler_url,
        "EVENT_BOT_DELETE": handler_url,
        "EVENT_MESSAGE_LIKE": handler_url,   # реакции на сообщения бота
        "PROPERTIES": {
            "NAME": "Бот доставок",
            "COLOR": "AQUA",
            "WORK_POSITION": "Учёт доставок",
        },
        "auth": auth_context["access_token"],
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json=body)
        data = r.json()
    return data.get("result")
