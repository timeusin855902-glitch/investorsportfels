from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Инвесторы", callback_data="investors_list")
    kb.button(text="📊 Аналитика", callback_data="analytics_menu")
    kb.button(text="⚙️ Настройки", callback_data="settings_menu")
    kb.adjust(1)
    return kb.as_markup()


def investors_list_kb(investors: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for inv in investors:
        kb.button(text=f"👤 {inv['name']}", callback_data=f"investor:{inv['id']}")
    kb.button(text="➕ Добавить инвестора", callback_data="investor_add")
    kb.button(text="⬅️ Главное меню", callback_data="main_menu")
    kb.adjust(1)
    return kb.as_markup()


def investor_menu_kb(investor_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить актив", callback_data=f"asset_add:{investor_id}")
    kb.button(text="✏️ Изменить баланс", callback_data=f"asset_edit:{investor_id}")
    kb.button(text="❌ Удалить актив", callback_data=f"asset_delete:{investor_id}")
    kb.button(text="🗑 Удалить инвестора", callback_data=f"investor_delete:{investor_id}")
    kb.button(text="⬅️ Назад", callback_data="investors_list")
    kb.adjust(1)
    return kb.as_markup()


def assets_list_kb(positions: list[dict], action: str, investor_id: int) -> InlineKeyboardMarkup:
    """Список активов инвестора для выбора (редактирование / удаление)."""
    kb = InlineKeyboardBuilder()
    for pos in positions:
        ticker = pos["asset_ticker"]
        kb.button(text=ticker, callback_data=f"{action}:{investor_id}:{ticker}")
    kb.button(text="⬅️ Назад", callback_data=f"investor:{investor_id}")
    kb.adjust(2)
    return kb.as_markup()


def confirm_delete_investor_kb(investor_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, удалить", callback_data=f"investor_delete_confirm:{investor_id}")
    kb.button(text="❌ Отмена", callback_data=f"investor:{investor_id}")
    kb.adjust(2)
    return kb.as_markup()


def analytics_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📈 Топ роста за 24ч", callback_data="analytics_top_growth")
    kb.button(text="📉 Топ падения за 24ч", callback_data="analytics_top_drop")
    kb.button(text="📋 Общий отчёт", callback_data="analytics_full_report")
    kb.button(text="⬅️ Главное меню", callback_data="main_menu")
    kb.adjust(1)
    return kb.as_markup()


def settings_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🕐 Время ежедневного отчёта", callback_data="settings_report_time")
    kb.button(text="🔔 Порог алертов волатильности", callback_data="settings_volatility")
    kb.button(text="⬅️ Главное меню", callback_data="main_menu")
    kb.adjust(1)
    return kb.as_markup()


def back_to_investor_kb(investor_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ К инвестору", callback_data=f"investor:{investor_id}")
    return kb.as_markup()
