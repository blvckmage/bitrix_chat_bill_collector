"""FastAPI-приложение: вебхук от Битрикс24. Дайджесты запускаются внешним кроном."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException

from config import (
    BITRIX_CHAT_IDS,
    MANAGER_USER_ID,
    SECRET_TOKEN,
)
from storage import (
    init_storage,
    init_orders_storage, add_order, mark_accepted, mark_delivered, mark_cancelled,
    update_order, clear_orders,
)
from bitrix import send_message_to_chat, get_user_name, register_chatbot
from report import send_digest_today, send_digest_tomorrow, send_report_to_chat
import auth_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("bot")

from parsing import parse_message, parse_edits, resolve_target_date
from llm import parse_message_llm


def format_delivery_summary(d: dict) -> str:
    """Сформировать многострочное описание заявки для ответа бота."""
    lines = []
    if d.get("order_number"):
        lines.append(f"🧾 Номер: №{d['order_number']}")
    if d.get("doc_date"):
        lines.append(f"📅 Дата: {d['doc_date']}")
    if d.get("address"):
        lines.append(f"📍 Адрес: {d['address']}")
    if d.get("client"):
        lines.append(f"👤 Клиент: {d['client']}")
    if d.get("phone"):
        lines.append(f"📞 Телефон: {d['phone']}")
    if d.get("desired_time"):
        lines.append(f"🕒 Время: {d['desired_time']}")
    if d.get("files"):
        files = d["files"]
        if isinstance(files, list):
            for f in files:
                lines.append(f"📎 {f}")
        elif files:
            for f in str(files).split("|"):
                if f:
                    lines.append(f"📎 {f}")
    if not lines:
        lines.append("⚠️ Деталей не нашёл — заявка создана пустой.")
    return "\n".join(lines)


import re as _re
_BBCODE_RE = _re.compile(r"\[/?[A-Za-z][^\]]*\]")


def _strip_bbcode_simple(text: str) -> str:
    return _BBCODE_RE.sub("", text or "").strip()


def extract_filenames(body: dict) -> list[str]:
    """Достаём имена прикреплённых файлов из form-данных события Битрикса.
    Файлы приходят с ключами вида data[PARAMS][FILES][N][name] или
    data[PARAMS][FILES_RAW][N][name] — берём всё, что выглядит как имя файла.
    """
    names: list[str] = []
    seen = set()
    for key, value in body.items():
        if "FILES" not in key.upper():
            continue
        # Имя может быть в полях NAME / name / fileName
        if any(s in key for s in ("[NAME]", "[name]", "[fileName]", "[FILE_NAME]")):
            if value and value not in seen:
                seen.add(value)
                names.append(value)
    return names


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл: создаём таблицы. Дайджесты — снаружи (cron-job.org)."""
    init_storage()
    init_orders_storage()
    logger.info("Бот запущен. Дайджесты ожидаются от внешнего крона на /admin/run-digest")
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def healthcheck() -> dict:
    """Healthcheck для render.com — отвечает 200 OK."""
    return {"status": "ok"}


@app.post("/bitrix/webhook")
async def bitrix_webhook(request: Request) -> dict:
    """Входящий вебхук от Битрикс24 — событие OnImBotMessageAdd / ONIMMESSAGEADD."""

    # Битрикс24 присылает application/x-www-form-urlencoded с вложенными ключами data[...]
    # Парсим и form-data, и JSON — на всякий случай.
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
    else:
        form = await request.form()
        body = dict(form)

    # Проверка секретного токена. Битрикс24 присылает поле auth[application_token] или просто token.
    received_token = (
        body.get("auth[application_token]")
        or body.get("application_token")
        or body.get("token")
    )
    if SECRET_TOKEN and received_token != SECRET_TOKEN:
        logger.warning("Неверный токен в запросе. Получено: %r, ожидалось: %r",
                       received_token, SECRET_TOKEN)
        raise HTTPException(status_code=403, detail="invalid token")

    # Имя события и полезная нагрузка
    event = body.get("event") or ""

    # OAuth-токены из события (локальное приложение)
    access_token = body.get("auth[access_token]")
    client_endpoint = body.get("auth[client_endpoint]")
    refresh_token = body.get("auth[refresh_token]")
    expires_in = body.get("auth[expires_in]") or 3600
    auth_context = None
    if access_token and client_endpoint:
        auth_context = {
            "access_token": access_token,
            "client_endpoint": client_endpoint,
        }
        # Сохраняем самые свежие токены — пригодится фоновому отчёту в 17:30
        auth_store.save({
            "access_token": access_token,
            "refresh_token": refresh_token or "",
            "client_endpoint": client_endpoint,
            "domain": body.get("auth[domain]", ""),
            "expires_in": expires_in,
        })
    logger.info("Получено событие: %s", event)

    return await handle_bot_message(body, auth_context)


