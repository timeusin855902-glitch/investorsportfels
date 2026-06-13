"""Раздел «Инвесторы»: карточка портфеля, точки входа, продажи, удаление."""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.database import Database
from app.handlers.common import send_rich
from app.keyboards import reply
from app.services.coingecko import CoinGeckoClient, CoinGeckoError
from app.services.pnl import build_investor_pnl
from app.services.reports import build_investor_card, fmt_usd
from app.states import St
from app.utils import parse_date, parse_positive_float, today_str

logger = logging.getLogger(__name__)
router = Router()


# ---------------------------------------------------------------------------
# Показ экранов
# ---------------------------------------------------------------------------

async def show_investors_list(message: Message, db: Database, state: FSMContext) -> None:
    """Список инвесторов в виде reply-кнопок."""
    investors = await db.get_investors()
    await state.set_state(St.investors)
    text = ("👥 <b>Инвесторы</b>\n\nВыберите инвестора или добавьте нового:"
            if investors else "👥 <b>Инвесторы</b>\n\nСписок пуст — добавьте первого:")
    await message.answer(text, reply_markup=reply.investors_list(investors))


async def show_investor_card(message: Message, db: Database, api: CoinGeckoClient,
                             state: FSMContext, investor_id: int) -> None:
    """Rich-карточка портфеля инвестора + меню действий."""
    investor = await db.get_investor(investor_id)
    if investor is None:
        await message.answer("⚠️ Инвестор не найден.")
        await show_investors_list(message, db, state)
        return
    await state.set_state(St.investor)
    await state.update_data(inv_id=investor_id, inv_name=investor["name"])
    html = await build_investor_card(db, api, investor_id)
    await send_rich(message, html, reply.investor_actions())


async def _current_investor_id(state: FSMContext) -> int | None:
    data = await state.get_data()
    return data.get("inv_id")


# ---------------------------------------------------------------------------
# Вход в раздел и выбор инвестора
# ---------------------------------------------------------------------------

@router.message(St.main, F.text == reply.INVESTORS)
async def open_investors(message: Message, db: Database, state: FSMContext) -> None:
    await show_investors_list(message, db, state)


@router.message(St.investors, F.text == reply.ADD_INVESTOR)
async def add_investor_start(message: Message, state: FSMContext) -> None:
    await state.set_state(St.add_investor)
    await message.answer("✍️ Введите имя нового инвестора:", reply_markup=reply.back_only())


@router.message(St.investors)
async def pick_investor(message: Message, db: Database, api: CoinGeckoClient,
                        state: FSMContext) -> None:
    """Выбор инвестора по имени с кнопки."""
    investor = await db.find_investor_by_name(message.text.strip())
    if investor is None:
        await message.answer("⚠️ Выберите инвестора кнопкой из списка.")
        await show_investors_list(message, db, state)
        return
    await show_investor_card(message, db, api, state, investor["id"])


@router.message(St.add_investor, F.text == reply.BACK)
async def add_investor_back(message: Message, db: Database, state: FSMContext) -> None:
    await show_investors_list(message, db, state)


@router.message(St.add_investor)
async def add_investor_name(message: Message, db: Database, api: CoinGeckoClient,
                            state: FSMContext) -> None:
    name = message.text.strip()
    if not name or len(name) > 64:
        await message.answer("⚠️ Имя должно быть 1–64 символа. Повторите:")
        return
    investor_id = await db.add_investor(name)
    await message.answer(f"✅ Инвестор <b>{name}</b> добавлен!")
    await show_investor_card(message, db, api, state, investor_id)


# ---------------------------------------------------------------------------
# Меню карточки инвестора
# ---------------------------------------------------------------------------

@router.message(St.investor, F.text == reply.BACK)
async def card_back(message: Message, db: Database, state: FSMContext) -> None:
    await show_investors_list(message, db, state)


@router.message(St.investor, F.text == reply.INVESTOR_PNL)
async def card_pnl(message: Message, db: Database, api: CoinGeckoClient,
                   state: FSMContext) -> None:
    inv_id = await _current_investor_id(state)
    if inv_id is None:
        await show_investors_list(message, db, state)
        return
    html = await build_investor_pnl(db, api, inv_id)
    await send_rich(message, html, reply.investor_actions())


