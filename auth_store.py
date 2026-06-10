"""Хранилище OAuth-токенов локального приложения Битрикс24.

Файл auth.json содержит:
    {
        "access_token": "...",
        "refresh_token": "...",
        "client_endpoint": "https://portal.bitrix24.kz/rest/",
        "domain": "portal.bitrix24.kz",
        "expires_at": 1739999999  // unix-время истечения access_token
    }
"""
import json
import os
import time
import threading

import httpx

from config import AUTH_STORE_PATH, BITRIX_CLIENT_ID, BITRIX_CLIENT_SECRET

_lock = threading.Lock()
OAUTH_TOKEN_URL = "https://oauth.bitrix.info/oauth/token/"


def save(data: dict) -> None:
    """Сохранить токены. data — словарь с access_token, refresh_token, client_endpoint, domain, expires_in."""
    payload = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "client_endpoint": data["client_endpoint"].rstrip("/") + "/",
        "domain": data.get("domain", ""),
        "expires_at": int(time.time()) + int(data.get("expires_in", 3600)) - 60,
    }
    with _lock:
        with open(AUTH_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)


def load() -> dict | None:
    """Прочитать токены из файла. Возвращает None, если файла нет."""
    with _lock:
        if not os.path.exists(AUTH_STORE_PATH):
            return None
        with open(AUTH_STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)


async def refresh_if_needed() -> dict | None:
    """Если access_token истёк — обновить через refresh_token. Вернуть актуальный auth_dict."""
    auth = load()
    if not auth:
        return None
    if auth["expires_at"] > int(time.time()):
        return auth
    if not auth.get("refresh_token") or not BITRIX_CLIENT_ID or not BITRIX_CLIENT_SECRET:
        return auth  # обновить нечем — вернём как есть, пусть упадёт на вызове

    params = {
        "grant_type": "refresh_token",
        "client_id": BITRIX_CLIENT_ID,
        "client_secret": BITRIX_CLIENT_SECRET,
        "refresh_token": auth["refresh_token"],
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(OAUTH_TOKEN_URL, params=params)
        r.raise_for_status()
        data = r.json()
    # Битрикс возвращает access_token, refresh_token, expires_in, client_endpoint, domain
    save(data)
    return load()
