"""Middleware контроля доступа.

Бот реагирует на ЛЮБЫЕ апдейты только от пользователей из ALLOWED_USERS (.env)
или из таблицы admins (добавленных через меню настроек).
Сообщения всех остальных пользователей полностью игнорируются — без ответа.
"""
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from app.database import Database

logger = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    def __init__(self, allowed_users: set[int], db: Database):
        self._allowed_users = allowed_users  # владельцы из .env (нельзя удалить через меню)
        self._db = db

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # aiogram кладет автора апдейта в data["event_from_user"]
        user: User | None = data.get("event_from_user")
        if user is None:
            # Апдейт без пользователя (например, из канала) — игнорируем
            return None

        # Доступ разрешен: владельцы из .env + админы из БД
        if user.id in self._allowed_users or user.id in await self._db.get_admins():
            return await handler(event, data)

        logger.info("Игнорируем апдейт от неавторизованного пользователя %s", user.id)
        return None  # полное игнорирование: ни ответа, ни обработки
