from aiogram import Router, F
from aiogram.types import CallbackQuery

from database.db import get_all_portfolios
from handlers.keyboards import analytics_menu_kb, main_menu_kb
from services.formatter import build_full_report, build_analytics_top

router = Router()


@router.callback_query(F.data == "analytics_menu")
async def cb_analytics_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "📊 <b>Аналитика</b>\n\nВыбери раздел:",
        reply_markup=analytics_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.in_({"analytics_top_growth", "analytics_top_drop"}))
async def cb_analytics_top(callback: CallbackQuery) -> None:
    await callback.answer("⏳ Загружаю данные...")
    positions = await get_all_portfolios()
    growth_text, drop_text = await build_analytics_top(positions)

    if callback.data == "analytics_top_growth":
        text = growth_text
    else:
        text = drop_text

    await callback.message.edit_text(
        text,
        reply_markup=analytics_menu_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "analytics_full_report")
async def cb_analytics_full_report(callback: CallbackQuery) -> None:
    await callback.answer("⏳ Формирую отчёт...")
    positions = await get_all_portfolios()
    text = await build_full_report(positions)
    await callback.message.edit_text(
        text,
        reply_markup=analytics_menu_kb(),
        parse_mode="HTML",
    )
