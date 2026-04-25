from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from collections import Counter
from datetime import datetime
import secrets
import re

# 1. Импорт CORS
from fastapi.middleware.cors import CORSMiddleware

# 2. Создаём приложение ОДИН РАЗ
app = FastAPI(title="Bar API", version="1.0.0", docs_url=None, redoc_url=None)

# 3. Подключаем CORS сразу после создания
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== МОДЕЛИ ======================================== МОДЕЛИ ====================

class OrderRequest(BaseModel):
    name: str


class MixRequest(BaseModel):
    ingredients: List[str] = Field(default_factory=list)


class TipRequest(BaseModel):
    amount: int


# ==================== КОНФИГУРАЦИЯ ====================

# Все доступные ингредиенты
ALL_INGREDIENTS = ["водка", "ром", "текила", "виски", "джин", "кола", "сок", "тоник", "лёд", "молоко"]

# Базовое меню (публичные рецепты)
BASE_MENU: Dict[str, Dict[str, Any]] = {
    "Русский": {"price": 10, "ingredients": ["водка", "лёд"]},
    "Отвёртка": {"price": 12, "ingredients": ["водка", "сок"]},
}

# Скрытые рецепты (обнаруживаются экспериментально)
SECRET_RECIPES: Dict[tuple, Dict[str, Any]] = {
    tuple(sorted(["ром", "кола"])): {"name": "Куба Либре", "price": 14, "unlock_time": None},
    tuple(sorted(["текила", "сок", "лёд"])): {"name": "Маргарита", "price": 15, "unlock_time": None},
    tuple(sorted(["виски", "кола"])): {"name": "Кубинский", "price": 13, "unlock_time": None},
    tuple(sorted(["джин", "тоник", "лёд"])): {"name": "Джин-тоник", "price": 11, "unlock_time": None},
    tuple(sorted(["водка", "молоко"])): {"name": "Белый русский", "price": 16, "unlock_time": (20, 6)},  # ночь
    tuple(sorted(["ром", "молоко", "лёд"])): {"name": "Пина Колада", "price": 18, "unlock_time": None},
    tuple(sorted(["водка", "ром", "текила"])): {"name": "Адский микс", "price": 25, "unlock_time": (0, 5)},
    # только ночью
}


# Объединённое меню для поиска
def get_all_recipes() -> Dict[tuple, Dict[str, Any]]:
    recipes = {}
    # Добавляем базовые
    for name, data in BASE_MENU.items():
        key = tuple(sorted(data["ingredients"]))
        recipes[key] = {"name": name, "price": data["price"], "unlock_time": None}
    # Добавляем скрытые
    for key, data in SECRET_RECIPES.items():
        recipes[key] = data.copy()
    return recipes


# Хранилище пользователей (в памяти)
users: Dict[str, Dict[str, Any]] = {}

# ==================== ПРИЛОЖЕНИЕ ====================

app = FastAPI(title="Bar API", version="1.0.0", docs_url=None, redoc_url=None)


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def parse_time_header(x_time: Optional[str]) -> Optional[datetime]:
    """Парсит заголовок времени в формате HH:MM"""
    if not x_time or not re.match(r"^\d{2}:\d{2}$", x_time):
        return None
    try:
        return datetime.strptime(x_time, "%H:%M")
    except ValueError:
        return None


def get_current_hour(x_time: Optional[str]) -> Optional[int]:
    """Возвращает текущий час из заголовка"""
    time_obj = parse_time_header(x_time)
    return time_obj.hour if time_obj else None


def is_night_time(x_time: Optional[str]) -> bool:
    """Проверяет, ночное ли время (0-6 или 20-24)"""
    hour = get_current_hour(x_time)
    if hour is None:
        return False
    return hour >= 20 or hour < 6


def is_bar_closed(x_time: Optional[str]) -> bool:
    """Проверяет, закрыт ли бар в данное время"""
    hour = get_current_hour(x_time)
    if hour is None:
        return False
    # Бар закрыт с 3:00 до 5:59
    return 3 <= hour < 6


