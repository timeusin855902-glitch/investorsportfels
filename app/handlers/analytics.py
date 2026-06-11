"""Раздел «Аналитика»: топы роста/падения за 24ч и общий отчёт (rich-таблицы)."""
from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.database import Database
from app.handlers.start import safe_edit
from app.keyboards import inline
from app.services.coingecko import CoinGeckoClient
from app.services.reports import build_summary_report, build_top_movers
from app.services.rich import edit_rich_message

router = Router()


async def _show_rich(callback: CallbackQuery, html: str) -> None:
    """Заменяет сообщение rich-контентом с кнопкой возврата в аналитику."""
    await edit_rich_message(
        callback.message.bot,
        callback.message.chat.id,
        callback.message.message_id,
        html,
        inline.back_to_analytics(),
    )


@router.callback_query(F.data == "menu_analytics")
async def show_analytics_menu(callback: CallbackQuery) -> None:
    # Меню остаётся обычным сообщением (таблицы тут не нужны)
    await safe_edit(
        callback.message,
        "📊 <b>Аналитика</b>\n\nБыстрый срез рынка по монетам из портфелей:",
        inline.analytics_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "an_gainers")
async def show_gainers(callback: CallbackQuery, db: Database, api: CoinGeckoClient) -> None:
    await callback.answer("Загружаю данные…")
    await _show_rich(callback, await build_top_movers(db, api, gainers=True))


@router.callback_query(F.data == "an_losers")
async def show_losers(callback: CallbackQuery, db: Database, api: CoinGeckoClient) -> None:
    await callback.answer("Загружаю данные…")
    await _show_rich(callback, await build_top_movers(db, api, gainers=False))


@router.callback_query(F.data == "an_report")
async def show_report(callback: CallbackQuery, db: Database, api: CoinGeckoClient) -> None:
    await callback.answer("Формирую отчёт…")
    await _show_rich(callback, await build_summary_report(db, api))
