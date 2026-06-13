"""Reply-клавиатуры (кнопки под полем ввода).

Навигация бота построена на ReplyKeyboardMarkup: нажатие кнопки присылает её
текст обычным сообщением, которое маршрутизируется по состоянию FSM. Подписи
кнопок вынесены в константы, чтобы хэндлеры сопоставляли их без «магических строк».
"""
import aiosqlite
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# ---- Общие кнопки ----
HOME = "🏠 Главное меню"
BACK = "⬅️ Назад"
SKIP = "⏭ Пропустить"
YES = "✅ Да"
NO = "❌ Нет"

# ---- Главное меню ----
INVESTORS = "👥 Инвесторы"
ANALYTICS = "📊 Аналитика"
PNL = "💹 Прибыль/Убыток"
SETTINGS = "⚙️ Настройки"

# ---- Список инвесторов ----
ADD_INVESTOR = "➕ Добавить инвестора"

# ---- Карточка инвестора ----
ADD_ASSET = "➕ Добавить актив"
SELL_ASSET = "💰 Продать актив"
DEL_ASSET = "🗑 Удалить актив"
INVESTOR_PNL = "💹 P&L портфеля"
DEL_INVESTOR = "❌ Удалить инвестора"

# ---- Аналитика ----
TOP_GAINERS = "📈 Топ роста"
TOP_LOSERS = "📉 Топ падения"
SUMMARY = "📋 Общий отчёт"

# ---- Настройки ----
SET_FREQ = "⏰ Частота отчётов"
SET_THRESHOLD = "🚨 Порог алертов"
SET_ADMINS = "👮 Админы"
SET_CHAT_HERE = "📍 Отчёты в этот чат"
ADD_ADMIN = "➕ Добавить админа"
THRESHOLD_CUSTOM = "✍️ Ввести вручную"
FREQ_CUSTOM = "✍️ Задать часы"


def _kb(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    """Собирает ReplyKeyboardMarkup из матрицы подписей."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in rows],
        resize_keyboard=True,
    )


def main_menu() -> ReplyKeyboardMarkup:
    return _kb([[INVESTORS], [ANALYTICS, PNL], [SETTINGS]])


def investors_list(investors: list[aiosqlite.Row]) -> ReplyKeyboardMarkup:
    """Список инвесторов (по кнопке на инвестора) + добавление + домой."""
    rows = [[inv["name"]] for inv in investors]
    rows.append([ADD_INVESTOR])
    rows.append([HOME])
    return _kb(rows)


def investor_actions() -> ReplyKeyboardMarkup:
    return _kb([
        [ADD_ASSET, SELL_ASSET],
        [DEL_ASSET, INVESTOR_PNL],
        [DEL_INVESTOR],
        [BACK, HOME],
    ])


def tickers_list(tickers_with_amounts: list[tuple[str, float]]) -> ReplyKeyboardMarkup:
    """Список активов для продажи/удаления: «BTC — 0.45 шт» на кнопке."""
    rows = [[f"{tk} — {amt:g} шт"] for tk, amt in tickers_with_amounts]
    rows.append([BACK])
    return _kb(rows)


def coin_label(name: str, symbol: str) -> str:
    """Подпись кнопки выбора монеты: «Wormhole (W)»."""
    return f"{name} ({symbol.upper()})"


def coins_list(candidates: list) -> ReplyKeyboardMarkup:
    """Список монет-кандидатов для выбора при неоднозначном тикере."""
    rows = [[coin_label(c["name"], c["symbol"])] for c in candidates]
    rows.append([BACK])
    return _kb(rows)


def analytics_menu() -> ReplyKeyboardMarkup:
    return _kb([[TOP_GAINERS, TOP_LOSERS], [SUMMARY], [HOME]])


def pnl_investors(investors: list[aiosqlite.Row]) -> ReplyKeyboardMarkup:
    """Список инвесторов для детализации P&L + домой."""
    rows = [[inv["name"]] for inv in investors]
    rows.append([HOME])
    return _kb(rows)


def settings_menu() -> ReplyKeyboardMarkup:
    return _kb([
        [SET_FREQ, SET_THRESHOLD],
        [SET_ADMINS, SET_CHAT_HERE],
        [HOME],
    ])


def freq_menu() -> ReplyKeyboardMarkup:
    return _kb([["6 часов", "12 часов"], ["24 часа", "48 часов"], [FREQ_CUSTOM], [BACK]])


def threshold_menu() -> ReplyKeyboardMarkup:
    return _kb([["10%", "20%"], ["30%", "50%"], [THRESHOLD_CUSTOM], [BACK]])


def admins_menu(db_admins: set[int]) -> ReplyKeyboardMarkup:
    """Кнопки удаления добавленных админов + добавление + назад."""
    rows = [[f"🗑 {uid}"] for uid in sorted(db_admins)]
    rows.append([ADD_ADMIN])
    rows.append([BACK])
    return _kb(rows)


def back_only() -> ReplyKeyboardMarkup:
    return _kb([[BACK]])


def skip_or_back() -> ReplyKeyboardMarkup:
    return _kb([[SKIP], [BACK]])


def yes_no() -> ReplyKeyboardMarkup:
    return _kb([[YES, NO]])
