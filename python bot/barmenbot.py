import os
import asyncio
import re
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
import aiohttp

# ================= КОНФИГУРАЦИЯ =================
BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "8682249064:AAGlLFoBjkGXc-6BRX5NU_EPSSLo9PRnk8M")
API_URL = os.getenv("API_URL", "http://localhost:8000")

user_tokens = {}
api_session = None

# ================= RP-ДИКЦИОНАРИЙ БАРМЕНА =================
RP = {
    "normal": {
        "welcome": "Добро пожаловать в бар. Что будете заказывать?",
        "order_ok": "Вот ваш {drink}. С вас {price}₽. Баланс: {balance}₽.",
        "order_err": "Такого напитка у нас нет. Загляните в /menu.",
        "mix_ok": "Смешал {drink}. Цена: {price}₽. Баланс: {balance}₽.",
        "mix_err": "Такая комбинация не работает. Попробуйте другую.",
        "tip_ok": "Спасибо за {amount}₽. Баланс: {balance}₽. Настроение: {mood}.",
        "tip_err": "Чаевые должны быть положительным целым числом.",
        "balance": "У вас {balance}₽. Настроение бармена: {mood}.",
        "profile": "ID: {id}\nРанг: {rank}\nВсего заказов: {total_orders}\nУникальных напитков: {unique}\nЛюбимое: {fav}\nБар закрыт: {closed}",
        "closed": "Бар временно закрыт. Откроется в {reopens}.",
        "empty": "Бармен молча протирает стакан. Ждёт вашего заказа.",
        "rate_limit": "Слишком много запросов. Дайте мне пару секунд перевести дух."
    },
    "grumpy": {
        "welcome": "Чего надо? Заказывай быстрее, у меня дел по горло.",
        "order_ok": "Держи {drink}. {price}₽. {balance}₽ осталось. Не мешай.",
        "order_err": "Не слышал я такого. Или иди читай меню, или уходи.",
        "mix_ok": "Намешал. {drink}. {price}₽. {balance}₽. Доволен?",
        "mix_err": "Ерунду просишь. В следующий раз думай, прежде чем смешивать.",
        "tip_ok": "Ладно, {amount}₽ принял. {mood}. {balance}₽. Хоть что-то.",
        "tip_err": "Мелочь не принимаю. Или вообще не давай.",
        "balance": "{balance}₽. {mood}. Не трать моё время зря.",
        "profile": "ID {id}. Ранг {rank}. Заказов {total_orders}. Любимое {fav}. Всё.",
        "closed": "Закрыто. До {reopens}. Вали отсюда.",
        "empty": "...",
        "rate_limit": "Отстань. Ты уже достал. Подожди минуту."
    },
    "hostile": {
        "welcome": "Убирайся. Или заказывай, но быстро.",
        "order_ok": "Бери {drink}. {price}₽. {balance}₽. И проваливай.",
        "order_err": "Ты смеёшься надо мной? Такого нет. Не позорься.",
        "mix_ok": "Вылил {drink}. {price}₽. {balance}₽. Доволен?",
        "mix_err": "Ты что, издеваешься? Неизвестная смесь. Уходи.",
        "tip_ok": "Кидаю {amount}₽ в ящик. {mood}. {balance}₽. Хватит.",
        "tip_err": "Подачку не принимаю. Или плати нормально.",
        "balance": "{balance}₽. {mood}. Уходи.",
        "profile": "ID {id}. Ранг {rank}. Заказов {total_orders}. Любимое {fav}. Всё.",
        "closed": "Бар закрыт. До {reopens}. Не суйся.",
        "empty": "Бармен смотрит на тебя как на мусор.",
        "rate_limit": "Я сказал, заткнись. Подожди, пока я не передумаю."
    },
    "friendly": {
        "welcome": "Привет! Рад тебя видеть. Что хочешь сегодня? 🍸",
        "order_ok": "С удовольствием! {drink} готов. Всего {price}₽. Баланс: {balance}₽. 😊",
        "order_err": "Ой, такого у нас нет. Давай выберем что-нибудь другое! ✨",
        "mix_ok": "Отличный выбор! {drink} смешан. Цена: {price}₽. Баланс: {balance}₽. 🥂",
        "mix_err": "Хм, такая смесь не сработает. Попробуем другую? 🤔",
        "tip_ok": "Огромное спасибо за {amount}₽! Ты лучший. Баланс: {balance}₽. Настроение: {mood}. 💖",
        "tip_err": "Чаевые только положительные, друг. 😉",
        "balance": "У тебя {balance}₽. Настроение: {mood}. Всегда рад помочь! ✨",
        "profile": "ID: {id} | Ранг: {rank} | Заказов: {total_orders} | Любимое: {fav}. Отличный прогресс! 🌟",
        "closed": "Ой, бар пока закрыт до {reopens}. Заходи чуть позже, я всё подготовлю! 🌙",
        "empty": "Бармен улыбается и ждёт твой заказ. 😊",
        "rate_limit": "Эй, полегче! Дай мне перевести дух. Подожди секунду. ⏳"
    },
    "generous": {
        "welcome": "Добро пожаловать, дорогой гость! Сегодня всё для тебя! 🎉",
        "order_ok": "Бесплатно! {drink} готов. Баланс: {balance}₽. Гуляем! 🥳",
        "order_err": "Такого нет, но я сделаю тебе что-то особенное! 🌈",
        "mix_ok": "Вот твой {drink}! Всё за мой счёт. Баланс: {balance}₽. Наслаждайся! 🍹",
        "mix_err": "Не сработало, но не переживай! Попробуем ещё раз! 💫",
        "tip_ok": "Ты слишком щедр! {amount}₽ приняты. Настроение: {mood}. Баланс: {balance}₽. Ты звезда! ⭐",
        "tip_err": "Не надо стесняться, но давай только целые и больше нуля! 😄",
        "balance": "У тебя {balance}₽! Настроение: {mood}. Я сегодня на волне! 🌊",
        "profile": "ID: {id} | Ранг: {rank} | Заказов: {total_orders} | Любимое: {fav}. Ты легенда этого бара! 🏆",
        "closed": "Бар временно закрыт до {reopens}. Но я уже готовлю для тебя сюрприз! 🎁",
        "empty": "Бармен танцует за стойкой и ждёт твоего слова! 💃",
        "rate_limit": "Ох, ты меня завалил! Дай 5 минут, я всё наготовлю! ⏳"
    }
}