# ---- Добавление актива (точка входа) ----

@router.message(St.investor, F.text == reply.ADD_ASSET)
async def add_asset_start(message: Message, state: FSMContext) -> None:
    await state.set_state(St.a_ticker)
    await message.answer(
        "✍️ Введите тикер монеты (например, <code>BTC</code> или <code>ZEC</code>):",
        reply_markup=reply.back_only(),
    )


@router.message(St.a_ticker, F.text == reply.BACK)
async def add_asset_ticker_back(message: Message, db: Database, api: CoinGeckoClient,
                                state: FSMContext) -> None:
    await _back_to_card(message, db, api, state)


@router.message(St.a_ticker)
async def add_asset_ticker(message: Message, api: CoinGeckoClient, state: FSMContext) -> None:
    ticker = message.text.strip().upper()
    if not ticker.isalnum() or len(ticker) > 15:
        await message.answer("⚠️ Тикер — до 15 букв/цифр. Повторите:")
        return
    try:
        coin_id = await api.resolve_ticker(ticker)
    except CoinGeckoError as e:
        await message.answer(f"⚠️ {e}\nПопробуйте ещё раз:")
        return
    if coin_id is None:
        await message.answer(f"⚠️ Монета <b>{ticker}</b> не найдена на CoinGecko. Проверьте тикер:")
        return
    await state.update_data(t_ticker=ticker)
    await state.set_state(St.a_price)
    await message.answer(
        f"Монета <b>{ticker}</b> найдена ✅\n💵 Введите цену покупки за 1 монету (в $):",
        reply_markup=reply.back_only(),
    )


@router.message(St.a_price, F.text == reply.BACK)
async def add_asset_price_back(message: Message, db: Database, api: CoinGeckoClient,
                               state: FSMContext) -> None:
    await _back_to_card(message, db, api, state)


@router.message(St.a_price)
async def add_asset_price(message: Message, state: FSMContext) -> None:
    price = parse_positive_float(message.text)
    if price is None:
        await message.answer("⚠️ Введите цену числом больше 0, например <code>65000</code>:")
        return
    await state.update_data(t_price=price)
    await state.set_state(St.a_amount)
    await message.answer("📦 Введите количество монет:", reply_markup=reply.back_only())


@router.message(St.a_amount, F.text == reply.BACK)
async def add_asset_amount_back(message: Message, db: Database, api: CoinGeckoClient,
                                state: FSMContext) -> None:
    await _back_to_card(message, db, api, state)


@router.message(St.a_amount)
async def add_asset_amount(message: Message, state: FSMContext) -> None:
    amount = parse_positive_float(message.text)
    if amount is None:
        await message.answer("⚠️ Введите количество числом больше 0, например <code>0.5</code>:")
        return
    await state.update_data(t_amount=amount)
    await state.set_state(St.a_date)
    await message.answer(
        "📅 Введите дату покупки (ДД.ММ.ГГГГ)\n"
        "или нажмите «⏭ Пропустить» — бот определит дату по цене через CoinGecko:",
        reply_markup=reply.skip_or_back(),
    )


@router.message(St.a_date, F.text == reply.BACK)
async def add_asset_date_back(message: Message, db: Database, api: CoinGeckoClient,
                              state: FSMContext) -> None:
    await _back_to_card(message, db, api, state)


@router.message(St.a_date)
async def add_asset_date(message: Message, db: Database, api: CoinGeckoClient,
                         state: FSMContext) -> None:
    data = await state.get_data()
    ticker, price, amount = data["t_ticker"], data["t_price"], data["t_amount"]

    if message.text.strip() == reply.SKIP:
        # Автоопределение даты по цене через исторический график
        await message.answer("⏳ Ищу дату по цене через CoinGecko…")
        try:
            date = await api.find_date_for_price(ticker, price)
        except CoinGeckoError:
            date = None
        if date:
            await message.answer(f"📅 Найдена примерная дата: <b>{date}</b>")
        else:
            date = today_str()
            await message.answer(f"⚠️ Не удалось определить дату, поставил текущую: {date}")
    else:
        date = parse_date(message.text)
        if date is None:
            await message.answer("⚠️ Неверный формат. Введите дату как ДД.ММ.ГГГГ:")
            return

    await db.add_transaction(data["inv_id"], ticker, "buy", price, amount, date)
    await message.answer(
        f"✅ Куплено: <b>{ticker}</b> — {amount:g} шт по {fmt_usd(price)} $ "
        f"(сумма {fmt_usd(price * amount)} $), дата {date}"
    )
    await show_investor_card(message, db, api, state, data["inv_id"])


