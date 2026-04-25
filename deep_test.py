"""
deep_bartender_test.py
Полный регрессионный тест для API Чёрного Бармена.
Проверяет: настроения, цены, секреты, закрытие бара, rate-limit, валидацию, ранги.
"""

import requests
import time
import sys
import re
from typing import Dict, Any


class DeepBartenderTest:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.token = None
        self.account_id = None
        self.passed = 0
        self.failed = 0

    # ---------------- Утилиты ----------------
    def _call(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        headers = kwargs.get("headers", {})
        if self.token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {self.token}"
        kwargs["headers"] = headers

        for _ in range(5):
            try:
                resp = self.session.request(method, f"{self.base}{path}", timeout=20, **kwargs)
            except requests.RequestException as e:
                return {"status_code": 0, "error": str(e)}

            # Обработка 429
            if resp.status_code == 429:
                try:
                    wait = resp.json().get("retry_after", 3)
                except Exception:
                    wait = 3
                print(f"⏳ [429] Лимит запросов. Ждём {wait}с...")
                time.sleep(wait + 0.5)
                continue

            # Обработка rate_limit в теле 200 OK (иногда встречается в старых логах)
            try:
                data = resp.json()
                if isinstance(data, dict) and data.get("error") == "rate_limit":
                    wait = data.get("retry_after", 2)
                    print(f"⏳ [BODY LIMIT] Лимит в ответе. Ждём {wait}с...")
                    time.sleep(wait + 0.5)
                    continue
                return {**data, "status_code": resp.status_code}
            except ValueError:
                return {"status_code": resp.status_code, "raw": resp.text}

    def _assert(self, name: str, cond: bool, detail: str = ""):
        if cond:
            self.passed += 1
            print(f"✅ {name}")
        else:
            self.failed += 1
            print(f"❌ {name} | {detail}")

    def _reset_and_wait(self):
        self._call("POST", "/reset")
        time.sleep(0.3)

    # ---------------- Блоки тестов ----------------
    def test_register(self):
        print("\n📦 1. Регистрация и Auth")
        res = self._call("POST", "/register")
        self._assert("Статус регистрации", res.get("status") == "ok", res)
        self._assert("Получен токен", "token" in res, res)
        self._assert("Получен ID", res.get("id", "").startswith("BAR-"), res)
        if res.get("token"):
            self.token = res["token"]
            self.account_id = res.get("id")

    def test_day_menu_and_base_prices(self):
        print("\n📦 2. Дневное меню и базовые цены")
        self._reset_and_wait()
        res = self._call("GET", "/menu", headers={"X-Time": "12:00"})
        self._assert("Меню ок", res.get("status") == "ok")
        self._assert("8 напитков", len(res.get("drinks", [])) == 8, f"Найдено: {len(res.get('drinks', []))}")

        prices = {d["name"]: d["price"] for d in res.get("drinks", [])}
        self._assert("Русский 10₽", prices.get("Русский") == 10, f"Русский: {prices.get('Русский')}")
        self._assert("Лонг-Айленд 25₽", prices.get("Лонг-Айленд") == 25)
        self._assert("Баланс 100", res.get("balance") == 100)
        self._assert("Настроение normal", res.get("mood_level") == "normal")

    def test_night_menu(self):
        print("\n📦 3. Ночное меню (00:00-05:59)")
        self._reset_and_wait()
        res = self._call("GET", "/menu", headers={"X-Time": "03:00"})
        drinks = res.get("drinks", [])
        self._assert("3 ночных напитка", len(drinks) == 3, f"Найдено: {len(drinks)}")
        names = {d["name"] for d in drinks}
        self._assert("Ночной русский в меню", "Ночной русский" in names)
        self._assert("Цена Ночного русского 8₽", any(d["price"] == 8 and d["name"] == "Ночной русский" for d in drinks))

    def test_mood_progression_and_pricing(self):
        print("\n📦 4. Динамика настроения и цен")
        self._reset_and_wait()

        # 1. Делаем ошибки, чтобы ухудшить настроение
        for _ in range(4):
            self._call("POST", "/mix", json={"ingredients": ["foo"]})
            time.sleep(0.1)

        res = self._call("GET", "/menu")
        mood = res.get("mood_level")
        self._assert("Настроение ухудшилось", mood in ("grumpy", "hostile"), f"Текущее: {mood}")

        # Проверяем рост цен
        prices = {d["name"]: d["price"] for d in res.get("drinks", [])}
        self._assert("Цена Русского выросла", prices.get("Русский", 10) >= 11, f"Русский: {prices.get('Русский')}")

        # 2. Улучшаем настроение чаевыми
        self._call("POST", "/tip", json={"amount": 100})
        res = self._call("GET", "/menu")
        self._assert("Настроение friendly после 100₽", res.get("mood_level") == "friendly")
        self._assert("Баланс 0 после 100₽", res.get("balance") == 0)

    def test_orders_favorites_and_rank(self):
        print("\n📦 5. Заказы, избранное и ранги")
        self._reset_and_wait()

        # 5 заказов
        for i in range(1, 6):
            res = self._call("POST", "/order", json={"name": "Русский"})
            self._assert(f"Заказ {i} успешен", res.get("status") == "ok")
            if i == 5:
                self._assert("Появляется favorite", res.get("favorite") is True, res)
            time.sleep(0.1)

        # 7-й бесплатный
        res = self._call("POST", "/order", json={"name": "Русский"})
        self._assert("7-й заказ бесплатный", res.get("free_every_7th") is True)
        self._assert("Цена 0", res.get("price") == 0)
        self._assert("Баланс не изменился", res.get("balance") == 42,
                     f"Баланс: {res.get('balance')}")  # 100 - 6*10 + 5(tip) - ... зависит от тестов, проверяем логику

        prof = self._call("GET", "/profile")
        self._assert("Ранг обновился", prof.get("rank") != "Новичок", f"Ранг: {prof.get('rank')}")
        self._assert("total_orders > 0", prof.get("total_orders", 0) > 0)
        self._assert("unique_drinks == 1", prof.get("unique_drinks") == 1)

    def test_mixes_and_secrets(self):
        print("\n📦 6. Миксы и скрытые рецепты")
        self._reset_and_wait()

        # Валидный микс (цена 80% от заказа)
        mix_res = self._call("POST", "/mix", json={"ingredients": ["водка", "лёд"]})
        self._assert("Микс Русский создан", mix_res.get("drink") == "Русский")
        self._assert("Цена микса 8₽ (80%)", mix_res.get("price") == 8, f"Цена: {mix_res.get('price')}")

        # Ошибка: невалидный ингредиент
        err = self._call("POST", "/mix", json={"ingredients": ["бензин"]})
        self._assert("Ошибка invalid_ingredient", err.get("error") == "invalid_ingredient")

        # Ошибка: неизвестный рецепт
        err = self._call("POST", "/mix", json={"ingredients": ["водка", "ром"]})
        self._assert("Ошибка unknown_recipe", err.get("error") == "unknown_recipe")

        # Пустой микс -> Воздух
        air = self._call("POST", "/mix", json={"ingredients": []})
        self._assert("Пустой микс = Воздух", air.get("drink") == "Воздух")
        self._assert("Воздух бесплатный", air.get("price") == 0)

        # Секрет: Мертвец (x2 баланс)
        self._reset_and_wait()
        self._call("POST", "/tip", json={"amount": 10})  # оставим 90
        dead = self._call("POST", "/mix", json={"ingredients": ["водка", "ром", "молоко"]})
        self._assert("Мертвец создан", dead.get("drink") == "Мертвец")
        self._assert("Эффект balance_doubled", dead.get("effect") == "balance_doubled")
        self._assert("Баланс удвоился", dead.get("balance") == 180, f"Баланс: {dead.get('balance')}")

        # Секрет: Ошибка бармена (max mood)
        self._reset_and_wait()
        mistake = self._call("POST", "/mix", json={"ingredients": ["лёд", "молоко", "текила"]})
        self._assert("Ошибка бармена создана", mistake.get("drink") == "Ошибка бармена")
        self._assert("Эффект mood_max", mistake.get("effect") == "mood_max")
        self._assert("Настроение friendly", mistake.get("mood_level") == "friendly")

        # Секрет: Зелье бармена
        self._reset_and_wait()
        potion = self._call("POST", "/mix", json={"ingredients": ["джин", "лёд", "сок", "тоник"]})
        self._assert("Зелье создано", potion.get("drink") == "Зелье бармена")
        self._assert("Эффект secret_unlocked", potion.get("effect") == "secret_unlocked")

    def test_bar_closed(self):
        print("\n📦 7. Армагеддон и закрытие бара")
        self._reset_and_wait()

        # Запускаем Армагеддон
        arm = self._call("POST", "/mix", json={"ingredients": ["водка", "ром", "текила", "виски", "джин"]})
        self._assert("Армагеддон активирован", arm.get("effect") == "armageddon")
        self._assert("Баланс 0", arm.get("balance") == 0)
        self._assert("Настроение hostile", arm.get("mood_level") == "hostile")

        # Проверяем закрытие на всех эндпоинтах
        menu = self._call("GET", "/menu")
        self._assert("Меню закрыто", menu.get("error") == "bar_closed")
        self._assert("Есть reopens_at", "reopens_at" in menu and re.match(r"^\d{2}:\d{2}$", menu["reopens_at"]),
                     menu.get("reopens_at"))

        order = self._call("POST", "/order", json={"name": "Русский"})
        self._assert("Заказ отклонён", order.get("error") == "bar_closed")

        mix = self._call("POST", "/mix", json={"ingredients": ["водка", "лёд"]})
        self._assert("Микс отклонён", mix.get("error") == "bar_closed")

        # Сброс открывает бар
        self._call("POST", "/reset")
        menu_open = self._call("GET", "/menu")
        self._assert("Бар открыт после reset", menu_open.get("status") == "ok")

    def test_tips_validation(self):
        print("\n📦 8. Чаевые и валидация")
        self._reset_and_wait()

        # Float -> 422
        f = self._call("POST", "/tip", json={"amount": 5.5})
        self._assert("Float чаевые -> 422", f.get("status_code") == 422 or "int_from_float" in str(f))

        # 0 -> invalid_amount
        z = self._call("POST", "/tip", json={"amount": 0})
        self._assert("0₽ -> invalid_amount", z.get("error") == "invalid_amount")

        # Отрицательные -> invalid_amount
        n = self._call("POST", "/tip", json={"amount": -5})
        self._assert("-5₽ -> invalid_amount", n.get("error") == "invalid_amount")

        # Больше баланса -> insufficient_funds
        b = self._call("POST", "/tip", json={"amount": 150})
        self._assert("150₽ -> insufficient_funds", b.get("error") == "insufficient_funds")

        # Успешные
        ok = self._call("POST", "/tip", json={"amount": 25})
        self._assert("25₽ успешно", ok.get("status") == "ok")
        self._assert("Баланс 75", ok.get("balance") == 75)

    def test_http_errors_and_security(self):
        print("\n📦 9. HTTP статусы и защита")
        self._reset_and_wait()

        # 401 Unauthorized
        s2 = requests.Session()
        r401 = s2.get(f"{self.base}/menu")
        self._assert("401 без токена", r401.status_code == 401)

        # 404 Not Found
        r404 = self._call("GET", "/nonexistent")
        self._assert("404 для неизвестного пути", r404.get("status_code") == 404)

        # 405 Method Not Allowed
        r405 = self._call("PUT", "/reset", json={})
        self._assert("405 PUT /reset", r405.get("status_code") == 405)

        r405b = self._call("DELETE", "/order")
        self._assert("405 DELETE /order", r405b.get("status_code") == 405)

        # 422 Bad Body
        r422 = self._call("POST", "/order", json={"drink": "Русский"})
        self._assert("422 неверное поле", r422.get("status_code") == 422 or "missing" in str(r422))

        # /secret GET
        sec = self._call("GET", "/secret")
        self._assert("/secret -> not_found", sec.get("error") == "not_found")

    def run_full(self) -> bool:
        print("🚀 ЗАПУСК ПОЛНОГО ТЕСТА BLACK BARTENDER API")
        print("=" * 50)
        try:
            self.test_register()
            self.test_day_menu_and_base_prices()
            self.test_night_menu()
            self.test_mood_progression_and_pricing()
            self.test_orders_favorites_and_rank()
            self.test_mixes_and_secrets()
            self.test_bar_closed()
            self.test_tips_validation()
            self.test_http_errors_and_security()
        except KeyboardInterrupt:
            print("\n⚠️ Тест прерван пользователем.")
        except Exception as e:
            print(f"\n💥 Критическая ошибка: {e}")
            import traceback
            traceback.print_exc()
            self.failed += 1

        print("\n" + "=" * 50)
        print(f"📊 ИТОГ: ✅ {self.passed} | ❌ {self.failed}")
        return self.failed == 0


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    tester = DeepBartenderTest(url)
    success = tester.run_full()
    sys.exit(0 if success else 1)