"""Команда /start, главное меню и глобальная кнопка «🏠 Главное меню»."""
from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.database import Database
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


@router.message(Command("setforum"))
async def cmd_setforum(message: Message, db: Database) -> None:
    """Назначает текущую форум-супергруппу для персональных тем инвесторов.

    Вызывать внутри супергруппы с включёнными «Темами», где бот — админ
    с правом управления темами. Темы по инвесторам создаются автоматически.
    """
    chat = message.chat
    if chat.type != "supergroup" or not getattr(chat, "is_forum", False):
        await message.answer(
            "⚠️ Команду нужно вызвать в супергруппе с включёнными «Темами» (Topics), "
            "где бот добавлен администратором с правом «Управление темами»."
        )
        return
    await db.set_setting("forum_chat_id", str(chat.id))
    await message.answer(
        "✅ Эта группа назначена для персональных тем инвесторов.\n"
        "Темы будут создаваться автоматически — туда пойдут личные отчёты и алерты."
    )


@router.message(Command("unsetforum"))
async def cmd_unsetforum(message: Message, db: Database) -> None:
    """Отключает отправку персональных отчётов/алертов в форум-темы."""
    await db.set_setting("forum_chat_id", "")
    await message.answer("✅ Форум-группа для персональных тем отключена.")


@router.message(Command("bindtopic"))
async def cmd_bindtopic(message: Message, command: CommandObject, db: Database) -> None:
    """Привязывает ТЕКУЩУЮ тему к инвестору: его алерты/отчёты пойдут именно сюда.

    Вызывать ВНУТРИ нужной темы: /bindtopic Имя инвестора
    """
    chat = message.chat
    if chat.type != "supergroup" or not getattr(chat, "is_forum", False):
        await message.answer("⚠️ Команду нужно вызвать в форум-супергруппе с «Темами».")
        return
    # Сообщение в General не относится к теме — message_thread_id отсутствует
    thread_id = message.message_thread_id
    if thread_id is None:
        await message.answer("⚠️ Вызовите команду ВНУТРИ нужной темы инвестора, а не в General.")
        return

    name = (command.args or "").strip()
    investors = await db.get_investors()
    if not name:
        names = ", ".join(i["name"] for i in investors) or "— (сначала добавьте инвесторов)"
        await message.answer(f"Укажите инвестора: <code>/bindtopic Имя</code>\nДоступны: {names}")
        return

    investor = await db.find_investor_by_name(name)
    if investor is None:
        await message.answer(f"⚠️ Инвестор «{name}» не найден. Проверьте имя.")
        return

    # Запоминаем эту группу как форум и привязываем тему к инвестору
    await db.set_setting("forum_chat_id", str(chat.id))
    await db.set_investor_thread(investor["id"], thread_id)
    await message.answer(
        f"✅ Тема привязана к инвестору <b>{investor['name']}</b>.\n"
        "Сюда будут приходить его персональные отчёты и алерты по его монетам."
    )


@router.message(F.text == reply.HOME)
async def btn_home(message: Message, state: FSMContext) -> None:
    """Глобальная кнопка возврата в главное меню (работает в любом состоянии)."""
    await go_main(message, state)


@router.message(StateFilter(None))
async def recover_after_restart(message: Message, state: FSMContext) -> None:
    """Если состояние потеряно (например, после перезапуска бота) — показываем меню."""
    await go_main(message, state)
