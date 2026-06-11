"""Загрузка конфигурации из .env файла."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Конфигурация бота."""
    bot_token: str
    coingecko_api_key: str
    allowed_users: set[int]        # ID владельцев из .env
    analytics_chat_id: int | None  # Чат для отчетов/алертов (может быть задан позже через меню)
    db_path: str                   # Путь к файлу SQLite


def _parse_int(value: str) -> int | None:
    """Безопасный парсинг целого числа (поддерживает отрицательные ID чатов)."""
    value = value.strip()
    if value.lstrip("-").isdigit():
        return int(value)
    return None


def load_config() -> Config:
    """Читает переменные окружения и возвращает объект конфигурации."""
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не задан в .env — бот не может быть запущен")

    # Парсим список разрешенных пользователей
    allowed: set[int] = set()
    for part in os.getenv("ALLOWED_USERS", "").split(","):
        user_id = _parse_int(part)
        if user_id is not None:
            allowed.add(user_id)
    if not allowed:
        raise RuntimeError("ALLOWED_USERS пуст — никто не сможет пользоваться ботом")

    return Config(
        bot_token=token,
        coingecko_api_key=os.getenv("COINGECKO_API_KEY", "").strip(),
        allowed_users=allowed,
        analytics_chat_id=_parse_int(os.getenv("ANALYTICS_CHAT_ID", "")),
        db_path=os.getenv("DB_PATH", "portfolio.db"),
    )
