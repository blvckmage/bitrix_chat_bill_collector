"""Формирование и отправка ежедневного отчёта заведующему."""
from datetime import datetime, time, timedelta

import pytz

from config import MANAGER_USER_ID, TIMEZONE
from storage import read_all
from bitrix import send_message_to_user, send_message_to_chat


def _day_bounds_utc(local_now: datetime) -> tuple[datetime, datetime]:
    """Границы локальных суток (00:00–24:00) в UTC для фильтрации записей."""
    tz = pytz.timezone(TIMEZONE)
    start_local = tz.localize(datetime.combine(local_now.date(), time.min))
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(pytz.UTC).replace(tzinfo=None),
        end_local.astimezone(pytz.UTC).replace(tzinfo=None),
    )


def build_report_text() -> str:
    """Собрать текст отчёта за сегодня (по локальному времени)."""
    tz = pytz.timezone(TIMEZONE)
    today_local = datetime.now(tz)
    start_utc, end_utc = _day_bounds_utc(today_local)

    rows = [d for d in read_all() if start_utc <= d.created_at_utc < end_utc]
    rows.sort(key=lambda d: d.created_at_utc)

    date_str = today_local.strftime("%d.%m.%Y")
    if not rows:
        return f"📦 Отчёт по доставкам за {date_str}\nЗа сегодня доставок не зафиксировано."

    lines = [f"📦 Отчёт по доставкам за {date_str}"]
    for r in rows:
        local_time = pytz.UTC.localize(r.created_at_utc).astimezone(tz).strftime("%H:%M")
        lines.append(f"✅ Накладная №{r.invoice_number} — {r.courier_name} — {local_time}")
    lines.append(f"Итого выполнено: {len(rows)} доставки")
    return "\n".join(lines)


async def build_and_send_report() -> None:
    """Ежедневный отчёт заведующему складу в личку."""
    text = build_report_text()
    if MANAGER_USER_ID:
        await send_message_to_user(MANAGER_USER_ID, text)


async def send_report_to_chat(chat_id: str | int, auth_context: dict | None = None) -> None:
    """Отправить отчёт прямо в чат (по запросу командой /отчет).
    Если передан auth_context — сообщение уйдёт от имени бота.
    """
    await send_message_to_chat(chat_id, build_report_text(), auth_context=auth_context)