# ---- Продажа актива ----

@router.message(St.investor, F.text == reply.SELL_ASSET)
async def sell_start(message: Message, db: Database, state: FSMContext) -> None:
    inv_id = await _current_investor_id(state)
    assets = await db.get_portfolio(inv_id)
    if not assets:
        await message.answer("В портфеле нет активов для продажи.",
                             reply_markup=reply.investor_actions())
        return
    await state.set_state(St.s_pick)
    pairs = [(a["asset_ticker"], a["amount"]) for a in assets]
    await message.answer("💰 Выберите актив для продажи:",
                         reply_markup=reply.tickers_list(pairs))


@router.message(St.s_pick, F.text == reply.BACK)
async def sell_pick_back(message: Message, db: Database, api: CoinGeckoClient,
                         state: FSMContext) -> None:
    await _back_to_card(message, db, api, state)


@router.message(St.s_pick)
async def sell_pick(message: Message, db: Database, state: FSMContext) -> None:
    ticker = message.text.split("—")[0].strip().upper()
    inv_id = await _current_investor_id(state)
    remaining = await db.remaining_amount(inv_id, ticker)
    if remaining <= 0:
        await message.answer("⚠️ Выберите актив кнопкой из списка.")
        return
    await state.update_data(sell_ticker=ticker, sell_remaining=remaining)
    await state.set_state(St.s_price)
    await message.answer(
        f"Остаток <b>{ticker}</b>: {remaining:g} шт\n💵 Введите цену продажи за 1 монету (в $):",
        reply_markup=reply.back_only(),
    )


@router.message(St.s_price, F.text == reply.BACK)
async def sell_price_back(message: Message, db: Database, api: CoinGeckoClient,
                          state: FSMContext) -> None:
    await _back_to_card(message, db, api, state)


@router.message(St.s_price)
async def sell_price(message: Message, state: FSMContext) -> None:
    price = parse_positive_float(message.text)
    if price is None:
        await message.answer("⚠️ Введите цену числом больше 0:")
        return
    await state.update_data(sell_price=price)
    await state.set_state(St.s_amount)
    await message.answer("📦 Введите количество для продажи:", reply_markup=reply.back_only())


@router.message(St.s_amount, F.text == reply.BACK)
async def sell_amount_back(message: Message, db: Database, api: CoinGeckoClient,
                           state: FSMContext) -> None:
    await _back_to_card(message, db, api, state)


@router.message(St.s_amount)
async def sell_amount(message: Message, state: FSMContext) -> None:
    amount = parse_positive_float(message.text)
    if amount is None:
        await message.answer("⚠️ Введите количество числом больше 0:")
        return
    data = await state.get_data()
    if amount > data["sell_remaining"] + 1e-9:
        await message.answer(
            f"⚠️ Недостаточно. Остаток: {data['sell_remaining']:g} шт. Введите меньше:")
        return
    await state.update_data(sell_amount=amount)
    await state.set_state(St.s_date)
    await message.answer(
        "📅 Введите дату продажи (ДД.ММ.ГГГГ) или «⏭ Пропустить» для текущей:",
        reply_markup=reply.skip_or_back(),
    )


@router.message(St.s_date, F.text == reply.BACK)
async def sell_date_back(message: Message, db: Database, api: CoinGeckoClient,
                         state: FSMContext) -> None:
    await _back_to_card(message, db, api, state)


