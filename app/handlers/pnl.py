"""Раздел «Прибыль/Убыток»: сводка по всем инвесторам и детализация по активам."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.database import Database
from app.handlers.common import send_rich
from app.keyboards import reply
from app.services.coingecko import CoinGeckoClient
from app.services.pnl import build_investor_pnl, build_pnl_summary
from app.states import St

router = Router()


@router.message(St.main, F.text == reply.PNL)
async def open_pnl(message: Message, db: Database, api: CoinGeckoClient,
                   state: FSMContext) -> None:
    """Сводная таблица P&L по всем инвесторам + кнопки для детализации."""
    await state.set_state(St.pnl)
    investors = await db.get_investors()
    await send_rich(message, await build_pnl_summary(db, api), reply.pnl_investors(investors))


@router.message(St.pnl)
async def pnl_detail(message: Message, db: Database, api: CoinGeckoClient,
                     state: FSMContext) -> None:
    """Детальный P&L по выбранному инвестору (таблица по каждому активу)."""
    investor = await db.find_investor_by_name(message.text.strip())
    if investor is None:
        await message.answer("⚠️ Выберите инвестора кнопкой из списка.")
        return
    investors = await db.get_investors()
    html = await build_investor_pnl(db, api, investor["id"])
    await send_rich(message, html, reply.pnl_investors(investors))
