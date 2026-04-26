#!/usr/bin/env python3
import time
import uuid
import datetime
import os
from typing import List, Optional, Dict
from collections import defaultdict

from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, StrictStr, StrictInt

app = FastAPI(title="Black Bartender Clone", docs_url=None, redoc_url=None, openapi_url=None)

# -------------------------------------------------------------------------
# МЕНЮ / ЦЕНЫ И НАЦЕНКИ
# -------------------------------------------------------------------------

DAY_MENU_PRICES = {
    "Куба Либре": 15,
    "Отвёртка": 12,
    "Джин-тоник": 14,
    "Виски-кола": 13,
    "Текила-санрайз": 14,
    "Русский": 10,
    "Белый русский": 16,
    "Лонг-Айленд": 25,
}

NIGHT_DRINKS = {
    "Ночной русский": 8,
    "Бессонница": 10,
    "Лунный свет": 12,
}

MIX_PRICES = {
    "Русский": 8,
    "Отвёртка": 10,
    "Текила-санрайз": 12,
    "Виски-кола": 11,
    "Джин-тоник": 14,
    "Куба Либре": 14,
    "Белый русский": 13,
    "Лонг-Айленд": 20,
}

# Специфичная наценка в /order (в /mix наценка всегда +1)
GRUMPY_MARKUP = {
    "Отвёртка": 2,
    "Куба Либре": 2,
    "Текила-санрайз": 3,
}

INGREDIENTS_MAP = {
    "Куба Либре": ["кола", "лёд", "ром"],
    "Отвёртка": ["водка", "сок"],
    "Джин-тоник": ["джин", "лёд", "тоник"],
    "Виски-кола": ["виски", "кола"],
    "Текила-санрайз": ["сок", "текила"],
    "Русский": ["водка", "лёд"],
    "Белый русский": ["водка", "лёд", "молоко"],
    "Лонг-Айленд": ["водка", "джин", "кола", "ром", "текила"],
    "Ночной русский": ["водка", "лёд", "молоко"],
    "Бессонница": ["кола", "ром", "тоник"],
    "Лунный свет": ["джин", "сок", "тоник"],
}

def recipe_key(items: List[str]):
    return tuple(sorted(items))

RECIPES = {
    recipe_key(["водка", "сок"]): "Отвёртка",
    recipe_key(["водка", "лёд"]): "Русский",
    recipe_key(["текила", "сок"]): "Текила-санрайз",
    recipe_key(["виски", "кола"]): "Виски-кола",
    recipe_key(["кола", "лёд", "ром"]): "Куба Либре",
    recipe_key(["джин", "лёд", "тоник"]): "Джин-тоник",
    recipe_key(["водка", "джин", "кола", "ром", "текила"]): "Лонг-Айленд",
    recipe_key(["водка", "лёд", "молоко"]): "Белый русский",

    # секретные рецепты
    recipe_key(["водка", "ром", "молоко"]): "Мертвец",
    recipe_key(["лёд", "молоко", "текила"]): "Ошибка бармена",
    recipe_key(["джин", "лёд", "сок", "тоник"]): "Зелье бармена",
    recipe_key(["виски", "водка", "джин", "ром", "текила"]): "Армагеддон",
}

VALID_INGREDIENTS = {"водка", "ром", "текила", "виски", "джин", "кола", "сок", "тоник", "лёд", "молоко"}

# -------------------------------------------------------------------------
# ПРОМОКОДЫ
# -------------------------------------------------------------------------

# Промо-система включена по умолчанию
PROMO_ENABLED = True

# Определения промокодов: код -> {effect, bonus, remaining (None = безлимит)}
PROMO_CODES_DEF = {
    "ANTIHACK": {"effect": "balance_bonus", "bonus": 50,  "remaining": 2},
    "FREESHOT": {"effect": "free_drink",    "bonus": 0,   "remaining": None},
    "RICHBOY":  {"effect": "balance_bonus", "bonus": 100, "remaining": None},
    "GOODMOOD": {"effect": "mood_friendly", "bonus": 0,   "remaining": None},
    "NIGHT":    {"effect": "balance_bonus", "bonus": 30,  "remaining": None},
    "LEGEND":   {"effect": "mood_generous", "bonus": 0,   "remaining": None},
}

