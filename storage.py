"""Хранилище доставок в локальном CSV-файле."""
import csv
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from config import CSV_PATH, ORDERS_CSV_PATH

# CSV не потокобезопасен сам по себе — защищаем запись/чтение блокировкой,
# чтобы вебхук-обработчики и планировщик не наступали друг другу на пятки.
_lock = threading.Lock()

FIELDS = ["invoice_number", "courier_name", "courier_id", "created_at_utc"]


@dataclass
class Delivery:
    invoice_number: str
    courier_name: str
    courier_id: str | None
    created_at_utc: datetime  # naive UTC


def init_storage() -> None:
    """Создать CSV-файл с заголовком, если его ещё нет."""
    with _lock:
        if not os.path.exists(CSV_PATH):
            os.makedirs(os.path.dirname(CSV_PATH) or ".", exist_ok=True)
            with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writeheader()


def add_delivery(invoice_number: str, courier_name: str, courier_id: str | None) -> None:
    """Дописать одну строку в CSV."""
    row = {
        "invoice_number": invoice_number,
        "courier_name": courier_name,
        "courier_id": courier_id or "",
        "created_at_utc": datetime.utcnow().isoformat(timespec="seconds"),
    }
    with _lock:
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writerow(row)


def read_all() -> Iterable[Delivery]:
    """Прочитать все записи из CSV."""
    with _lock:
        if not os.path.exists(CSV_PATH):
            return []
        with open(CSV_PATH, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

    result = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["created_at_utc"])
        except (ValueError, KeyError):
            continue
        result.append(Delivery(
            invoice_number=r.get("invoice_number", ""),
            courier_name=r.get("courier_name", ""),
            courier_id=r.get("courier_id") or None,
            created_at_utc=ts,
        ))
    return result


# ──────────────────────────────────────────────────────────────────────────
# Заявки (новый поток: сообщение от зава → реакция → отметка о доставке)
# ──────────────────────────────────────────────────────────────────────────

ORDER_FIELDS = [
    "order_number",
    "doc_date",
    "address",
    "client",
    "phone",
    "desired_time",
    "target_date",
    "files",
    "raw_text",
    "chat_id",
    "message_id",
    "author_id",
    "author_name",
    "created_at_utc",
    "accepted_at_utc",
    "accepted_by_id",
    "accepted_by_name",
    "delivered_at_utc",
    "delivered_by_id",
    "delivered_by_name",
    "cancelled_at_utc",
    "cancelled_by_id",
    "cancelled_by_name",
]


@dataclass
class Order:
    order_number: str
    doc_date: str
    address: str
    client: str
    phone: str
    desired_time: str
    target_date: str  # YYYY-MM-DD или ''
    files: str
    raw_text: str
    chat_id: str
    message_id: str
    author_id: str
    author_name: str
    created_at_utc: datetime
    accepted_at_utc: datetime | None
    accepted_by_id: str | None
    accepted_by_name: str | None
    delivered_at_utc: datetime | None
    delivered_by_id: str | None
    delivered_by_name: str | None
    cancelled_at_utc: datetime | None
    cancelled_by_id: str | None
    cancelled_by_name: str | None

    @property
    def status(self) -> str:
        if self.cancelled_at_utc:
            return "cancelled"
        if self.delivered_at_utc:
            return "delivered"
        if self.accepted_at_utc:
            return "accepted"
        return "pending"


