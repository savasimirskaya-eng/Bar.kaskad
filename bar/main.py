# main.py
from fastapi import FastAPI, Header, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, Any
import secrets
from datetime import datetime, timedelta
from collections import Counter

from config import DRINK_INGREDIENTS, RECIPES
from models import OrderRequest, MixRequest, TipRequest
from utils import (
    get_menu_names, get_mood, get_rank, calc_price,
    parse_time, is_bar_closed, format_reopens_at
)

app = FastAPI(title="Black Bartender Clone", version="1.0.0", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== ХРАНИЛИЩЕ ПОЛЬЗОВАТЕЛЕЙ ====================
users_db: Dict[str, Dict[str, Any]] = {}


# ==================== ЗАВИСИМОСТЬ АВТОРИЗАЦИИ ====================
def get_current_user(authorization: Optional[str] = Header(None, alias="Authorization")):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"status": "error", "error": "unauthorized"})

    token = authorization.split(" ")[1]
    if token not in users_db:
        raise HTTPException(status_code=401, detail={"status": "error", "error": "unauthorized"})

    return users_db[token]


# ==================== МАРШРУТЫ ====================

@app.post("/register", status_code=201)
async def register():
    token = secrets.token_hex(16)
    uid = f"BAR-{secrets.token_hex(4).upper()}"
    users_db[token] = {
        "id": uid,
        "balance": 100,
        "orders": [],
        "mood": "normal",
        "bar_closed_until": None,
        "drink_counters": {},
        "drinks_tried": set()
    }
    return {"status": "ok", "id": uid, "token": token}


@app.post("/reset")
async def reset(user: dict = Depends(get_current_user)):
    user.update({
        "balance": 100,
        "orders": [],
        "mood": "normal",
        "bar_closed_until": None,
        "drink_counters": {},
        "drinks_tried": set()
    })
    return {"status": "ok"}


@app.get("/menu")
async def get_menu(
        user: dict = Depends(get_current_user),
        x_time: Optional[str] = Header(None, alias="X-Time")
):
    now = parse_time(x_time)
    hour = now.hour if now else 12

    if is_bar_closed(user, now):
        return JSONResponse(content={
            "status": "error", "error": "bar_closed",
            "reopens_at": format_reopens_at(now.hour, now.minute),
            "balance": user["balance"], "mood_level": user["mood"]
        })

    user["mood"] = get_mood(len(user["orders"]), user["balance"])
    menu_names = get_menu_names(hour)

    drinks = []
    for name in menu_names:
        price = calc_price(name, user["mood"], hour, is_mix=False)
        drinks.append({
            "name": name,
            "price": price,
            "ingredients": DRINK_INGREDIENTS.get(name, [])
        })

    return {
        "status": "ok",
        "drinks": drinks,
        "balance": user["balance"],
        "mood_level": user["mood"]
    }


@app.post("/order")
async def order(
        req: OrderRequest,
        user: dict = Depends(get_current_user),
        x_time: Optional[str] = Header(None, alias="X-Time")
):
    now = parse_time(x_time)
    hour = now.hour if now else 12

    if is_bar_closed(user, now):
        return JSONResponse(content={
            "status": "error", "error": "bar_closed",
            "reopens_at": format_reopens_at(now.hour, now.minute),
            "balance": user["balance"], "mood_level": user["mood"]
        })

    menu_names = get_menu_names(hour)
    if req.name not in menu_names:
        return JSONResponse(content={
            "status": "error", "error": "unknown_drink",
            "balance": user["balance"], "mood_level": user["mood"]
        })

    price = calc_price(req.name, user["mood"], hour, is_mix=False)

    user["drink_counters"].setdefault(req.name, 0)
    user["drink_counters"][req.name] += 1

    is_free = user["drink_counters"][req.name] % 7 == 0
    if is_free:
        price = 0
    elif user["balance"] < price:
        return JSONResponse(content={
            "status": "error", "error": "insufficient_funds",
            "price": price, "balance": user["balance"], "mood_level": user["mood"]
        })

    if not is_free:
        user["balance"] -= price

    user["orders"].append({"drink": req.name, "price": price, "method": "order"})
    user["drinks_tried"].add(req.name)

    # Любимый напиток
    counts = {}
    for o in user["orders"]:
        counts[o["drink"]] = counts.get(o["drink"], 0) + 1
    favorite = None
    if counts:
        max_count = max(counts.values())
        if counts.get(req.name) == max_count and max_count > 1:
            favorite = True

    response = {
        "status": "ok", "drink": req.name, "price": price,
        "balance": user["balance"], "mood_level": user["mood"]
    }
    if is_free:
        response["free_every_7th"] = True
    if favorite:
        response["favorite"] = True
    return response


