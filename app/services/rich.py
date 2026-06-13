"""Поддержка Rich Messages (Telegram Bot API 10.1, июнь 2026).

Bot API 10.1 добавил нативный структурированный формат сообщений:
методы sendRichMessage / editMessageText(rich_message) с собственным
расширенным HTML (теги <table>, <h1>..<h6>, <blockquote>, <details>, <hr/>,
<mark>, <tg-math> и т.д.).

aiogram 3.x вышел ДО этого обновления и не знает о новом методе, поэтому
вызываем его напрямую сырым HTTP-запросом к Bot API. Клавиатуры (reply_markup)
методом поддерживаются — сериализуем модель aiogram в JSON.

Документация: https://core.telegram.org/bots/api#rich-message-formatting-options
"""
import logging

import aiohttp
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

# Любая клавиатура, которую принимает Bot API в reply_markup
Markup = InlineKeyboardMarkup | ReplyKeyboardMarkup

logger = logging.getLogger(__name__)

# Базовый адрес Bot API (по умолчанию официальный сервер Telegram)
API_BASE = "https://api.telegram.org"
_TIMEOUT = aiohttp.ClientTimeout(total=30)


class RichMessageError(Exception):
    """Ошибка при вызове методов Rich Messages."""


# ---------------------------------------------------------------------------
# Экранирование и сборка таблиц для расширенного HTML rich-сообщений
# ---------------------------------------------------------------------------

def esc(text: object) -> str:
    """Экранирует спецсимволы для rich-HTML.

    В rich-режиме обязательны к экранированию & < >; кавычки внутри текста
    допустимы, но & < > сломают разметку. Применяется ко ВСЕМ данным из БД
    (имена инвесторов, тикеры), чтобы символы вроде «&» или «<» не ломали
    структуру сообщения.
    """
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_table(
    headers: list[str],
    rows: list[list[str]],
    aligns: list[str] | None = None,
    caption: str | None = None,
    bordered: bool = True,
    striped: bool = True,
) -> str:
    """Собирает нативную таблицу <table> из массива данных.

    Args:
        headers: подписи колонок (строка <th>).
        rows:    строки данных; длина каждой == длине headers.
        aligns:  выравнивание по колонкам: "left" | "center" | "right".
                 По умолчанию первая колонка слева, остальные справа.
        caption: необязательная подпись таблицы (<caption>).
        bordered, striped: атрибуты оформления таблицы Telegram.

    Returns:
        HTML-фрагмент <table>…</table> с экранированными ячейками.
    """
    n = len(headers)
    if aligns is None:
        aligns = ["left"] + ["right"] * (n - 1)

    attrs = ""
    if bordered:
        attrs += " bordered"
    if striped:
        attrs += " striped"

    parts = [f"<table{attrs}>"]
    if caption:
        parts.append(f"<caption>{esc(caption)}</caption>")

    # Шапка таблицы
    head_cells = "".join(f"<th>{esc(h)}</th>" for h in headers)
    parts.append(f"<tr>{head_cells}</tr>")

    # Строки данных (в ячейках допустимо только инлайн-форматирование)
    for row in rows:
        cells = "".join(
            f'<td align="{aligns[i]}">{esc(cell)}</td>' for i, cell in enumerate(row)
        )
        parts.append(f"<tr>{cells}</tr>")

    parts.append("</table>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Низкоуровневый вызов Bot API
# ---------------------------------------------------------------------------

def _markup_json(reply_markup: Markup | None) -> dict | None:
    """Сериализует клавиатуру aiogram (inline или reply) в JSON для сырого запроса."""
    if reply_markup is None:
        return None
    return reply_markup.model_dump(mode="json", by_alias=True, exclude_none=True)


async def _call(bot: Bot, method: str, payload: dict) -> dict:
    """Выполняет POST-запрос к методу Bot API и возвращает поле result."""
    url = f"{API_BASE}/bot{bot.token}/{method}"
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
    except aiohttp.ClientError as e:
        raise RichMessageError(f"Сетевая ошибка при вызове {method}: {e}") from e

    if not data.get("ok"):
        raise RichMessageError(data.get("description", f"{method}: неизвестная ошибка"))
    return data["result"]


async def send_rich_message(
    bot: Bot,
    chat_id: int | str,
    html: str,
    reply_markup: Markup | None = None,
    **extra,
) -> dict:
    """Отправляет rich-сообщение (метод sendRichMessage).

    Args:
        html: контент в расширенном rich-HTML (таблицы, заголовки и т.д.).
        reply_markup: необязательная клавиатура (inline или reply).
        extra: дополнительные параметры метода (disable_notification и пр.).
    """
    payload: dict = {"chat_id": chat_id, "rich_message": {"html": html}}
    markup = _markup_json(reply_markup)
    if markup is not None:
        payload["reply_markup"] = markup
    payload.update(extra)
    return await _call(bot, "sendRichMessage", payload)


async def create_forum_topic(bot: Bot, chat_id: int | str, name: str) -> int:
    """Создаёт тему в форум-супергруппе (createForumTopic) и возвращает её id.

    Бот должен быть админом группы с правом can_manage_topics. Имя темы — 1..128
    символов. Возвращает message_thread_id созданной темы.
    """
    result = await _call(bot, "createForumTopic", {"chat_id": chat_id, "name": name[:128]})
    return result["message_thread_id"]
