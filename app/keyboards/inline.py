"""Все Inline-клавиатуры бота."""
import aiosqlite
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu() -> InlineKeyboardMarkup:
    """Главное меню (/start)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Инвесторы", callback_data="menu_investors")
    kb.button(text="📊 Аналитика", callback_data="menu_analytics")
    kb.button(text="⚙️ Настройки", callback_data="menu_settings")
    kb.adjust(1)
    return kb.as_markup()


def investors_list(investors: list[aiosqlite.Row]) -> InlineKeyboardMarkup:
    """Список инвесторов + кнопки добавления и возврата."""
    kb = InlineKeyboardBuilder()
    for inv in investors:
        kb.button(text=f"👤 {inv['name']}", callback_data=f"inv:{inv['id']}")
    kb.button(text="➕ Добавить инвестора", callback_data="inv_add")
    kb.button(text="⬅️ Назад", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()


def investor_menu(investor_id: int) -> InlineKeyboardMarkup:
    """Меню действий над портфелем конкретного инвестора."""
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить актив", callback_data=f"asset_add:{investor_id}")
    kb.button(text="✏️ Изменить баланс", callback_data=f"asset_edit:{investor_id}")
    kb.button(text="❌ Удалить актив", callback_data=f"asset_del:{investor_id}")
    kb.button(text="🗑 Удалить инвестора", callback_data=f"inv_del:{investor_id}")
    kb.button(text="⬅️ Назад", callback_data="menu_investors")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def assets_list(assets: list[aiosqlite.Row], action: str, investor_id: int) -> InlineKeyboardMarkup:
    """Выбор актива для редактирования (action='edit') или удаления (action='del')."""
    kb = InlineKeyboardBuilder()
    for asset in assets:
        kb.button(
            text=f"{asset['asset_ticker']} ({asset['amount']:g})",
            callback_data=f"asset_{action}_sel:{asset['id']}",
        )
    kb.button(text="⬅️ Назад", callback_data=f"inv:{investor_id}")
    kb.adjust(1)
    return kb.as_markup()


def confirm_delete_investor(investor_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления инвестора со всеми его активами."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, удалить", callback_data=f"inv_del_yes:{investor_id}")
    kb.button(text="↩️ Отмена", callback_data=f"inv:{investor_id}")
    kb.adjust(2)
    return kb.as_markup()


def cancel_input() -> InlineKeyboardMarkup:
    """Кнопка отмены при ожидании текстового ввода (FSM)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="↩️ Отмена", callback_data="fsm_cancel")
    return kb.as_markup()


def analytics_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📈 Топ роста за 24ч", callback_data="an_gainers")
    kb.button(text="📉 Топ падения за 24ч", callback_data="an_losers")
    kb.button(text="📋 Общий отчет", callback_data="an_report")
    kb.button(text="⬅️ Назад", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()


def back_to_analytics() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="menu_analytics")
    return kb.as_markup()


def settings_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⏰ Частота отчетов", callback_data="set_freq")
    kb.button(text="🚨 Порог алертов", callback_data="set_threshold")
    kb.button(text="👮 Админы", callback_data="set_admins")
    kb.button(text="📍 Отчеты в этот чат", callback_data="set_chat_here")
    kb.button(text="⬅️ Назад", callback_data="back_main")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def report_freq_options() -> InlineKeyboardMarkup:
    """Варианты частоты отправки сводного отчета."""
    kb = InlineKeyboardBuilder()
    for hours, label in [(6, "Каждые 6 часов"), (12, "Каждые 12 часов"), (24, "Раз в сутки")]:
        kb.button(text=label, callback_data=f"set_freq_val:{hours}")
    kb.button(text="⬅️ Назад", callback_data="menu_settings")
    kb.adjust(1)
    return kb.as_markup()


def threshold_options() -> InlineKeyboardMarkup:
    """Готовые пороги алертов + ручной ввод."""
    kb = InlineKeyboardBuilder()
    for pct in (10, 20, 30, 50):
        kb.button(text=f"{pct}%", callback_data=f"set_threshold_val:{pct}")
    kb.button(text="✍️ Ввести вручную", callback_data="set_threshold_custom")
    kb.button(text="⬅️ Назад", callback_data="menu_settings")
    kb.adjust(4, 1, 1)
    return kb.as_markup()


def admins_menu(db_admins: set[int]) -> InlineKeyboardMarkup:
    """Список добавленных через меню админов с кнопками удаления."""
    kb = InlineKeyboardBuilder()
    for user_id in sorted(db_admins):
        kb.button(text=f"🗑 {user_id}", callback_data=f"admin_del:{user_id}")
    kb.button(text="➕ Добавить админа", callback_data="admin_add")
    kb.button(text="⬅️ Назад", callback_data="menu_settings")
    kb.adjust(1)
    return kb.as_markup()


def back_to_settings() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="menu_settings")
    return kb.as_markup()
