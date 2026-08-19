
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, ContentType
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

from database import Database

load_dotenv()
BOT_TOKEN = "8998138881:AAEvMMxIuti_p1GYs_bQ8fHwDbMnPV1KupA"
OWNER_ID = 8872934046


DB_PATH = "data/maison.db"
REQUIRED_CHANNEL_ID = -1003783779233
db = Database(DB_PATH)

router = Router()
logging.basicConfig(level=logging.INFO)

# -------------------- Text/config --------------------

DEFAULTS = {
    "start": "Maison Accs - твой бот для покупки аккаунтов\n\n{user}, твой баланс {balance} ₽",
    "stock": "В наличии: {count} аккаунтов",
    "balance": "Ваш баланс: {balance} ₽\nПополнить его вы можете кнопками ниже",
    "rubles": "₽ рубли\n\n+79313716777 • Т-банк\n! переводите точную сумму !",
    "stars_pay": "Звезды\n\nОтправьте звезды на аккаунт @fegote\nКомиссия 10%",
    "stars_empty": "На данный момент звезд нету в наличии, посмотрите этот раздел чуть позже",
    "news": "Новостной канал - @MaisonAccsChannel",
    "profile": "Ваш профиль\n\nID: {id}\nБаланс: {balance} ₽",
    "reviews": "Наши отзывы - @repacrisov",
    "support": "Есть какой-то вопрос? Напиши в поддержку @fegote",
    "faq": "FAQ\n\nЗдесь вы сможете разместить свой текст.",
    "bad_star_amount": "Выберите число, которое можно отправить подарком",
    "star_purchase": "Доступно звезд: {count}\n\nВыберите количество для покупки:",
    "accounts_purchase": "В наличии: {count} аккаунтов\n\nЦена аккаунта: {price} ₽\n\nВыберите действие:",
}

ALLOWED_STAR_AMOUNTS = [15,25,30,40,45,50,65,75,80,100,150,200,250,300]
# Star stock is an integer inventory. Delivery/confirmation is manual in this version.
# Admin can change the stock from the admin panel.


def subscribe_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/MaisonAccsChannel")],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]
    ])

async def is_subscribed(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logging.warning("Subscription check failed: %s", e)
        return False

async def require_subscription(message: Message) -> bool:
    if await is_subscribed(message.bot, message.from_user.id):
        return True
    await message.answer(
        "Чтобы пользоваться ботом, необходимо подписаться на наш канал.\n\n"
        "После подписки нажмите «Проверить подписку».",
        reply_markup=subscribe_kb()
    )
    return False

def text(key, **kwargs):
    return db.get_setting(key, DEFAULTS[key]).format(**kwargs)

def is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пополнить баланс", callback_data="balance")],
        [InlineKeyboardButton(text="Купить аккаунты", callback_data="accounts")],
        [InlineKeyboardButton(text="Купить звезды", callback_data="stars")],
        [
            InlineKeyboardButton(text="Новостоной канал", url="https://t.me/MaisonAccsChannel"),
            InlineKeyboardButton(text="Мой профиль", callback_data="profile")
        ],
        [
            InlineKeyboardButton(text="Отзывы", url="https://t.me/repacrisov"),
            InlineKeyboardButton(text="Поддержка", url="https://t.me/fegote")
        ],
        [InlineKeyboardButton(text="FAQ", callback_data="faq")],
    ])

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="home")]
    ])

def balance_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="₽ рубли", callback_data="topup_rubles")],
        [InlineKeyboardButton(text="Звезды", callback_data="topup_stars")],
        [InlineKeyboardButton(text="Назад", callback_data="home")],
    ])

def stars_kb(stock):
    if stock <= 0:
        return back_kb()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Купить", callback_data="stars_buy")],
        [InlineKeyboardButton(text="Назад", callback_data="home")],
    ])

def stars_buy_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Купить все", callback_data="stars_all")],
        [InlineKeyboardButton(text="Купить другое количество", callback_data="stars_other")],
        [InlineKeyboardButton(text="Назад", callback_data="stars")],
    ])

