"""Раздел «Инвесторы»: список, карточка портфеля и все операции над активами."""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.database import Database
from app.handlers.start import safe_edit
from app.keyboards import inline
from app.services.coingecko import CoinGeckoClient, CoinGeckoError
from app.services.reports import build_investor_card

logger = logging.getLogger(__name__)
router = Router()


# ---------- FSM-состояния диалогов ----------

class AddInvestor(StatesGroup):
    name = State()          # ожидаем имя нового инвестора


class AddAsset(StatesGroup):
    ticker = State()        # ожидаем тикер монеты
    amount = State()        # ожидаем количество


class EditAsset(StatesGroup):
    amount = State()        # ожидаем новое количество для выбранного актива


def _parse_amount(text: str) -> float | None:
    """Парсит количество монет: поддерживает запятую, требует значение > 0."""
    try:
        value = float(text.replace(",", ".").replace(" ", ""))
    except ValueError:
        return None
    return value if value > 0 else None


async def show_investor_card(message: Message, db: Database, api: CoinGeckoClient,
                             investor_id: int, edit: bool = True) -> None:
    """Показывает карточку инвестора (редактирует сообщение или шлет новое)."""
    text = await build_investor_card(db, api, investor_id)
    markup = inline.investor_menu(investor_id)
    if edit:
        await safe_edit(message, text, markup)
    else:
        await message.answer(text, reply_markup=markup)


# ---------- Список инвесторов ----------

@router.callback_query(F.data == "menu_investors")
async def list_investors(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    investors = await db.get_investors()
    text = "👥 <b>Инвесторы</b>\n\nВыберите инвестора или добавьте нового:" if investors \
        else "👥 <b>Инвесторы</b>\n\nСписок пуст — добавьте первого инвестора:"
    await safe_edit(callback.message, text, inline.investors_list(investors))
    await callback.answer()


@router.callback_query(F.data.startswith("inv:"))
async def open_investor(callback: CallbackQuery, db: Database, api: CoinGeckoClient,
                        state: FSMContext) -> None:
    await state.clear()
    investor_id = int(callback.data.split(":")[1])
    await callback.answer("Загружаю цены…")
    await show_investor_card(callback.message, db, api, investor_id)


# ---------- Добавление инвестора ----------

@router.callback_query(F.data == "inv_add")
async def add_investor_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddInvestor.name)
    await safe_edit(callback.message, "✍️ Введите имя нового инвестора:", inline.cancel_input())
    await callback.answer()


@router.message(AddInvestor.name, F.text)
async def add_investor_name(message: Message, state: FSMContext, db: Database) -> None:
    name = message.text.strip()
    if not name or len(name) > 64:
        await message.answer("⚠️ Имя должно быть от 1 до 64 символов. Попробуйте еще раз:")
        return
    await state.clear()
    await db.add_investor(name)
    investors = await db.get_investors()
    await message.answer(
        f"✅ Инвестор <b>{name}</b> добавлен!",
        reply_markup=inline.investors_list(investors),
    )


# ---------- Добавление актива ----------

@router.callback_query(F.data.startswith("asset_add:"))
async def add_asset_start(callback: CallbackQuery, state: FSMContext) -> None:
    investor_id = int(callback.data.split(":")[1])
    await state.set_state(AddAsset.ticker)
    await state.update_data(investor_id=investor_id)
    await safe_edit(
        callback.message,
        "✍️ Введите тикер монеты (например, <code>BTC</code> или <code>ZEC</code>):",
        inline.cancel_input(),
    )
    await callback.answer()


@router.message(AddAsset.ticker, F.text)
async def add_asset_ticker(message: Message, state: FSMContext, api: CoinGeckoClient) -> None:
    ticker = message.text.strip().upper()
    if not ticker.isalnum() or len(ticker) > 15:
        await message.answer("⚠️ Тикер — до 15 букв/цифр. Попробуйте еще раз:")
        return

    # Проверяем, что монета существует на CoinGecko, до записи в БД
    try:
        coin_id = await api.resolve_ticker(ticker)
    except CoinGeckoError as e:
        await message.answer(f"⚠️ {e}\nПопробуйте еще раз чуть позже:")
        return
    if coin_id is None:
        await message.answer(
            f"⚠️ Монета <b>{ticker}</b> не найдена на CoinGecko. Проверьте тикер:"
        )
        return

    await state.update_data(ticker=ticker)
    await state.set_state(AddAsset.amount)
    await message.answer(
        f"Тикер <b>{ticker}</b> найден ✅\n✍️ Теперь введите количество монет:",
        reply_markup=inline.cancel_input(),
    )


