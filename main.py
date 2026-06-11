import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database.db import init_db
from middlewares.auth import AuthMiddleware
from handlers import common, investors, analytics, settings as settings_handler
from services.coingecko import coingecko
from services.scheduler import setup_scheduler, reschedule_daily_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot, scheduler) -> None:
    """Действия при запуске: инициализация БД, планировщика."""
    await init_db()
    logger.info("База данных инициализирована.")

    # Устанавливаем время ежедневного отчёта из настроек
    await reschedule_daily_report(bot)

    scheduler.start()
    logger.info("Планировщик задач запущен.")

    me = await bot.get_me()
    logger.info(f"Бот запущен: @{me.username}")


async def on_shutdown(scheduler) -> None:
    """Действия при остановке."""
    scheduler.shutdown(wait=False)
    await coingecko.close()
    logger.info("Бот остановлен.")


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в .env!")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрируем middleware (применяется ко всем обновлениям)
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    # Регистрируем роутеры хэндлеров
    dp.include_router(common.router)
    dp.include_router(investors.router)
    dp.include_router(analytics.router)
    dp.include_router(settings_handler.router)

    scheduler = setup_scheduler(bot)

    try:
        await on_startup(bot, scheduler)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await on_shutdown(scheduler)


if __name__ == "__main__":
    asyncio.run(main())