async def handle_bot_message(body: dict, auth_context: dict | None) -> dict:
    """Сообщение в чате (с упоминанием бота): /отчет, заявки от зава, /готово как fallback."""
    chat_id = body.get("data[PARAMS][CHAT_ID]") or body.get("data[PARAMS][DIALOG_ID]") or ""
    message_text = body.get("data[PARAMS][MESSAGE]") or ""
    from_user_id = body.get("data[PARAMS][FROM_USER_ID]") or body.get("data[USER][ID]") or ""

    # ID родительского сообщения, если это reply (для подтверждения доставки)
    reply_to_id = (
        body.get("data[PARAMS][REPLY_ID]")
        or body.get("data[PARAMS][PARAMS][REPLY_ID]")
        or body.get("data[PARAMS][CHAT_PREV_MESSAGE_ID]")  # запасной вариант
        or ""
    )

    logger.info("BOT_MSG: chat_id=%r from=%r reply_to=%r text=%r",
                chat_id, from_user_id, reply_to_id, message_text)

    # Многочатовый фильтр: если BITRIX_CHAT_IDS пуст — принимаем все, иначе сравниваем.
    chat_id_norm = str(chat_id).lstrip("chat")
    if BITRIX_CHAT_IDS and chat_id_norm not in [str(c) for c in BITRIX_CHAT_IDS]:
        logger.info("BOT_MSG: игнор — чат %s не в списке %s", chat_id_norm, BITRIX_CHAT_IDS)
        return {"status": "ignored", "reason": "other chat"}

    text_lower = message_text.lower()

    # Команда /отчет
    if "/отчет" in text_lower or "/отчёт" in text_lower:
        await send_report_to_chat(chat_id_norm, auth_context=auth_context)
        return {"status": "ok", "result": "report sent"}

    # Reply на сообщение бота — действия:
    #   «п»     — принято (зав склад увидел/подтвердил)
    #   «д»     — доставлено
    #   «отмена» — отменено
    #   метки (Адрес: …) — редактирование
    if reply_to_id:
        user_name = await get_user_name(from_user_id) if from_user_id else "Сотрудник"
        body_text = _strip_bbcode_simple(message_text)
        cleaned = body_text.strip(" .,!?\n\t").lower()

        # Отмена
        if "отмен" in cleaned:
            cancelled = mark_cancelled(str(reply_to_id), from_user_id, user_name)
            if cancelled:
                logger.info("Заявка msg=%s отменена пользователем %s", reply_to_id, user_name)
                await send_message_to_chat(
                    chat_id_norm,
                    "❌ Заявка отменена",
                    auth_context=auth_context,
                )
                return {"status": "ok", "cancelled": True}

        # «д» — доставлено (включая авто-принятие, если не было)
        if cleaned == "д":
            delivered = mark_delivered(str(reply_to_id), from_user_id, user_name)
            if delivered:
                logger.info("Доставка msg=%s подтверждена пользователем %s", reply_to_id, user_name)
                summary = format_delivery_summary(delivered[0]) or "—"
                await send_message_to_chat(
                    chat_id_norm,
                    f"✅ Доставлено\n{summary}",
                    auth_context=auth_context,
                )
                return {"status": "ok", "delivered": True}
            return {"status": "ok", "result": "already finalized"}

        # «п» — принято
        if cleaned == "п":
            accepted = mark_accepted(str(reply_to_id), from_user_id, user_name)
            if accepted:
                logger.info("Заявка msg=%s принята пользователем %s", reply_to_id, user_name)
                await send_message_to_chat(
                    chat_id_norm,
                    "📥 Принято в работу",
                    auth_context=auth_context,
                )
                return {"status": "ok", "accepted": True}
            return {"status": "ok", "result": "already accepted/finalized"}

        # Редактирование полей
        updates = parse_edits(message_text)
        if updates:
            updated = update_order(str(reply_to_id), updates)
            if updated:
                logger.info("Заявка msg=%s обновлена: %s", reply_to_id, updates)
                await send_message_to_chat(
                    chat_id_norm,
                    f"✏️ Заявка обновлена\n{format_delivery_summary(updated)}",
                    auth_context=auth_context,
                )
                return {"status": "ok", "updated": updates}

        logger.info("Reply на msg=%s не распознан как действие (text=%r)", reply_to_id, body_text)

    # Команды без слэша
    clean = _strip_bbcode_simple(message_text).lower().strip(" ./!?")
    if clean in {"отчет", "отчёт"}:
        await send_report_to_chat(chat_id_norm, auth_context=auth_context)
        return {"status": "ok", "result": "report sent"}
    if clean in {"очистить все", "очистить всё", "очистка"}:
        count = clear_orders()
        await send_message_to_chat(
            chat_id_norm,
            f"🗑 Архивирована и очищена база заявок. Удалено записей: {count}.",
            auth_context=auth_context,
        )
        return {"status": "ok", "cleared": count}

    # Любое сообщение, адресованное боту → новая заявка.
    # Достаём имена файлов, пробуем LLM-парсер; если он недоступен — regex-fallback.
    filenames = extract_filenames(body)
    parsed = await parse_message_llm(message_text, filenames)
    if parsed is None:
        parsed = parse_message(message_text, filenames)
    logger.info("Парсинг заявки: %s", parsed)

    author_name = await get_user_name(from_user_id) if from_user_id else "Сотрудник"
    summary = format_delivery_summary(parsed)

    resp = await send_message_to_chat(
        chat_id_norm,
        "📦 Заявка зафиксирована:\n"
        f"{summary}\n\n"
        "Ответьте на это сообщение:\n"
        "  «п» — принято в работу\n"
        "  «д» — доставлено\n"
        "  «отмена» — отменить",
        auth_context=auth_context,
    )
    bot_msg_id = str(resp.get("result") or "")
    if not bot_msg_id:
        logger.error("Не удалось получить message_id ответа бота: %s", resp)
        return {"status": "error", "reason": "no bot message id"}

    add_order(
        order_number=parsed["order_number"],
        doc_date=parsed["doc_date"],
        address=parsed["address"],
        client=parsed["client"],
        phone=parsed["phone"],
        desired_time=parsed["desired_time"],
        target_date=resolve_target_date(parsed["desired_time"]),
        files="|".join(parsed["files"]) if parsed["files"] else "",
        raw_text=message_text,
        chat_id=str(chat_id).lstrip("chat"),
        message_id=bot_msg_id,
        author_id=str(from_user_id),
        author_name=author_name,
    )
    logger.info("Заявка сохранена (msg=%s)", bot_msg_id)
    return {"status": "ok", "saved": parsed, "bot_message_id": bot_msg_id}


