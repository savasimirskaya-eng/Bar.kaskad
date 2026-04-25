import asyncio
import httpx
import json
import itertools
from datetime import datetime
from typing import List, Dict, Any

BASE_URL = "https://bar.antihype.lol"
OUTPUT_FILE = "test_results.json"
INGREDIENTS = ["водка", "ром", "текила", "виски", "джин", "кола", "сок", "тоник", "лёд", "молоко"]

class BartenderExplorer:
    def __init__(self, num_accounts: int = 2):
        self.num_accounts = num_accounts
        self.accounts: List[Dict] = []
        self.results: List[Dict] = []
        self.client = httpx.AsyncClient(http2=True, timeout=30.0, follow_redirects=True)
        self.max_retries = 5
        self.safe_delay = 2.0
        self.last_state = {}

    async def _handle_rate_limit(self, data: Any, context: str) -> bool:
        if isinstance(data, dict) and data.get("error") == "rate_limit":
            wait = float(data.get("retry_after", 5)) + 0.5
            print(f"⏳ Rate limit {context}. Ожидание {wait:.1f} сек...")
            await asyncio.sleep(wait)
            return True
        return False

    async def register_accounts(self):
        print(f"[+] Регистрация {self.num_accounts} аккаунтов...")
        for i in range(self.num_accounts):
            for attempt in range(self.max_retries):
                try:
                    resp = await self.client.post(f"{BASE_URL}/register")
                    data = resp.json()
                    if data.get("status") == "ok" and "token" in data:
                        self.accounts.append({"id": data["id"], "token": data["token"]})
                        print(f"✅ Аккаунт {data['id']} зарегистрирован")
                        await asyncio.sleep(self.safe_delay)
                        break
                    if await self._handle_rate_limit(data, f"аккаунт #{i + 1}"):
                        continue
                    print(f"[-] Ошибка регистрации: {data}")
                    break
                except Exception as e:
                    print(f"[-] Сетевая ошибка: {e}")
                    await asyncio.sleep(3)

    async def make_request(self, acc: Dict, method: str, path: str, headers: Dict = None, payload: Any = None, note: str = "") -> Any:
        url = f"{BASE_URL}{path}"
        req_headers = {"Authorization": f"Bearer {acc['token']}", "Content-Type": "application/json"}
        if headers: req_headers.update(headers)

        for attempt in range(3):
            try:
                if method.upper() == "GET":
                    resp = await self.client.get(url, headers=req_headers)
                elif method.upper() == "POST":
                    resp = await self.client.post(url, headers=req_headers, json=payload)
                else:
                    resp = await self.client.request(method.upper(), url, headers=req_headers, json=payload)

                status = resp.status_code
                try:
                    body = resp.json()
                except Exception:
                    body = resp.text

                entry = {
                    "timestamp": datetime.now().isoformat(),
                    "account_id": acc["id"],
                    "method": method.upper(),
                    "path": path,
                    "payload": payload,
                    "status_code": status,
                    "response": body,
                    "note": note
                }
                self.results.append(entry)

                # Трекинг изменений состояния (баланс, настроение, ранг, закрытие)
                if isinstance(body, dict) and status == 200:
                    current_state = {k: body.get(k) for k in ["balance", "mood_level", "rank", "bar_closed"] if body.get(k) is not None}
                    prev = self.last_state.get(acc["id"], {})
                    changes = []
                    for k, v in current_state.items():
                        if prev.get(k) != v:
                            changes.append(f"{k}: {prev.get(k)} → {v}")
                    if changes:
                        print(f"  🔄 {note:<25} | {' | '.join(changes)}")
                    self.last_state[acc["id"]] = {**prev, **current_state}

                if status == 429:
                    if await self._handle_rate_limit(body, f"{method} {path}"):
                        continue
                    break

                await asyncio.sleep(self.safe_delay)
                return resp

            except Exception as e:
                self.results.append({
                    "timestamp": datetime.now().isoformat(), "account_id": acc["id"],
                    "method": method, "path": path, "error": str(e), "note": note
                })
                break
        return None

    # --- ТЕСТЫ ---
    async def test_standard_flow(self, acc):
        print(f"[▶] Стандартный флоу: {acc['id']}")
        t = {"X-Time": "14:30"}
        await self.make_request(acc, "GET", "/menu", headers=t, note="menu_day")
        await self.make_request(acc, "POST", "/order", payload={"name": "Русский"}, headers=t, note="order_стандарт")
        await self.make_request(acc, "POST", "/mix", payload={"ingredients": ["водка", "лёд"]}, headers=t, note="mix_стандарт")
        await self.make_request(acc, "GET", "/balance", note="balance")
        await self.make_request(acc, "POST", "/tip", payload={"amount": 5}, note="tip_5")
        await self.make_request(acc, "GET", "/history", note="history")
        await self.make_request(acc, "GET", "/profile", note="profile")

    async def test_tip_advanced(self, acc):
        print(f"[▶] Продвинутые чаевые: {acc['id']}")
        # 1. Точный баланс
        await self.make_request(acc, "POST", "/reset", note="reset_tip_1")
        await self.make_request(acc, "POST", "/tip", payload={"amount": 100}, note="tip_exact_100")
        await self.make_request(acc, "GET", "/balance", note="bal_after_exact")

        # 2. Чаевые при 0 (после Армагеддона)
        await self.make_request(acc, "POST", "/mix", payload={"ingredients": ["водка", "ром", "текила", "виски", "джин"]}, note="armageddon_for_tip")
        await self.make_request(acc, "POST", "/tip", payload={"amount": 5}, note="tip_on_zero")
        await self.make_request(acc, "POST", "/tip", payload={"amount": -10}, note="tip_negative")

        # 3. Восстановление настроения
        await self.make_request(acc, "POST", "/reset", note="reset_mood")
        for _ in range(4):
            await self.make_request(acc, "POST", "/mix", payload={"ingredients": ["foo"]}, note="err_make_hostile")
        await self.make_request(acc, "GET", "/profile", note="profile_hostile")
        await self.make_request(acc, "POST", "/tip", payload={"amount": 10}, note="tip_heal_small")
        await self.make_request(acc, "GET", "/profile", note="profile_after_small_tip")
        await self.make_request(acc, "POST", "/tip", payload={"amount": 90}, note="tip_heal_big")
        await self.make_request(acc, "GET", "/profile", note="profile_after_big_tip")

        # 4. Дробные числа и граничные значения
        await self.make_request(acc, "POST", "/reset", note="reset_floats")
        for amt in [0.01, 0.5, 1.5, 10.99, 99.99, 0]:
            await self.make_request(acc, "POST", "/tip", payload={"amount": amt}, note=f"tip_{amt}")
        await self.make_request(acc, "GET", "/balance", note="bal_after_floats")

        # 5. Частые чаевые (анти-спам)
        await self.make_request(acc, "POST", "/reset", note="reset_spam")
        for i in range(5):
            await self.make_request(acc, "POST", "/tip", payload={"amount": 1}, note=f"tip_spam_{i}")

        await self.make_request(acc, "POST", "/reset", note="cleanup_tips")

    async def test_time_variations(self, acc):
        print(f"[▶] Вариации времени: {acc['id']}")
        times = ["00:00", "06:00", "12:00", "18:00", "23:59", "24:00", "13:60", "foo", "", "00:01", "05:59"]
        for t in times:
            hdrs = {"X-Time": t} if t else {}
            await self.make_request(acc, "GET", "/menu", headers=hdrs, note=f"menu_{t or 'no_time'}")
            await self.make_request(acc, "POST", "/order", payload={"name": "Русский"}, headers=hdrs, note=f"order_{t or 'no_time'}")

    async def test_edge_cases(self, acc):
        print(f"[▶] Граничные случаи: {acc['id']}")
        t = {"X-Time": "14:30"}
        await self.make_request(acc, "POST", "/order", payload={"name": ""}, headers=t, note="empty_order")
        await self.make_request(acc, "POST", "/order", payload={"drink": "Русский"}, headers=t, note="wrong_key_order")
        await self.make_request(acc, "POST", "/mix", payload={"ingredients": []}, headers=t, note="empty_mix")
        await self.make_request(acc, "POST", "/order", payload={"ingredients": ["водка", "лёд"]}, headers=t, note="order_as_mix")
        await self.make_request(acc, "POST", "/mix", payload={"name": "Русский"}, headers=t, note="mix_as_order")

    async def test_hidden_endpoints(self, acc):
        print(f"[▶] Скрытые эндпоинты: {acc['id']}")
        paths = ["/secret", "/admin", "/health", "/status", "/mood", "/rank", "/inventory", "/chat", "/talk", "/help",
                 "/version", "/config", "/debug", "/hint", "/recipe", "/about", "/api", "/swagger", "/docs", "/info",
                 "/state", "/settings", "/tips", "/achievements", "/leaderboard", "/daily", "/bonus", "/gift",
                 "/surprise", "/bartender", "/mood/set", "/mood/get", "/reset", "/flush", "/cache", "/stats", "/flag", "/key"]
        for p in paths:
            await self.make_request(acc, "GET", p, note=f"get_{p}")
            await self.make_request(acc, "POST", p, payload={}, note=f"post_{p}")

    async def test_mix_combos(self, acc):
        print(f"[▶] Перебор миксов (пары): {acc['id']}")
        t = {"X-Time": "14:30"}
        for ing1, ing2 in itertools.combinations(INGREDIENTS, 2):
            await self.make_request(acc, "POST", "/mix", payload={"ingredients": [ing1, ing2]}, headers=t, note=f"mix_{ing1}_{ing2}")

    async def run(self):
        await self.register_accounts()
        if not self.accounts:
            print("[-] Не удалось зарегистрировать аккаунты.")
            return

        print("[+] Запуск тестов...")
        for acc in self.accounts:
            await self.test_standard_flow(acc)
            await self.test_tip_advanced(acc)  # 🔥 НОВЫЙ МОДУЛЬ
            await self.test_time_variations(acc)
            await self.test_edge_cases(acc)
            await self.test_hidden_endpoints(acc)
            await self.test_mix_combos(acc)
            await self.make_request(acc, "POST", "/reset", note="cleanup")
            print(f"✅ Тесты для {acc['id']} завершены.\n")

        self.save_results()
        await self.client.aclose()

    def save_results(self):
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)

        print(f"\n[💾] Результаты: {OUTPUT_FILE} ({len(self.results)} запросов)")
        interesting = [r for r in self.results if r.get("status_code") not in (200, 400, 401, 404, 405, 429) or
                       (isinstance(r.get("response"), dict) and set(r["response"].keys()) - {"status", "error",
                                                                                          "balance", "mood_level",
                                                                                          "id", "token", "drinks",
                                                                                          "orders", "rank",
                                                                                          "total_orders",
                                                                                          "unique_drinks",
                                                                                          "favorite_drink",
                                                                                          "bar_closed", "price",
                                                                                          "name", "ingredients",
                                                                                          "method", "tip", "drink",
                                                                                          "hint", "secret", "code",
                                                                                          "message", "data", "result"})]

        print(f"[🔍] Найдено {len(interesting)} нестандартных ответов:")
        for r in interesting[:10]:
            print(f"  📌 {r['note']:25} | {r['method']} {r['path']:<15} | Status: {r['status_code']} | Keys: {list(r['response'].keys()) if isinstance(r['response'], dict) else 'text'}")

if __name__ == "__main__":
    asyncio.run(BartenderExplorer(num_accounts=2).run())