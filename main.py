import time
import uuid
import datetime
from typing import List, Optional, Dict, Any
from collections import defaultdict

from fastapi import FastAPI, Request, Header, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Black Bartender Clone")

# ---------------- КОНФИГУРАЦИЯ И ЦЕНЫ ----------------
PRICES = {
    "normal": {"Куба Либре": 15, "Отвёртка": 12, "Джин-тоник": 14, "Виски-кола": 13, "Текила-санрайз": 14,
               "Русский": 10, "Белый русский": 16, "Лонг-Айленд": 25},
    "grumpy": {"Куба Либре": 18, "Отвёртка": 15, "Джин-тоник": 17, "Виски-кола": 16, "Текила-санрайз": 17, "Русский": 9,
               "Белый русский": 20, "Лонг-Айленд": 30},
    "hostile": {"Куба Либре": 23, "Отвёртка": 18, "Джин-тоник": 21, "Виски-кола": 20, "Текила-санрайз": 21,
                "Русский": 11, "Белый русский": 24, "Лонг-Айленд": 38},
    "friendly": {"Куба Либре": 12, "Отвёртка": 10, "Джин-тоник": 11, "Виски-кола": 10, "Текила-санрайз": 11,
                 "Русский": 8, "Белый русский": 13, "Лонг-Айленд": 20},
    "generous": {"Куба Либре": 11, "Отвёртка": 9, "Джин-тоник": 13, "Виски-кола": 9, "Текила-санрайз": 10, "Русский": 7,
                 "Белый русский": 12, "Лонг-Айленд": 18}
}

NIGHT_PRICES = {
    "normal": {"Ночной русский": 8, "Бессонница": 10, "Лунный свет": 12},
    "grumpy": {"Ночной русский": 10, "Бессонница": 12, "Лунный свет": 15},
    "hostile": {"Ночной русский": 12, "Бессонница": 15, "Лунный свет": 18},
    "friendly": {"Ночной русский": 6, "Бессонница": 8, "Лунный свет": 10},
    "generous": {"Ночной русский": 5, "Бессонница": 7, "Лунный свет": 9}
}

INGREDIENTS_MAP = {
    "Куба Либре": ["кола", "лёд", "ром"], "Отвёртка": ["водка", "сок"],
    "Джин-тоник": ["джин", "лёд", "тоник"], "Виски-кола": ["виски", "кола"],
    "Текила-санрайз": ["сок", "текила"], "Русский": ["водка", "лёд"],
    "Белый русский": ["водка", "лёд", "молоко"], "Лонг-Айленд": ["водка", "джин", "кола", "ром", "текила"],
    "Ночной русский": ["водка", "лёд", "молоко"], "Бессонница": ["кола", "ром", "тоник"],
    "Лунный свет": ["джин", "сок", "тоник"]
}

RECIPES = {
    frozenset(["водка", "сок"]): "Отвёртка",
    frozenset(["водка", "лёд"]): "Русский",
    frozenset(["текила", "сок"]): "Текила-санрайз",
    frozenset(["виски", "кола"]): "Виски-кола",
    frozenset(["кола", "лёд", "ром"]): "Куба Либре",
    frozenset(["джин", "лёд", "тоник"]): "Джин-тоник",
    frozenset(["водка", "джин", "кола", "ром", "текила"]): "Лонг-Айленд",
    frozenset(["водка", "лёд", "молоко"]): "Белый русский",
    # Секреты
    frozenset(["водка", "ром", "молоко"]): "Мертвец",
    frozenset(["лёд", "молоко", "текила"]): "Ошибка бармена",
    frozenset(["джин", "лёд", "сок", "тоник"]): "Зелье бармена",
    frozenset(["виски", "водка", "джин", "ром", "текила"]): "Армагеддон"
}

VALID_INGREDIENTS = {"водка", "ром", "текила", "виски", "джин", "кола", "сок", "тоник", "лёд", "молоко"}

# Хранилище сессий и лимитов
USERS: Dict[str, dict] = {}
RATE_LIMITS: Dict[str, list] = defaultdict(list)


class OrderReq(BaseModel): name: str


class MixReq(BaseModel): ingredients: List[str]


class TipReq(BaseModel): amount: int


# ---------------- УТИЛИТЫ ----------------
def check_rate_limit(token: str, limit: int = 30, window: int = 60):
    now = time.time()
    reqs = RATE_LIMITS[token]
    reqs[:] = [t for t in reqs if now - t < window]
    if len(reqs) >= limit:
        wait = max(1, round(window - (now - reqs[0])))
        return JSONResponse(status_code=429, content={"status": "error", "error": "rate_limit", "retry_after": wait})
    reqs.append(now)
    return None


def is_night(x_time: Optional[str]) -> bool:
    if not x_time: return False
    try:
        h, m = map(int, x_time.split(":"))
        return 0 <= h < 6
    except:
        return False


def get_user(token: str):
    if token not in USERS:
        return JSONResponse(status_code=401, content={"detail": {"status": "error", "error": "unauthorized"}})
    return USERS[token]


