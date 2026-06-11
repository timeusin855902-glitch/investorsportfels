"""Раздел «Аналитика»: топы роста/падения за 24ч и общий отчет по инвесторам."""
from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.database import Database
from app.handlers.start import safe_edit
from app.keyboards import inline
from app.services.coingecko import CoinGeckoClient
from app.services.reports import build_summary_report, build_top_movers

router = Router()


@router.callback_query(F.data == "menu_analytics")
async def show_analytics_menu(callback: CallbackQuery) -> None:
    await safe_edit(
        callback.message,
        "📊 <b>Аналитика</b>\n\nБыстрый срез рынка по монетам из портфелей:",
        inline.analytics_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "an_gainers")
async def show_gainers(callback: CallbackQuery, db: Database, api: CoinGeckoClient) -> None:
    await callback.answer("Загружаю данные…")
    text = await build_top_movers(db, api, gainers=True)
    await safe_edit(callback.message, text, inline.back_to_analytics())


@router.callback_query(F.data == "an_losers")
async def show_losers(callback: CallbackQuery, db: Database, api: CoinGeckoClient) -> None:
    await callback.answer("Загружаю данные…")
    text = await build_top_movers(db, api, gainers=False)
    await safe_edit(callback.message, text, inline.back_to_analytics())


@router.callback_query(F.data == "an_report")
async def show_report(callback: CallbackQuery, db: Database, api: CoinGeckoClient) -> None:
    await callback.answer("Формирую отчет…")
    text = await build_summary_report(db, api)
    await safe_edit(callback.message, text, inline.back_to_analytics())
