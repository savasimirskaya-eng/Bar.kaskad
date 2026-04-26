#!/usr/bin/env python3
"""
🍸 Телеграм-бот "Чёрный бармен"
Бот с характером — ведёт себя как сам бармен
"""

import os
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Конфиг ───────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
API_URL   = os.environ.get("API_URL",   "http://localhost:8000")

# Состояния ConversationHandler
CHOOSING, TYPING_INGREDIENT, TYPING_TIP, TYPING_PROMO = range(4)

# ─── Фразы с "характером" бармена ─────────────────────────────────────────────
MOOD_PHRASES = {
    "normal": {
        "greet":   "Добро пожаловать. Чего желаете?",
        "order_ok": "Держи, {drink}. С тебя {price}₽. Остаток: {balance}₽.",
        "order_err_funds": "Денег нет. У тебя {balance}₽, а надо {price}₽.",
        "order_err_unknown": "Такого не делаю.",
        "mix_ok":  "Смешал. Получилось — {drink}. Цена: {price}₽.",
        "mix_err": "Не знаю такого рецепта. Учи матчасть.",
        "balance": "На счету у тебя {balance}₽.",
        "tip_ok":  "Чаевые принял. Спасибо.",
        "profile": "Ты — {rank}. Заказов: {total}. Уникальных напитков: {unique}.",
    },
    "grumpy": {
        "greet":   "Чего надо? Говори быстро.",
        "order_ok": "*ставит стакан* {drink}. {price}₽. Не задерживай.",
        "order_err_funds": "Денег нет — иди домой. У тебя {balance}₽.",
        "order_err_unknown": "Не знаю такого. Следующий.",
        "mix_ok":  "На. {drink}. {price}₽. И не надоедай.",
        "mix_err": "Что ты вообще мешаешь? Это не рецепт.",
        "balance": "{balance}₽. Мало.",
        "tip_ok":  "Мм. Принято.",
        "profile": "Ранг: {rank}. Заказов: {total}.",
    },
    "hostile": {
        "greet":   "...",
        "order_ok": "*молча ставит* {drink}. {price}₽.",
        "order_err_funds": "Вали отсюда. Денег нет.",
        "order_err_unknown": "*смотрит волком*",
        "mix_ok":  "{drink}. {price}₽. Ещё слово — выгоню.",
        "mix_err": "НЕТ.",
        "balance": "{balance}₽.",
        "tip_ok":  "*берёт молча*",
        "profile": "...",
    },
    "friendly": {
        "greet":   "О, снова ты! Рад видеть. Что будем пить?",
        "order_ok": "Отличный выбор — {drink}! Всего {price}₽. Осталось {balance}₽ 😊",
        "order_err_funds": "Эх, не хватает... У тебя {balance}₽, нужно {price}₽.",
        "order_err_unknown": "Такого у меня нет, но могу что-нибудь смешать!",
        "mix_ok":  "Вот твой {drink}! За {price}₽ — наслаждайся 🍹",
        "mix_err": "Хм, не знаю такого сочетания. Попробуй другое!",
        "balance": "У тебя {balance}₽ — хватит на хороший коктейль!",
        "tip_ok":  "Спасибо за чаевые! Ты душа-человек ❤️",
        "profile": "Ты {rank} — гордись! Заказов: {total}, напитков: {unique}.",
    },
    "generous": {
        "greet":   "Добро пожаловать! Сегодня я щедр. Что угодно!",
        "order_ok": "{drink} — прекрасный выбор! {price}₽. Осталось {balance}₽ 🎉",
        "order_err_funds": "Подожди, займу тебе... шучу. {balance}₽ у тебя.",
        "order_err_unknown": "Этого нет, но попроси — придумаем!",
        "mix_ok":  "Шедевр — {drink}! Всего {price}₽ 🥂",
        "mix_err": "Не знаю, но это звучало смело!",
        "balance": "Богатей! У тебя {balance}₽ 💰",
        "tip_ok":  "Ты слишком добр! Спасибо от всей души! 🙌",
        "profile": "Легенда! {rank}, {total} заказов!",
    },
}

