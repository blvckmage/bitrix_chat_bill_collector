"""FastAPI-приложение: вебхук от Битрикс24 + планировщик ежедневного отчёта."""
import re
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    BITRIX_CHAT_ID,
    SECRET_TOKEN,
    TIMEZONE,
    REPORT_HOUR,
    REPORT_MINUTE,
)
from storage import init_storage, add_delivery
from bitrix import send_message_to_chat, get_user_name, register_chatbot
from report import build_and_send_report, send_report_to_chat
import auth_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("bot")

# Регулярка: команда /готово, опционально слово "Накладная", символ № и сам номер.
# Номер обязателен — без него совпадения нет, и бот попросит уточнить.
INVOICE_RE = re.compile(
    r"/готово\s+(?:накладн\w*\s*)?№?\s*([A-Za-zА-Яа-я0-9\-_/]+)",
    re.IGNORECASE,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл: создаём таблицы и запускаем планировщик."""
    init_storage()
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        build_and_send_report,
        CronTrigger(hour=REPORT_HOUR, minute=REPORT_MINUTE, timezone=TIMEZONE),
        id="daily_report",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Планировщик запущен — отчёт каждый день в %02d:%02d (%s)",
                REPORT_HOUR, REPORT_MINUTE, TIMEZONE)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


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
    # Поля сообщения приходят с префиксом data[PARAMS][...] или data[FIELDS_AFTER][...].
    # Извлекаем стандартные поля события ONIMMESSAGEADD / OnImBotMessageAdd.
    chat_id = (
        body.get("data[PARAMS][CHAT_ID]")
        or body.get("data[PARAMS][DIALOG_ID]")
        or ""
    )
    message_text = body.get("data[PARAMS][MESSAGE]") or body.get("data[PARAMS][MESSAGE_TEXT]") or ""
    from_user_id = body.get("data[PARAMS][FROM_USER_ID]") or body.get("data[USER][ID]") or ""

    # Если событие на иной чат — игнорируем
    if BITRIX_CHAT_ID and str(chat_id).lstrip("chat") not in (str(BITRIX_CHAT_ID), f"chat{BITRIX_CHAT_ID}"):
        return {"status": "ignored", "reason": "other chat"}

    text_lower = message_text.lower()

    # Команда /отчет — отправить сводный отчёт прямо в чат
    if "/отчет" in text_lower or "/отчёт" in text_lower:
        logger.info("Запрошен отчёт пользователем %s", from_user_id)
        await send_report_to_chat(BITRIX_CHAT_ID, auth_context=auth_context)
        return {"status": "ok", "result": "report sent"}

    # Реагируем только на /готово
    if "/готово" not in text_lower:
        return {"status": "ignored", "reason": "not a command"}

    logger.info("Получена команда от user=%s: %s", from_user_id, message_text)

    match = INVOICE_RE.search(message_text)
    invoice = match.group(1).strip() if match else None

    if not invoice:
        await send_message_to_chat(
            BITRIX_CHAT_ID,
            "⚠️ Пожалуйста, укажите номер накладной. Пример: /готово Накладная №1234",
            auth_context=auth_context,
        )
        return {"status": "ok", "result": "asked for invoice"}

    courier_name = await get_user_name(from_user_id) if from_user_id else "Неизвестный"

    add_delivery(
        invoice_number=invoice,
        courier_name=courier_name,
        courier_id=str(from_user_id) if from_user_id else None,
    )

    logger.info("Сохранена доставка: №%s — %s", invoice, courier_name)

    # Подтверждение в чат от имени бота
    await send_message_to_chat(
        BITRIX_CHAT_ID,
        f"✅ Сохранил доставку №{invoice} — {courier_name}",
        auth_context=auth_context,
    )
    return {"status": "ok", "saved": {"invoice": invoice, "courier": courier_name}}


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
        msg = f"<h2>Установка завершена ✅</h2><p>BOT_ID: <b>{bot_id}</b></p>" \
              f"<p>Запишите BOT_ID в переменную окружения <code>BITRIX_BOT_ID</code> и перезапустите сервис.</p>"
    except Exception as e:
        logger.exception("Не удалось зарегистрировать бота")
        msg = f"<h2>OAuth сохранён, но imbot.register упал</h2><pre>{e}</pre>"

    return HTMLResponse(msg)


@app.post("/admin/run-report")
async def admin_run_report(token: str) -> dict:
    """Ручной запуск отчёта — удобно для проверки после деплоя.
    Вызывать: POST /admin/run-report?token=SECRET_TOKEN"""
    if not SECRET_TOKEN or token != SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="invalid token")
    await build_and_send_report()
    return {"status": "ok"}