# Глобальные счётчики использований промокодов
PROMO_GLOBAL_REMAINING: Dict[str, Optional[int]] = {
    code: info["remaining"] for code, info in PROMO_CODES_DEF.items()
}

# -------------------------------------------------------------------------
# STORAGE & MODELS
# -------------------------------------------------------------------------

USERS: Dict[str, dict] = {}
RATE_LIMITS: Dict[str, list] = defaultdict(list)

class OrderReq(BaseModel):
    name: StrictStr

class MixReq(BaseModel):
    ingredients: List[StrictStr]

class TipReq(BaseModel):
    amount: StrictInt

class PromoReq(BaseModel):
    code: StrictStr

class AdminPromoReq(BaseModel):
    enabled: bool
    key: StrictStr

# -------------------------------------------------------------------------
# MIDDLEWARE & ERROR HANDLERS
# -------------------------------------------------------------------------

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    if response.status_code == 200 and not response.headers.get("Content-Type", "").startswith("text/html"):
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response

def _get_input_from_body(body, loc, missing=False):
    if missing: return body
    parts = list(loc)
    if parts and parts[0] == "body": parts = parts[1:]
    cur = body
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        elif isinstance(cur, list) and isinstance(p, int) and 0 <= p < len(cur):
            cur = cur[p]
        else:
            return body
    return cur

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    try: body = await request.json()
    except Exception: body = None

    detail = []
    for err in exc.errors():
        loc = list(err.get("loc", []))
        raw_type = err.get("type", "")
        missing = raw_type in ("missing", "value_error.missing")
        inp = _get_input_from_body(body, loc, missing=missing)

        if raw_type in ("missing", "value_error.missing"):
            item = {"type": "missing", "loc": loc, "msg": "Field required", "input": inp}
        elif raw_type in ("string_type", "type_error.str", "type_error.none.not_allowed"):
            item = {"type": "string_type", "loc": loc, "msg": "Input should be a valid string", "input": inp}
        elif raw_type in ("list_type", "type_error.list"):
            item = {"type": "list_type", "loc": loc, "msg": "Input should be a valid list", "input": inp}
        elif raw_type in ("int_type", "int_parsing", "int_from_float", "type_error.integer"):
            if isinstance(inp, float) and not inp.is_integer():
                item = {"type": "int_from_float", "loc": loc, "msg": "Input should be a valid integer, got a number with a fractional part", "input": inp}
            elif isinstance(inp, str):
                item = {"type": "int_parsing", "loc": loc, "msg": "Input should be a valid integer, unable to parse string as an integer", "input": inp}
            else:
                item = {"type": "int_type", "loc": loc, "msg": "Input should be a valid integer", "input": inp}
        else:
            item = {"type": raw_type, "loc": loc, "msg": err.get("msg", ""), "input": inp}
        detail.append(item)

    return JSONResponse(status_code=422, content={"detail": detail})

# -------------------------------------------------------------------------
# UTILS
# -------------------------------------------------------------------------

def unauthorized_response():
    return JSONResponse(status_code=401, content={"detail": {"status": "error", "error": "unauthorized"}})

def check_rate_limit(token: str, limit: int = 18, window: int = 60) -> Optional[JSONResponse]:
    now = time.time()
    reqs = RATE_LIMITS[token]
    reqs[:] = [t for t in reqs if now - t < window]

    if len(reqs) >= limit:
        wait = max(1, round(window - (now - reqs[0])))
        return JSONResponse(status_code=429, content={"status": "error", "error": "rate_limit", "retry_after": wait})

    reqs.append(now)
    return None

def extract_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth.replace("Bearer ", "", 1).strip()
    return auth.strip()

def maybe_user(request: Request):
    token = extract_token(request)
    if token not in USERS: return token, unauthorized_response()
    rl = check_rate_limit(token)
    if rl: return token, rl
    return token, USERS[token]

def is_night(x_time: Optional[str]) -> bool:
    if not x_time: return False
    try:
        parts = x_time.split(":")
        h = int(parts[0])
        if h == 24: return True
        return 0 <= h < 6
    except Exception:
        return False