def get_phrase(mood: str, key: str, **kwargs) -> str:
    """Получить фразу в зависимости от настроения бармена."""
    phrases = MOOD_PHRASES.get(mood, MOOD_PHRASES["normal"])
    template = phrases.get(key, MOOD_PHRASES["normal"].get(key, "..."))
    try:
        return template.format(**kwargs)
    except KeyError:
        return template

def mood_emoji(mood: str) -> str:
    return {
        "normal":   "😐",
        "grumpy":   "😠",
        "hostile":  "😡",
        "friendly": "😊",
        "generous": "🤩",
    }.get(mood, "😐")

# ─── Хранилище токенов (tg_user_id -> api_token) ──────────────────────────────
USER_TOKENS: dict[int, str] = {}

async def api_request(method: str, endpoint: str, token: str = None,
                      json: dict = None, headers: dict = None) -> dict:
    """Универсальная функция для запросов к API."""
    url = f"{API_URL}{endpoint}"
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if headers:
        hdrs.update(headers)

    async with httpx.AsyncClient(timeout=10) as client:
        if method == "GET":
            resp = await client.get(url, headers=hdrs)
        else:
            resp = await client.post(url, json=json or {}, headers=hdrs)

    try:
        return resp.json()
    except Exception:
        return {"status": "error", "error": "api_unavailable"}

# ─── Главное меню (клавиатура) ────────────────────────────────────────────────
def main_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("🍹 Меню",       callback_data="menu"),
         InlineKeyboardButton("📋 Заказать",   callback_data="order")],
        [InlineKeyboardButton("🧪 Смешать",    callback_data="mix"),
         InlineKeyboardButton("💰 Баланс",     callback_data="balance")],
        [InlineKeyboardButton("🎁 Промокод",   callback_data="promo"),
         InlineKeyboardButton("💸 Чаевые",     callback_data="tip")],
        [InlineKeyboardButton("📜 История",    callback_data="history"),
         InlineKeyboardButton("👤 Профиль",    callback_data="profile")],
        [InlineKeyboardButton("🔄 Сброс",      callback_data="reset")],
    ]
    return InlineKeyboardMarkup(buttons)

def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад", callback_data="back")]
    ])

# ─── /start ───────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid not in USER_TOKENS:
        data = await api_request("POST", "/register")
        if data.get("status") == "ok":
            USER_TOKENS[uid] = data["token"]
            await update.message.reply_text(
                f"🍸 *Добро пожаловать в Чёрный бар!*\n\n"
                f"Твой ID: `{data['id']}`\n"
                f"Начальный баланс: *100₽*\n\n"
                f"Я — бармен. У меня есть настроение, и оно меняется.\n"
                f"Не зли меня — будет дороже. Радуй — будет дешевле.\n\n"
                f"Чего желаешь?",
                parse_mode="Markdown",
                reply_markup=main_keyboard()
            )
        else:
            await update.message.reply_text("❌ Не могу подключиться к бару. Попробуй позже.")
    else:
        await update.message.reply_text(
            "🍸 *Чёрный бар*\n\nТы уже зарегистрирован. Выбирай:",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )

