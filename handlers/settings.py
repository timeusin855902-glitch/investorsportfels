from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from database.db import get_setting, set_setting
from handlers.keyboards import settings_menu_kb
from handlers.states import SettingsReportSG, SettingsVolatilitySG

router = Router()


async def _settings_text() -> str:
    hour = await get_setting("report_hour") or "9"
    minute = await get_setting("report_minute") or "0"
    threshold = await get_setting("volatility_threshold") or "30"
    return (
        "⚙️ <b>Настройки</b>\n\n"
        f"🕐 Время ежедневного отчёта: <b>{hour}:{int(minute):02d} UTC</b>\n"
        f"🔔 Порог алерта волатильности: <b>{threshold}%</b>"
    )


@router.callback_query(F.data == "settings_menu")
async def cb_settings_menu(callback: CallbackQuery) -> None:
    text = await _settings_text()
    await callback.message.edit_text(text, reply_markup=settings_menu_kb(), parse_mode="HTML")
    await callback.answer()


# ---------------------------------------------------------------------------
# Настройка времени отчёта
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "settings_report_time")
async def cb_settings_report_time(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsReportSG.waiting_time)
    await callback.message.edit_text(
        "🕐 Введи время отправки ежедневного отчёта в формате <code>ЧЧ:ММ</code> (UTC).\n"
        "Пример: <code>09:00</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(SettingsReportSG.waiting_time)
async def msg_report_time(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    try:
        parts = raw.split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, IndexError):
        await message.answer("Неверный формат. Введи время как <code>ЧЧ:ММ</code>:", parse_mode="HTML")
        return

    await set_setting("report_hour", str(hour))
    await set_setting("report_minute", str(minute))
    await state.clear()

    await message.answer(
        f"✅ Время отчёта установлено: <b>{hour}:{minute:02d} UTC</b>",
        parse_mode="HTML",
    )
    text = await _settings_text()
    await message.answer(text, reply_markup=settings_menu_kb(), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Настройка порога волатильности
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "settings_volatility")
async def cb_settings_volatility(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsVolatilitySG.waiting_threshold)
    await callback.message.edit_text(
        "🔔 Введи порог волатильности в процентах (число от 1 до 100).\n"
        "Пример: <code>30</code> означает алерт при изменении цены >30% за 24ч.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(SettingsVolatilitySG.waiting_threshold)
async def msg_volatility_threshold(message: Message, state: FSMContext) -> None:
    try:
        threshold = float(message.text.strip().replace(",", "."))
        if not (0 < threshold <= 100):
            raise ValueError
    except ValueError:
        await message.answer("Введи число от 1 до 100:")
        return

    await set_setting("volatility_threshold", str(threshold))
    await state.clear()

    await message.answer(
        f"✅ Порог алертов установлен: <b>{threshold}%</b>",
        parse_mode="HTML",
    )
    text = await _settings_text()
    await message.answer(text, reply_markup=settings_menu_kb(), parse_mode="HTML")
