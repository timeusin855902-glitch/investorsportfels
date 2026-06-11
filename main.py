"""Точка входа: инициализация БД, бота, middleware, роутеров и планировщика."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import load_config
from app.database import Database
from app.handlers import get_main_router
from app.middlewares import AccessMiddleware
from app.scheduler import setup_scheduler
from app.services import CoinGeckoClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()

    # Инициализация БД и клиента CoinGecko
    db = Database(config.db_path)
    await db.init()
    api = CoinGeckoClient(config.coingecko_api_key)

    # Бот с HTML-разметкой по умолчанию
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Контроль доступа: внешний middleware на все типы апдейтов
    dp.update.outer_middleware(AccessMiddleware(config.allowed_users, db))

    # Фоновые задачи (отчеты и алерты волатильности)
    scheduler = await setup_scheduler(bot, db, api, config)

    # Зависимости, которые aiogram внедрит в хэндлеры по именам аргументов
    dp["db"] = db
    dp["api"] = api
    dp["config"] = config
    dp["scheduler"] = scheduler

    dp.include_router(get_main_router())

    logger.info("Бот запускается…")
    try:
        # Сбрасываем накопившиеся апдейты и стартуем long polling
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        # Аккуратно освобождаем ресурсы при остановке
        scheduler.shutdown(wait=False)
        await api.close()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
