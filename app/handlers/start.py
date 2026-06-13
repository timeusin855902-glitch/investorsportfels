"""Команда /start, главное меню и глобальная кнопка «🏠 Главное меню»."""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.keyboards import reply
from app.states import St

router = Router()

WELCOME_TEXT = (
    "🏦 <b>Портфельный трекер</b>\n\n"
    "Учёт криптопортфелей инвесторов с точками входа, аналитикой рынка, "
    "сводкой прибыли/убытка и алертами волатильности.\n\n"
    "Выберите раздел кнопками ниже 👇"
)


async def go_main(message: Message, state: FSMContext) -> None:
    """Сбрасывает диалог и показывает главное меню."""
    await state.clear()
    await state.set_state(St.main)
    await message.answer(WELCOME_TEXT, reply_markup=reply.main_menu())


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await go_main(message, state)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await go_main(message, state)


@router.message(F.text == reply.HOME)
async def btn_home(message: Message, state: FSMContext) -> None:
    """Глобальная кнопка возврата в главное меню (работает в любом состоянии)."""
    await go_main(message, state)


@router.message(StateFilter(None))
async def recover_after_restart(message: Message, state: FSMContext) -> None:
    """Если состояние потеряно (например, после перезапуска бота) — показываем меню."""
    await go_main(message, state)
