from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from config import ALLOWED_USERS


class AuthMiddleware(BaseMiddleware):
    """
    Пропускает обновления только от пользователей из ALLOWED_USERS.
    Все остальные сообщения/callback-и молча игнорируются.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None or user.id not in ALLOWED_USERS:
            return  # игнорируем
        return await handler(event, data)
