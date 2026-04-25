import time
import uuid
import math
import datetime
from typing import List, Optional, Dict, Any
from collections import defaultdict

from fastapi import FastAPI, Request, Header, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

app = FastAPI(title="Black Bartender Clone")

# --- Конфигурация и Данные ---
VALID_INGREDIENTS = {"водка", "ром", "текила", "виски", "джин", "кола", "сок", "тоник", "лёд", "молоко"}

PRICES = {
    "normal_day": {"Куба Либре": 15, "Отвёртка": 12, "Джин-тоник": 14, "Виски-кола": 13, "Текила-санрайз": 14,
                   "Русский": 10, "Белый русский": 16, "Лонг-Айленд": 25},
    "grumpy_day": {"Куба Либре": 18, "Отвёртка": 15, "Джин-тоник": 17, "Виски-кола": 16, "Текила-санрайз": 17,
                   "Русский": 9, "Белый русский": 20, "Лонг-Айленд": 30},
    "hostile_day": {"Куба Либре": 23, "Отвёртка": 18, "Джин-тоник": 21, "Виски-кола": 20, "Текила-санрайз": 21,
                    "Русский": 15, "Белый русский": 24, "Лонг-Айленд": 38},
    "normal_night": {"Ночной русский": 8, "Бессонница": 10, "Лунный свет": 12},
    "grumpy_night": {"Ночной русский": 10, "Бессонница": 12, "Лунный свет": 15},
    "hostile_night": {"Ночной русский": 12, "Бессонница": 15, "Лунный свет": 18}
}

MIX_RECIPES = {
    frozenset(["водка", "сок"]): "Отвёртка",
    frozenset(["водка", "лёд"]): "Русский",
    frozenset(["текила", "сок"]): "Текила-санрайз",
    frozenset(["виски", "кола"]): "Виски-кола",
    frozenset(["кола", "лёд", "ром"]): "Куба Либре",
    frozenset(["джин", "лёд", "тоник"]): "Джин-тоник",
    frozenset(["водка", "джин", "кола", "ром", "текила"]): "Лонг-Айленд",
    frozenset(["водка", "лёд", "молоко"]): "Белый русский",
    # Секретные
    frozenset(["водка", "молоко", "ром"]): "Мертвец",
    frozenset(["лёд", "молоко", "текила"]): "Ошибка бармена",
    frozenset(["джин", "лёд", "сок", "тоник"]): "Зелье бармена",
    frozenset(["виски", "водка", "джин", "ром", "текила"]): "Армагеддон"
}

# Хранилище состояний
USERS: Dict[str, dict] = {}


# --- Модели запросов ---
class OrderReq(BaseModel):
    name: str


class MixReq(BaseModel):
    ingredients: List[str]


class TipReq(BaseModel):
    amount: int


# --- Вспомогательные функции ---
def get_user(token: str):
    if token not in USERS:
        raise HTTPException(status_code=401, detail={"status": "error", "error": "unauthorized"})
    return USERS[token]


def parse_xtime(x_time: Optional[str]) -> str:
    if not x_time or not isinstance(x_time, str):
        return "12:00"
    try:
        h, m = map(int, x_time.split(":"))
        if 0 <= h < 24 and 0 <= m < 60:
            return x_time
    except:
        pass
    return "12:00"


def is_night(time_str: str) -> bool:
    h = int(time_str.split(":")[0])
    return 0 <= h < 6


def get_price_table(mood: str, night: bool) -> dict:
    key = f"{mood}_{'night' if night else 'day'}"
    return PRICES.get(key, PRICES["normal_day"])


def update_mood(user: dict, delta: int):
    user["mood_score"] = max(0, min(10, user["mood_score"] + delta))
    s = user["mood_score"]
    if s >= 8:
        user["mood"] = "friendly"
    elif s >= 5:
        user["mood"] = "normal"
    elif s >= 3:
        user["mood"] = "grumpy"
    else:
        user["mood"] = "hostile"


def get_rank(unique: int) -> str:
    if unique == 0: return "Новичок"
    if unique <= 2: return "Гость"
    if unique <= 5: return "Постоянный"
    return "Ветеран"


def get_favorite(drink_counts: dict) -> Optional[str]:
    if not drink_counts: return None
    return max(drink_counts.items(), key=lambda x: x[1])[0]