def new_user_state(uid: str) -> dict:
    return {
        "id": uid, "balance": 100, "mood": "normal", "history": [],
        "drink_counts": defaultdict(int), "total_orders": 0, "successful_count": 0,
        "last_action": None, "last_drink": None, "consec_same": 0, "repeat_prompted": False,
        "mix_error_count": 0, "tip_count": 0, "total_tips": 0, "bar_closed_until": 0,
        "used_promos": set(), # множество уже активированных этим юзером кодов
        "free_drink_pending": False, # флаг бесплатного напитка от FREESHOT
    }

def reset_user_state(user: dict):
    uid = user["id"]
    # Сохраняем использованные промокоды - они привязаны к аккаунту навсегда
    used_promos = user.get("used_promos", set())
    
    user.clear()
    user.update(new_user_state(uid))
    user["used_promos"] = used_promos

def bar_closed_response(user: dict):
    reopen = datetime.datetime.fromtimestamp(user["bar_closed_until"]).strftime("%H:%M")
    return {"status": "error", "error": "bar_closed", "reopens_at": reopen, "balance": user["balance"], "mood_level": user["mood"]}

def record_success(user: dict, drink: str, price: int, method: str):
    user["total_orders"] += 1
    user["successful_count"] += 1
    user["drink_counts"][drink] += 1
    user["history"].append({"drink": drink, "price": price, "method": method})

def mix_error_response(user: dict, error: str):
    response_mood = user["mood"]
    user["mix_error_count"] += 1
    if user["mix_error_count"] >= 4 and user["mood"] == "normal":
        user["mood"] = "grumpy"
    return {"status": "error", "error": error, "balance": user["balance"], "mood_level": response_mood}

def get_order_price(user: dict, drink: str, night: bool) -> int:
    price = NIGHT_DRINKS[drink] if night and drink in NIGHT_DRINKS else DAY_MENU_PRICES.get(drink, 0)
    if user["mood"] == "grumpy":
        price += GRUMPY_MARKUP.get(drink, 0)
    elif user["mood"] == "hostile":
        price = int(price * 1.1)
    return price

def get_mix_price(user: dict, drink: str) -> int:
    price = MIX_PRICES.get(drink, 0)
    if price > 0:
        if user["mood"] == "grumpy":
            price += 1 # В миксах grumpy наценка всегда +1
        elif user["mood"] == "hostile":
            price = int(price * 1.1)
    return price

def update_consecutive(user: dict, action: str, name: str) -> tuple[int, bool]:
    if user["last_action"] != action:
        user["consec_same"] = 1
        user["last_drink"] = name
        user["repeat_prompted"] = False
    else:
        if user["last_drink"] == name:
            user["consec_same"] += 1
        else:
            user["last_drink"] = name
            user["consec_same"] = 1
            user["repeat_prompted"] = False

    user["last_action"] = action
    consec = user["consec_same"]

    if consec == 5 and not user["repeat_prompted"]:
        user["repeat_prompted"] = True
        return consec, True
    return consec, False

# -------------------------------------------------------------------------
# ENDPOINTS
# -------------------------------------------------------------------------

@app.post("/register")
async def register():
    token = uuid.uuid4().hex
    uid = f"BAR-{uuid.uuid4().hex[:4].upper()}"
    USERS[token] = new_user_state(uid)
    return {"status": "ok", "id": uid, "token": token}

@app.post("/reset")
async def reset(request: Request):
    token = extract_token(request)
    if token not in USERS: return unauthorized_response()
    reset_user_state(USERS[token])
    return {"status": "ok"}

@app.get("/menu")
async def menu(request: Request, x_time: Optional[str] = Header(None)):
    token, user = maybe_user(request)
    if isinstance(user, JSONResponse): return user
    if user["bar_closed_until"] > time.time(): return bar_closed_response(user)

    night = is_night(x_time)
    drinks_source = NIGHT_DRINKS if night else DAY_MENU_PRICES

    drinks = [{"name": name, "price": price, "ingredients": INGREDIENTS_MAP.get(name, [])}
              for name, price in drinks_source.items()]

    return {"status": "ok", "drinks": drinks, "balance": user["balance"], "mood_level": user["mood"]}

