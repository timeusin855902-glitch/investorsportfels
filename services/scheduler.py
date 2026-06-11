import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from aiogram import Bot

from config import ANALYTICS_CHAT_ID, VOLATILITY_CHECK_INTERVAL
from database.db import (
    get_all_portfolios, get_all_unique_tickers, get_setting,
)
from services.coingecko import coingecko
from services.formatter import build_full_report

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def send_daily_report(bot: Bot) -> None:
    """Формирует и отправляет ежедневный отчёт в ANALYTICS_CHAT_ID."""
    logger.info("Запуск ежедневного отчёта...")
    try:
        positions = await get_all_portfolios()
        text = await build_full_report(positions)
        await bot.send_message(ANALYTICS_CHAT_ID, text, parse_mode="HTML")
        logger.info("Ежедневный отчёт успешно отправлен.")
    except Exception as exc:
        logger.error(f"Ошибка отправки ежедневного отчёта: {exc}")


async def check_volatility(bot: Bot) -> None:
    """Проверяет волатильность и отправляет алерты при превышении порога."""
    logger.debug("Проверка волатильности...")
    try:
        threshold_raw = await get_setting("volatility_threshold")
        threshold = float(threshold_raw) if threshold_raw else 30.0

        tickers = await get_all_unique_tickers()
        if not tickers:
            return

        prices = await coingecko.get_prices(tickers)

        for ticker, info in prices.items():
            if "error" in info:
                continue
            change = info.get("change_24h", 0.0)
            price = info.get("price", 0.0)

            if abs(change) >= threshold:
                direction = "рост" if change > 0 else "падение"
                emoji = "🚀" if change > 0 else "🔻"
                alert_text = (
                    f"🚨 <b>Внимание!</b> Актив <b>{ticker}</b> показал "
                    f"{direction} на <b>{change:+.2f}%</b> за последние 24 часа!\n"
                    f"{emoji} Текущая цена: <b>${price:,.4f}</b>"
                )
                await bot.send_message(ANALYTICS_CHAT_ID, alert_text, parse_mode="HTML")
                logger.info(f"Алерт отправлен: {ticker} {change:+.2f}%")
    except Exception as exc:
        logger.error(f"Ошибка проверки волатильности: {exc}")


async def reschedule_daily_report(bot: Bot) -> None:
    """Перепланирует задачу ежедневного отчёта по настройкам из БД."""
    hour_raw = await get_setting("report_hour")
    minute_raw = await get_setting("report_minute")
    hour = int(hour_raw) if hour_raw else 9
    minute = int(minute_raw) if minute_raw else 0

    if scheduler.get_job("daily_report"):
        scheduler.remove_job("daily_report")

    scheduler.add_job(
        send_daily_report,
        trigger=CronTrigger(hour=hour, minute=minute, timezone="UTC"),
        args=[bot],
        id="daily_report",
        replace_existing=True,
    )
    logger.info(f"Ежедневный отчёт запланирован на {hour}:{minute:02d} UTC")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Инициализирует и запускает планировщик задач."""
    # Проверка волатильности каждые N минут
    scheduler.add_job(
        check_volatility,
        trigger=IntervalTrigger(minutes=VOLATILITY_CHECK_INTERVAL),
        args=[bot],
        id="volatility_check",
        replace_existing=True,
    )

    # Ежедневный отчёт — время берём из БД при старте
    scheduler.add_job(
        reschedule_daily_report,
        trigger=CronTrigger(hour=0, minute=0, timezone="UTC"),  # каждый день переустанавливает время
        args=[bot],
        id="reschedule_report",
        replace_existing=True,
    )

    return scheduler