def get_mood(orders_count: int, x_time: Optional[str] = None) -> str:
    """Определяет настроение бармена"""
    # Время может влиять на настроение
    hour = get_current_hour(x_time)

    if orders_count < 3:
        base_mood = "normal"
    elif orders_count < 8:
        base_mood = "grumpy"
    else:
        base_mood = "hostile"

    # Ночью бармен добрее
    if is_night_time(x_time) and base_mood == "hostile":
        return "grumpy"

    return base_mood


def get_rank(unique_count: int) -> str:
    """Определяет ранг пользователя"""
    if unique_count == 0:
        return "Новичок"
    elif unique_count < 3:
        return "Постоянный"
    elif unique_count < 6:
        return "Знаток"
    return "Легенда"


def get_mixin_price(base_price: int, method: str) -> int:
    """Рассчитывает цену для микса"""
    if method == "mix":
        # Скидка 2 рубля, но не меньше 1
        return max(1, base_price - 2)
    return base_price


def create_error_response(error_code: str, balance: int, mood: str, **extra) -> JSONResponse:
    """Создаёт стандартизированный ответ об ошибке"""
    content = {
        "status": "error",
        "error": error_code,
        "balance": balance,
        "mood_level": mood
    }
    content.update(extra)
    return JSONResponse(status_code=400, content=content)


def create_auth_error(detail: str) -> JSONResponse:
    """Создаёт ответ об ошибке авторизации"""
    return JSONResponse(status_code=401, content={"detail": detail})


def create_funds_error(price: int, balance: int, mood: str) -> JSONResponse:
    """Создаёт ответ о недостатке средств"""
    return JSONResponse(
        status_code=402,
        content={
            "status": "error",
            "error": "insufficient_funds",
            "price": price,
            "balance": balance,
            "mood_level": mood
        }
    )


# ==================== ЗАВИСИМОСТИ ====================