# ================= БЕЗОПАСНОЕ ФОРМАТИРОВАНИЕ =================
def safe_fmt(mood: str, action: str, data: dict) -> str:
    """Безопасно подставляет переменные. Если ключа нет, ставит '—'."""
    mood = (mood or "normal").lower().strip()
    if mood not in RP:
        mood = "normal"
    tpl = RP[mood].get(action, RP["normal"].get(action, RP["normal"].get("empty", "")))

    def replacer(match):
        key = match.group(1)
        return str(data.get(key, "—"))

    return re.sub(r"\{(\w+)\}", replacer, tpl)


# ================= API КЛИЕНТ =================
async def api_call(method: str, path: str, token: str = None, json_data: dict = None) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with api_session.request(method, f"{API_URL}{path}", json=json_data, headers=headers) as r:
            # Пытаемся получить JSON, даже если статус не 200
            try:
                data = await r.json()
            except:
                data = {"error": f"Invalid JSON response", "status": "error"}
            return r.status, data
    except Exception as e:
        logging.error(f"API Error: {e}")
        return 500, {"error": str(e), "status": "error"}


# ================= КЛАВИАТУРЫ =================
MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/menu"), KeyboardButton(text="/balance")],
        # 🔥 Исправлено: balance вместо /balance для текста кнопки
        [KeyboardButton(text="/profile"), KeyboardButton(text="/reset")],
        [KeyboardButton(text="/mix"), KeyboardButton(text="/order")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие или введите команду..."
)

