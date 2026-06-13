"""Общие помощники для хэндлеров на reply-клавиатурах."""
from aiogram.types import Message, ReplyKeyboardMarkup

from app.services.rich import send_rich_message


async def send_rich(message: Message, html: str, keyboard: ReplyKeyboardMarkup) -> None:
    """Отправляет rich-сообщение (нативные таблицы) с reply-клавиатурой."""
    await send_rich_message(message.bot, message.chat.id, html, keyboard)