@app.post("/bitrix/install")
@app.get("/bitrix/install")
async def bitrix_install(request: Request):
    """Обработчик установки локального приложения.
    Битрикс POSTит сюда OAuth-токены при первой установке. Мы их сохраняем
    и сразу же регистрируем чат-бота через imbot.register.
    """
    from fastapi.responses import HTMLResponse

    if request.method == "POST":
        form = await request.form()
        data = dict(form)
    else:
        data = dict(request.query_params)

    logger.info("Получен запрос на установку. Ключи: %s", list(data.keys()))

    # Битрикс при установке локального приложения присылает:
    # AUTH_ID (access_token), REFRESH_ID (refresh_token), AUTH_EXPIRES, DOMAIN, member_id и т.д.
    access_token = data.get("AUTH_ID") or data.get("auth[access_token]")
    refresh_token = data.get("REFRESH_ID") or data.get("auth[refresh_token]") or ""
    domain = data.get("DOMAIN") or data.get("auth[domain]") or ""
    expires_in = data.get("AUTH_EXPIRES") or data.get("auth[expires_in]") or 3600
    client_endpoint = data.get("auth[client_endpoint]") or (f"https://{domain}/rest/" if domain else "")

    if not access_token or not client_endpoint:
        logger.warning("В запросе установки нет токенов — ничего не делаем.")
        return HTMLResponse("<h2>Не получены токены, проверьте настройки приложения.</h2>",
                            status_code=400)

    auth_store.save({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "client_endpoint": client_endpoint,
        "domain": domain,
        "expires_in": expires_in,
    })
    logger.info("OAuth-токены сохранены (domain=%s)", domain)

    # Зарегистрировать чат-бота
    handler_url = str(request.url_for("bitrix_webhook"))
    try:
        bot_id = await register_chatbot(
            {"access_token": access_token, "client_endpoint": client_endpoint},
            handler_url,
        )
        logger.info("imbot.register результат: BOT_ID=%s", bot_id)
        msg = (
            f"<h2>Установка завершена ✅</h2>"
            f"<p>BOT_ID: <b>{bot_id}</b></p>"
            f"<p>Запишите BOT_ID в <code>BITRIX_BOT_ID</code> и перезапустите сервис.</p>"
        )
    except Exception as e:
        logger.exception("Не удалось зарегистрировать бота")
        msg = f"<h2>OAuth сохранён, но imbot.register упал</h2><pre>{e}</pre>"

    return HTMLResponse(msg)


@app.api_route("/admin/run-digest", methods=["GET", "POST"])
async def admin_run_digest(token: str, kind: str = "today") -> dict:
    """Запуск дайджеста (внешним кроном или вручную).
    Поддерживает и GET, и POST для удобства cron-job.org.
    kind=today — на сегодня, kind=tomorrow — на завтра."""
    if not SECRET_TOKEN or token != SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="invalid token")
    if kind == "tomorrow":
        result = await send_digest_tomorrow()
    else:
        result = await send_digest_today()
    return {"status": "ok", **result}
