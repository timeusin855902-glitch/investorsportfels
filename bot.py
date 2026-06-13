"""
Telegram-бот для управления инвестиционным портфелем криптовалют.

Функционал:
- Создание/удаление портфелей
- Добавление активов с точками входа (цена, количество, дата)
- Продажа/удаление активов (цена продажи, количество, дата)
- Статистика: профит/убыток по портфелю и по каждому активу
- Интеграция с CoinGecko API для текущих цен
- Интерфейс через ReplyKeyboardMarkup (кнопки под полем ввода)
- Весь интерфейс на русском языке
"""

import json
import os
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import requests
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы / состояния ConversationHandler
# ---------------------------------------------------------------------------
DATA_FILE = "portfolios.json"

# Состояния для ConversationHandler
(
    MAIN_MENU,
    SELECT_PORTFOLIO,
    CREATE_PORTFOLIO_NAME,
    DELETE_PORTFOLIO_CONFIRM,
    PORTFOLIO_MENU,
    ADD_ASSET_COIN,
    ADD_ASSET_PRICE,
    ADD_ASSET_AMOUNT,
    ADD_ASSET_DATE,
    SELL_ASSET_SELECT,
    SELL_ASSET_PRICE,
    SELL_ASSET_AMOUNT,
    SELL_ASSET_DATE,
    STATS_SELECT_PORTFOLIO,
    STATS_PORTFOLIO_DETAIL,
    DELETE_ASSET_SELECT,
) = range(16)

# ---------------------------------------------------------------------------
# Клавиатуры (ReplyKeyboardMarkup)
# ---------------------------------------------------------------------------

def main_menu_keyboard():
    """Главное меню."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📂 Мои портфели"), KeyboardButton("➕ Создать портфель")],
            [KeyboardButton("📊 Статистика"), KeyboardButton("ℹ️ Помощь")],
        ],
        resize_keyboard=True,
    )


def portfolio_menu_keyboard():
    """Меню выбранного портфеля."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ Добавить актив"), KeyboardButton("💰 Продать актив")],
            [KeyboardButton("🗑 Удалить актив"), KeyboardButton("📊 Статистика портфеля")],
            [KeyboardButton("❌ Удалить портфель"), KeyboardButton("🔙 Назад")],
        ],
        resize_keyboard=True,
    )


def back_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🔙 Назад")]],
        resize_keyboard=True,
    )


def yes_no_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("✅ Да"), KeyboardButton("❌ Нет")]],
        resize_keyboard=True,
    )


def skip_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("⏭ Пропустить")], [KeyboardButton("🔙 Назад")]],
        resize_keyboard=True,
    )


# ---------------------------------------------------------------------------
# Хранилище данных (JSON)
# ---------------------------------------------------------------------------

def _data_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), DATA_FILE)