# ─── Callback обработчик ──────────────────────────────────────────────────────
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid   = query.from_user.id
    data  = query.data
    token = USER_TOKENS.get(uid)

    if not token and data != "back":
        await query.edit_message_text(
            "Ты не зарегистрирован. Напиши /start",
            reply_markup=back_keyboard()
        )
        return

    # ── НАЗАД ──────────────────────────────────────────────────────────────
    if data == "back":
        await query.edit_message_text(
            "🍸 Чёрный бар. Что дальше?",
            reply_markup=main_keyboard()
        )
        ctx.user_data.clear()
        return

    # ── МЕНЮ ───────────────────────────────────────────────────────────────
    if data == "menu":
        resp = await api_request("GET", "/menu", token=token)
        if resp.get("status") == "error" and resp.get("error") == "bar_closed":
            mood = resp.get("mood_level", "normal")
            text = (f"{mood_emoji(mood)} Бар закрыт. Откроется в {resp.get('reopens_at')}.\n"
                    f"Баланс: {resp.get('balance')}₽")
        else:
            mood   = resp.get("mood_level", "normal")
            drinks = resp.get("drinks", [])
            lines  = [f"{mood_emoji(mood)} *Меню* (настроение: {mood})\n"]
            for d in drinks:
                ings = ", ".join(d.get("ingredients", []))
                lines.append(f"• *{d['name']}* — {d['price']}₽\n  _{ings}_")
            lines.append(f"\nТвой баланс: *{resp.get('balance')}₽*")
            text = "\n".join(lines)
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=back_keyboard())

    # ── ЗАКАЗАТЬ (показать список) ──────────────────────────────────────────
    elif data == "order":
        resp = await api_request("GET", "/menu", token=token)
        if resp.get("status") == "error":
            await query.edit_message_text("Бар закрыт или ошибка.", reply_markup=back_keyboard())
            return
        drinks  = resp.get("drinks", [])
        buttons = []
        for d in drinks:
            buttons.append([InlineKeyboardButton(
                f"{d['name']} — {d['price']}₽",
                callback_data=f"do_order:{d['name']}"
            )])
        buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="back")])
        await query.edit_message_text(
            "📋 Выбери напиток:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    # ── СДЕЛАТЬ ЗАКАЗ ──────────────────────────────────────────────────────
    elif data.startswith("do_order:"):
        drink_name = data.split(":", 1)[1]
        resp = await api_request("POST", "/order", token=token,
                                 json={"name": drink_name})
        mood = resp.get("mood_level", "normal")

        if resp.get("status") == "ok":
            extra = ""
            if resp.get("favorite"):
                extra += "\n⭐ Любимый напиток — скидка 10%!"
            if resp.get("free_every_7th"):
                extra += "\n🎉 Каждый 7-й бесплатно!"
            if resp.get("note"):
                extra += f"\n💬 _{resp['note']}_"
            text = (get_phrase(mood, "order_ok",
                               drink=drink_name,
                               price=resp['price'],
                               balance=resp['balance'])
                    + extra)
        elif resp.get("error") == "insufficient_funds":
            text = get_phrase(mood, "order_err_funds",
                              balance=resp.get('balance', 0),
                              price=resp.get('price', 0))
        elif resp.get("error") == "bar_closed":
            text = f"Бар закрыт. Открытие в {resp.get('reopens_at')}."
        elif resp.get("status") == "prompt":
            text = f"⚠️ {mood_emoji(mood)} Ты уже пьёшь это пятый раз подряд... точно продолжаем?"
        else:
            text = get_phrase(mood, "order_err_unknown")

        await query.edit_message_text(
            f"{mood_emoji(mood)} {text}",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )

    # ── СМЕШАТЬ (выбор ингредиентов) ──────────────────────────────────────
    elif data == "mix":
        ctx.user_data["mix_ingredients"] = []
        await _show_mix_menu(query, ctx)

    elif data.startswith("mix_add:"):
        ing = data.split(":", 1)[1]
        ctx.user_data.setdefault("mix_ingredients", []).append(ing)
        await _show_mix_menu(query, ctx)

    elif data.startswith("mix_remove:"):
        ing = data.split(":", 1)[1]
        lst = ctx.user_data.get("mix_ingredients", [])
        if ing in lst:
            lst.remove(ing)
        await _show_mix_menu(query, ctx)

    elif data == "mix_confirm":
        ings = ctx.user_data.get("mix_ingredients", [])
        resp = await api_request("POST", "/mix", token=token,
                                 json={"ingredients": ings})
        mood = resp.get("mood_level", "normal")

        if resp.get("status") == "ok":
            extra = ""
            if resp.get("secret"):
                effects = {
                    "balance_doubled": "💀 Баланс удвоен... но это плохо.",
                    "mood_max":        "😌 Бармен стал щедрым!",
                    "secret_unlocked": "🔮 Секрет раскрыт!",
                    "armageddon":      "☠️ АРМАГЕДДОН. Бар закрыт на 10 минут.",
                }
                extra = f"\n🤫 *Секрет:* {effects.get(resp.get('effect'), resp.get('effect'))}"
            if resp.get("favorite"):
                extra += "\n⭐ Любимый — скидка 25%!"
            if resp.get("free_every_7th"):
                extra += "\n🎉 Каждый 7-й бесплатно!"

            text = (get_phrase(mood, "mix_ok",
                               drink=resp['drink'],
                               price=resp['price'],
                               balance=resp['balance'])
                    + extra)
        elif resp.get("status") == "prompt":
            text = f"⚠️ Ты делаешь это в 5-й раз подряд... точно?"
        elif resp.get("error") == "insufficient_funds":
            text = f"Не хватает средств. Баланс: {resp.get('balance')}₽"
        elif resp.get("error") == "invalid_ingredient":
            text = "Такого ингредиента не существует."
        else:
            text = get_phrase(mood, "mix_err")

        ctx.user_data["mix_ingredients"] = []
        await query.edit_message_text(
            f"{mood_emoji(mood)} {text}",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )

    # ── БАЛАНС ─────────────────────────────────────────────────────────────
    elif data == "balance":
        resp = await api_request("GET", "/balance", token=token)
        mood = resp.get("mood_level", "normal")
        text = get_phrase(mood, "balance", balance=resp.get("balance", 0))
        if resp.get("note"):
            text += f"\n💬 _{resp['note']}_"
        await query.edit_message_text(
            f"{mood_emoji(mood)} {text}",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )

    # ── ПРОМОКОД ───────────────────────────────────────────────────────────
    elif data == "promo":
        # Показать активные промокоды
        resp = await api_request("GET", "/promo", token=token)
        if resp.get("status") == "ok":
            active = resp.get("active", [])
            if active:
                lines = ["🎁 *Активные промокоды:*\n"]
                buttons = []
                for p in active:
                    rem = f"(осталось: {p['remaining']})" if p.get("remaining") else "(безлимит)"
                    lines.append(f"• `{p['code']}` {rem}")
                    buttons.append([InlineKeyboardButton(
                        f"Активировать {p['code']}",
                        callback_data=f"use_promo:{p['code']}"
                    )])
                buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="back")])
                await query.edit_message_text(
                    "\n".join(lines),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            else:
                await query.edit_message_text(
                    "🎁 Нет доступных промокодов.",
                    reply_markup=back_keyboard()
                )
        else:
            await query.edit_message_text(
                "❌ Промокоды недоступны.",
                reply_markup=back_keyboard()
            )

    elif data.startswith("use_promo:"):
        code = data.split(":", 1)[1]
        resp = await api_request("POST", "/promo", token=token,
                                 json={"code": code})
        mood = resp.get("mood_level", "normal")
        if resp.get("status") == "ok":
            text = f"✅ Промокод *{code}* активирован!\nБаланс: {resp['balance']}₽"
        elif resp.get("error") == "already_used":
            text = "Этот промокод уже использован."
        else:
            text = "Неверный промокод."
        await query.edit_message_text(
            f"{mood_emoji(mood)} {text}",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )

    # ── ЧАЕВЫЕ ─────────────────────────────────────────────────────────────
    elif data == "tip":
        buttons = [
            [InlineKeyboardButton("5₽",  callback_data="do_tip:5"),
             InlineKeyboardButton("10₽", callback_data="do_tip:10"),
             InlineKeyboardButton("20₽", callback_data="do_tip:20")],
            [InlineKeyboardButton("50₽", callback_data="do_tip:50"),
             InlineKeyboardButton("100₽",callback_data="do_tip:100")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back")],
        ]
        await query.edit_message_text(
            "💸 Сколько оставишь на чай?",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data.startswith("do_tip:"):
        amount = int(data.split(":", 1)[1])
        resp = await api_request("POST", "/tip", token=token,
                                 json={"amount": amount})
        mood = resp.get("mood_level", "normal")
        if resp.get("status") == "ok":
            text = get_phrase(mood, "tip_ok")
            text += f"\nОсталось: {resp['balance']}₽"
        else:
            text = f"Ошибка: {resp.get('error', 'unknown')}"
        await query.edit_message_text(
            f"{mood_emoji(mood)} {text}",
            reply_markup=back_keyboard()
        )

    # ── ИСТОРИЯ ────────────────────────────────────────────────────────────
    elif data == "history":
        resp = await api_request("GET", "/history", token=token)
        orders = resp.get("orders", [])
        if not orders:
            text = "📜 История пуста. Пора что-нибудь заказать!"
        else:
            last = orders[-10:]  # последние 10
            lines = [f"📜 *Последние {len(last)} заказов:*\n"]
            for o in reversed(last):
                method = "📋" if o["method"] == "order" else "🧪"
                lines.append(f"{method} {o['drink']} — {o['price']}₽")
            lines.append(f"\nБаланс: *{resp.get('balance')}₽*")
            text = "\n".join(lines)
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=back_keyboard())

    # ── ПРОФИЛЬ ────────────────────────────────────────────────────────────
    elif data == "profile":
        resp = await api_request("GET", "/profile", token=token)
        mood_resp = await api_request("GET", "/balance", token=token)
        mood = mood_resp.get("mood_level", "normal")

        if resp.get("status") == "ok":
            fav = resp.get("favorite_drink") or "нет"
            closed = "🔒 Закрыт" if resp.get("bar_closed") else "🟢 Открыт"
            text = (
                f"{mood_emoji(mood)} *Профиль*\n\n"
                f"🆔 ID: `{resp['id']}`\n"
                f"🏆 Ранг: *{resp['rank']}*\n"
                f"📊 Заказов: {resp['total_orders']}\n"
                f"🍹 Уникальных напитков: {resp['unique_drinks']}\n"
                f"⭐ Любимый: {fav}\n"
                f"🚪 Бар: {closed}\n"
                f"😏 Настроение бармена: {mood}"
            )
        else:
            text = "Не удалось загрузить профиль."
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=back_keyboard())

    # ── СБРОС ──────────────────────────────────────────────────────────────
    elif data == "reset":
        buttons = [
            [InlineKeyboardButton("✅ Да, сбросить", callback_data="reset_confirm"),
             InlineKeyboardButton("❌ Отмена", callback_data="back")]
        ]
        await query.edit_message_text(
            "⚠️ Сбросить аккаунт к начальному состоянию?\n"
            "(баланс станет 100₽, история удалится)",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data == "reset_confirm":
        resp = await api_request("POST", "/reset", token=token)
        if resp.get("status") == "ok":
            text = "✅ Аккаунт сброшен. Начинаем заново!"
        else:
            text = "❌ Ошибка сброса."
        await query.edit_message_text(text, reply_markup=back_keyboard())


# ─── Вспомогательная функция для экрана смешивания ────────────────────────────
VALID_INGREDIENTS = [
    "водка", "ром", "текила", "виски", "джин",
    "кола", "сок", "тоник", "лёд", "молоко"
]

async def _show_mix_menu(query, ctx):
    selected = ctx.user_data.get("mix_ingredients", [])
    selected_str = ", ".join(selected) if selected else "ничего не выбрано"

    buttons = []
    row = []
    for i, ing in enumerate(VALID_INGREDIENTS):
        mark = "✅" if ing in selected else ""
        action = f"mix_remove:{ing}" if ing in selected else f"mix_add:{ing}"
        row.append(InlineKeyboardButton(f"{mark}{ing}", callback_data=action))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    bottom = []
    if selected:
        bottom.append(InlineKeyboardButton("🧪 Смешать!", callback_data="mix_confirm"))
    bottom.append(InlineKeyboardButton("◀️ Назад", callback_data="back"))
    buttons.append(bottom)

    await query.edit_message_text(
        f"🧪 *Выбери ингредиенты:*\n\nВыбрано: _{selected_str}_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ─── /help ────────────────────────────────────────────────────────────────────
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🍸 *Чёрный бармен — справка*\n\n"
        "*/start* — начать / главное меню\n"
        "*/help*  — эта справка\n\n"
        "*Как работает:*\n"
        "• Заказывай напитки из меню\n"
        "• Смешивай сам — дешевле!\n"
        "• Оставляй чаевые — бармен подобреет\n"
        "• Ищи секретные рецепты\n"
        "• Активируй промокоды\n\n"
        "*Ингредиенты:* водка, ром, текила, виски, джин, кола, сок, тоник, лёд, молоко\n\n"
        "*Настроение бармена влияет на цены!*\n"
        "😐 normal → 😠 grumpy (+наценка) → 😡 hostile (+10%)\n"
        "😊 friendly / 🤩 generous → скидки"
    )
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=main_keyboard())


# ─── Запуск ───────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("🍸 Бот запускается...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()