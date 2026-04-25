"""
bartender_test.py
Тест-клиент для клона API Black Bartender.
Автоматически обрабатывает rate-limit (429), ждёт указанное время и повторяет запрос.
"""

import requests
import time
import sys
from typing import Any, Dict, Optional

class BartenderTester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.token: Optional[str] = None
        self.max_retries = 15  # Максимум попыток при лимите

    def _log(self, msg: str):
        print(f"🔹 {msg}")

    def _safe_request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        if self.token:
            kwargs.setdefault("headers", {})["Authorization"] = f"Bearer {self.token}"

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.request(method, url, timeout=15, **kwargs)
            except requests.RequestException as e:
                return {"error": f"NetworkError: {e}"}

            # 1️⃣ Обработка HTTP 429
            if resp.status_code == 429:
                wait = 2
                try:
                    wait = resp.json().get("retry_after", 2)
                except Exception:
                    pass
                self._log(f"⏳ [429] Rate limit. Ждём {wait}с (попытка {attempt})...")
                time.sleep(float(wait) + 0.2)
                continue

            # 2️⃣ Обработка 200 OK, но тело содержит rate_limit
            try:
                data = resp.json()
                if data.get("error") == "rate_limit":
                    wait = data.get("retry_after", 2)
                    self._log(f"⏳ [RATE_BODY] Лимит в теле ответа. Ждём {wait}с...")
                    time.sleep(float(wait) + 0.2)
                    continue
                return data
            except ValueError:
                return {"raw": resp.text, "status_code": resp.status_code}

        return {"error": "Превышено максимальное количество попыток из-за лимита запросов"}

    # --- Эндпоинты ---
    def register(self) -> Dict:
        res = self._safe_request("POST", "/register")
        if "token" in res:
            self.token = res["token"]
            self._log(f"✅ Токен получен: {self.token[:8]}...")
        return res

    def reset(self) -> Dict:
        return self._safe_request("POST", "/reset")

    def menu(self, x_time: Optional[str] = None) -> Dict:
        headers = {"X-Time": x_time} if x_time else {}
        return self._safe_request("GET", "/menu", headers=headers)

    def order(self, name: str) -> Dict:
        return self._safe_request("POST", "/order", json={"name": name})

    def mix(self, ingredients: list) -> Dict:
        return self._safe_request("POST", "/mix", json={"ingredients": ingredients})

    def balance(self) -> Dict:
        return self._safe_request("GET", "/balance")

    def tip(self, amount: int) -> Dict:
        return self._safe_request("POST", "/tip", json={"amount": amount})

    def history(self) -> Dict:
        return self._safe_request("GET", "/history")

    def profile(self) -> Dict:
        return self._safe_request("GET", "/profile")

    # --- Тестовый сценарий ---
    def run_full_test(self) -> bool:
        self._log("🚀 Запуск полного теста API...")
        time.sleep(0.5)

        steps = [
            ("Регистрация", lambda: self.register()),
            ("Дневное меню (12:00)", lambda: self.menu("12:00")),
            ("Заказ 'Русский'", lambda: self.order("Русский")),
            ("Микс 'Русский'", lambda: self.mix(["водка", "лёд"])),
            ("Баланс", lambda: self.balance()),
            ("Чаевые 5₽", lambda: self.tip(5)),
            ("История", lambda: self.history()),
            ("Профиль", lambda: self.profile()),
            ("Ночное меню (02:00)", lambda: self.menu("02:00")),
            ("Попытка заказать дневной напиток ночью", lambda: self.order("Русский")),
            ("Сброс аккаунта", lambda: self.reset()),
            ("Повторная регистрация (авто)", lambda: self.register()),
            ("Секретный микс 'Мертвец'", lambda: self.mix(["водка", "ром", "молоко"])),
            ("Баланс после секрета", lambda: self.balance()),
        ]

        passed = 0
        failed = 0

        for name, func in steps:
            self._log(f"📦 Тест: {name}")
            try:
                res = func()
                if "error" in res and res["error"] not in ("rate_limit",):
                    print(f"  ❌ Ошибка: {res}")
                    failed += 1
                else:
                    print(f"  ✅ ОК: {res.get('status', 'ok')} | Баланс: {res.get('balance', 'N/A')}")
                    passed += 1
            except Exception as e:
                print(f"  ❌ Исключение: {e}")
                failed += 1
            # Небольшая пауза между шагами, чтобы не спамить API
            time.sleep(0.3)

        self._log(f"\n📊 Итог: ✅ {passed} | ❌ {failed}")
        return failed == 0

if __name__ == "__main__":
    BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    tester = BartenderTester(BASE_URL)
    success = tester.run_full_test()
    sys.exit(0 if success else 1)