def accounts_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Купить", callback_data="account_buy")],
        [InlineKeyboardButton(text="Назад", callback_data="home")],
    ])

# -------------------- States --------------------

class AdminState(StatesGroup):
    broadcast = State()
    edit_key = State()
    edit_value = State()
    star_stock = State()
    account_stock = State()

class PurchaseState(StatesGroup):
    star_amount = State()

class TopupState(StatesGroup):
    payment_type = State()
    amount = State()
    receipt = State()

# -------------------- Helpers --------------------

async def safe_edit(call: CallbackQuery, body: str, markup=None):
    try:
        await call.message.edit_text(body, reply_markup=markup)
    except Exception:
        await call.message.answer(body, reply_markup=markup)

async def pin_start(bot: Bot, chat_id: int, message_id: int, previous_id: int | None):
    if previous_id:
        try:
            await bot.unpin_chat_message(chat_id=chat_id, message_id=previous_id)
        except Exception:
            pass
    try:
        await bot.pin_chat_message(chat_id=chat_id, message_id=message_id, disable_notification=True)
    except Exception:
        # Bot needs can_pin_messages permission in the chat to pin successfully.
        pass

# -------------------- /start --------------------

@router.message(CommandStart())
async def start(message: Message):
    if not await require_subscription(message):
        return
    user = db.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or ""
    )
    body = text("start", user=(message.from_user.first_name or "пользователь"), balance=user["balance"])
    sent = await message.answer(body, reply_markup=main_kb())

    old = user.get("last_start_message_id")
    db.set_last_start_message(message.from_user.id, sent.message_id)
    await pin_start(message.bot, message.chat.id, sent.message_id, old)

# -------------------- Main navigation --------------------


@router.callback_query(F.data == "check_subscription")
async def check_subscription(call: CallbackQuery):
    if await is_subscribed(call.bot, call.from_user.id):
        user = db.get_or_create_user(
            call.from_user.id,
            call.from_user.username or "",
            call.from_user.first_name or ""
        )
        await safe_edit(
            call,
            text("start", user=(call.from_user.first_name or "пользователь"), balance=user["balance"]),
            main_kb()
        )
        await call.answer("Подписка подтверждена ✅")
    else:
        await call.answer("Вы еще не подписались на канал.", show_alert=True)

@router.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    user = db.get_user(call.from_user.id)
    await safe_edit(call, text("start", user=(call.from_user.first_name or "пользователь"), balance=user["balance"]), main_kb())
    await call.answer()