@router.message(AddAsset.amount, F.text)
async def add_asset_amount(message: Message, state: FSMContext, db: Database,
                           api: CoinGeckoClient) -> None:
    amount = _parse_amount(message.text)
    if amount is None:
        await message.answer("⚠️ Введите положительное число, например <code>0.5</code>:")
        return

    data = await state.get_data()
    await state.clear()
    await db.add_asset(data["investor_id"], data["ticker"], amount)
    await message.answer(f"✅ Актив <b>{data['ticker']}</b> добавлен!")
    await show_investor_card(message, db, api, data["investor_id"], edit=False)


# ---------- Изменение количества актива ----------

@router.callback_query(F.data.startswith("asset_edit:"))
async def edit_asset_choose(callback: CallbackQuery, db: Database) -> None:
    investor_id = int(callback.data.split(":")[1])
    assets = await db.get_portfolio(investor_id)
    if not assets:
        await callback.answer("Портфель пуст — нечего изменять", show_alert=True)
        return
    await safe_edit(
        callback.message,
        "✏️ Выберите актив для изменения количества:",
        inline.assets_list(assets, "edit", investor_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("asset_edit_sel:"))
async def edit_asset_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    asset_id = int(callback.data.split(":")[1])
    asset = await db.get_asset(asset_id)
    if asset is None:
        await callback.answer("Актив не найден", show_alert=True)
        return
    await state.set_state(EditAsset.amount)
    await state.update_data(asset_id=asset_id, investor_id=asset["investor_id"])
    await safe_edit(
        callback.message,
        f"✍️ Текущее количество <b>{asset['asset_ticker']}</b>: {asset['amount']:g}\n"
        "Введите новое количество:",
        inline.cancel_input(),
    )
    await callback.answer()


@router.message(EditAsset.amount, F.text)
async def edit_asset_amount(message: Message, state: FSMContext, db: Database,
                            api: CoinGeckoClient) -> None:
    amount = _parse_amount(message.text)
    if amount is None:
        await message.answer("⚠️ Введите положительное число, например <code>1.25</code>:")
        return

    data = await state.get_data()
    await state.clear()
    await db.update_asset_amount(data["asset_id"], amount)
    await message.answer("✅ Количество обновлено!")
    await show_investor_card(message, db, api, data["investor_id"], edit=False)


# ---------- Удаление актива ----------

@router.callback_query(F.data.startswith("asset_del:"))
async def delete_asset_choose(callback: CallbackQuery, db: Database) -> None:
    investor_id = int(callback.data.split(":")[1])
    assets = await db.get_portfolio(investor_id)
    if not assets:
        await callback.answer("Портфель пуст — нечего удалять", show_alert=True)
        return
    await safe_edit(
        callback.message,
        "❌ Выберите актив для удаления:",
        inline.assets_list(assets, "del", investor_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("asset_del_sel:"))
async def delete_asset_confirm(callback: CallbackQuery, db: Database,
                               api: CoinGeckoClient) -> None:
    asset_id = int(callback.data.split(":")[1])
    asset = await db.get_asset(asset_id)
    if asset is None:
        await callback.answer("Актив не найден", show_alert=True)
        return
    await db.delete_asset(asset_id)
    await callback.answer(f"Актив {asset['asset_ticker']} удален")
    await show_investor_card(callback.message, db, api, asset["investor_id"])


# ---------- Удаление инвестора (с подтверждением) ----------

@router.callback_query(F.data.startswith("inv_del:"))
async def delete_investor_ask(callback: CallbackQuery, db: Database) -> None:
    investor_id = int(callback.data.split(":")[1])
    investor = await db.get_investor(investor_id)
    if investor is None:
        await callback.answer("Инвестор не найден", show_alert=True)
        return
    await safe_edit(
        callback.message,
        f"🗑 Удалить инвестора <b>{investor['name']}</b> и все его активы?\n"
        "Действие необратимо.",
        inline.confirm_delete_investor(investor_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("inv_del_yes:"))
async def delete_investor_do(callback: CallbackQuery, db: Database) -> None:
    investor_id = int(callback.data.split(":")[1])
    await db.delete_investor(investor_id)
    investors = await db.get_investors()
    await safe_edit(
        callback.message,
        "✅ Инвестор удален.\n\n👥 <b>Инвесторы</b>",
        inline.investors_list(investors),
    )
    await callback.answer()