# ================= HANDLERS =================
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message):
    uid = message.from_user.id
    status, data = await api_call("POST", "/register")

    if status == 200 and "token" in data:
        user_tokens[uid] = data["token"]
        text = (
            "🍸 <b>Добро пожаловать в «Чёрный Бармен»!</b>\n\n"
            "Я управляю этим заведением. У меня свой характер, скрытые рецепты и динамические цены.\n\n"
            "📜 <b>Доступные команды:</b>\n"
            "• /order &lt;название&gt; — заказать готовый коктейль\n"
            "• /mix &lt;ингр1, ингр2&gt; — смешать коктейль самому\n"
            "• /tip &lt;сумма&gt; — оставить чаевые (влияют на настроение!)\n"
            "• /balance — проверить баланс и моё настроение\n"
            "• /profile — ваш ранг, статистика и любимый напиток\n"
            "• /reset — начать с чистого листа\n\n"
            "💡 <i>Совет:</i> Ночью меню меняется, а ошибки меня портят настроение. Удачного вечера!"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=MAIN_KB)
    else:
        error_msg = data.get("error", "Неизвестная ошибка")
        await message.answer(f"❌ Ошибка подключения к бару: {error_msg}\nПопробуйте позже.", reply_markup=MAIN_KB)


@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    token = user_tokens.get(message.from_user.id)
    if not token:
        await message.answer("Сначала нажмите /start", reply_markup=MAIN_KB)
        return

    status, data = await api_call("GET", "/menu", token)

    if status == 200 and data.get("status") == "ok":
        drinks_list = data.get("drinks", [])
        if drinks_list:
            drinks = "\n".join(
                [f"🔹 {d['name']} — {d['price']}₽ ({', '.join(d['ingredients'])})" for d in drinks_list]
            )
        else:
            drinks = "🍺 Меню пусто..."

        mood = data.get("mood_level", "normal")
        welcome_text = safe_fmt(mood, "welcome", {})
        await message.answer(f"{welcome_text}\n\n{drinks}", reply_markup=MAIN_KB)
    else:
        await message.answer("❌ Не удалось загрузить меню.", reply_markup=MAIN_KB)


@dp.message(Command("order"))
async def cmd_order(message: Message):
    # 🔥 Исправлена обработка аргументов
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("❓ Пример: `/order Маргарита` или `/order Отвёртка`\n\nСписок напитков: /menu",
                                    reply_markup=MAIN_KB)

    drink_name = args[1].strip()
    token = user_tokens.get(message.from_user.id)
    if not token:
        await message.answer("Сначала нажмите /start", reply_markup=MAIN_KB)
        return

    status, data = await api_call("POST", "/order", token, {"name": drink_name})
    mood = data.get("mood_level", "normal")

    if status == 200:
        fmt_data = {
            "drink": drink_name,
            "price": data.get("price", 0),
            "balance": data.get("balance", 0),
            "mood": mood
        }

        if data.get("status") == "ok":
            await message.answer(safe_fmt(mood, "order_ok", fmt_data), reply_markup=MAIN_KB)
        elif data.get("error") == "rate_limit":
            await message.answer(safe_fmt(mood, "rate_limit", fmt_data), reply_markup=MAIN_KB)
        elif data.get("status") == "prompt":
            await message.answer(safe_fmt(mood, "empty", fmt_data), reply_markup=MAIN_KB)
        else:
            await message.answer(safe_fmt(mood, "order_err", fmt_data), reply_markup=MAIN_KB)
    else:
        await message.answer("❌ Ошибка при заказе. Попробуйте позже.", reply_markup=MAIN_KB)