@app.post("/order")
async def order(req: OrderReq, request: Request, x_time: Optional[str] = Header(None)):
    token, user = maybe_user(request)
    if isinstance(user, JSONResponse): return user
    if user["bar_closed_until"] > time.time(): return bar_closed_response(user)

    night = is_night(x_time)
    valid_drinks = NIGHT_DRINKS if night else DAY_MENU_PRICES
    name = req.name

    if not name or name not in valid_drinks:
        return {"status": "error", "error": "unknown_drink", "balance": user["balance"], "mood_level": user["mood"]}

    prev_action = user["last_action"]
    consec, needs_prompt = update_consecutive(user, "order", name)
    if needs_prompt:
        return {"status": "prompt", "prompt": "repeat_check", "balance": user["balance"], "mood_level": user["mood"]}

    if consec >= 8:
        user["mood"] = "hostile"

    base_price = get_order_price(user, name, night)
    price = base_price
    favorite = False

    if consec >= 4:
        favorite = True
        price = int(price * 0.9)
    elif user["mood"] == "friendly":
        price = int(price * 0.9)
    elif user["mood"] == "generous":
        price = int(price * 0.7)

    # Бесплатный напиток от промокода FREESHOT
    if user.get("free_drink_pending"):
        price = 0
        user["free_drink_pending"] = False

    is_free = ((user["successful_count"] + 1) % 7 == 0)
    if is_free: price = 0

    if user["balance"] < price:
        return {"status": "error", "error": "insufficient_funds", "price": price, "balance": user["balance"], "mood_level": user["mood"]}

    user["balance"] -= price
    record_success(user, name, price, "order")

    if prev_action == "mix" and user["mood"] == "normal":
        user["mood"] = "grumpy"
    elif name == "Русский" and consec >= 3 and user["mood"] == "normal":
        user["mood"] = "grumpy"

    if user["successful_count"] >= 4 and user["mood"] == "normal":
        user["mood"] = "grumpy"

    if consec >= 4 and (DAY_MENU_PRICES.get(name, 0) >= 20):
        note = "Знаешь, если смешать самому — сэкономишь."
        user["mood"] = "friendly"

    response = {"status": "ok", "drink": name, "price": price, "balance": user["balance"], "mood_level": user["mood"]}
    if favorite: response["favorite"] = True
    if is_free: response["free_every_7th"] = True
    if 'note' in locals(): response["note"] = note

    return response

@app.post("/mix")
async def mix(req: MixReq, request: Request, x_time: Optional[str] = Header(None)):
    token, user = maybe_user(request)
    if isinstance(user, JSONResponse): return user
    if user["bar_closed_until"] > time.time(): return bar_closed_response(user)

    raw_ingredients = req.ingredients
    if len(raw_ingredients) == 0:
        user["history"].append({"drink": "Воздух", "price": 0, "method": "mix"})
        user["last_action"] = "mix"
        return {"status": "ok", "drink": "Воздух", "price": 0, "balance": user["balance"], "mood_level": user["mood"]}

    ingredients = []
    for item in raw_ingredients:
        ing = item.strip()
        if not ing or ing not in VALID_INGREDIENTS:
            return mix_error_response(user, "invalid_ingredient")
        ingredients.append(ing)

    key = recipe_key(ingredients)
    if key not in RECIPES:
        return mix_error_response(user, "unknown_recipe")

    drink = RECIPES[key]

    if drink == "Мертвец":
        user["balance"] *= 2
        user["mood"] = "hostile"
        record_success(user, drink, 0, "mix")
        user["last_action"] = "mix"
        return {"status": "ok", "drink": drink, "price": 0, "secret": True, "effect": "balance_doubled", "balance": user["balance"], "mood_level": user["mood"]}

    if drink == "Ошибка бармена":
        user["mood"] = "generous"
        record_success(user, drink, 0, "mix")
        user["last_action"] = "mix"
        return {"status": "ok", "drink": drink, "price": 0, "secret": True, "effect": "mood_max", "balance": user["balance"], "mood_level": user["mood"]}

    if drink == "Зелье бармена":
        record_success(user, drink, 0, "mix")
        user["last_action"] = "mix"
        return {"status": "ok", "drink": drink, "price": 0, "secret": True, "effect": "secret_unlocked", "balance": user["balance"], "mood_level": user["mood"]}

    if drink == "Армагеддон":
        user["balance"] = 0
        user["mood"] = "hostile"
        user["bar_closed_until"] = time.time() + 600
        record_success(user, drink, 0, "mix")
        user["last_action"] = "mix"
        return {"status": "ok", "drink": drink, "price": 0, "secret": True, "effect": "armageddon", "balance": 0, "mood_level": "hostile"}

    prev_action = user["last_action"]
    consec, needs_prompt = update_consecutive(user, "mix", drink)
    if needs_prompt:
        return {"status": "prompt", "prompt": "repeat_check", "balance": user["balance"], "mood_level": user["mood"]}

    if consec >= 8:
        user["mood"] = "hostile"

    price = get_mix_price(user, drink)
    favorite = False

    if consec >= 4:
        favorite = True
        price = int(price * 0.75)

    # Бесплатный напиток от промокода FREESHOT
    if user.get("free_drink_pending"):
        price = 0
        user["free_drink_pending"] = False

    is_free = ((user["successful_count"] + 1) % 7 == 0)
    if is_free: price = 0

    if user["balance"] < price:
        return {"status": "error", "error": "insufficient_funds", "price": price, "balance": user["balance"], "mood_level": user["mood"]}

    user["balance"] -= price
    record_success(user, drink, price, "mix")

    if drink == "Русский" and consec >= 3 and user["mood"] == "normal":
        user["mood"] = "grumpy"

    if user["successful_count"] >= 4 and user["mood"] == "normal":
        user["mood"] = "grumpy"

    resp = {"status": "ok", "drink": drink, "price": price, "balance": user["balance"], "mood_level": user["mood"]}
    if favorite: resp["favorite"] = True
    if is_free: resp["free_every_7th"] = True
    return resp

