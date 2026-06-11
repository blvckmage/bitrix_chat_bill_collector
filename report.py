"""Формирование и отправка отчётов и дайджестов."""
from datetime import datetime, time, timedelta

import pytz

from config import BITRIX_CHAT_IDS, MANAGER_USER_ID, TIMEZONE
from storage import read_orders
from bitrix import send_message_to_user, send_message_to_chat
import auth_store


STATUS_EMOJI = {"delivered": "✅", "accepted": "📥", "pending": "⌛", "cancelled": "❌"}


def _day_bounds_utc(local_now: datetime) -> tuple[datetime, datetime]:
    """Границы локальных суток (00:00–24:00) в UTC для фильтрации записей."""
    tz = pytz.timezone(TIMEZONE)
    start_local = tz.localize(datetime.combine(local_now.date(), time.min))
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(pytz.UTC).replace(tzinfo=None),
        end_local.astimezone(pytz.UTC).replace(tzinfo=None),
    )


def _short_desc(o) -> str:
    head = f"№{o.order_number}" if o.order_number else None
    parts = [head, o.address, o.client, o.phone, o.desired_time]
    parts = [p for p in parts if p]
    return " / ".join(parts) if parts else "(без деталей)"


def _bucket_for(o, today_iso: str, tomorrow_iso: str,
                today_start_utc: datetime, today_end_utc: datetime) -> str | None:
    """Определить, в какой раздел отчёта попадает заявка: 'today', 'tomorrow' или None."""
    if o.target_date == today_iso:
        return "today"
    if o.target_date == tomorrow_iso:
        return "tomorrow"
    # Без target_date — относим к «сегодня» по времени создания, если попадает в сутки
    if not o.target_date and today_start_utc <= o.created_at_utc < today_end_utc:
        return "today"
    return None


def _format_section(title: str, delivered: list, accepted: list, pending: list,
                    cancelled: list, tz, show_pending_as_planned: bool = False) -> list[str]:
    """Отрендерить один раздел отчёта (сегодня или завтра)."""
    lines = [f"━━━━━ {title} ━━━━━"]
    total = len(delivered) + len(accepted) + len(pending) + len(cancelled)
    if total == 0:
        lines.append("  — заявок нет")
        return lines

    if delivered:
        lines.append(f"✅ Доставлено: {len(delivered)}")
        for o in delivered:
            t = pytz.UTC.localize(o.delivered_at_utc).astimezone(tz).strftime("%H:%M")
            lines.append(f"   • {_short_desc(o)}  ⟶ {t}")
    if accepted:
        lines.append(f"📥 Принято: {len(accepted)}")
        for o in accepted:
            t = pytz.UTC.localize(o.accepted_at_utc).astimezone(tz).strftime("%H:%M")
            lines.append(f"   • {_short_desc(o)}  ⟶ {t}")
    if pending:
        label = "Запланировано" if show_pending_as_planned else "Не принято"
        emoji = "📦" if show_pending_as_planned else "⌛"
        lines.append(f"{emoji} {label}: {len(pending)}")
        for o in pending:
            lines.append(f"   • {_short_desc(o)}")
    if cancelled:
        lines.append(f"❌ Отменено: {len(cancelled)}")
        for o in cancelled:
            t = pytz.UTC.localize(o.cancelled_at_utc).astimezone(tz).strftime("%H:%M")
            lines.append(f"   • {_short_desc(o)}  ⟶ {t}")
    return lines


