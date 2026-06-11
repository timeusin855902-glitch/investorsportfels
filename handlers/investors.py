from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from database.db import (
    get_all_investors, add_investor, get_investor, delete_investor,
    get_portfolio, add_or_update_asset, delete_asset,
)
from handlers.keyboards import (
    investors_list_kb, investor_menu_kb, assets_list_kb,
    confirm_delete_investor_kb, back_to_investor_kb,
)
from handlers.states import AddInvestorSG, AddAssetSG, EditAssetSG
from services.formatter import build_portfolio_text

router = Router()


# ---------------------------------------------------------------------------
# Список инвесторов
# ---------------------------------------------------------------------------

async def _show_investors_list(target, edit: bool = True) -> None:
    investors = await get_all_investors()
    text = "👥 <b>Инвесторы</b>\n\nВыбери инвестора или добавь нового:"
    kb = investors_list_kb(investors)
    if edit:
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "investors_list")
async def cb_investors_list(callback: CallbackQuery) -> None:
    await _show_investors_list(callback, edit=True)
    await callback.answer()


# ---------------------------------------------------------------------------
# Добавление инвестора (FSM)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "investor_add")
async def cb_investor_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddInvestorSG.waiting_name)
    await callback.message.edit_text("✏️ Введи имя нового инвестора:", parse_mode="HTML")
    await callback.answer()


@router.message(AddInvestorSG.waiting_name)
async def msg_investor_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("Имя не может быть пустым. Попробуй снова:")
        return
    try:
        await add_investor(name)
        await state.clear()
        await message.answer(f"✅ Инвестор <b>{name}</b> добавлен!", parse_mode="HTML")
    except Exception:
        await message.answer("⚠️ Инвестор с таким именем уже существует.", parse_mode="HTML")
        await state.clear()

    investors = await get_all_investors()
    await message.answer(
        "👥 <b>Инвесторы</b>",
        reply_markup=investors_list_kb(investors),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Просмотр портфеля инвестора
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("investor:"))
async def cb_investor_view(callback: CallbackQuery) -> None:
    investor_id = int(callback.data.split(":")[1])
    investor = await get_investor(investor_id)
    if not investor:
        await callback.answer("Инвестор не найден.", show_alert=True)
        return

    positions = await get_portfolio(investor_id)
    text = await build_portfolio_text(investor["name"], positions)
    kb = investor_menu_kb(investor_id)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ---------------------------------------------------------------------------
# Удаление инвестора
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("investor_delete:"))
async def cb_investor_delete_ask(callback: CallbackQuery) -> None:
    investor_id = int(callback.data.split(":")[1])
    investor = await get_investor(investor_id)
    name = investor["name"] if investor else "?"
    await callback.message.edit_text(
        f"🗑 Удалить инвестора <b>{name}</b> и все его активы?",
        reply_markup=confirm_delete_investor_kb(investor_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("investor_delete_confirm:"))
async def cb_investor_delete_confirm(callback: CallbackQuery) -> None:
    investor_id = int(callback.data.split(":")[1])
    await delete_investor(investor_id)
    await callback.answer("✅ Инвестор удалён.", show_alert=True)
    await _show_investors_list(callback, edit=True)


# ---------------------------------------------------------------------------
# Добавление актива (FSM)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("asset_add:"))
async def cb_asset_add(callback: CallbackQuery, state: FSMContext) -> None:
    investor_id = int(callback.data.split(":")[1])
    await state.update_data(investor_id=investor_id)
    await state.set_state(AddAssetSG.waiting_ticker)
    await callback.message.edit_text(
        "➕ Введи тикер актива (например, <code>BTC</code>, <code>ZEC</code>):",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AddAssetSG.waiting_ticker)
async def msg_asset_ticker(message: Message, state: FSMContext) -> None:
    ticker = message.text.strip().upper()
    if not ticker.isalpha():
        await message.answer("Тикер должен содержать только буквы. Попробуй снова:")
        return
    await state.update_data(ticker=ticker)
    await state.set_state(AddAssetSG.waiting_amount)
    await message.answer(f"Введи количество монет <b>{ticker}</b>:", parse_mode="HTML")


@router.message(AddAssetSG.waiting_amount)
async def msg_asset_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = float(message.text.strip().replace(",", "."))
        if amount < 0:
            raise ValueError
    except ValueError:
        await message.answer("Введи корректное положительное число:")
        return

    data = await state.get_data()
    investor_id: int = data["investor_id"]
    ticker: str = data["ticker"]

    await add_or_update_asset(investor_id, ticker, amount)
    await state.clear()
    await message.answer(
        f"✅ Актив <b>{ticker}</b> ({amount:g}) добавлен/обновлён.",
        parse_mode="HTML",
    )

    investor = await get_investor(investor_id)
    positions = await get_portfolio(investor_id)
    text = await build_portfolio_text(investor["name"], positions)
    await message.answer(text, reply_markup=investor_menu_kb(investor_id), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Редактирование актива (FSM)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("asset_edit:"))
async def cb_asset_edit_select(callback: CallbackQuery) -> None:
    investor_id = int(callback.data.split(":")[1])
    positions = await get_portfolio(investor_id)
    if not positions:
        await callback.answer("Портфель пуст.", show_alert=True)
        return
    await callback.message.edit_text(
        "✏️ Выбери актив для изменения:",
        reply_markup=assets_list_kb(positions, "asset_edit_do", investor_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("asset_edit_do:"))
async def cb_asset_edit_do(callback: CallbackQuery, state: FSMContext) -> None:
    _, investor_id_str, ticker = callback.data.split(":")
    investor_id = int(investor_id_str)
    await state.update_data(investor_id=investor_id, ticker=ticker)
    await state.set_state(EditAssetSG.waiting_amount)
    await callback.message.edit_text(
        f"Введи новое количество для <b>{ticker}</b>:", parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditAssetSG.waiting_amount)
async def msg_edit_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = float(message.text.strip().replace(",", "."))
        if amount < 0:
            raise ValueError
    except ValueError:
        await message.answer("Введи корректное положительное число:")
        return

    data = await state.get_data()
    investor_id: int = data["investor_id"]
    ticker: str = data["ticker"]

    await add_or_update_asset(investor_id, ticker, amount)
    await state.clear()
    await message.answer(f"✅ Баланс <b>{ticker}</b> обновлён: {amount:g}", parse_mode="HTML")

    investor = await get_investor(investor_id)
    positions = await get_portfolio(investor_id)
    text = await build_portfolio_text(investor["name"], positions)
    await message.answer(text, reply_markup=investor_menu_kb(investor_id), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Удаление актива
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("asset_delete:"))
async def cb_asset_delete_select(callback: CallbackQuery) -> None:
    investor_id = int(callback.data.split(":")[1])
    positions = await get_portfolio(investor_id)
    if not positions:
        await callback.answer("Портфель пуст.", show_alert=True)
        return
    await callback.message.edit_text(
        "❌ Выбери актив для удаления:",
        reply_markup=assets_list_kb(positions, "asset_delete_do", investor_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("asset_delete_do:"))
async def cb_asset_delete_do(callback: CallbackQuery) -> None:
    _, investor_id_str, ticker = callback.data.split(":")
    investor_id = int(investor_id_str)
    await delete_asset(investor_id, ticker)
    await callback.answer(f"✅ Актив {ticker} удалён.", show_alert=True)

    investor = await get_investor(investor_id)
    positions = await get_portfolio(investor_id)
    text = await build_portfolio_text(investor["name"], positions)
    await callback.message.edit_text(
        text, reply_markup=investor_menu_kb(investor_id), parse_mode="HTML"
    )