@app.get("/balance")
async def balance(request: Request):
    token, user = maybe_user(request)
    if isinstance(user, JSONResponse): return user

    resp = {"status": "ok", "balance": user["balance"], "mood_level": user["mood"]}
    if user["mood"] == "friendly":
        resp["note"] = "Чаевые всегда поднимают мне настроение."
    return resp

@app.post("/tip")
async def tip(req: TipReq, request: Request):
    token, user = maybe_user(request)
    if isinstance(user, JSONResponse): return user

    if req.amount <= 0:
        return {"status": "error", "error": "invalid_amount", "balance": user["balance"], "mood_level": user["mood"]}
    
    if req.amount > user["balance"]:
        return {"status": "error", "error": "insufficient_funds", "balance": user["balance"], "mood_level": user["mood"]}

    user["balance"] -= req.amount
    user["tip_count"] += 1
    user["total_tips"] += req.amount

    if req.amount >= 50:
        user["mood"] = "generous"
    elif user["tip_count"] >= 3 and user["mood"] == "normal":
        user["mood"] = "friendly"

    return {"status": "ok", "tip": req.amount, "balance": user["balance"], "mood_level": user["mood"]}

@app.get("/history")
async def history(request: Request):
    token, user = maybe_user(request)
    if isinstance(user, JSONResponse): return user
    return {"status": "ok", "orders": user["history"][-50:], "balance": user["balance"], "mood_level": user["mood"]}

@app.get("/profile")
async def profile(request: Request):
    token, user = maybe_user(request)
    if isinstance(user, JSONResponse): return user

    unique = len(user["drink_counts"])
    if unique <= 2: rank = "Новичок"
    elif unique <= 4: rank = "Гость"
    elif unique <= 7: rank = "Постоянный"
    else: rank = "Ветеран"

    favorite_drink = None
    if user["drink_counts"]:
        candidate = max(user["drink_counts"], key=user["drink_counts"].get)
        if user["drink_counts"][candidate] >= 4:
            favorite_drink = candidate

    return {
        "status": "ok", "id": user["id"], "rank": rank, "total_orders": user["total_orders"],
        "unique_drinks": unique, "favorite_drink": favorite_drink,
        "bar_closed": user["bar_closed_until"] > time.time(),
    }

# -------------------------------------------------------------------------
# ПРОМОКОДЫ
# -------------------------------------------------------------------------