@dp.message(Command("mix"))
async def cmd_mix(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("❓ Пример: `/mix водка, апельсиновый сок` или `/mix ром, кола, лёд`",
                                    reply_markup=MAIN_KB)

    token = user_tokens.get(message.from_user.id)
    if not token:
        await message.answer("Сначала нажмите /start", reply_markup=MAIN_KB)
        return

    # 🔥 Разделяем ингредиенты по запятым, игнорируя лишние пробелы
    ingredients = [i.strip().lower() for i in args[1].split(",") if i.strip()]

    if not ingredients:
        return await message.answer("❓ Укажите ингредиенты через запятую. Пример: `/mix водка, апельсиновый сок`",
                                    reply_markup=MAIN_KB)

    status, data = await api_call("POST", "/mix", token, {"ingredients": ingredients})
    mood = data.get("mood_level", "normal")

    if status == 200:
        drink_name = data.get("drink", "неизвестный напиток")
        fmt_data = {
            "drink": drink_name,
            "price": data.get("price", 0),
            "balance": data.get("balance", 0),
            "mood": mood
        }

        if data.get("status") == "ok":
            await message.answer(safe_fmt(mood, "mix_ok", fmt_data), reply_markup=MAIN_KB)
        elif data.get("error") == "rate_limit":
            await message.answer(safe_fmt(mood, "rate_limit", fmt_data), reply_markup=MAIN_KB)
        else:
            await message.answer(safe_fmt(mood, "mix_err", fmt_data), reply_markup=MAIN_KB)
    else:
        await message.answer("❌ Ошибка при смешивании. Попробуйте позже.", reply_markup=MAIN_KB)


@dp.message(Command("tip"))
async def cmd_tip(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("❓ Пример: `/tip 50` (сумма чаевых)", reply_markup=MAIN_KB)

    # 🔥 Проверяем, что введено целое положительное число
    try:
        tip_amount = int(args[1])
        if tip_amount <= 0:
            raise ValueError
    except ValueError:
        return await message.answer("💰 Чаевые должны быть положительным целым числом. Пример: `/tip 50`",
                                    reply_markup=MAIN_KB)

    token = user_tokens.get(message.from_user.id)
    if not token:
        await message.answer("Сначала нажмите /start", reply_markup=MAIN_KB)
        return

    status, data = await api_call("POST", "/tip", token, {"amount": tip_amount})
    mood = data.get("mood_level", "normal")

    if status == 200:
        fmt_data = {
            "amount": tip_amount,
            "balance": data.get("balance", 0),
            "mood": mood
        }

        if data.get("status") == "ok":
            await message.answer(safe_fmt(mood, "tip_ok", fmt_data), reply_markup=MAIN_KB)
        elif data.get("error") == "rate_limit":
            await message.answer(safe_fmt(mood, "rate_limit", fmt_data), reply_markup=MAIN_KB)
        else:
            await message.answer(safe_fmt(mood, "tip_err", fmt_data), reply_markup=MAIN_KB)
    else:
        await message.answer("❌ Ошибка при передаче чаевых.", reply_markup=MAIN_KB)


@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    token = user_tokens.get(message.from_user.id)
    if not token:
        await message.answer("Сначала нажмите /start", reply_markup=MAIN_KB)
        return

    status, data = await api_call("GET", "/balance", token)

    if status == 200:
        fmt_data = {
            "balance": data.get("balance", 0),
            "mood": data.get("mood_level", "normal")
        }
        await message.answer(safe_fmt(data.get("mood_level", "normal"), "balance", fmt_data), reply_markup=MAIN_KB)
    else:
        await message.answer("❌ Не удалось проверить баланс.", reply_markup=MAIN_KB)


@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    token = user_tokens.get(message.from_user.id)
    if not token:
        await message.answer("Сначала нажмите /start", reply_markup=MAIN_KB)
        return

    status, data = await api_call("GET", "/profile", token)

    if status == 200 and data.get("status") == "ok":
        fmt_data = {
            "id": data.get("id", "—"),
            "rank": data.get("rank", "—"),
            "total_orders": data.get("total_orders", 0),
            "unique": data.get("unique_drinks", 0),
            "fav": data.get("favorite_drink") or "нет",
            "closed": "Да" if data.get("bar_closed") else "Нет",
            "reopens": data.get("reopens_at", "скоро"),
            "mood": data.get("mood_level", "normal")
        }
        await message.answer(safe_fmt(data.get("mood_level", "normal"), "profile", fmt_data), reply_markup=MAIN_KB)
    else:
        await message.answer("❌ Не удалось загрузить профиль.", reply_markup=MAIN_KB)


@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    token = user_tokens.get(message.from_user.id)
    if not token:
        await message.answer("Сначала нажмите /start", reply_markup=MAIN_KB)
        return

    status, data = await api_call("POST", "/reset", token)

    if status == 200 and data.get("status") == "ok":
        # 🔥 Обновляем токен после сброса, если API вернул новый
        if "token" in data:
            user_tokens[message.from_user.id] = data["token"]
        await message.answer("🔄 Аккаунт сброшен. Добро пожаловать снова!", reply_markup=MAIN_KB)
    else:
        error_msg = data.get("error", "Неизвестная ошибка")
        await message.answer(f"❌ Ошибка при сбросе: {error_msg}", reply_markup=MAIN_KB)


# 🔥 Добавлена поддержка текстовых команд без слеша
@dp.message(F.text.lower().startswith(("заказать", "order ")))
async def text_order(message: Message):
    # Извлекаем название напитка из текста
    text = message.text.lower()
    if text.startswith("заказать"):
        drink_name = text.replace("заказать", "", 1).strip()
    else:
        drink_name = text.replace("order", "", 1).strip()

    if drink_name:
        # Создаем искусственную команду
        message.text = f"/order {drink_name}"
        await cmd_order(message)
    else:
        await message.answer("❓ Что заказать? Например: `Заказать Маргарита`", reply_markup=MAIN_KB)


@dp.message(F.text.lower().startswith(("смешать", "mix ")))
async def text_mix(message: Message):
    text = message.text.lower()
    if text.startswith("смешать"):
        ingredients = text.replace("смешать", "", 1).strip()
    else:
        ingredients = text.replace("mix", "", 1).strip()

    if ingredients:
        message.text = f"/mix {ingredients}"
        await cmd_mix(message)
    else:
        await message.answer("❓ Что смешать? Например: `Смешать водка, апельсиновый сок`", reply_markup=MAIN_KB)


@dp.message()
async def fallback(message: Message):
    # 🔥 Игнорируем сообщения, которые являются командами (начинаются с /)
    if message.text and message.text.startswith('/'):
        return

    # Проверяем, не является ли сообщение числом (чаевые)
    if message.text and message.text.strip().isdigit():
        message.text = f"/tip {message.text}"
        await cmd_tip(message)
    else:
        await message.answer(safe_fmt("normal", "empty", {}), reply_markup=MAIN_KB)


# ================= ЗАПУСК =================
async def main():
    global api_session
    api_session = aiohttp.ClientSession()

    bot = Bot(token=BOT_TOKEN)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("🍸 Бот 'Чёрный Бармен' запускается...")
    print(f"🌐 API URL: {API_URL}")
    print(f"🤖 Bot Token: {'✅ Установлен' if BOT_TOKEN and BOT_TOKEN != 'ВСТАВЬТЕ_ТОКЕН_БОТА' else '❌ Не установлен'}")

    # Проверка подключения к API
    try:
        async with api_session.get(f"{API_URL}/health") as resp:
            if resp.status == 200:
                print("✅ API сервер доступен")
            else:
                print(f"⚠️ API сервер ответил с кодом {resp.status}")
    except Exception as e:
        print(f"❌ Не удалось подключиться к API: {e}")

    try:
        await dp.start_polling(bot)
    finally:
        await api_session.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())