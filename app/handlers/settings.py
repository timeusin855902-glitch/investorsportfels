"""Раздел «Настройки»: частота отчетов, порог алертов, админы, чат для отчетов."""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Config
from app.database import Database
from app.handlers.start import safe_edit
from app.keyboards import inline
from app.scheduler.tasks import reschedule_report

logger = logging.getLogger(__name__)
router = Router()


class SetThreshold(StatesGroup):
    value = State()         # ожидаем порог алерта в процентах


class AddAdmin(StatesGroup):
    user_id = State()       # ожидаем Telegram ID нового админа


async def _settings_text(db: Database, config: Config) -> str:
    """Текст экрана настроек с текущими значениями."""
    freq = await db.get_setting("report_freq_hours", "24")
    threshold = await db.get_setting("alert_threshold", "30")
    chat_id = await db.get_setting("analytics_chat_id") or config.analytics_chat_id
    chat_str = str(chat_id) if chat_id else "не задан ⚠️"
    return (
        "⚙️ <b>Настройки</b>\n\n"
        f"⏰ Частота отчетов: каждые <b>{freq} ч</b>\n"
        f"🚨 Порог алертов: <b>±{threshold}%</b> за 24ч\n"
        f"📍 Чат для отчетов: <b>{chat_str}</b>"
    )


@router.callback_query(F.data == "menu_settings")
async def show_settings(callback: CallbackQuery, db: Database, config: Config,
                        state: FSMContext) -> None:
    await state.clear()
    await safe_edit(callback.message, await _settings_text(db, config), inline.settings_menu())
    await callback.answer()


# ---------- Частота отчетов ----------

@router.callback_query(F.data == "set_freq")
async def choose_freq(callback: CallbackQuery) -> None:
    await safe_edit(
        callback.message,
        "⏰ Как часто отправлять сводный отчет в аналитический чат?",
        inline.report_freq_options(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_freq_val:"))
async def set_freq(callback: CallbackQuery, db: Database, config: Config,
                   scheduler: AsyncIOScheduler) -> None:
    hours = int(callback.data.split(":")[1])
    await db.set_setting("report_freq_hours", str(hours))
    # Перепланируем фоновую задачу без перезапуска бота
    reschedule_report(scheduler, hours)
    await callback.answer(f"Отчеты — каждые {hours} ч ✅")
    await safe_edit(callback.message, await _settings_text(db, config), inline.settings_menu())


# ---------- Порог алертов ----------

@router.callback_query(F.data == "set_threshold")
async def choose_threshold(callback: CallbackQuery) -> None:
    await safe_edit(
        callback.message,
        "🚨 Выберите порог изменения цены за 24ч, при котором отправлять алерт:",
        inline.threshold_options(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_threshold_val:"))
async def set_threshold(callback: CallbackQuery, db: Database, config: Config) -> None:
    pct = int(callback.data.split(":")[1])
    await db.set_setting("alert_threshold", str(pct))
    await callback.answer(f"Порог алертов — {pct}% ✅")
    await safe_edit(callback.message, await _settings_text(db, config), inline.settings_menu())


@router.callback_query(F.data == "set_threshold_custom")
async def set_threshold_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SetThreshold.value)
    await safe_edit(
        callback.message,
        "✍️ Введите порог в процентах (число от 1 до 500), например <code>25</code>:",
        inline.cancel_input(),
    )
    await callback.answer()


@router.message(SetThreshold.value, F.text)
async def set_threshold_value(message: Message, state: FSMContext, db: Database,
                              config: Config) -> None:
    try:
        pct = float(message.text.replace(",", ".").replace("%", "").strip())
    except ValueError:
        pct = -1
    if not 1 <= pct <= 500:
        await message.answer("⚠️ Введите число от 1 до 500:")
        return
    await state.clear()
    await db.set_setting("alert_threshold", f"{pct:g}")
    await message.answer(
        f"✅ Порог алертов установлен: ±{pct:g}%\n\n" + await _settings_text(db, config),
        reply_markup=inline.settings_menu(),
    )


# ---------- Чат для отчетов ----------

@router.callback_query(F.data == "set_chat_here")
async def set_analytics_chat(callback: CallbackQuery, db: Database, config: Config) -> None:
    """Назначает текущий чат получателем отчетов и алертов."""
    chat_id = callback.message.chat.id
    await db.set_setting("analytics_chat_id", str(chat_id))
    await callback.answer("Этот чат назначен для отчетов ✅", show_alert=True)
    await safe_edit(callback.message, await _settings_text(db, config), inline.settings_menu())


# ---------- Управление админами ----------

async def _admins_text(db: Database, config: Config) -> str:
    owners = ", ".join(str(u) for u in sorted(config.allowed_users))
    return (
        "👮 <b>Админы</b>\n\n"
        f"Владельцы из .env (нельзя удалить): <code>{owners}</code>\n\n"
        "Добавленные через меню (нажмите, чтобы удалить):"
    )


@router.callback_query(F.data == "set_admins")
async def show_admins(callback: CallbackQuery, db: Database, config: Config) -> None:
    db_admins = await db.get_admins()
    await safe_edit(callback.message, await _admins_text(db, config), inline.admins_menu(db_admins))
    await callback.answer()


@router.callback_query(F.data == "admin_add")
async def add_admin_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddAdmin.user_id)
    await safe_edit(
        callback.message,
        "✍️ Введите Telegram ID нового админа (узнать ID можно у @userinfobot):",
        inline.cancel_input(),
    )
    await callback.answer()


@router.message(AddAdmin.user_id, F.text)
async def add_admin_finish(message: Message, state: FSMContext, db: Database,
                           config: Config) -> None:
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("⚠️ ID — это положительное число. Попробуйте еще раз:")
        return
    await state.clear()
    await db.add_admin(int(text))
    db_admins = await db.get_admins()
    await message.answer(
        f"✅ Админ <code>{text}</code> добавлен!\n\n" + await _admins_text(db, config),
        reply_markup=inline.admins_menu(db_admins),
    )


@router.callback_query(F.data.startswith("admin_del:"))
async def delete_admin(callback: CallbackQuery, db: Database, config: Config) -> None:
    user_id = int(callback.data.split(":")[1])
    await db.remove_admin(user_id)
    db_admins = await db.get_admins()
    await callback.answer(f"Админ {user_id} удален")
    await safe_edit(callback.message, await _admins_text(db, config), inline.admins_menu(db_admins))
