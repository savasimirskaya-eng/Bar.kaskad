# utils.py
import re
from datetime import datetime, timedelta
import math


def parse_time(x_time: str = None) -> datetime:
    """Парсит заголовок X-Time."""
    if not x_time:
        return datetime.now()
    match = re.match(r"^(\d{1,2}):(\d{2})$", x_time.strip())
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        if 0 <= h <= 23 and 0 <= m <= 59:
            return datetime(2026, 4, 25, h, m)
    return datetime.now()


def get_menu_names(hour: int):
    """Возвращает список доступных напитков."""
    from config import NIGHT_MENU_NAMES, DAY_MENU_NAMES
    if hour is None or not (0 <= hour <= 23):
        hour = 12
    if 0 <= hour < 6:
        return NIGHT_MENU_NAMES
    return DAY_MENU_NAMES


def get_mood(orders_count: int, balance: int):
    """Определяет настроение бармена."""
    if balance == 0:
        return "hostile"
    if orders_count >= 6:
        return "hostile"
    if orders_count >= 3:
        return "grumpy"
    return "normal"


def get_rank(unique_drinks: int, balance: int):
    """Определяет ранг пользователя."""
    if balance == 0:
        return "Гость"
    if unique_drinks == 0:
        return "Гость"
    if unique_drinks < 3:
        return "Новичок"
    if unique_drinks < 6:
        return "Постоянный"
    return "Знаток"


def calc_price(drink: str, mood: str, hour: int, is_mix: bool = False):
    """Рассчитывает цену напитка."""
    from config import BASE_PRICES

    base = BASE_PRICES.get(drink, 10)

    if drink in ["Воздух", "Мертвец", "Армагеддон"]:
        return 0

    if drink == "Русский":
        if 12 <= hour < 18:
            base = 7
        elif 18 <= hour < 24:
            base = 9

    if mood == "grumpy":
        if is_mix:
            price = base
        else:
            price = math.ceil(base * 1.2)
    elif mood == "hostile":
        if is_mix:
            price = base + 4
        else:
            price = base + 2
    else:
        price = base

    return max(1, price)


def is_bar_closed(user: dict, now: datetime) -> bool:
    """Проверяет, закрыт ли бар."""
    return bool(user.get("bar_closed_until") and now < user["bar_closed_until"])


def format_reopens_at(hour: int, minute: int) -> str:
    """Форматирует время открытия."""
    return f"{hour:02d}:{minute:02d}"