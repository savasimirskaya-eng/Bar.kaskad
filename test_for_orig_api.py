"""
original_api_probe.py
Тест-зонд для оригинального API bar.antihype.lol
Сохраняет полный JSON-лог всех запросов/ответов в original_api_log.json
"""

import requests
import time
import json
import sys
from datetime import datetime

BASE_URL = "http://127.0.0.1:8000/"
LOG_FILE = "original_api_log.json"
SESSION = requests.Session()

log_entries = []


def log_entry(step, method, path, payload, headers, response):
    entry = {
        "step": step,
        "timestamp": datetime.utcnow().isoformat(),
        "request": {
            "method": method,
            "path": path,
            "payload": payload,
            "headers": {k: v for k, v in headers.items() if k.lower() != "authorization"}
        },
        "response": {
            "status_code": response.status_code,
            "body": response.json() if response.headers.get("content-type", "").startswith(
                "application/json") else response.text
        }
    }
    log_entries.append(entry)
    print(f"[{step}] {method} {path} -> {response.status_code}")
    if response.status_code == 429:
        wait = response.json().get("retry_after", 5)
        print(f"   ⏳ Rate limit. Ждём {wait}с...")
        time.sleep(wait + 1)
    time.sleep(1.5)  # Пауза между запросами
    return entry


def req(step, method, path, payload=None, headers=None):
    h = headers or {}
    url = f"{BASE_URL}{path}"
    try:
        if method == "POST":
            resp = SESSION.post(url, json=payload, headers=h, timeout=15)
        else:
            resp = SESSION.get(url, headers=h, timeout=15)
        return log_entry(step, method, path, payload, h, resp)
    except requests.RequestException as e:
        print(f"   ❌ Network error: {e}")
        return log_entry(step, method, path, payload, h, type("DummyResponse", (),
                                                              {"status_code": 0, "json": lambda: {"error": str(e)},
                                                               "text": str(e)})())


def main():
    print("🔍 Зондирование оригинального API bar.antihype.lol")
    print("=" * 60)

    # 1. Регистрация
    r = req("1_reg", "POST", "/register")
    token = r["response"]["body"].get("token", "")
    if not token:
        print("❌ Не удалось получить токен. Выход.")
        return

    AUTH = {"Authorization": f"Bearer {token}"}

    # 2. Базовое состояние
    req("2_menu_day", "GET", "/menu", headers={**AUTH, "X-Time": "12:00"})
    req("3_order_rus_1", "POST", "/order", payload={"name": "Русский"}, headers=AUTH)

    # 3. Проверка favorite и repeat_check
    req("4_order_rus_2", "POST", "/order", payload={"name": "Русский"}, headers=AUTH)
    req("5_order_rus_3", "POST", "/order", payload={"name": "Русский"}, headers=AUTH)
    req("6_order_rus_4", "POST", "/order", payload={"name": "Русский"}, headers=AUTH)
    req("7_order_rus_5", "POST", "/order", payload={"name": "Русский"}, headers=AUTH)
    req("8_order_rus_6", "POST", "/order", payload={"name": "Русский"}, headers=AUTH)
    req("9_order_rus_7", "POST", "/order", payload={"name": "Русский"}, headers=AUTH)
    req("10_profile_after_7", "GET", "/profile", headers=AUTH)

    # 4. Тест настроения (ошибки)
    req("11_mix_foo_1", "POST", "/mix", payload={"ingredients": ["foo"]}, headers=AUTH)
    req("12_mix_foo_2", "POST", "/mix", payload={"ingredients": ["foo"]}, headers=AUTH)
    req("13_mix_foo_3", "POST", "/mix", payload={"ingredients": ["foo"]}, headers=AUTH)
    req("14_mix_foo_4", "POST", "/mix", payload={"ingredients": ["foo"]}, headers=AUTH)
    req("15_menu_after_errors", "GET", "/menu", headers={**AUTH, "X-Time": "12:00"})

    # 5. Тест секретов
    req("16_mix_mistake", "POST", "/mix", payload={"ingredients": ["лёд", "молоко", "текила"]}, headers=AUTH)
    req("17_balance_after_mistake", "GET", "/balance", headers=AUTH)

    # 6. Тест рангов
    req("18_order_mix_drinks", "POST", "/order", payload={"name": "Отвёртка"}, headers=AUTH)
    req("19_order_mix_drinks2", "POST", "/order", payload={"name": "Куба Либре"}, headers=AUTH)
    req("20_order_mix_drinks3", "POST", "/order", payload={"name": "Джин-тоник"}, headers=AUTH)
    req("21_profile_ranks", "GET", "/profile", headers=AUTH)

    # 7. Сохранение лога
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log_entries, f, ensure_ascii=False, indent=2)
    print(f"\n📁 Лог сохранён: {LOG_FILE}")
    print("🔍 Проанализируйте файл, чтобы найти отличия логики оригинала.")


if __name__ == "__main__":
    main()