@router.callback_query(F.data == "balance")
async def balance(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    user = db.get_user(call.from_user.id)
    await safe_edit(call, text("balance", balance=user["balance"]), balance_kb())
    await call.answer()

@router.callback_query(F.data == "rubles")
async def rubles(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    await safe_edit(call, text("rubles"), back_kb())
    await call.answer()

@router.callback_query(F.data == "stars_pay")
async def stars_pay(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    await safe_edit(call, text("stars_pay"), back_kb())
    await call.answer()


@router.callback_query(F.data == "topup_rubles")
async def topup_rubles(call: CallbackQuery, state: FSMContext):
    await state.set_state(TopupState.amount)
    await state.update_data(payment_type="rubles")
    await safe_edit(
        call,
        "Пополнение в рублях\n\n"
        "+79313716777 • Т-банк\n"
        "! переводите точную сумму !\n\n"
        "Введите сумму, которую вы отправили (только число).",
        back_kb()
    )
    await call.answer()

@router.callback_query(F.data == "topup_stars")
async def topup_stars(call: CallbackQuery, state: FSMContext):
    await state.set_state(TopupState.amount)
    await state.update_data(payment_type="stars")
    await safe_edit(
        call,
        "Пополнение звездами\n\n"
        "Отправьте звезды на аккаунт @fegote.\n"
        "Комиссия 10%.\n\n"
        "Введите количество отправленных звезд (только число).",
        back_kb()
    )
    await call.answer()

@router.message(TopupState.amount)
async def topup_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip().replace(",", "."))
        if amount <= 0:
            raise ValueError
    except Exception:
        await message.answer("Введите положительную сумму числом.")
        return

    data = await state.get_data()
    payment_type = data["payment_type"]

    if payment_type == "rubles":
        sent = round(amount, 2)
        credited = sent
        info = f"Отправлено: {sent:g} ₽\nЗачислится: {credited:g} ₽"
    else:
        if amount != int(amount):
            await message.answer("Количество звезд должно быть целым числом.")
            return
        sent = int(amount)
        credited = round(sent * 0.90, 2)
        info = f"Отправлено: {sent} ⭐\nЗачислится: {credited:g} ⭐ (минус 10%)"

    await state.update_data(sent_amount=sent, credited_amount=credited)
    await state.set_state(TopupState.receipt)
    await message.answer(
        f"{info}\n\n"
        "Теперь отправьте скриншот/чек оплаты фотографией или документом."
    )

@router.message(TopupState.receipt, F.photo)
async def topup_receipt_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = message.photo[-1].file_id
    await create_topup_request_and_notify(message, state, file_id, "photo")

@router.message(TopupState.receipt, F.document)
async def topup_receipt_document(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = message.document.file_id
    await create_topup_request_and_notify(message, state, file_id, "document")

async def create_topup_request_and_notify(message: Message, state: FSMContext, file_id: str, receipt_type: str):
    data = await state.get_data()
    payment_type = data["payment_type"]
    sent = data["sent_amount"]
    credited = data["credited_amount"]

    request_id = db.create_topup_request(
        message.from_user.id, payment_type, sent, credited, file_id, receipt_type
    )
    user = db.get_user(message.from_user.id)

    type_name = "₽ рубли" if payment_type == "rubles" else "⭐ звезды"
    owner_text = (
        f"🔔 Заявка на пополнение #{request_id}\n\n"
        f"Пользователь: {message.from_user.full_name}\n"
        f"Username: @{message.from_user.username or 'нет'}\n"
        f"Telegram ID: {message.from_user.id}\n"
        f"ID в боте: {user['internal_id']}\n\n"
        f"Способ: {type_name}\n"
        f"Отправлено: {sent:g} {'₽' if payment_type == 'rubles' else '⭐'}\n"
        f"Зачислится: {credited:g} {'₽' if payment_type == 'rubles' else '⭐'}"
    )
    owner_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Выдать", callback_data=f"topup_approve:{request_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"topup_cancel:{request_id}")
        ]
    ])

    try:
        if receipt_type == "photo":
            await message.bot.send_photo(OWNER_ID, file_id, caption=owner_text, reply_markup=owner_kb)
        else:
            await message.bot.send_document(OWNER_ID, file_id, caption=owner_text, reply_markup=owner_kb)
    except Exception:
        db.finish_topup_request(request_id, "failed")
        await message.answer("Не удалось отправить заявку владельцу. Попробуйте еще раз.", reply_markup=back_kb())
        await state.clear()
        return

    await message.answer(
        f"Заявка #{request_id} отправлена владельцу.\n\n"
        f"К зачислению: {credited:g} {'₽' if payment_type == 'rubles' else '⭐'}\n"
        "Баланс будет изменен после проверки чека.",
        reply_markup=back_kb()
    )
    await state.clear()

@router.message(TopupState.receipt)
async def topup_receipt_invalid(message: Message):
    await message.answer("Отправьте скриншот/чек фотографией или документом.")

@router.callback_query(F.data.startswith("topup_approve:"))
async def topup_approve(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    request_id = int(call.data.split(":")[1])
    req = db.get_topup_request(request_id)
    if not req or req["status"] != "pending":
        return await call.answer("Заявка уже обработана.", show_alert=True)

    db.add_topup(req["telegram_id"], req["credited_amount"])
    db.finish_topup_request(request_id, "approved")

    try:
        await call.bot.send_message(
            req["telegram_id"],
            f"✅ Пополнение подтверждено.\n\n"
            f"Зачислено: {req['credited_amount']:g} "
            f"{'₽' if req['payment_type'] == 'rubles' else '⭐'}"
        )
    except Exception:
        pass

    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"Заявка #{request_id}: выдано.")
    await call.answer("Зачислено")