def init_orders_storage() -> None:
    with _lock:
        os.makedirs(os.path.dirname(ORDERS_CSV_PATH) or ".", exist_ok=True)
        if os.path.exists(ORDERS_CSV_PATH):
            # Если набор колонок изменился — отложим старый файл и создадим новый
            with open(ORDERS_CSV_PATH, "r", newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                try:
                    header = next(reader)
                except StopIteration:
                    header = []
            if header != ORDER_FIELDS:
                backup = ORDERS_CSV_PATH + ".bak"
                os.replace(ORDERS_CSV_PATH, backup)
            else:
                return
        with open(ORDERS_CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=ORDER_FIELDS).writeheader()


def _read_orders_rows() -> list[dict]:
    with _lock:
        if not os.path.exists(ORDERS_CSV_PATH):
            return []
        with open(ORDERS_CSV_PATH, "r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))


def _write_orders_rows(rows: list[dict]) -> None:
    with _lock:
        with open(ORDERS_CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=ORDER_FIELDS)
            writer.writeheader()
            writer.writerows(rows)


def add_order(*, order_number: str = "", doc_date: str = "",
              address: str = "", client: str = "", phone: str = "",
              desired_time: str = "", target_date: str = "",
              files: str = "", raw_text: str = "",
              chat_id: str, message_id: str,
              author_id: str, author_name: str) -> None:
    """Сохранить новую заявку (status=pending). Все поля кроме идентификаторов опциональны."""
    rows = _read_orders_rows()
    if any(r.get("message_id") == str(message_id) for r in rows):
        return
    rows.append({
        "order_number": order_number,
        "doc_date": doc_date,
        "address": address,
        "client": client,
        "phone": phone,
        "desired_time": desired_time,
        "target_date": target_date,
        "files": files,
        "raw_text": raw_text,
        "chat_id": str(chat_id),
        "message_id": str(message_id),
        "author_id": str(author_id),
        "author_name": author_name,
        "created_at_utc": datetime.utcnow().isoformat(timespec="seconds"),
        "accepted_at_utc": "",
        "accepted_by_id": "",
        "accepted_by_name": "",
        "delivered_at_utc": "",
        "delivered_by_id": "",
        "delivered_by_name": "",
        "cancelled_at_utc": "",
        "cancelled_by_id": "",
        "cancelled_by_name": "",
    })
    _write_orders_rows(rows)


def mark_accepted(message_id: str, by_id: str, by_name: str) -> list[dict]:
    """Отметить заявку как принятую заведующим складом."""
    rows = _read_orders_rows()
    changed = []
    for r in rows:
        if r.get("message_id") == str(message_id) \
                and not r.get("accepted_at_utc") \
                and not r.get("delivered_at_utc") \
                and not r.get("cancelled_at_utc"):
            r["accepted_at_utc"] = datetime.utcnow().isoformat(timespec="seconds")
            r["accepted_by_id"] = str(by_id)
            r["accepted_by_name"] = by_name
            changed.append(r.copy())
    if changed:
        _write_orders_rows(rows)
    return changed


def mark_delivered(message_id: str, by_id: str, by_name: str) -> list[dict]:
    """Отметить заявку как доставленную."""
    rows = _read_orders_rows()
    changed = []
    for r in rows:
        if r.get("message_id") == str(message_id) \
                and not r.get("delivered_at_utc") \
                and not r.get("cancelled_at_utc"):
            # Если ещё не была принята — авто-принимаем тем же сотрудником
            if not r.get("accepted_at_utc"):
                r["accepted_at_utc"] = datetime.utcnow().isoformat(timespec="seconds")
                r["accepted_by_id"] = str(by_id)
                r["accepted_by_name"] = by_name
            r["delivered_at_utc"] = datetime.utcnow().isoformat(timespec="seconds")
            r["delivered_by_id"] = str(by_id)
            r["delivered_by_name"] = by_name
            changed.append(r.copy())
    if changed:
        _write_orders_rows(rows)
    return changed


def mark_cancelled(message_id: str, by_id: str, by_name: str) -> list[dict]:
    """Отметить заявку как отменённую."""
    rows = _read_orders_rows()
    changed = []
    for r in rows:
        if r.get("message_id") == str(message_id) \
                and not r.get("cancelled_at_utc") \
                and not r.get("delivered_at_utc"):
            r["cancelled_at_utc"] = datetime.utcnow().isoformat(timespec="seconds")
            r["cancelled_by_id"] = str(by_id)
            r["cancelled_by_name"] = by_name
            changed.append(r.copy())
    if changed:
        _write_orders_rows(rows)
    return changed


def update_order(message_id: str, updates: dict) -> dict | None:
    """Обновить поля заявки (только разрешённые: address, client, phone, desired_time,
    target_date, order_number, doc_date). Не трогает уже доставленные/отменённые."""
    allowed = {"address", "client", "phone", "desired_time",
               "target_date", "order_number", "doc_date"}
    rows = _read_orders_rows()
    updated = None
    for r in rows:
        if r.get("message_id") == str(message_id) \
                and not r.get("delivered_at_utc") \
                and not r.get("cancelled_at_utc"):
            for k, v in updates.items():
                if k in allowed and v:
                    r[k] = v
            updated = r.copy()
            break
    if updated:
        _write_orders_rows(rows)
    return updated


def clear_orders() -> int:
    """Очистить все заявки. Старый файл сохраняется в orders_YYYYMMDD_HHMMSS.csv.bak.
    Возвращает число удалённых записей."""
    rows = _read_orders_rows()
    count = len(rows)
    with _lock:
        if os.path.exists(ORDERS_CSV_PATH):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = f"{ORDERS_CSV_PATH}.{ts}.bak"
            os.replace(ORDERS_CSV_PATH, backup)
        with open(ORDERS_CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=ORDER_FIELDS).writeheader()
    return count


def read_orders() -> list[Order]:
    result = []
    for r in _read_orders_rows():
        try:
            created = datetime.fromisoformat(r["created_at_utc"])
        except (ValueError, KeyError):
            continue
        def _parse_dt(key: str):
            if r.get(key):
                try:
                    return datetime.fromisoformat(r[key])
                except ValueError:
                    return None
            return None

        result.append(Order(
            order_number=r.get("order_number", ""),
            doc_date=r.get("doc_date", ""),
            address=r.get("address", ""),
            client=r.get("client", ""),
            phone=r.get("phone", ""),
            desired_time=r.get("desired_time", ""),
            target_date=r.get("target_date", ""),
            files=r.get("files", ""),
            raw_text=r.get("raw_text", ""),
            chat_id=r.get("chat_id", ""),
            message_id=r.get("message_id", ""),
            author_id=r.get("author_id", ""),
            author_name=r.get("author_name", ""),
            created_at_utc=created,
            accepted_at_utc=_parse_dt("accepted_at_utc"),
            accepted_by_id=r.get("accepted_by_id") or None,
            accepted_by_name=r.get("accepted_by_name") or None,
            delivered_at_utc=_parse_dt("delivered_at_utc"),
            delivered_by_id=r.get("delivered_by_id") or None,
            delivered_by_name=r.get("delivered_by_name") or None,
            cancelled_at_utc=_parse_dt("cancelled_at_utc"),
            cancelled_by_id=r.get("cancelled_by_id") or None,
            cancelled_by_name=r.get("cancelled_by_name") or None,
        ))
    return result