def load_data() -> dict:
    path = _data_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_data(data: dict):
    with open(_data_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def user_key(update: Update) -> str:
    return str(update.effective_user.id)


def get_user_portfolios(data: dict, uid: str) -> dict:
    return data.setdefault(uid, {})


# ---------------------------------------------------------------------------
# CoinGecko API (бесплатный, без ключа)
# ---------------------------------------------------------------------------
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Кэш id монет
_coin_list_cache: list | None = None


def _get_coin_list() -> list:
    global _coin_list_cache
    if _coin_list_cache is None:
        try:
            r = requests.get(f"{COINGECKO_BASE}/coins/list", timeout=15)
            r.raise_for_status()
            _coin_list_cache = r.json()
        except Exception:
            _coin_list_cache = []
    return _coin_list_cache


def resolve_coin_id(symbol_or_name: str) -> str | None:
    """Определить CoinGecko coin id по символу или имени."""
    s = symbol_or_name.lower().strip()
    coins = _get_coin_list()
    # Точное совпадение по символу
    for c in coins:
        if c["symbol"] == s:
            return c["id"]
    # Точное совпадение по имени
    for c in coins:
        if c["name"].lower() == s:
            return c["id"]
    # Частичное совпадение
    for c in coins:
        if s in c["name"].lower() or s in c["id"]:
            return c["id"]
    return None


def get_current_price(coin_id: str) -> float | None:
    """Получить текущую цену монеты в USD."""
    try:
        r = requests.get(
            f"{COINGECKO_BASE}/simple/price",
            params={"ids": coin_id, "vs_currencies": "usd"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        return data.get(coin_id, {}).get("usd")
    except Exception:
        return None


def get_price_at_date(coin_id: str, date_str: str) -> float | None:
    """Получить цену монеты на указанную дату (dd-mm-yyyy)."""
    try:
        r = requests.get(
            f"{COINGECKO_BASE}/coins/{coin_id}/history",
            params={"date": date_str, "localization": "false"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("market_data", {}).get("current_price", {}).get("usd")
    except Exception:
        return None


def find_date_for_price(coin_id: str, target_price: float) -> str | None:
    """
    Найти последнюю дату, когда актив стоил примерно target_price.
    Используем market_chart за последние 365 дней и ищем ближайшую цену.
    """
    try:
        r = requests.get(
            f"{COINGECKO_BASE}/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": "365"},
            timeout=15,
        )
        r.raise_for_status()
        prices = r.json().get("prices", [])
        if not prices:
            return None

        best_ts = None
        best_diff = float("inf")
        for ts, price in prices:
            diff = abs(price - target_price)
            if diff < best_diff:
                best_diff = diff
                best_ts = ts
        if best_ts is None:
            return None
        dt = datetime.fromtimestamp(best_ts / 1000, tz=timezone.utc)
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Форматирование
# ---------------------------------------------------------------------------

def fmt_money(val: float) -> str:
    if abs(val) >= 1:
        return f"${val:,.2f}"
    return f"${val:.6f}"


def fmt_pct(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def fmt_pnl(pnl: float) -> str:
    emoji = "🟢" if pnl >= 0 else "🔴"
    sign = "+" if pnl >= 0 else ""
    return f"{emoji} {sign}{fmt_money(pnl)}"


# ---------------------------------------------------------------------------
# Хендлеры бота
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /start — главное меню."""
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Добро пожаловать в Инвестор Портфель!\n\n"
        "Я помогу вам управлять вашими крипто-портфелями, "
        "отслеживать прибыль и убытки.\n\n"
        "Выберите действие:",
        reply_markup=main_menu_keyboard(),
    )
    return MAIN_MENU


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "ℹ️ <b>Инвестор Портфель — Помощь</b>\n\n"
        "📂 <b>Мои портфели</b> — список ваших портфелей\n"
        "➕ <b>Создать портфель</b> — создать новый портфель\n"
        "📊 <b>Статистика</b> — профит/убыток по портфелям\n\n"
        "<b>Внутри портфеля:</b>\n"
        "➕ Добавить актив — указать монету, цену покупки, количество, дату\n"
        "💰 Продать актив — зафиксировать продажу\n"
        "🗑 Удалить актив — полностью убрать актив\n"
        "📊 Статистика портфеля — детальная таблица P&L\n\n"
        "Цены получаются через CoinGecko API.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    return MAIN_MENU


# ---- Главное меню ----

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if text == "📂 Мои портфели":
        return await show_portfolios(update, context)
    elif text == "➕ Создать портфель":
        await update.message.reply_text(
            "📝 Введите название нового портфеля:",
            reply_markup=back_keyboard(),
        )
        return CREATE_PORTFOLIO_NAME
    elif text == "📊 Статистика":
        return await stats_select_portfolio(update, context)
    elif text == "ℹ️ Помощь":
        return await help_cmd(update, context)
    else:
        await update.message.reply_text(
            "Пожалуйста, используйте кнопки меню.",
            reply_markup=main_menu_keyboard(),
        )
        return MAIN_MENU


# ---- Портфели ----

async def show_portfolios(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = load_data()
    uid = user_key(update)
    portfolios = get_user_portfolios(data, uid)

    if not portfolios:
        await update.message.reply_text(
            "У вас пока нет портфелей.\nСоздайте первый с помощью кнопки «➕ Создать портфель».",
            reply_markup=main_menu_keyboard(),
        )
        return MAIN_MENU

    buttons = [[KeyboardButton(name)] for name in portfolios.keys()]
    buttons.append([KeyboardButton("🔙 Назад")])
    await update.message.reply_text(
        "📂 Выберите портфель:",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True),
    )
    return SELECT_PORTFOLIO


async def select_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "🔙 Назад":
        await update.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    data = load_data()
    uid = user_key(update)
    portfolios = get_user_portfolios(data, uid)

    if text not in portfolios:
        await update.message.reply_text("Портфель не найден. Выберите из списка.")
        return SELECT_PORTFOLIO

    context.user_data["current_portfolio"] = text
    assets = portfolios[text].get("assets", {})
    assets_text = ""
    if assets:
        lines = []
        for coin, info in assets.items():
            total_qty = sum(float(e["amount"]) for e in info.get("entries", []))
            sold_qty = sum(float(s["amount"]) for s in info.get("sells", []))
            remaining = total_qty - sold_qty
            if remaining > 0:
                lines.append(f"  • {coin.upper()}: {remaining:.6g} шт.")
        if lines:
            assets_text = "\n📋 Активы:\n" + "\n".join(lines)
        else:
            assets_text = "\n📋 Все активы проданы."
    else:
        assets_text = "\n📋 Активов пока нет."

    await update.message.reply_text(
        f"📁 Портфель: <b>{text}</b>{assets_text}\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=portfolio_menu_keyboard(),
    )
    return PORTFOLIO_MENU


# ---- Создание портфеля ----

async def create_portfolio_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "🔙 Назад":
        await update.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    data = load_data()
    uid = user_key(update)
    portfolios = get_user_portfolios(data, uid)

    if text in portfolios:
        await update.message.reply_text(
            f"Портфель «{text}» уже существует. Введите другое название:",
            reply_markup=back_keyboard(),
        )
        return CREATE_PORTFOLIO_NAME

    portfolios[text] = {"assets": {}, "created": datetime.now().strftime("%d.%m.%Y %H:%M")}
    save_data(data)

    await update.message.reply_text(
        f"✅ Портфель «{text}» создан!",
        reply_markup=main_menu_keyboard(),
    )
    return MAIN_MENU


# ---- Меню портфеля ----

async def portfolio_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    pname = context.user_data.get("current_portfolio")

    if text == "🔙 Назад":
        await update.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    if not pname:
        await update.message.reply_text("Выберите портфель.", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    if text == "➕ Добавить актив":
        await update.message.reply_text(
            "🪙 Введите символ или название криптовалюты\n"
            "(например: BTC, ETH, SOL, bitcoin):",
            reply_markup=back_keyboard(),
        )
        return ADD_ASSET_COIN
    elif text == "💰 Продать актив":
        return await sell_asset_select(update, context)
    elif text == "🗑 Удалить актив":
        return await delete_asset_select(update, context)
    elif text == "📊 Статистика портфеля":
        return await show_portfolio_stats(update, context, pname)
    elif text == "❌ Удалить портфель":
        await update.message.reply_text(
            f"Вы уверены, что хотите удалить портфель «{pname}»?\n"
            "Все данные будут потеряны!",
            reply_markup=yes_no_keyboard(),
        )
        return DELETE_PORTFOLIO_CONFIRM
    else:
        await update.message.reply_text(
            "Используйте кнопки меню.", reply_markup=portfolio_menu_keyboard()
        )
        return PORTFOLIO_MENU


# ---- Удаление портфеля ----

async def delete_portfolio_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    pname = context.user_data.get("current_portfolio")

    if text == "✅ Да" and pname:
        data = load_data()
        uid = user_key(update)
        portfolios = get_user_portfolios(data, uid)
        if pname in portfolios:
            del portfolios[pname]
            save_data(data)
        await update.message.reply_text(
            f"🗑 Портфель «{pname}» удалён.",
            reply_markup=main_menu_keyboard(),
        )
        context.user_data.pop("current_portfolio", None)
        return MAIN_MENU
    else:
        await update.message.reply_text(
            "Отменено.", reply_markup=portfolio_menu_keyboard()
        )
        return PORTFOLIO_MENU


# ---- Добавление актива ----

async def add_asset_coin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "🔙 Назад":
        await update.message.reply_text(
            "Меню портфеля:", reply_markup=portfolio_menu_keyboard()
        )
        return PORTFOLIO_MENU

    # Попытка найти монету
    coin_id = resolve_coin_id(text)
    if not coin_id:
        await update.message.reply_text(
            f"❌ Монета «{text}» не найдена.\n"
            "Попробуйте ввести символ (BTC, ETH) или полное название (bitcoin):",
            reply_markup=back_keyboard(),
        )
        return ADD_ASSET_COIN

    context.user_data["add_coin_symbol"] = text.upper()
    context.user_data["add_coin_id"] = coin_id
    await update.message.reply_text(
        f"✅ Найдена: <b>{text.upper()}</b> (CoinGecko ID: {coin_id})\n\n"
        "💵 Введите цену покупки (в USD):",
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )
    return ADD_ASSET_PRICE


async def add_asset_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "🔙 Назад":
        await update.message.reply_text(
            "Меню портфеля:", reply_markup=portfolio_menu_keyboard()
        )
        return PORTFOLIO_MENU

    try:
        price = float(text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        await update.message.reply_text(
            "❌ Введите корректную цену (число > 0):", reply_markup=back_keyboard()
        )
        return ADD_ASSET_PRICE

    context.user_data["add_price"] = price
    await update.message.reply_text(
        "📦 Введите количество:", reply_markup=back_keyboard()
    )
    return ADD_ASSET_AMOUNT


async def add_asset_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "🔙 Назад":
        await update.message.reply_text(
            "Меню портфеля:", reply_markup=portfolio_menu_keyboard()
        )
        return PORTFOLIO_MENU

    try:
        amount = float(text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        await update.message.reply_text(
            "❌ Введите корректное количество (число > 0):", reply_markup=back_keyboard()
        )
        return ADD_ASSET_AMOUNT

    context.user_data["add_amount"] = amount
    await update.message.reply_text(
        "📅 Введите дату покупки (ДД.ММ.ГГГГ)\n"
        "или нажмите «⏭ Пропустить» — бот определит дату по цене через CoinGecko:",
        reply_markup=skip_keyboard(),
    )
    return ADD_ASSET_DATE


async def add_asset_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "🔙 Назад":
        await update.message.reply_text(
            "Меню портфеля:", reply_markup=portfolio_menu_keyboard()
        )
        return PORTFOLIO_MENU

    coin_id = context.user_data["add_coin_id"]
    symbol = context.user_data["add_coin_symbol"]
    price = context.user_data["add_price"]
    amount = context.user_data["add_amount"]

    if text == "⏭ Пропустить":
        await update.message.reply_text("⏳ Ищу дату по цене через CoinGecko...")
        found_date = find_date_for_price(coin_id, price)
        if found_date:
            date_str = found_date
            await update.message.reply_text(
                f"📅 Найдена примерная дата: <b>{found_date}</b>",
                parse_mode="HTML",
            )
        else:
            date_str = datetime.now().strftime("%d.%m.%Y")
            await update.message.reply_text(
                f"⚠️ Не удалось определить дату. Установлена текущая: {date_str}"
            )
    else:
        try:
            dt = datetime.strptime(text, "%d.%m.%Y")
            date_str = dt.strftime("%d.%m.%Y")
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат. Введите дату в формате ДД.ММ.ГГГГ:",
                reply_markup=skip_keyboard(),
            )
            return ADD_ASSET_DATE

    # Сохранение
    pname = context.user_data["current_portfolio"]
    data = load_data()
    uid = user_key(update)
    portfolios = get_user_portfolios(data, uid)
    portfolio = portfolios.get(pname, {"assets": {}})

    coin_key = symbol.lower()
    if coin_key not in portfolio["assets"]:
        portfolio["assets"][coin_key] = {
            "coin_id": coin_id,
            "symbol": symbol,
            "entries": [],
            "sells": [],
        }

    portfolio["assets"][coin_key]["entries"].append({
        "price": price,
        "amount": amount,
        "date": date_str,
    })
    portfolios[pname] = portfolio
    save_data(data)

    total_cost = price * amount
    await update.message.reply_text(
        f"✅ Актив добавлен!\n\n"
        f"🪙 Монета: <b>{symbol}</b>\n"
        f"💵 Цена: {fmt_money(price)}\n"
        f"📦 Количество: {amount}\n"
        f"💰 Сумма: {fmt_money(total_cost)}\n"
        f"📅 Дата: {date_str}",
        parse_mode="HTML",
        reply_markup=portfolio_menu_keyboard(),
    )
    return PORTFOLIO_MENU


# ---- Продажа актива ----

async def sell_asset_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pname = context.user_data.get("current_portfolio")
    data = load_data()
    uid = user_key(update)
    portfolios = get_user_portfolios(data, uid)
    assets = portfolios.get(pname, {}).get("assets", {})

    # Список активов с положительным остатком
    available = []
    for coin_key, info in assets.items():
        total_qty = sum(float(e["amount"]) for e in info.get("entries", []))
        sold_qty = sum(float(s["amount"]) for s in info.get("sells", []))
        remaining = total_qty - sold_qty
        if remaining > 0:
            available.append((info["symbol"], remaining))

    if not available:
        await update.message.reply_text(
            "В портфеле нет активов для продажи.",
            reply_markup=portfolio_menu_keyboard(),
        )
        return PORTFOLIO_MENU

    buttons = [[KeyboardButton(f"{sym} ({rem:.6g} шт.)")] for sym, rem in available]
    buttons.append([KeyboardButton("🔙 Назад")])
    await update.message.reply_text(
        "💰 Выберите актив для продажи:",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True),
    )
    return SELL_ASSET_SELECT


async def sell_asset_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "🔙 Назад":
        await update.message.reply_text(
            "Меню портфеля:", reply_markup=portfolio_menu_keyboard()
        )
        return PORTFOLIO_MENU

    # Извлекаем символ из "BTC (1.5 шт.)"
    sym = text.split("(")[0].strip().lower()
    context.user_data["sell_coin"] = sym

    pname = context.user_data.get("current_portfolio")
    data = load_data()
    uid = user_key(update)
    assets = get_user_portfolios(data, uid).get(pname, {}).get("assets", {})

    if sym not in assets:
        await update.message.reply_text("Актив не найден.", reply_markup=portfolio_menu_keyboard())
        return PORTFOLIO_MENU

    await update.message.reply_text(
        f"💵 Введите цену продажи {sym.upper()} (в USD):",
        reply_markup=back_keyboard(),
    )
    return SELL_ASSET_PRICE


async def sell_asset_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "🔙 Назад":
        await update.message.reply_text(
            "Меню портфеля:", reply_markup=portfolio_menu_keyboard()
        )
        return PORTFOLIO_MENU

    try:
        price = float(text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        await update.message.reply_text(
            "❌ Введите корректную цену:", reply_markup=back_keyboard()
        )
        return SELL_ASSET_PRICE

    context.user_data["sell_price"] = price
    await update.message.reply_text(
        "📦 Введите количество для продажи:", reply_markup=back_keyboard()
    )
    return SELL_ASSET_AMOUNT


async def sell_asset_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "🔙 Назад":
        await update.message.reply_text(
            "Меню портфеля:", reply_markup=portfolio_menu_keyboard()
        )
        return PORTFOLIO_MENU

    try:
        amount = float(text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        await update.message.reply_text(
            "❌ Введите корректное количество:", reply_markup=back_keyboard()
        )
        return SELL_ASSET_AMOUNT

    # Проверяем, не превышает ли остаток
    pname = context.user_data["current_portfolio"]
    coin_key = context.user_data["sell_coin"]
    data = load_data()
    uid = user_key(update)
    assets = get_user_portfolios(data, uid).get(pname, {}).get("assets", {})
    info = assets.get(coin_key, {})
    total_qty = sum(float(e["amount"]) for e in info.get("entries", []))
    sold_qty = sum(float(s["amount"]) for s in info.get("sells", []))
    remaining = total_qty - sold_qty

    if amount > remaining + 0.000001:
        await update.message.reply_text(
            f"❌ Недостаточно активов. Остаток: {remaining:.6g} шт.\n"
            "Введите меньшее количество:",
            reply_markup=back_keyboard(),
        )
        return SELL_ASSET_AMOUNT

    context.user_data["sell_amount"] = amount
    await update.message.reply_text(
        "📅 Введите дату продажи (ДД.ММ.ГГГГ)\nили нажмите «⏭ Пропустить» для текущей даты:",
        reply_markup=skip_keyboard(),
    )
    return SELL_ASSET_DATE


async def sell_asset_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "🔙 Назад":
        await update.message.reply_text(
            "Меню портфеля:", reply_markup=portfolio_menu_keyboard()
        )
        return PORTFOLIO_MENU

    if text == "⏭ Пропустить":
        date_str = datetime.now().strftime("%d.%m.%Y")
    else:
        try:
            dt = datetime.strptime(text, "%d.%m.%Y")
            date_str = dt.strftime("%d.%m.%Y")
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат. Введите дату в формате ДД.ММ.ГГГГ:",
                reply_markup=skip_keyboard(),
            )
            return SELL_ASSET_DATE

    # Сохранение
    pname = context.user_data["current_portfolio"]
    coin_key = context.user_data["sell_coin"]
    sell_price = context.user_data["sell_price"]
    sell_amount = context.user_data["sell_amount"]

    data = load_data()
    uid = user_key(update)
    portfolios = get_user_portfolios(data, uid)
    assets = portfolios[pname]["assets"]

    assets[coin_key]["sells"].append({
        "price": sell_price,
        "amount": sell_amount,
        "date": date_str,
    })
    save_data(data)

    # Рассчитаем P&L по этой продаже (средняя цена покупки)
    entries = assets[coin_key]["entries"]
    avg_buy = sum(e["price"] * e["amount"] for e in entries) / sum(e["amount"] for e in entries)
    pnl = (sell_price - avg_buy) * sell_amount
    pnl_pct = ((sell_price / avg_buy) - 1) * 100 if avg_buy > 0 else 0

    await update.message.reply_text(
        f"✅ Продажа зафиксирована!\n\n"
        f"🪙 Монета: <b>{coin_key.upper()}</b>\n"
        f"💵 Цена продажи: {fmt_money(sell_price)}\n"
        f"📦 Количество: {sell_amount}\n"
        f"💰 Сумма: {fmt_money(sell_price * sell_amount)}\n"
        f"📅 Дата: {date_str}\n\n"
        f"📈 P&L по сделке: {fmt_pnl(pnl)} ({fmt_pct(pnl_pct)})",
        parse_mode="HTML",
        reply_markup=portfolio_menu_keyboard(),
    )
    return PORTFOLIO_MENU


# ---- Удаление актива ----

async def delete_asset_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pname = context.user_data.get("current_portfolio")
    data = load_data()
    uid = user_key(update)
    assets = get_user_portfolios(data, uid).get(pname, {}).get("assets", {})

    if not assets:
        await update.message.reply_text(
            "В портфеле нет активов.",
            reply_markup=portfolio_menu_keyboard(),
        )
        return PORTFOLIO_MENU

    buttons = [[KeyboardButton(info["symbol"])] for info in assets.values()]
    buttons.append([KeyboardButton("🔙 Назад")])
    await update.message.reply_text(
        "🗑 Выберите актив для полного удаления:",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True),
    )
    return DELETE_ASSET_SELECT


async def delete_asset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "🔙 Назад":
        await update.message.reply_text(
            "Меню портфеля:", reply_markup=portfolio_menu_keyboard()
        )
        return PORTFOLIO_MENU

    pname = context.user_data.get("current_portfolio")
    coin_key = text.lower()
    data = load_data()
    uid = user_key(update)
    portfolios = get_user_portfolios(data, uid)
    assets = portfolios.get(pname, {}).get("assets", {})

    if coin_key in assets:
        del assets[coin_key]
        save_data(data)
        await update.message.reply_text(
            f"🗑 Актив {text.upper()} полностью удалён из портфеля.",
            reply_markup=portfolio_menu_keyboard(),
        )
    else:
        await update.message.reply_text(
            "Актив не найден.",
            reply_markup=portfolio_menu_keyboard(),
        )
    return PORTFOLIO_MENU


# ---- Статистика ----

async def stats_select_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = load_data()
    uid = user_key(update)
    portfolios = get_user_portfolios(data, uid)

    if not portfolios:
        await update.message.reply_text(
            "У вас нет портфелей для отображения статистики.",
            reply_markup=main_menu_keyboard(),
        )
        return MAIN_MENU

    # Показать сводку по всем портфелям
    lines = ["📊 <b>Сводка по портфелям</b>\n"]
    for pname, pdata in portfolios.items():
        assets = pdata.get("assets", {})
        total_invested = 0
        total_sold = 0
        active_count = 0
        for info in assets.values():
            for e in info.get("entries", []):
                total_invested += e["price"] * e["amount"]
            for s in info.get("sells", []):
                total_sold += s["price"] * s["amount"]
            total_qty = sum(e["amount"] for e in info.get("entries", []))
            sold_qty = sum(s["amount"] for s in info.get("sells", []))
            if total_qty - sold_qty > 0.000001:
                active_count += 1
        lines.append(
            f"📁 <b>{pname}</b>\n"
            f"   Инвестировано: {fmt_money(total_invested)}\n"
            f"   Продано на: {fmt_money(total_sold)}\n"
            f"   Активных монет: {active_count}\n"
        )

    lines.append("\n👆 Выберите портфель для детальной статистики:")

    buttons = [[KeyboardButton(name)] for name in portfolios.keys()]
    buttons.append([KeyboardButton("🔙 Назад")])
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True),
    )
    return STATS_SELECT_PORTFOLIO


async def stats_portfolio_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "🔙 Назад":
        await update.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    data = load_data()
    uid = user_key(update)
    portfolios = get_user_portfolios(data, uid)

    if text not in portfolios:
        await update.message.reply_text("Портфель не найден.")
        return STATS_SELECT_PORTFOLIO

    return await show_portfolio_stats(update, context, text)


async def show_portfolio_stats(
    update: Update, context: ContextTypes.DEFAULT_TYPE, pname: str
) -> int:
    """Показать детальную статистику по портфелю."""
    data = load_data()
    uid = user_key(update)
    portfolios = get_user_portfolios(data, uid)
    portfolio = portfolios.get(pname, {})
    assets = portfolio.get("assets", {})

    if not assets:
        await update.message.reply_text(
            f"📁 Портфель «{pname}» пуст.",
            reply_markup=portfolio_menu_keyboard()
            if context.user_data.get("current_portfolio") == pname
            else main_menu_keyboard(),
        )
        return PORTFOLIO_MENU if context.user_data.get("current_portfolio") == pname else MAIN_MENU

    await update.message.reply_text("⏳ Загружаю текущие цены с CoinGecko...")

    lines = [f"📊 <b>Статистика портфеля «{pname}»</b>\n"]
    total_pnl_realized = 0.0
    total_pnl_unrealized = 0.0
    total_invested = 0.0
    total_current_value = 0.0

    for coin_key, info in assets.items():
        symbol = info.get("symbol", coin_key.upper())
        coin_id = info.get("coin_id", "")
        entries = info.get("entries", [])
        sells = info.get("sells", [])

        # Средняя цена покупки
        total_buy_qty = sum(e["amount"] for e in entries)
        total_buy_cost = sum(e["price"] * e["amount"] for e in entries)
        avg_buy = total_buy_cost / total_buy_qty if total_buy_qty > 0 else 0

        # Продажи
        total_sell_qty = sum(s["amount"] for s in sells)
        total_sell_revenue = sum(s["price"] * s["amount"] for s in sells)
        realized_pnl = total_sell_revenue - (avg_buy * total_sell_qty)

        # Остаток
        remaining = total_buy_qty - total_sell_qty
        invested_remaining = avg_buy * remaining

        # Текущая цена
        current_price = get_current_price(coin_id) if coin_id else None
        unrealized_pnl = 0.0
        current_val = 0.0
        price_text = "н/д"
        unrealized_text = "н/д"

        if current_price is not None and remaining > 0:
            current_val = current_price * remaining
            unrealized_pnl = current_val - invested_remaining
            unrealized_pct = ((current_price / avg_buy) - 1) * 100 if avg_buy > 0 else 0
            price_text = fmt_money(current_price)
            unrealized_text = f"{fmt_pnl(unrealized_pnl)} ({fmt_pct(unrealized_pct)})"
        elif remaining <= 0.000001:
            price_text = "—"
            unrealized_text = "полностью продан"

        total_pnl_realized += realized_pnl
        total_pnl_unrealized += unrealized_pnl
        total_invested += total_buy_cost
        total_current_value += current_val

        lines.append(
            f"{'─' * 28}\n"
            f"🪙 <b>{symbol}</b>\n"
            f"   Ср. цена покупки: {fmt_money(avg_buy)}\n"
            f"   Куплено: {total_buy_qty:.6g} шт. на {fmt_money(total_buy_cost)}\n"
        )
        if total_sell_qty > 0:
            lines.append(
                f"   Продано: {total_sell_qty:.6g} шт. на {fmt_money(total_sell_revenue)}\n"
                f"   Реализованный P&L: {fmt_pnl(realized_pnl)}\n"
            )
        if remaining > 0.000001:
            lines.append(
                f"   Остаток: {remaining:.6g} шт.\n"
                f"   Текущая цена: {price_text}\n"
                f"   Нереализованный P&L: {unrealized_text}\n"
            )
        elif remaining <= 0.000001:
            lines.append(f"   Статус: полностью продан ✅\n")

    # Итог
    total_pnl = total_pnl_realized + total_pnl_unrealized
    total_pnl_pct = ((total_pnl / total_invested) * 100) if total_invested > 0 else 0

    lines.append(
        f"\n{'═' * 28}\n"
        f"📈 <b>ИТОГО по портфелю:</b>\n"
        f"   Инвестировано: {fmt_money(total_invested)}\n"
        f"   Текущая стоимость: {fmt_money(total_current_value)}\n"
        f"   Реализованный P&L: {fmt_pnl(total_pnl_realized)}\n"
        f"   Нереализованный P&L: {fmt_pnl(total_pnl_unrealized)}\n"
        f"   Общий P&L: {fmt_pnl(total_pnl)} ({fmt_pct(total_pnl_pct)})"
    )

    # Определяем какую клавиатуру показать
    if context.user_data.get("current_portfolio") == pname:
        kb = portfolio_menu_keyboard()
        next_state = PORTFOLIO_MENU
    else:
        kb = main_menu_keyboard()
        next_state = MAIN_MENU

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=kb,
    )
    return next_state


# ---- Обработчик отмены ----

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Действие отменено. Главное меню:",
        reply_markup=main_menu_keyboard(),
    )
    return MAIN_MENU


# ---------------------------------------------------------------------------
# Запуск бота
# ---------------------------------------------------------------------------

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error(
            "Не задан TELEGRAM_BOT_TOKEN. "
            "Установите переменную окружения: export TELEGRAM_BOT_TOKEN=ваш_токен"
        )
        return

    app = ApplicationBuilder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler),
            ],
            SELECT_PORTFOLIO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_portfolio),
            ],
            CREATE_PORTFOLIO_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_portfolio_name),
            ],
            DELETE_PORTFOLIO_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, delete_portfolio_confirm),
            ],
            PORTFOLIO_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, portfolio_menu_handler),
            ],
            ADD_ASSET_COIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_asset_coin),
            ],
            ADD_ASSET_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_asset_price),
            ],
            ADD_ASSET_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_asset_amount),
            ],
            ADD_ASSET_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_asset_date),
            ],
            SELL_ASSET_SELECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_asset_selected),
            ],
            SELL_ASSET_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_asset_price),
            ],
            SELL_ASSET_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_asset_amount),
            ],
            SELL_ASSET_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_asset_date),
            ],
            STATS_SELECT_PORTFOLIO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, stats_portfolio_selected),
            ],
            STATS_PORTFOLIO_DETAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler),
            ],
            DELETE_ASSET_SELECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, delete_asset_confirm),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", cancel),
            CommandHandler("help", help_cmd),
        ],
    )

    app.add_handler(conv)

    logger.info("Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
