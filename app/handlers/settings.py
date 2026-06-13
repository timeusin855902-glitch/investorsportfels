"""Раздел «Настройки»: частота отчётов, порог алертов, админы, чат для отчётов."""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Config
from app.database import Database
from app.keyboards import reply
from app.scheduler.tasks import reschedule_report
from app.states import St

logger = logging.getLogger(__name__)
router = Router()


async def _settings_text(db: Database, config: Config) -> str:
    """Текст экрана настроек с текущими значениями."""
    freq = await db.get_setting("report_freq_hours", "24")
    threshold = await db.get_setting("alert_threshold", "30")
    chat_id = await db.get_setting("analytics_chat_id") or config.analytics_chat_id
    chat_str = str(chat_id) if chat_id else "не задан ⚠️"
    return (
        "⚙️ <b>Настройки</b>\n\n"
        f"⏰ Частота отчётов: каждые <b>{freq} ч</b>\n"
        f"🚨 Порог алертов: <b>±{threshold}%</b> за 24ч\n"
        f"📍 Чат для отчётов: <b>{chat_str}</b>\n\n"
        "Выберите параметр:"
    )


async def show_settings(message: Message, db: Database, config: Config,
                        state: FSMContext) -> None:
    await state.set_state(St.settings)
    await message.answer(await _settings_text(db, config), reply_markup=reply.settings_menu())


@router.message(St.main, F.text == reply.SETTINGS)
async def open_settings(message: Message, db: Database, config: Config,
                        state: FSMContext) -> None:
    await show_settings(message, db, config, state)


# ---- Частота отчётов ----

@router.message(St.settings, F.text == reply.SET_FREQ)
async def freq_menu(message: Message, state: FSMContext) -> None:
    await state.set_state(St.set_freq)
    await message.answer("⏰ Как часто отправлять сводный отчёт?",
                         reply_markup=reply.freq_menu())


@router.message(St.set_freq, F.text == reply.BACK)
async def freq_back(message: Message, db: Database, config: Config, state: FSMContext) -> None:
    await show_settings(message, db, config, state)


@router.message(St.set_freq)
async def freq_set(message: Message, db: Database, config: Config,
                   scheduler: AsyncIOScheduler, state: FSMContext) -> None:
    digits = "".join(c for c in message.text if c.isdigit())
    if digits not in {"6", "12", "24"}:
        await message.answer("⚠️ Выберите вариант кнопкой.")
        return
    hours = int(digits)
    await db.set_setting("report_freq_hours", str(hours))
    reschedule_report(scheduler, hours)
    await message.answer(f"✅ Отчёты — каждые {hours} ч.")
    await show_settings(message, db, config, state)


# ---- Порог алертов ----

@router.message(St.settings, F.text == reply.SET_THRESHOLD)
async def threshold_menu(message: Message, state: FSMContext) -> None:
    await state.set_state(St.set_threshold)
    await message.answer("🚨 Порог изменения цены за 24ч для алерта:",
                         reply_markup=reply.threshold_menu())


@router.message(St.set_threshold, F.text == reply.BACK)
async def threshold_back(message: Message, db: Database, config: Config,
                         state: FSMContext) -> None:
    await show_settings(message, db, config, state)


@router.message(St.set_threshold, F.text == reply.THRESHOLD_CUSTOM)
async def threshold_custom(message: Message, state: FSMContext) -> None:
    await state.set_state(St.set_threshold_input)
    await message.answer("✍️ Введите порог в процентах (число от 1 до 500):",
                         reply_markup=reply.back_only())


@router.message(St.set_threshold)
async def threshold_set(message: Message, db: Database, config: Config,
                        state: FSMContext) -> None:
    digits = "".join(c for c in message.text if c.isdigit())
    if digits not in {"10", "20", "30", "50"}:
        await message.answer("⚠️ Выберите вариант кнопкой или «✍️ Ввести вручную».")
        return
    await db.set_setting("alert_threshold", digits)
    await message.answer(f"✅ Порог алертов — {digits}%.")
    await show_settings(message, db, config, state)


@router.message(St.set_threshold_input, F.text == reply.BACK)
async def threshold_input_back(message: Message, db: Database, config: Config,
                               state: FSMContext) -> None:
    await show_settings(message, db, config, state)


@router.message(St.set_threshold_input)
async def threshold_input(message: Message, db: Database, config: Config,
                          state: FSMContext) -> None:
    try:
        pct = float(message.text.replace(",", ".").replace("%", "").strip())
    except ValueError:
        pct = -1
    if not 1 <= pct <= 500:
        await message.answer("⚠️ Введите число от 1 до 500:")
        return
    await db.set_setting("alert_threshold", f"{pct:g}")
    await message.answer(f"✅ Порог алертов — ±{pct:g}%.")
    await show_settings(message, db, config, state)


# ---- Чат для отчётов ----

@router.message(St.settings, F.text == reply.SET_CHAT_HERE)
async def set_chat_here(message: Message, db: Database, config: Config,
                        state: FSMContext) -> None:
    await db.set_setting("analytics_chat_id", str(message.chat.id))
    await message.answer("📍 Этот чат назначен для отчётов и алертов ✅")
    await show_settings(message, db, config, state)


# ---- Админы ----

async def _admins_text(db: Database, config: Config) -> str:
    owners = ", ".join(str(u) for u in sorted(config.allowed_users))
    return (
        "👮 <b>Админы</b>\n\n"
        f"Владельцы из .env (неудаляемы): <code>{owners}</code>\n\n"
        "Добавленные через меню — нажмите «🗑 ID», чтобы удалить:"
    )


@router.message(St.settings, F.text == reply.SET_ADMINS)
async def admins_menu(message: Message, db: Database, config: Config,
                      state: FSMContext) -> None:
    await state.set_state(St.set_admins)
    db_admins = await db.get_admins()
    await message.answer(await _admins_text(db, config),
                         reply_markup=reply.admins_menu(db_admins))


@router.message(St.set_admins, F.text == reply.BACK)
async def admins_back(message: Message, db: Database, config: Config, state: FSMContext) -> None:
    await show_settings(message, db, config, state)


@router.message(St.set_admins, F.text == reply.ADD_ADMIN)
async def admin_add_start(message: Message, state: FSMContext) -> None:
    await state.set_state(St.set_admin_add)
    await message.answer("✍️ Введите Telegram ID нового админа:", reply_markup=reply.back_only())


@router.message(St.set_admins)
async def admin_remove(message: Message, db: Database, config: Config,
                       state: FSMContext) -> None:
    digits = "".join(c for c in message.text if c.isdigit())
    if not digits:
        await message.answer("⚠️ Используйте кнопки меню.")
        return
    await db.remove_admin(int(digits))
    await message.answer(f"🗑 Админ {digits} удалён.")
    db_admins = await db.get_admins()
    await message.answer(await _admins_text(db, config),
                         reply_markup=reply.admins_menu(db_admins))


@router.message(St.set_admin_add, F.text == reply.BACK)
async def admin_add_back(message: Message, db: Database, config: Config,
                         state: FSMContext) -> None:
    await admins_menu(message, db, config, state)


@router.message(St.set_admin_add)
async def admin_add_finish(message: Message, db: Database, config: Config,
                           state: FSMContext) -> None:
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("⚠️ ID — это число. Повторите:")
        return
    await db.add_admin(int(text))
    await message.answer(f"✅ Админ <code>{text}</code> добавлен.")
    await admins_menu(message, db, config, state)