def build_report_text(chat_id: str | None = None) -> str:
    """Отчёт с разделами «Сегодня» и «Завтра». Можно отфильтровать по chat_id."""
    tz = pytz.timezone(TIMEZONE)
    now_local = datetime.now(tz)
    today = now_local.date()
    tomorrow = today + timedelta(days=1)
    today_iso = today.isoformat()
    tomorrow_iso = tomorrow.isoformat()
    today_start_utc, today_end_utc = _day_bounds_utc(now_local)

    all_orders = list(read_orders())
    if chat_id:
        chat_id_str = str(chat_id).lstrip("chat")
        all_orders = [o for o in all_orders if str(o.chat_id) == chat_id_str]

    by_bucket = {"today": [], "tomorrow": []}
    for o in all_orders:
        b = _bucket_for(o, today_iso, tomorrow_iso, today_start_utc, today_end_utc)
        if b:
            by_bucket[b].append(o)

    def split(orders):
        d = sorted([o for o in orders if o.status == "delivered"],
                   key=lambda o: o.delivered_at_utc or o.created_at_utc)
        a = sorted([o for o in orders if o.status == "accepted"],
                   key=lambda o: o.accepted_at_utc or o.created_at_utc)
        p = sorted([o for o in orders if o.status == "pending"],
                   key=lambda o: o.created_at_utc)
        c = sorted([o for o in orders if o.status == "cancelled"],
                   key=lambda o: o.cancelled_at_utc or o.created_at_utc)
        return d, a, p, c

    t_del, t_acc, t_pen, t_can = split(by_bucket["today"])
    tm_del, tm_acc, tm_pen, tm_can = split(by_bucket["tomorrow"])

    lines = [f"📊 Отчёт по доставкам", f"📅 {now_local.strftime('%d.%m.%Y, %H:%M')}", ""]
    lines += _format_section(
        f"СЕГОДНЯ ({today.strftime('%d.%m')})",
        t_del, t_acc, t_pen, t_can, tz,
        show_pending_as_planned=False,
    )
    lines.append("")
    lines += _format_section(
        f"ЗАВТРА ({tomorrow.strftime('%d.%m')})",
        tm_del, tm_acc, tm_pen, tm_can, tz,
        show_pending_as_planned=True,
    )

    total_today = len(t_del) + len(t_acc) + len(t_pen) + len(t_can)
    total_tomorrow = len(tm_del) + len(tm_acc) + len(tm_pen) + len(tm_can)
    lines.append("")
    lines.append(
        f"📈 Итого  сегодня: ✅{len(t_del)} 📥{len(t_acc)} ⌛{len(t_pen)} ❌{len(t_can)} (всего {total_today})"
    )
    lines.append(
        f"           завтра: 📦{len(tm_pen)} 📥{len(tm_acc)} ✅{len(tm_del)} ❌{len(tm_can)} (всего {total_tomorrow})"
    )
    return "\n".join(lines)


def build_digest_text(target_iso_date: str, header: str, chat_id: str | None = None) -> str:
    """Дайджест: все активные (pending) заявки с заданной target_date.
    Если chat_id указан — фильтрует только заявки этого чата."""
    orders = [o for o in read_orders()
              if o.target_date == target_iso_date and o.status == "pending"]
    if chat_id:
        cid = str(chat_id).lstrip("chat")
        orders = [o for o in orders if str(o.chat_id) == cid]
    if not orders:
        return f"{header}\nНа эту дату заявок нет."
    lines = [header]
    for o in orders:
        lines.append(f"• {_short_desc(o)}")
    lines.append(f"\nВсего: {len(orders)}")
    return "\n".join(lines)


async def _send_digest_for_date(target_iso: str, header: str) -> dict:
    """Разослать дайджест во все настроенные чаты. Возвращает статистику."""
    if not BITRIX_CHAT_IDS:
        return {"sent_to": 0, "reason": "BITRIX_CHAT_IDS пуст"}
    auth_context = await auth_store.refresh_if_needed()
    sent = []
    failed = []
    for cid in BITRIX_CHAT_IDS:
        text = build_digest_text(target_iso, header, chat_id=cid)
        try:
            await send_message_to_chat(cid, text, auth_context=auth_context)
            sent.append(cid)
        except Exception as e:
            failed.append({"chat": cid, "error": str(e)})
    return {"sent_to": sent, "failed": failed}


async def send_digest_today() -> dict:
    """Дайджест в 8:00 — доставки на сегодня — во все настроенные чаты."""
    tz = pytz.timezone(TIMEZONE)
    today = datetime.now(tz).date().isoformat()
    return await _send_digest_for_date(today, "🌅 Доставки на сегодня")


async def send_digest_tomorrow() -> dict:
    """Дайджест в 17:30 — доставки на завтра — во все настроенные чаты."""
    tz = pytz.timezone(TIMEZONE)
    tomorrow = (datetime.now(tz).date() + timedelta(days=1)).isoformat()
    return await _send_digest_for_date(tomorrow, "🌙 Доставки на завтра")


async def send_report_to_chat(chat_id: str | int, auth_context: dict | None = None) -> None:
    """Отчёт в один чат по запросу — фильтр по этому же чату."""
    await send_message_to_chat(
        chat_id, build_report_text(chat_id=str(chat_id)), auth_context=auth_context,
    )
