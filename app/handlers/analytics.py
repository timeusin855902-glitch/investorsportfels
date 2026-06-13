"""Раздел «Аналитика»: топы роста/падения за 24ч и общий отчёт (rich-таблицы)."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.database import Database
from app.handlers.common import send_rich
from app.keyboards import reply
from app.services.coingecko import CoinGeckoClient
from app.services.reports import build_summary_report, build_top_movers
from app.states import St

router = Router()


@router.message(St.main, F.text == reply.ANALYTICS)
async def open_analytics(message: Message, state: FSMContext) -> None:
    await state.set_state(St.analytics)
    await message.answer(
        "📊 <b>Аналитика</b>\n\nБыстрый срез рынка по монетам из портфелей:",
        reply_markup=reply.analytics_menu(),
    )


@router.message(St.analytics, F.text == reply.TOP_GAINERS)
async def top_gainers(message: Message, db: Database, api: CoinGeckoClient) -> None:
    await send_rich(message, await build_top_movers(db, api, gainers=True), reply.analytics_menu())


@router.message(St.analytics, F.text == reply.TOP_LOSERS)
async def top_losers(message: Message, db: Database, api: CoinGeckoClient) -> None:
    await send_rich(message, await build_top_movers(db, api, gainers=False), reply.analytics_menu())


@router.message(St.analytics, F.text == reply.SUMMARY)
async def summary(message: Message, db: Database, api: CoinGeckoClient) -> None:
    await send_rich(message, await build_summary_report(db, api), reply.analytics_menu())