def update_mood(user: dict, delta: int):
    if delta < 0:
        if user["mood"] == "normal":
            user["mood"] = "grumpy"
        elif user["mood"] == "grumpy":
            user["mood"] = "hostile"
    elif delta > 0:
        if user["mood"] in ("normal", "grumpy", "hostile"): user["mood"] = "friendly"


def get_drink_list(night: bool, mood: str) -> list:
    table = NIGHT_PRICES[mood] if night else PRICES[mood]
    return [{"name": n, "price": p, "ingredients": INGREDIENTS_MAP[n]} for n, p in table.items()]


def bar_closed_response(user: dict):
    reopen = datetime.datetime.fromtimestamp(user["bar_closed_until"]).strftime("%H:%M")
    return {"status": "error", "error": "bar_closed", "reopens_at": reopen, "balance": user["balance"],
            "mood_level": user["mood"]}


# ---------------- ЭНДПОИНТЫ ----------------
@app.post("/register")
async def register():
    token = uuid.uuid4().hex
    uid = f"BAR-{uuid.uuid4().hex[:4].upper()}"
    USERS[token] = {
        "id": uid, "balance": 100, "mood": "normal",
        "history": [], "drink_counts": defaultdict(int), "total_orders": 0,
        "generous_orders": 0, "last_drink": None, "consec_same": 0,
        "bar_closed_until": 0, "tip_note": False
    }
    return {"status": "ok", "id": uid, "token": token}


@app.post("/reset")
async def reset(request: Request):
    token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    user = USERS.get(token)
    if not user: return JSONResponse(status_code=401, content={"detail": {"status": "error", "error": "unauthorized"}})
    user.update({"balance": 100, "mood": "normal", "history": [], "drink_counts": defaultdict(int),
                 "total_orders": 0, "generous_orders": 0, "last_drink": None, "consec_same": 0, "bar_closed_until": 0,
                 "tip_note": False})
    return {"status": "ok"}


@app.get("/menu")
async def menu(request: Request, x_time: Optional[str] = Header(None)):
    token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    rl = check_rate_limit(token)
    if rl: return rl
    user = get_user(token)
    if isinstance(user, JSONResponse): return user
    if user["bar_closed_until"] > time.time(): return bar_closed_response(user)

    night = is_night(x_time)
    return {"status": "ok", "drinks": get_drink_list(night, user["mood"]), "balance": user["balance"],
            "mood_level": user["mood"]}


@app.post("/order")
async def order(req: OrderReq, request: Request, x_time: Optional[str] = Header(None)):
    token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    rl = check_rate_limit(token)
    if rl: return rl
    user = get_user(token)
    if isinstance(user, JSONResponse): return user
    if user["bar_closed_until"] > time.time(): return bar_closed_response(user)

    if not req.name or req.name not in PRICES["normal"]:
        update_mood(user, -1)
        return {"status": "error", "error": "unknown_drink", "balance": user["balance"], "mood_level": user["mood"]}

    night = is_night(x_time)
    if night and req.name not in NIGHT_PRICES["normal"]:
        update_mood(user, -1)
        return {"status": "error", "error": "unknown_drink", "balance": user["balance"], "mood_level": user["mood"]}

    # repeat_check логика
    if user["last_drink"] == req.name:
        user["consec_same"] += 1
        if user["consec_same"] >= 4:
            return {"status": "prompt", "prompt": "repeat_check", "balance": user["balance"],
                    "mood_level": user["mood"]}
    else:
        user["last_drink"] = req.name
        user["consec_same"] = 1

    price_table = NIGHT_PRICES[user["mood"]] if night else PRICES[user["mood"]]
    price = price_table.get(req.name, 0)

    user["total_orders"] += 1
    user["drink_counts"][req.name] += 1
    user["generous_orders"] += 1

    free_7th = user["total_orders"] % 7 == 0
    generous_free = user["mood"] == "generous" and user["generous_orders"] % 3 == 0

    final_price = 0 if (free_7th or generous_free) else price

    if user["balance"] < final_price:
        return {"status": "error", "error": "insufficient_funds", "price": final_price, "balance": user["balance"],
                "mood_level": user["mood"]}

    user["balance"] -= final_price
    user["history"].append({"drink": req.name, "price": final_price, "method": "order"})

    resp = {"status": "ok", "drink": req.name, "price": final_price, "balance": user["balance"],
            "mood_level": user["mood"]}
    if free_7th: resp["free_every_7th"] = True
    if generous_free: resp["generous_free"] = True
    if user["drink_counts"][req.name] >= 2: resp["favorite"] = True

    return resp


