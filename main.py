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
from bitrix import send_message_to_chat, get_user_name
from report import build_and_send_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("bot")

# Регулярка: команда /готово, опционально слово "Накладная", символ № и сам номер
INVOICE_RE = re.compile(
    r"/готово\b[\s\S]*?(?:накладн\w*)?\s*№?\s*([A-Za-zА-Яа-я0-9\-_/]+)?",
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
        logger.warning("Неверный токен в запросе")
        raise HTTPException(status_code=403, detail="invalid token")

    # Имя события и полезная нагрузка
    event = body.get("event") or ""
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

    # Реагируем только на /готово
    if "/готово" not in message_text.lower():
        return {"status": "ignored", "reason": "not a command"}

    logger.info("Получена команда от user=%s: %s", from_user_id, message_text)

    match = INVOICE_RE.search(message_text)
    invoice = match.group(1).strip() if match and match.group(1) else None

    # Защита от ложного срабатывания: иногда regex захватит само слово "Накладная"
    if invoice and invoice.lower().startswith("накладн"):
        invoice = None

    if not invoice:
        await send_message_to_chat(
            BITRIX_CHAT_ID,
            "⚠️ Пожалуйста, укажите номер накладной. Пример: /готово Накладная №1234",
        )
        return {"status": "ok", "result": "asked for invoice"}

    courier_name = await get_user_name(from_user_id) if from_user_id else "Неизвестный"

    add_delivery(
        invoice_number=invoice,
        courier_name=courier_name,
        courier_id=str(from_user_id) if from_user_id else None,
    )

    logger.info("Сохранена доставка: №%s — %s", invoice, courier_name)
    return {"status": "ok", "saved": {"invoice": invoice, "courier": courier_name}}


@app.post("/admin/run-report")
async def admin_run_report(token: str) -> dict:
    """Ручной запуск отчёта — удобно для проверки после деплоя.
    Вызывать: POST /admin/run-report?token=SECRET_TOKEN"""
    if not SECRET_TOKEN or token != SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="invalid token")
    await build_and_send_report()
    return {"status": "ok"}