def get_current_user(
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
        x_time: Optional[str] = Header(default=None, alias="X-Time")
):
    """Зависимость для получения текущего пользователя"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Неверный формат токена")

    token = authorization[7:]
    if token not in users:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    user = users[token]
    # Сохраняем время запроса в контексте (опционально)
    user["_x_time"] = x_time
    return user


# ==================== ЭНДПОИНТЫ ====================

@app.post("/register", status_code=201)
async def register():
    """Регистрация нового пользователя"""
    user_id = f"BAR-{secrets.token_hex(4).upper()}"
    token = secrets.token_hex(16)

    users[token] = {
        "id": user_id,
        "balance": 100,
        "orders": [],
        "drinks_tried": [],  # list вместо set для JSON-совместимости
    }

    return {"status": "ok", "id": user_id, "token": token}


@app.post("/reset")
async def reset(user: dict = Depends(get_current_user)):
    """Сброс аккаунта к начальному состоянию"""
    user["balance"] = 100
    user["orders"] = []
    user["drinks_tried"] = []
    return {"status": "ok"}


@app.get("/menu")
async def get_menu(
        user: dict = Depends(get_current_user),
        x_time: Optional[str] = Header(default=None, alias="X-Time")
):
    """Получение меню напитков"""
    # Проверяем, закрыт ли бар
    if is_bar_closed(x_time):
        return {
            "status": "ok",
            "drinks": [],
            "balance": user["balance"],
            "mood_level": get_mood(len(user["orders"]), x_time),
            "bar_closed": True
        }

    drinks_list = [
        {"name": name, "price": data["price"], "ingredients": data["ingredients"]}
        for name, data in BASE_MENU.items()
    ]

    return {
        "status": "ok",
        "drinks": drinks_list,
        "balance": user["balance"],
        "mood_level": get_mood(len(user["orders"]), x_time)
    }


@app.post("/order")
async def order(
        request: OrderRequest,
        user: dict = Depends(get_current_user),
        x_time: Optional[str] = Header(default=None, alias="X-Time")
):
    """Заказ напитка по названию"""
    mood = get_mood(len(user["orders"]), x_time)

    # Проверяем закрытие бара
    if is_bar_closed(x_time):
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "error": "bar_closed",
                "balance": user["balance"],
                "mood_level": mood
            }
        )

    if request.name not in BASE_MENU:
        return create_error_response("unknown_drink", user["balance"], mood)

    drink_data = BASE_MENU[request.name]
    price = drink_data["price"]

    if user["balance"] < price:
        return create_funds_error(price, user["balance"], mood)

    # Списываем баланс и записываем заказ
    user["balance"] -= price
    user["orders"].append({
        "drink": request.name,
        "price": price,
        "method": "order"
    })

    # Добавляем в список попробованных, если ещё нет
    if request.name not in user["drinks_tried"]:
        user["drinks_tried"].append(request.name)

    return {
        "status": "ok",
        "drink": request.name,
        "price": price,
        "balance": user["balance"],
        "mood_level": mood
    }


@app.post("/mix")
async def mix(
        request: MixRequest,
        user: dict = Depends(get_current_user),
        x_time: Optional[str] = Header(default=None, alias="X-Time")
):
    """Создание коктейля из ингредиентов"""
    mood = get_mood(len(user["orders"]), x_time)

    # Проверяем закрытие бара
    if is_bar_closed(x_time):
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "error": "bar_closed",
                "balance": user["balance"],
                "mood_level": mood
            }
        )

    # Нормализуем ингредиенты: сортируем и убираем дубликаты
    ingredients = sorted(set(request.ingredients))
    key = tuple(ingredients)

    # Ищем рецепт
    recipes = get_all_recipes()

    if key not in recipes:
        return create_error_response("unknown_recipe", user["balance"], mood)

    recipe = recipes[key]

    # Проверяем временное ограничение рецепта
    unlock_time = recipe.get("unlock_time")
    if unlock_time:
        start_hour, end_hour = unlock_time
        current_hour = get_current_hour(x_time)
        if current_hour is not None:
            # Проверка временного окна
            if start_hour > end_hour:  # окно переходит через полночь
                if not (current_hour >= start_hour or current_hour < end_hour):
                    return create_error_response("unknown_recipe", user["balance"], mood)
            else:
                if not (start_hour <= current_hour < end_hour):
                    return create_error_response("unknown_recipe", user["balance"], mood)

    drink_name = recipe["name"]
    base_price = recipe["price"]
    price = get_mixin_price(base_price, "mix")

    if user["balance"] < price:
        return create_funds_error(price, user["balance"], mood)

    # Списываем баланс и записываем заказ
    user["balance"] -= price
    user["orders"].append({
        "drink": drink_name,
        "price": price,
        "method": "mix"
    })

    # Добавляем в список попробованных
    if drink_name not in user["drinks_tried"]:
        user["drinks_tried"].append(drink_name)

    return {
        "status": "ok",
        "drink": drink_name,
        "price": price,
        "balance": user["balance"],
        "mood_level": mood
    }


@app.get("/balance")
async def get_balance(
        user: dict = Depends(get_current_user),
        x_time: Optional[str] = Header(default=None, alias="X-Time")
):
    """Получение текущего баланса"""
    return {
        "status": "ok",
        "balance": user["balance"],
        "mood_level": get_mood(len(user["orders"]), x_time)
    }


@app.post("/tip")
async def tip(
        request: TipRequest,
        user: dict = Depends(get_current_user),
        x_time: Optional[str] = Header(default=None, alias="X-Time")
):
    """Оставить чаевые"""
    mood = get_mood(len(user["orders"]), x_time)

    if request.amount <= 0 or user["balance"] < request.amount:
        return create_error_response("invalid_tip", user["balance"], mood)

    user["balance"] -= request.amount

    # Пасхалка: щедрые чаевые могут улучшить настроение
    if request.amount >= 50:
        # В следующем запросе настроение будет лучше (временно)
        user["_generous_tip"] = True

    return {
        "status": "ok",
        "tip": request.amount,
        "balance": user["balance"],
        "mood_level": mood
    }


@app.get("/history")
async def get_history(
        user: dict = Depends(get_current_user),
        x_time: Optional[str] = Header(default=None, alias="X-Time")
):
    """Получение истории заказов"""
    return {
        "status": "ok",
        "orders": user["orders"],
        "balance": user["balance"],
        "mood_level": get_mood(len(user["orders"]), x_time)
    }


@app.get("/profile")
async def get_profile(
        user: dict = Depends(get_current_user),
        x_time: Optional[str] = Header(default=None, alias="X-Time")
):
    """Получение профиля пользователя"""
    # Определяем любимый напиток
    favorite = None
    if user["orders"]:
        drinks = [o["drink"] for o in user["orders"]]
        counter = Counter(drinks)
        # most_common возвращает список, берём первый элемент
        favorite = counter.most_common(1)[0][0]

    return {
        "status": "ok",
        "id": user["id"],
        "rank": get_rank(len(user["drinks_tried"])),
        "total_orders": len(user["orders"]),
        "unique_drinks": len(user["drinks_tried"]),
        "favorite_drink": favorite,
        "bar_closed": is_bar_closed(x_time)
    }


# ==================== СКРЫТЫЕ / СЕКРЕТНЫЕ ЭНДПОИНТЫ ====================

@app.get("/hint")
async def hint(
        user: dict = Depends(get_current_user),
        x_time: Optional[str] = Header(default=None, alias="X-Time")
):
    """Секретный эндпоинт с подсказкой"""
    # Доступен только после 5 заказов
    if len(user["orders"]) < 5:
        raise HTTPException(status_code=403, detail="Слишком рано для подсказок")

    return {
        "status": "ok",
        "hint": "Попробуй смешать ром и колу... и не забудь про время",
        "mood_level": get_mood(len(user["orders"]), x_time)
    }


@app.get("/easter-egg")
async def easter_egg(
        user: dict = Depends(get_current_user),
        x_time: Optional[str] = Header(default=None, alias="X-Time")
):
    """Пасхалка: секретный напиток"""
    # Доступен только ночью и после попытки смешать 3+ уникальных рецепта
    if not is_night_time(x_time) or len(user["drinks_tried"]) < 3:
        raise HTTPException(status_code=403, detail="Условия не выполнены")

    # Даём секретный напиток бесплатно
    secret_drink = {
        "name": "Эликсир ночи",
        "price": 0,
        "ingredients": ["водка", "ром", "текила", "виски", "джин"]
    }

    user["orders"].append({
        "drink": secret_drink["name"],
        "price": 0,
        "method": "easter_egg"
    })
    if secret_drink["name"] not in user["drinks_tried"]:
        user["drinks_tried"].append(secret_drink["name"])

    return {
        "status": "ok",
        "drink": secret_drink["name"],
        "price": 0,
        "balance": user["balance"],
        "mood_level": "delighted",
        "message": "Бармен улыбается и наливает что-то особенное..."
    }


@app.get("/health")
async def health():
    """Health check для деплоя"""
    return {"status": "ok", "service": "bar-api"}


# ==================== ОБРАБОТКА ОШИБОК ====================

@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    """Кастомный обработчик 404"""
    return JSONResponse(
        status_code=404,
        content={"status": "error", "error": "not_found"}
    )


@app.exception_handler(405)
async def method_not_allowed_handler(request: Request, exc: HTTPException):
    """Обработчик неверного метода"""
    return JSONResponse(
        status_code=405,
        content={"status": "error", "error": "method_not_allowed"}
    )


# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=False
    )