def check_rate_limit(user: dict, limit: int = 30, window: int = 60):
    now = time.time()
    user["requests"] = [t for t in user["requests"] if now - t < window]
    if len(user["requests"]) >= limit:
        wait = round(window - (now - user["requests"][0]))
        raise HTTPException(status_code=429,
                            detail={"status": "error", "error": "rate_limit", "retry_after": max(1, wait)})
    user["requests"].append(now)


def check_bar_closed(user: dict):
    if user["bar_closed_until"] > time.time():
        reopen = datetime.datetime.fromtimestamp(user["bar_closed_until"]).strftime("%H:%M")
        return JSONResponse(status_code=200, content={
            "status": "error", "error": "bar_closed", "reopens_at": reopen,
            "balance": user["balance"], "mood_level": user["mood"]
        })
    return None


# --- Зависимости ---
async def get_auth_user(request: Request, x_time: Optional[str] = Header(None)):
    auth = request.headers.get("authorization", "")
    token = auth.replace("Bearer ", "").strip()
    if not token or token not in USERS:
        raise HTTPException(status_code=401, detail={"status": "error", "error": "unauthorized"})
    user = USERS[token]
    user["x_time"] = parse_xtime(x_time)
    check_rate_limit(user)
    return user


# --- Эндпоинты ---
@app.post("/register")
async def register():
    uid = f"BAR-{uuid.uuid4().hex[:4].upper()}"
    token = uuid.uuid4().hex
    USERS[token] = {
        "id": uid, "balance": 100, "mood": "normal", "mood_score": 5,
        "history": [], "drink_counts": defaultdict(int), "total_orders": 0,
        "bar_closed_until": 0, "requests": [], "x_time": "12:00",
        "secret_unlocked": False
    }
    return {"status": "ok", "id": uid, "token": token}


@app.post("/reset")
async def reset(user: dict = Depends(get_auth_user)):
    user.update({"balance": 100, "mood": "normal", "mood_score": 5, "history": [],
                 "drink_counts": defaultdict(int), "total_orders": 0,
                 "bar_closed_until": 0, "secret_unlocked": False})
    return {"status": "ok"}


@app.get("/menu")
async def menu(user: dict = Depends(get_auth_user)):
    blocked = check_bar_closed(user)
    if blocked: return blocked

    night = is_night(user["x_time"])
    prices = get_price_table(user["mood"], night)
    drinks = []
    for name, price in prices.items():
        ing = [ing for ing in MIX_RECIPES.keys() if any(name in MIX_RECIPES[k] for k in [ing])][0] if not night else []
        # Восстанавливаем ингредиенты из базы или хардкодим для скорости
        if not night:
            ing_map = {
                "Куба Либре": ["кола", "лёд", "ром"], "Отвёртка": ["водка", "сок"],
                "Джин-тоник": ["джин", "лёд", "тоник"], "Виски-кола": ["виски", "кола"],
                "Текила-санрайз": ["сок", "текила"], "Русский": ["водка", "лёд"],
                "Белый русский": ["водка", "лёд", "молоко"], "Лонг-Айленд": ["водка", "джин", "кола", "ром", "текила"]
            }
            ing = ing_map.get(name, [])
        else:
            ing_map = {"Ночной русский": ["водка", "лёд", "молоко"], "Бессонница": ["кола", "ром", "тоник"],
                       "Лунный свет": ["джин", "сок", "тоник"]}
            ing = ing_map.get(name, [])

        drinks.append({"name": name, "price": price, "ingredients": ing})
    return {"status": "ok", "drinks": drinks, "balance": user["balance"], "mood_level": user["mood"]}


@app.post("/order")
async def order(req: OrderReq, user: dict = Depends(get_auth_user)):
    blocked = check_bar_closed(user)
    if blocked: return blocked

    if not req.name or req.name not in PRICES["normal_day"]:
        update_mood(user, -1)
        return {"status": "error", "error": "unknown_drink", "balance": user["balance"], "mood_level": user["mood"]}

    night = is_night(user["x_time"])
    price_table = get_price_table(user["mood"], night)
    if req.name not in price_table:
        # Дневной напиток ночью или наоборот
        update_mood(user, -1)
        return {"status": "error", "error": "unknown_drink", "balance": user["balance"], "mood_level": user["mood"]}

    price = price_table[req.name]
    user["total_orders"] += 1
    user["drink_counts"][req.name] += 1

    free = user["total_orders"] % 7 == 0
    if free:
        price = 0

    if user["balance"] < price:
        update_mood(user, -1)
        return {"status": "error", "error": "insufficient_funds", "price": price, "balance": user["balance"],
                "mood_level": user["mood"]}

    user["balance"] -= price
    user["history"].append({"drink": req.name, "price": price, "method": "order"})

    resp = {"status": "ok", "drink": req.name, "price": price, "balance": user["balance"], "mood_level": user["mood"]}
    if free: resp["free_every_7th"] = True
    if user["drink_counts"][req.name] >= 2:
        resp["favorite"] = (req.name == get_favorite(user["drink_counts"]))

    return resp


