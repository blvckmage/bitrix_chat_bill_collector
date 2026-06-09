"""Хранилище доставок в локальном CSV-файле."""
import csv
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from config import CSV_PATH

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
