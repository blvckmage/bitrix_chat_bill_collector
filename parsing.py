"""Свободный парсер заявок: из текста сообщения + имён прикреплённых файлов
вытаскиваем структурированные поля. Все поля опциональны.
"""
import re
from datetime import datetime, timedelta

import pytz

from config import TIMEZONE

# Снимаем BBcode-разметку Битрикса (например, [USER=4163]Бот[/USER], [B]…[/B])
BBCODE_RE = re.compile(r"\[/?[A-Za-z][^\]]*\]")

# Телефон: +7..., 8..., может содержать пробелы/скобки/дефисы
PHONE_RE = re.compile(r"\+?[78][\s\-()]*\d[\d\s\-()]{7,11}\d")

# Желаемое время доставки
TIME_RE = re.compile(r"\b(сегодня|завтра)\b", re.IGNORECASE)

# Номер документа: "№ 5203", "№5203", "# 5203"
ORDER_NUM_RE = re.compile(r"[№#]\s*(\d{1,10})")

# Дата в формате DD.MM.YYYY (часто в имени файла после "от")
DATE_RE = re.compile(r"\b(\d{1,2}\.\d{1,2}\.\d{2,4})\b")

# Маркеры адреса — улица, проспект, микрорайон и т.п.
ADDRESS_HINT_RE = re.compile(
    r"(?:ул\.?|улица|пр-?т|пр\.?|проспект|мкр\.?|микрорайон|"
    r"пер\.?|переулок|пл\.?|площадь|шоссе|ш\.|бульвар|б-р|тракт)"
    r"\s*[А-ЯЁа-яёA-Za-z0-9\.\-\s]+?(?:\d+(?:[/\-]\d+)?(?:\s*кв\.?\s*\d+)?)",
    re.IGNORECASE,
)

# Метки (если пользователь всё-таки помечает явно — учитываем)
LABEL_RES = {
    "address": re.compile(r"(?:адрес)\s*[:\-]\s*([^\n;,]+)", re.IGNORECASE),
    "client":  re.compile(r"(?:клиент|получатель|имя)\s*[:\-]\s*([^\n;,]+)", re.IGNORECASE),
    "phone":   re.compile(r"(?:телефон|тел)\s*[:\-]\s*([+\d\s\-()]{7,})", re.IGNORECASE),
}


def _strip_bbcode(text: str) -> str:
    """Удалить BBcode-теги, оставив видимый текст."""
    return BBCODE_RE.sub("", text).strip()


def parse_edits(text: str) -> dict:
    """Из reply-сообщения вытащить поля для обновления заявки.
    Принимаем только явные метки (адрес: …, клиент: …, телефон: …, время: …)
    и слово 'сегодня'/'завтра', чтобы случайные совпадения не портили данные."""
    text = _strip_bbcode(text or "")
    updates: dict = {}
    for key, rx in LABEL_RES.items():
        if m := rx.search(text):
            updates[key] = m.group(1).strip()
    if m := re.search(r"(?:время|на)\s*[:\-]?\s*(сегодня|завтра)", text, re.IGNORECASE):
        updates["desired_time"] = m.group(1).lower()
    elif m := TIME_RE.search(text):
        updates["desired_time"] = m.group(1).lower()
    if updates.get("desired_time"):
        updates["target_date"] = resolve_target_date(updates["desired_time"])
    return updates


def resolve_target_date(desired_time: str) -> str:
    """Превратить 'сегодня'/'завтра' в YYYY-MM-DD (по локальной TZ)."""
    if not desired_time:
        return ""
    tz = pytz.timezone(TIMEZONE)
    today = datetime.now(tz).date()
    if desired_time == "сегодня":
        return today.isoformat()
    if desired_time == "завтра":
        return (today + timedelta(days=1)).isoformat()
    return ""


def parse_filename(name: str) -> dict:
    """Из имени файла вытаскиваем номер документа и дату."""
    result = {"order_number": "", "doc_date": ""}
    if m := ORDER_NUM_RE.search(name):
        result["order_number"] = m.group(1)
    if m := DATE_RE.search(name):
        result["doc_date"] = m.group(1)
    return result


def parse_message(text: str, filenames: list[str] | None = None) -> dict:
    """Свободный разбор сообщения + имён файлов.

    Возвращает: order_number, doc_date, address, client, phone, desired_time, files.
    Поля, которые не удалось определить — пустые строки (files — пустой список).
    """
    text = _strip_bbcode(text or "")
    filenames = filenames or []

    result = {
        "order_number": "",
        "doc_date": "",
        "address": "",
        "client": "",
        "phone": "",
        "desired_time": "",
        "files": filenames,
    }

    # 1) Поля из имён файлов — самые надёжные
    for fname in filenames:
        info = parse_filename(fname)
        if info["order_number"] and not result["order_number"]:
            result["order_number"] = info["order_number"]
        if info["doc_date"] and not result["doc_date"]:
            result["doc_date"] = info["doc_date"]

    # 2) Метки в тексте имеют высший приоритет
    for key, rx in LABEL_RES.items():
        if m := rx.search(text):
            result[key] = m.group(1).strip()

    # 3) Эвристики поверх "сырого" текста
    if not result["order_number"]:
        if m := ORDER_NUM_RE.search(text):
            result["order_number"] = m.group(1)
    if not result["doc_date"]:
        if m := DATE_RE.search(text):
            result["doc_date"] = m.group(1)
    if not result["phone"]:
        if m := PHONE_RE.search(text):
            result["phone"] = m.group(0).strip()
    if not result["desired_time"]:
        if m := TIME_RE.search(text):
            result["desired_time"] = m.group(1).lower()
    if not result["address"]:
        if m := ADDRESS_HINT_RE.search(text):
            result["address"] = m.group(0).strip()

    # 4) Имя клиента — если в тексте есть строка-кандидат без меток
    #    (два-три капитализированных слова подряд, не входящих в адрес/телефон).
    if not result["client"]:
        cleaned = text
        for v in (result["address"], result["phone"], result["doc_date"]):
            if v:
                cleaned = cleaned.replace(v, "")
        m = re.search(
            r"\b([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2})\b",
            cleaned,
        )
        if m:
            candidate = m.group(1)
            if not re.search(r"(сегодня|завтра|накладн|заявк|клиент|адрес|телефон)", candidate, re.I):
                result["client"] = candidate

    # 5) Запасной адрес — то, что осталось от текста после удаления распознанных кусков
    if not result["address"]:
        leftover = text
        for v in (result["phone"], result["client"], result["doc_date"],
                  result["desired_time"]):
            if v:
                leftover = leftover.replace(v, " ")
        # убираем номера документа (№NNN), метки, лишние знаки
        leftover = re.sub(r"[№#]\s*\d+", " ", leftover)
        leftover = re.sub(r"\b(сегодня|завтра)\b", " ", leftover, flags=re.IGNORECASE)
        leftover = re.sub(r"\b(адрес|клиент|телефон|тел|получатель|имя|время)\s*[:\-]?", " ",
                          leftover, flags=re.IGNORECASE)
        leftover = re.sub(r"[,;]+", " ", leftover)
        leftover = re.sub(r"\s+", " ", leftover).strip(" -—:.,")
        # если осталось хоть что-то осмысленное (>2 символа, не цифры) — считаем адресом
        if leftover and len(leftover) > 2 and not leftover.isdigit():
            result["address"] = leftover

    return result