@router.message(St.s_date)
async def sell_date(message: Message, db: Database, api: CoinGeckoClient,
                    state: FSMContext) -> None:
    if message.text.strip() == reply.SKIP:
        date = today_str()
    else:
        date = parse_date(message.text)
        if date is None:
            await message.answer("⚠️ Неверный формат. Введите дату как ДД.ММ.ГГГГ:")
            return

    data = await state.get_data()
    ticker = data["sell_ticker"]
    price = data["sell_price"]
    amount = data["sell_amount"]
    inv_id = data["inv_id"]

    await db.add_transaction(inv_id, ticker, "sell", price, amount, date)

    # Реализованный P&L сделки относительно средней цены входа
    pnl_line = ""
    transactions = await db.get_transactions(inv_id)
    buys = [t for t in transactions if t["asset_ticker"] == ticker and t["kind"] == "buy"]
    buy_qty = sum(t["amount"] for t in buys)
    buy_cost = sum(t["price"] * t["amount"] for t in buys)
    if buy_qty > 0 and buy_cost > 0:
        avg_buy = buy_cost / buy_qty
        pnl = (price - avg_buy) * amount
        pct = (price / avg_buy - 1) * 100
        sign = "+" if pnl >= 0 else "-"
        pnl_line = f"\n📈 P&L сделки: {sign}{fmt_usd(abs(pnl))} $ ({pct:+.2f}%)"

    await message.answer(
        f"✅ Продано: <b>{ticker}</b> — {amount:g} шт по {fmt_usd(price)} $ "
        f"(сумма {fmt_usd(price * amount)} $), дата {date}{pnl_line}"
    )
    await show_investor_card(message, db, api, state, inv_id)


# ---- Удаление актива (полностью) ----

@router.message(St.investor, F.text == reply.DEL_ASSET)
async def del_asset_start(message: Message, db: Database, state: FSMContext) -> None:
    inv_id = await _current_investor_id(state)
    assets = await db.get_portfolio(inv_id)
    if not assets:
        await message.answer("В портфеле нет активов.", reply_markup=reply.investor_actions())
        return
    await state.set_state(St.d_pick)
    pairs = [(a["asset_ticker"], a["amount"]) for a in assets]
    await message.answer("🗑 Выберите актив для полного удаления (со всеми сделками):",
                         reply_markup=reply.tickers_list(pairs))


@router.message(St.d_pick, F.text == reply.BACK)
async def del_asset_back(message: Message, db: Database, api: CoinGeckoClient,
                         state: FSMContext) -> None:
    await _back_to_card(message, db, api, state)


@router.message(St.d_pick)
async def del_asset(message: Message, db: Database, api: CoinGeckoClient,
                    state: FSMContext) -> None:
    ticker = message.text.split("—")[0].strip().upper()
    inv_id = await _current_investor_id(state)
    if await db.remaining_amount(inv_id, ticker) <= 0:
        await message.answer("⚠️ Выберите актив кнопкой из списка.")
        return
    await db.delete_asset(inv_id, ticker)
    await message.answer(f"🗑 Актив <b>{ticker}</b> удалён со всеми сделками.")
    await show_investor_card(message, db, api, state, inv_id)


# ---- Удаление инвестора (с подтверждением) ----

@router.message(St.investor, F.text == reply.DEL_INVESTOR)
async def del_investor_ask(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(St.del_investor)
    await message.answer(
        f"🗑 Удалить инвестора <b>{data.get('inv_name', '')}</b> и все его сделки?\n"
        "Действие необратимо.",
        reply_markup=reply.yes_no(),
    )


@router.message(St.del_investor, F.text == reply.YES)
async def del_investor_yes(message: Message, db: Database, state: FSMContext) -> None:
    inv_id = await _current_investor_id(state)
    if inv_id is not None:
        await db.delete_investor(inv_id)
    await message.answer("✅ Инвестор удалён.")
    await show_investors_list(message, db, state)


@router.message(St.del_investor)
async def del_investor_no(message: Message, db: Database, api: CoinGeckoClient,
                          state: FSMContext) -> None:
    await _back_to_card(message, db, api, state)


# ---------------------------------------------------------------------------
# Возврат к карточке текущего инвестора
# ---------------------------------------------------------------------------

async def _back_to_card(message: Message, db: Database, api: CoinGeckoClient,
                        state: FSMContext) -> None:
    inv_id = await _current_investor_id(state)
    if inv_id is None:
        await show_investors_list(message, db, state)
    else:
        await show_investor_card(message, db, api, state, inv_id)
