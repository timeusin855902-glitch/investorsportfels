"""Команда /start, главное меню и общая отмена FSM-ввода."""
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.keyboards import inline

router = Router()

WELCOME_TEXT = (
    "🏦 <b>Портфельный трекер</b>\n\n"
    "Отслеживание криптопортфелей инвесторов, аналитика рынка "
    "и автоматические алерты волатильности.\n\n"
    "Выберите раздел:"
)


async def safe_edit(message: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Редактирует сообщение, игнорируя ошибку 'message is not modified'."""
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Точка входа: сбрасываем незавершенные диалоги и показываем главное меню."""
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=inline.main_menu())


@router.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(callback.message, WELCOME_TEXT, inline.main_menu())
    await callback.answer()


@router.callback_query(F.data == "fsm_cancel")
async def cancel_fsm(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена любого ожидания текстового ввода."""
    await state.clear()
    await safe_edit(callback.message, WELCOME_TEXT, inline.main_menu())
    await callback.answer("Действие отменено")