@app.post("/mix")
async def mix(req: MixReq, request: Request, x_time: Optional[str] = Header(None)):
    token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    rl = check_rate_limit(token)
    if rl: return rl
    user = get_user(token)
    if isinstance(user, JSONResponse): return user
    if user["bar_closed_until"] > time.time(): return bar_closed_response(user)

    ingredients = [i.strip() for i in req.ingredients if i.strip()]
    if not ingredients:
        user["history"].append({"drink": "Воздух", "price": 0, "method": "mix"})
        update_mood(user, -2)
        return {"status": "ok", "drink": "Воздух", "price": 0, "balance": user["balance"], "mood_level": user["mood"]}

    for ing in ingredients:
        if ing not in VALID_INGREDIENTS:
            update_mood(user, -1)
            return {"status": "error", "error": "invalid_ingredient", "balance": user["balance"],
                    "mood_level": user["mood"]}

    key = frozenset(ingredients)
    if key not in RECIPES:
        update_mood(user, -1)
        return {"status": "error", "error": "unknown_recipe", "balance": user["balance"], "mood_level": user["mood"]}

    drink = RECIPES[key]
    # Цена микса = 80% от дневной нормальной цены (округление по правилам Python)
    base_price = PRICES["normal"].get(drink, NIGHT_PRICES["normal"].get(drink, 0))
    price = round(base_price * 0.8)

    # Секреты
    if drink == "Мертвец":
        user["balance"] *= 2
        user["drink_counts"]["Мертвец"] += 1
        return {"status": "ok", "drink": drink, "price": 0, "secret": True, "effect": "balance_doubled",
                "balance": user["balance"], "mood_level": user["mood"]}
    if drink == "Ошибка бармена":
        user["mood"] = "generous"
        user["generous_orders"] = 0
        return {"status": "ok", "drink": drink, "price": 0, "secret": True, "effect": "mood_max",
                "balance": user["balance"], "mood_level": "generous"}
    if drink == "Зелье бармена":
        return {"status": "ok", "drink": drink, "price": 0, "secret": True, "effect": "secret_unlocked",
                "balance": user["balance"], "mood_level": user["mood"]}
    if drink == "Армагеддон":
        user["balance"] = 0
        user["bar_closed_until"] = time.time() + 600
        return {"status": "ok", "drink": drink, "price": 0, "secret": True, "effect": "armageddon", "balance": 0,
                "mood_level": "hostile"}

    if user["balance"] < price:
        return {"status": "error", "error": "insufficient_funds", "price": price, "balance": user["balance"],
                "mood_level": user["mood"]}

    user["balance"] -= price
    user["history"].append({"drink": drink, "price": price, "method": "mix"})
    user["drink_counts"][drink] += 1
    return {"status": "ok", "drink": drink, "price": price, "balance": user["balance"], "mood_level": user["mood"]}


@app.get("/balance")
async def balance(request: Request):
    token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    rl = check_rate_limit(token)
    if rl: return rl
    user = get_user(token)
    if isinstance(user, JSONResponse): return user
    resp = {"status": "ok", "balance": user["balance"], "mood_level": user["mood"]}
    if user.get("tip_note"):
        resp["note"] = "Чаевые всегда поднимают мне настроение."
    return resp


@app.post("/tip")
async def tip(req: TipReq, request: Request):
    token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    rl = check_rate_limit(token)
    if rl: return rl
    user = get_user(token)
    if isinstance(user, JSONResponse): return user

    if req.amount <= 0: return {"status": "error", "error": "invalid_amount", "balance": user["balance"],
                                "mood_level": user["mood"]}
    if req.amount > user["balance"]: return {"status": "error", "error": "insufficient_funds",
                                             "balance": user["balance"], "mood_level": user["mood"]}

    user["balance"] -= req.amount
    update_mood(user, 5)
    if req.amount >= 100:
        user["mood"] = "friendly"
        user["tip_note"] = True
    else:
        user["tip_note"] = False

    return {"status": "ok", "tip": req.amount, "balance": user["balance"], "mood_level": user["mood"]}


@app.get("/history")
async def history(request: Request):
    token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    rl = check_rate_limit(token)
    if rl: return rl
    user = get_user(token)
    if isinstance(user, JSONResponse): return user
    return {"status": "ok", "orders": user["history"][-50:], "balance": user["balance"], "mood_level": user["mood"]}


@app.get("/profile")
async def profile(request: Request):
    token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    rl = check_rate_limit(token)
    if rl: return rl
    user = get_user(token)
    if isinstance(user, JSONResponse): return user

    unique = len(user["drink_counts"])
    rank = "Новичок" if unique == 0 else "Гость" if unique <= 2 else "Постоянный" if unique <= 6 else "Ветеран"
    fav = max(user["drink_counts"], key=user["drink_counts"].get) if user["drink_counts"] else None

    return {"status": "ok", "id": user["id"], "rank": rank, "total_orders": user["total_orders"],
            "unique_drinks": unique, "favorite_drink": fav, "bar_closed": user["bar_closed_until"] > time.time()}


@app.get("/secret")
async def secret_get():
    return {"status": "error", "error": "not_found"}


# Перехват 405 для нестандартных методов
@app.api_route("/{path:path}", methods=["PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def method_not_allowed():
    return JSONResponse(status_code=405, content={"detail": "Method Not Allowed"})


# ---------------- ЗАПУСК ДЛЯ PYCHARM ----------------
if __name__ == "__main__":
    import uvicorn

    print("🍸 Black Bartender API запускается...")
    print("💡 Откройте в браузере: http://127.0.0.1:8000/docs (не обязательно, API работает без него)")
    print("📝 Чтобы запустить тесты, используйте: http://localhost:8000")
    # log_level="info" покажет все запросы прямо в консоли PyCharm
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")