@router.callback_query(F.data.startswith("topup_cancel:"))
async def topup_cancel(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    request_id = int(call.data.split(":")[1])
    req = db.get_topup_request(request_id)
    if not req or req["status"] != "pending":
        return await call.answer("Заявка уже обработана.", show_alert=True)

    db.finish_topup_request(request_id, "cancelled")
    try:
        await call.bot.send_message(
            req["telegram_id"],
            f"❌ Пополнение #{request_id} отменено."
        )
    except Exception:
        pass

    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"Заявка #{request_id}: отменена.")
    await call.answer("Отменено")

@router.callback_query(F.data == "accounts")
async def accounts(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    count = db.get_account_stock()
    await safe_edit(call, text("stock", count=count), accounts_kb())
    await call.answer()

@router.callback_query(F.data == "account_buy")
async def account_buy(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    user = db.get_user(call.from_user.id)
    count = db.get_account_stock()
    price = db.get_cheapest_account_price()
    body = text("accounts_purchase", count=count, price=price)
    if count <= 0:
        body = text("stock", count=0)
    elif user["balance"] < price:
        body += "\n\nНедостаточно средств. Пополните баланс."
    else:
        item = db.take_account()
        if item is None:
            body = text("stock", count=0)
        else:
            price = item["price"]
            if user["balance"] < price:
                body = f"Стоимость аккаунта: {price:g} ₽\n\nНедостаточно средств. Пополните баланс."
                # Put the account back into stock if the user cannot afford it.
                db.conn.execute("UPDATE accounts SET sold=0 WHERE value=?", (item["value"],))
                db.conn.commit()
            else:
                db.change_balance(call.from_user.id, -price)
                db.add_account_purchase(call.from_user.id, price)
                body = f"Покупка оформлена.\n\nВаш аккаунт:\n{item['value']}\n\nЦена: {price:g} ₽" 
    await safe_edit(call, body, back_kb())
    await call.answer()

@router.callback_query(F.data == "stars")
async def stars(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    stock = db.get_star_stock()
    if stock <= 0:
        await safe_edit(call, text("stars_empty"), back_kb())
    else:
        await safe_edit(call, text("star_purchase", count=stock), stars_kb(stock))
    await call.answer()

@router.callback_query(F.data == "stars_buy")
async def stars_buy(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    await safe_edit(call, "Выберите количество звезд:", stars_buy_kb())
    await call.answer()

@router.callback_query(F.data == "stars_all")
async def stars_all(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    stock = db.get_star_stock()
    if stock <= 0:
        await safe_edit(call, text("stars_empty"), back_kb())
    elif stock not in ALLOWED_STAR_AMOUNTS:
        await safe_edit(call, text("bad_star_amount"), InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Выбрать другое кол-во звезд", callback_data="stars_other")],
            [InlineKeyboardButton(text="Назад", callback_data="stars")],
        ]))
    else:
        # Pricing is configurable in DB; default 1 ₽ per star.
        price = db.get_star_price() * stock
        user = db.get_user(call.from_user.id)
        if user["balance"] < price:
            await safe_edit(call, f"Стоимость: {price} ₽\n\nНедостаточно средств. Пополните баланс.", back_kb())
        else:
            db.change_star_stock(-stock)
            db.change_balance(call.from_user.id, -price)
            db.add_star_purchase(call.from_user.id, stock, price)
            await safe_edit(call, f"Покупка оформлена: {stock} звезд.\nСписано: {price} ₽", back_kb())
    await call.answer()

@router.callback_query(F.data == "stars_other")
async def stars_other(call: CallbackQuery, state: FSMContext):
    await state.set_state(PurchaseState.star_amount)
    await safe_edit(call, "Введите количество звезд:", back_kb())
    await call.answer()

@router.message(PurchaseState.star_amount)
async def star_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
    except Exception:
        await message.answer(text("bad_star_amount"), reply_markup=back_kb())
        return
    stock = db.get_star_stock()
    if amount not in ALLOWED_STAR_AMOUNTS or amount > stock:
        await message.answer(text("bad_star_amount"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Выбрать другое кол-во звезд", callback_data="stars_other")],
            [InlineKeyboardButton(text="Назад", callback_data="stars")],
        ]))
        return
    price = db.get_star_price() * amount
    user = db.get_user(message.from_user.id)
    if user["balance"] < price:
        await message.answer(f"Стоимость: {price} ₽\n\nНедостаточно средств. Пополните баланс.", reply_markup=back_kb())
    else:
        db.change_star_stock(-amount)
        db.change_balance(message.from_user.id, -price)
        db.add_star_purchase(message.from_user.id, amount, price)
        await message.answer(f"Покупка оформлена: {amount} звезд.\nСписано: {price} ₽", reply_markup=back_kb())
    await state.clear()

@router.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    user = db.get_user(call.from_user.id)
    await safe_edit(call, text("profile", id=user["internal_id"], balance=user["balance"]), back_kb())
    await call.answer()

@router.callback_query(F.data == "faq")
async def faq(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    await safe_edit(call, text("faq"), back_kb())
    await call.answer()

# -------------------- Admin --------------------

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статистика", callback_data="adm_stats")],
        [InlineKeyboardButton(text="Рассылка", callback_data="adm_broadcast")],
        [InlineKeyboardButton(text="Изменить текст", callback_data="adm_text")],
        [InlineKeyboardButton(text="Текст внутри кнопки", callback_data="adm_buttons")],
        [InlineKeyboardButton(text="Товары", callback_data="adm_products")],
        [InlineKeyboardButton(text="Назад", callback_data="home")],
    ])

@router.message(Command("admin"))
async def admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Админ-панель Maison Accs", reply_markup=admin_kb())

@router.callback_query(F.data == "adm_stats")
async def adm_stats(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    s = db.stats()
    body = (
        f"Статистика\n\n"
        f"Количество пользователей: {s['users']}\n"
        f"Максимальное ID: {s['max_id']}\n\n"
        f"Всего покупок аккаунтов: {s['account_purchases']}\n"
        f"Продано звезд: {s['stars_sold']}"
    )
    await safe_edit(call, body, admin_kb())
    await call.answer()

@router.callback_query(F.data == "adm_broadcast")
async def adm_broadcast(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await state.set_state(AdminState.broadcast)
    await safe_edit(call, "Отправьте текст рассылки одним сообщением.", back_kb())
    await call.answer()

@router.message(AdminState.broadcast)
async def do_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    users = db.all_telegram_ids()
    ok = 0
    fail = 0
    for uid in users:
        try:
            await message.bot.send_message(uid, message.text)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.03)
    await message.answer(f"Рассылка завершена.\nУспешно: {ok}\nОшибок: {fail}", reply_markup=admin_kb())
    await state.clear()

TEXT_KEYS = [
    ("start", "Главный экран"),
    ("balance", "Пополнение"),
    ("rubles", "Рубли"),
    ("stars_pay", "Оплата звездами"),
    ("stars_empty", "Нет звезд"),
    ("news", "Новости"),
    ("profile", "Профиль"),
    ("reviews", "Отзывы"),
    ("support", "Поддержка"),
    ("faq", "FAQ"),
    ("bad_star_amount", "Неверное количество звезд"),
    ("star_purchase", "Покупка звезд"),
    ("accounts_purchase", "Покупка аккаунтов"),
]

@router.callback_query(F.data == "adm_text")
async def adm_text(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    kb = [[InlineKeyboardButton(text=label, callback_data=f"edittext:{key}")] for key, label in TEXT_KEYS]
    kb.append([InlineKeyboardButton(text="Назад", callback_data="admin_home")])
    await safe_edit(call, "Выберите текст для изменения:", InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@router.callback_query(F.data.startswith("edittext:"))
async def edittext(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    key = call.data.split(":", 1)[1]
    await state.update_data(edit_key=key)
    await state.set_state(AdminState.edit_value)
    current = db.get_setting(key, DEFAULTS.get(key, ""))
    await safe_edit(call, f"Текущий текст:\n\n{current}\n\nОтправьте новый текст.", back_kb())
    await call.answer()

@router.message(AdminState.edit_value)
async def save_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    key = data["edit_key"]
    if key == "__star_price__":
        try:
            price = float(message.text.strip().replace(",", "."))
            if price < 0:
                raise ValueError
        except Exception:
            await message.answer("Цена должна быть неотрицательным числом.")
            return
        db.set_star_price(price)
        await message.answer(f"Цена звезды установлена: {price:g} ₽/шт.", reply_markup=admin_kb())
    else:
        db.set_setting(key, message.text)
        await message.answer("Текст сохранен.", reply_markup=admin_kb())
    await state.clear()

BUTTON_TEXTS = [
    ("btn_topup", "Пополнить баланс"),
    ("btn_accounts", "Купить аккаунты"),
    ("btn_stars", "Купить звезды"),
    ("btn_news", "Новостоной канал"),
    ("btn_profile", "Мой профиль"),
    ("btn_reviews", "Отзывы"),
    ("btn_support", "Поддержка"),
    ("btn_faq", "FAQ"),
]

@router.callback_query(F.data == "adm_buttons")
async def adm_buttons(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    kb = [[InlineKeyboardButton(text=label, callback_data=f"editbtn:{key}")] for key, label in BUTTON_TEXTS]
    kb.append([InlineKeyboardButton(text="Назад", callback_data="admin_home")])
    await safe_edit(call, "Выберите кнопку:", InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@router.callback_query(F.data.startswith("editbtn:"))
async def editbtn(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    key = call.data.split(":", 1)[1]
    await state.update_data(edit_key=key)
    await state.set_state(AdminState.edit_value)
    current = db.get_setting(key, "")
    await safe_edit(call, f"Текущее название: {current or '(по умолчанию)'}\n\nОтправьте новое название.", back_kb())
    await call.answer()

@router.callback_query(F.data == "adm_star_stock")
async def adm_star_stock(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await state.set_state(AdminState.star_stock)
    await safe_edit(call, f"Текущий запас звезд: {db.get_star_stock()}\n\nОтправьте новое число.", back_kb())
    await call.answer()

@router.message(AdminState.star_stock)
async def save_star_stock(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        n = int(message.text.strip())
        if n < 0: raise ValueError
    except Exception:
        await message.answer("Нужно неотрицательное целое число.")
        return
    db.set_star_stock(n)
    await message.answer(f"Запас звезд установлен: {n}", reply_markup=admin_kb())
    await state.clear()

@router.callback_query(F.data == "adm_add_account")
async def adm_add_account(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await state.set_state(AdminState.account_stock)
    await safe_edit(call, "Отправьте аккаунт одним сообщением.\nОн будет добавлен в склад.", back_kb())
    await call.answer()

@router.message(AdminState.account_stock)
async def save_account(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text.strip():
        await message.answer("Пустой аккаунт добавить нельзя.")
        return
    db.add_account(message.text.strip())
    await message.answer(f"Аккаунт добавлен. В наличии: {db.get_account_stock()}", reply_markup=admin_kb())
    await state.clear()


@router.callback_query(F.data == "adm_products")
async def adm_products(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    s = db.get_account_stock()
    sp = db.get_star_price()
    ss = db.get_star_stock()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Аккаунты", callback_data="adm_product_accounts")],
        [InlineKeyboardButton(text="Звезды", callback_data="adm_product_stars")],
        [InlineKeyboardButton(text="Назад", callback_data="admin_home")],
    ])
    await safe_edit(
        call,
        f"Товары\n\nАккаунты: {s} шт.\nЗвезды: {ss} шт. • {sp:g} ₽/шт.",
        kb
    )
    await call.answer()

@router.callback_query(F.data == "adm_product_accounts")
async def adm_product_accounts(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="+ Добавить аккаунт", callback_data="adm_add_account")],
        [InlineKeyboardButton(text="Назад", callback_data="adm_products")],
    ])
    await safe_edit(
        call,
        f"Аккаунты\n\nВ наличии: {db.get_account_stock()} шт.\n\nПри добавлении укажите:\n1. аккаунт\n2. цена в ₽",
        kb
    )
    await call.answer()

@router.callback_query(F.data == "adm_add_account")
async def adm_add_account(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await state.set_state(AdminState.account_stock)
    await safe_edit(
        call,
        "Добавление аккаунта\n\nОтправьте одной строкой:\nАККАУНТ | ЦЕНА\n\nНапример:\nlogin:password | 150",
        back_kb()
    )
    await call.answer()

@router.message(AdminState.account_stock)
async def save_account(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = message.text.strip()
    if "|" not in raw:
        await message.answer("Формат: АККАУНТ | ЦЕНА\nНапример: login:password | 150")
        return
    account, price_raw = [x.strip() for x in raw.split("|", 1)]
    try:
        price = float(price_raw.replace(",", "."))
        if price < 0:
            raise ValueError
    except Exception:
        await message.answer("Цена должна быть положительным числом.")
        return
    if not account:
        await message.answer("Аккаунт не может быть пустым.")
        return
    db.add_account(account, price)
    await message.answer(
        f"Аккаунт добавлен.\nЦена: {price:g} ₽\nВ наличии: {db.get_account_stock()} шт.",
        reply_markup=admin_kb()
    )
    await state.clear()

@router.callback_query(F.data == "adm_product_stars")
async def adm_product_stars(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить количество", callback_data="adm_star_stock")],
        [InlineKeyboardButton(text="Изменить цену за 1 шт.", callback_data="adm_star_price")],
        [InlineKeyboardButton(text="Назад", callback_data="adm_products")],
    ])
    await safe_edit(
        call,
        f"Звезды\n\nКоличество: {db.get_star_stock()} шт.\nЦена: {db.get_star_price():g} ₽/шт.",
        kb
    )
    await call.answer()

@router.callback_query(F.data == "adm_star_stock")
async def adm_star_stock(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await state.set_state(AdminState.star_stock)
    await safe_edit(
        call,
        f"Текущее количество звезд: {db.get_star_stock()} шт.\n\nОтправьте новое количество.",
        back_kb()
    )
    await call.answer()

@router.message(AdminState.star_stock)
async def save_star_stock(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        n = int(message.text.strip())
        if n < 0:
            raise ValueError
    except Exception:
        await message.answer("Нужно неотрицательное целое число.")
        return
    db.set_star_stock(n)
    await message.answer(f"Количество звезд установлено: {n} шт.", reply_markup=admin_kb())
    await state.clear()

@router.callback_query(F.data == "adm_star_price")
async def adm_star_price(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await state.set_state(AdminState.edit_value)
    await state.update_data(edit_key="__star_price__")
    await safe_edit(
        call,
        f"Текущая цена: {db.get_star_price():g} ₽/шт.\n\nОтправьте новую цену за 1 звезду.",
        back_kb()
    )
    await call.answer()

@router.callback_query(F.data == "admin_home")
async def admin_home(call: CallbackQuery):
    if not await is_subscribed(call.bot, call.from_user.id):
        await call.answer("Сначала подпишитесь на канал.", show_alert=True)
        await safe_edit(call, "Чтобы пользоваться ботом, необходимо подписаться на наш канал.", subscribe_kb())
        return
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await safe_edit(call, "Админ-панель Maison Accs", admin_kb())
    await call.answer()

async def main():
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="admin", description="Админ-панель"),
    ])
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


@router.message()
async def subscription_guard(message: Message):
    if message.text and message.text.startswith("/"):
        return
    if not await is_subscribed(message.bot, message.from_user.id):
        await require_subscription(message)