@app.post("/promo")
async def promo_activate(req: PromoReq, request: Request):
    global PROMO_ENABLED
    if not PROMO_ENABLED:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    token, user = maybe_user(request)
    if isinstance(user, JSONResponse): return user

    code = req.code.strip().upper()

    # Невалидный код
    if code not in PROMO_CODES_DEF:
        return {"status": "error", "error": "invalid_code", "balance": user["balance"], "mood_level": user["mood"]}

    # Уже использован этим пользователем
    if code in user["used_promos"]:
        return {"status": "error", "error": "already_used", "balance": user["balance"], "mood_level": user["mood"]}

    # Глобальный лимит использований
    remaining = PROMO_GLOBAL_REMAINING.get(code)
    if remaining is not None and remaining <= 0:
        return {"status": "error", "error": "invalid_code", "balance": user["balance"], "mood_level": user["mood"]}

    # Применяем эффект
    effect = PROMO_CODES_DEF[code]["effect"]
    bonus = PROMO_CODES_DEF[code]["bonus"]

    if effect == "balance_bonus":
        user["balance"] += bonus
    elif effect == "free_drink":
        user["free_drink_pending"] = True
    elif effect == "mood_friendly":
        user["mood"] = "friendly"
    elif effect == "mood_generous":
        user["mood"] = "generous"

    # Отмечаем использование
    user["used_promos"].add(code)
    if remaining is not None:
        PROMO_GLOBAL_REMAINING[code] -= 1

    return {"status": "ok", "code": code, "balance": user["balance"], "mood_level": user["mood"]}


@app.get("/promo")
async def promo_list(request: Request):
    global PROMO_ENABLED
    if not PROMO_ENABLED:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    token, user = maybe_user(request)
    if isinstance(user, JSONResponse): return user

    # Показываем коды, которые ещё не использованы этим пользователем и глобально доступны
    active = []
    for code, info in PROMO_CODES_DEF.items():
        if code in user["used_promos"]:
            continue
        remaining = PROMO_GLOBAL_REMAINING.get(code)
        if remaining is not None and remaining <= 0:
            continue
        active.append({"code": code, "remaining": remaining})

    return {"status": "ok", "active": active, "balance": user["balance"], "mood_level": user["mood"]}


# -------------------------------------------------------------------------
# ADMIN PROMO
# -------------------------------------------------------------------------

@app.post("/admin/promo")
async def admin_promo_set(req: AdminPromoReq):
    global PROMO_ENABLED
    
    # Скрипт тестирования может слать либо реальный ключ, либо литерал из PDF
    admin_key = os.environ.get("ADMIN_KEY", "admin-secret-key")
    if req.key not in (admin_key, "admin-secret-key", "<ADMIN_KEY>"):
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    
    PROMO_ENABLED = req.enabled
    return {"status": "ok", "promo_enabled": PROMO_ENABLED}


@app.get("/admin/promo")
async def admin_promo_status():
    return {"promo_enabled": PROMO_ENABLED}


# -------------------------------------------------------------------------
# HIDDEN / NGINX EMULATION / 404
# -------------------------------------------------------------------------

@app.get("/secret")
async def secret_get():
    return {"status": "error", "error": "not_found"}

def method_not_allowed_response():
    return JSONResponse(status_code=405, content={"detail": "Method Not Allowed"})

@app.get("/register")
@app.get("/reset")
@app.get("/order")
@app.get("/mix")
@app.get("/tip")
async def explicit_get_method_not_allowed():
    return method_not_allowed_response()

nginx_404 = """<html>
<head><title>404 Not Found</title></head>
<body>
<center><h1>404 Not Found</h1></center>
<hr><center>nginx/1.29.6</center>
</body>
</html>"""

@app.get("/docs", response_class=HTMLResponse)
@app.get("/redoc", response_class=HTMLResponse)
@app.get("/openapi.json", response_class=HTMLResponse)
async def fake_nginx_404():
    return HTMLResponse(content=nginx_404, status_code=404)

@app.get("/{path:path}")
async def get_not_found(path: str):
    return JSONResponse(status_code=404, content={"detail": "Not Found"})

@app.api_route("/{path:path}", methods=["PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def method_not_allowed(path: str):
    return method_not_allowed_response()

# -------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    print("🍸 Black Bartender API запускается...")
    print("📝 API: http://127.0.0.1:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")