@app.post("/mix")
async def mix(req: MixReq, user: dict = Depends(get_auth_user)):
    blocked = check_bar_closed(user)
    if blocked: return blocked

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
    if key not in MIX_RECIPES:
        update_mood(user, -1)
        return {"status": "error", "error": "unknown_recipe", "balance": user["balance"], "mood_level": user["mood"]}

    drink_name = MIX_RECIPES[key]
    night = is_night(user["x_time"])
    order_price = get_price_table(user["mood"], night).get(drink_name, 0)
    price = max(0, round(order_price * 0.8)) if order_price else 0

    # Секретные эффекты
    if drink_name == "Мертвец":
        user["balance"] *= 2
        return {"status": "ok", "drink": drink_name, "price": 0, "secret": True, "effect": "balance_doubled",
                "balance": user["balance"], "mood_level": user["mood"]}
    if drink_name == "Ошибка бармена":
        update_mood(user, 10)
        return {"status": "ok", "drink": drink_name, "price": 0, "secret": True, "effect": "mood_max",
                "balance": user["balance"], "mood_level": user["mood"]}
    if drink_name == "Зелье бармена":
        user["secret_unlocked"] = True
        return {"status": "ok", "drink": drink_name, "price": 0, "secret": True, "effect": "secret_unlocked",
                "balance": user["balance"], "mood_level": user["mood"]}
    if drink_name == "Армагеддон":
        user["balance"] = 0
        user["bar_closed_until"] = time.time() + 600
        return {"status": "ok", "drink": drink_name, "price": 0, "secret": True, "effect": "armageddon", "balance": 0,
                "mood_level": "hostile"}

    if user["balance"] < price:
        update_mood(user, -1)
        return {"status": "error", "error": "insufficient_funds", "price": price, "balance": user["balance"],
                "mood_level": user["mood"]}

    user["balance"] -= price
    user["history"].append({"drink": drink_name, "price": price, "method": "mix"})
    return {"status": "ok", "drink": drink_name, "price": price, "balance": user["balance"], "mood_level": user["mood"]}


@app.get("/balance")
async def balance(user: dict = Depends(get_auth_user)):
    return {"status": "ok", "balance": user["balance"], "mood_level": user["mood"]}


@app.post("/tip")
async def tip(req: TipReq, user: dict = Depends(get_auth_user)):
    blocked = check_bar_closed(user)
    if blocked: return blocked

    if req.amount <= 0:
        return {"status": "error", "error": "invalid_amount", "balance": user["balance"], "mood_level": user["mood"]}
    if req.amount > user["balance"]:
        return {"status": "error", "error": "insufficient_funds", "balance": user["balance"],
                "mood_level": user["mood"]}

    user["balance"] -= req.amount
    update_mood(user, 5)
    return {"status": "ok", "tip": req.amount, "balance": user["balance"], "mood_level": user["mood"]}


@app.get("/history")
async def history(user: dict = Depends(get_auth_user)):
    return {"status": "ok", "orders": user["history"][-50:], "balance": user["balance"], "mood_level": user["mood"]}


@app.get("/profile")
async def profile(user: dict = Depends(get_auth_user)):
    return {
        "status": "ok",
        "id": user["id"],
        "rank": get_rank(len(user["drink_counts"])),
        "total_orders": user["total_orders"],
        "unique_drinks": len(user["drink_counts"]),
        "favorite_drink": get_favorite(user["drink_counts"]),
        "bar_closed": user["bar_closed_until"] > time.time()
    }


# Обработка 405 для неверных методов
@app.api_route("/{path:path}", methods=["PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def method_not_allowed():
    return JSONResponse(status_code=405, content={"detail": "Method Not Allowed"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)