@app.post("/mix")
async def mix(
        req: MixRequest,
        user: dict = Depends(get_current_user),
        x_time: Optional[str] = Header(None, alias="X-Time")
):
    now = parse_time(x_time)
    hour = now.hour if now else 12

    if is_bar_closed(user, now):
        return JSONResponse(content={
            "status": "error", "error": "bar_closed",
            "reopens_at": format_reopens_at(now.hour, now.minute),
            "balance": user["balance"], "mood_level": user["mood"]
        })

    ingredients = sorted(set(req.ingredients))
    key = tuple(ingredients)
    drink_name = None
    effect = None
    is_secret = False

    # Секреты
    if len(ingredients) == 0:
        drink_name = "Воздух"
        price = 0
    elif key == tuple(sorted(["водка", "ром", "молоко"])):
        drink_name = "Мертвец"
        price = 0
        effect = "balance_doubled"
        is_secret = True
    elif key == tuple(sorted(["водка", "ром", "текила", "виски", "джин"])):
        drink_name = "Армагеддон"
        price = 0
        effect = "armageddon"
        is_secret = True
    else:
        # Обычные рецепты
        if key in RECIPES:
            drink_name = RECIPES[key]
            price = calc_price(drink_name, user["mood"], hour, is_mix=True)
        else:
            return JSONResponse(content={
                "status": "error", "error": "unknown_recipe",
                "balance": user["balance"], "mood_level": user["mood"]
            })

    if drink_name not in ["Воздух", "Мертвец", "Армагеддон"] and user["balance"] < price:
        return JSONResponse(content={
            "status": "error", "error": "insufficient_funds",
            "price": price, "balance": user["balance"], "mood_level": user["mood"]
        })

    user["balance"] -= price
    user["orders"].append({"drink": drink_name, "price": price, "method": "mix"})
    user["drinks_tried"].add(drink_name)

    # Эффекты
    if effect == "balance_doubled":
        user["balance"] *= 2
        user["mood"] = "hostile"
    elif effect == "armageddon":
        user["balance"] = 0
        user["mood"] = "hostile"
        user["bar_closed_until"] = now + timedelta(minutes=10)
    elif drink_name == "Воздух":
        user["mood"] = "hostile"

    response = {
        "status": "ok", "drink": drink_name, "price": price,
        "balance": user["balance"], "mood_level": user["mood"]
    }
    if is_secret:
        response["secret"] = True
        response["effect"] = effect
    return response


@app.get("/balance")
async def get_balance(user: dict = Depends(get_current_user)):
    user["mood"] = get_mood(len(user["orders"]), user["balance"])
    return {"status": "ok", "balance": user["balance"], "mood_level": user["mood"]}


@app.post("/tip")
async def tip(req: TipRequest, user: dict = Depends(get_current_user)):
    if req.amount <= 0:
        return JSONResponse(content={
            "status": "error", "error": "invalid_amount",
            "balance": user["balance"], "mood_level": user["mood"]
        })
    if user["balance"] < req.amount:
        return JSONResponse(content={
            "status": "error", "error": "insufficient_funds",
            "balance": user["balance"], "mood_level": user["mood"]
        })

    user["balance"] -= req.amount
    if req.amount >= 100:
        user["mood"] = "friendly"

    return {"status": "ok", "tip": req.amount, "balance": user["balance"], "mood_level": user["mood"]}


@app.get("/history")
async def get_history(user: dict = Depends(get_current_user)):
    user["mood"] = get_mood(len(user["orders"]), user["balance"])
    return {"status": "ok", "orders": user["orders"], "balance": user["balance"], "mood_level": user["mood"]}


@app.get("/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    drinks = [o["drink"] for o in user["orders"]]
    unique = len(user["drinks_tried"])
    fav = None
    if drinks:
        counts = Counter(drinks)
        fav = counts.most_common(1)[0][0]

    is_closed = bool(user["bar_closed_until"] and datetime.now() < user["bar_closed_until"])

    return {
        "status": "ok",
        "id": user["id"],
        "rank": get_rank(unique, user["balance"]),
        "total_orders": len(user["orders"]),
        "unique_drinks": unique,
        "favorite_drink": fav,
        "bar_closed": is_closed
    }


# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)