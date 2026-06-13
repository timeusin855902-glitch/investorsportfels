"""Фоновые задачи на APScheduler.

1. Сводный отчет — раз в N часов (N берется из настроек, по умолчанию 24)
   отправляется в аналитический чат.
2. Алерты волатильности — каждые 15 минут проверяются курсы всех уникальных
   монет из портфелей; при изменении за 24ч сильнее порога отправляется алерт.
"""
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Config
from app.database import Database
from app.services.coingecko import CoinGeckoClient, CoinGeckoError
from app.services.reports import build_summary_report, fmt_usd
from app.services.rich import esc, send_rich_message

logger = logging.getLogger(__name__)

REPORT_JOB_ID = "daily_report"
ALERT_JOB_ID = "volatility_alerts"
ALERT_CHECK_MINUTES = 15      # частота проверки курсов
ALERT_COOLDOWN = timedelta(hours=4)  # не слать повторный алерт по той же монете чаще, чем раз в 4ч

# Время последнего алерта по каждой монете (в памяти процесса)
_last_alert_at: dict[str, datetime] = {}


async def _get_analytics_chat_id(db: Database, config: Config) -> int | None:
    """Чат для отчетов: значение из настроек (меню) приоритетнее .env."""
    raw = await db.get_setting("analytics_chat_id")
    if raw.strip().lstrip("-").isdigit():
        return int(raw)
    return config.analytics_chat_id


async def send_daily_report(bot: Bot, db: Database, api: CoinGeckoClient,
                            config: Config) -> None:
    """Формирует и отправляет сводный отчет по всем инвесторам."""
    chat_id = await _get_analytics_chat_id(db, config)
    if chat_id is None:
        logger.warning("ANALYTICS_CHAT_ID не задан — отчет пропущен. "
                       "Назначьте чат кнопкой в меню «Настройки».")
        return
    try:
        html = await build_summary_report(
            db, api, title="🗞 Регулярный отчёт по портфелям"
        )
        await send_rich_message(bot, chat_id, html)
        logger.info("Сводный отчёт отправлен в чат %s", chat_id)
    except Exception:
        logger.exception("Ошибка при отправке сводного отчёта")


async def check_volatility(bot: Bot, db: Database, api: CoinGeckoClient,
                           config: Config) -> None:
    """Проверяет изменения цен за 24ч и шлет алерты при превышении порога."""
    chat_id = await _get_analytics_chat_id(db, config)
    if chat_id is None:
        return  # некуда слать — тихо пропускаем

    tickers = await db.get_unique_tickers()
    if not tickers:
        return

    try:
        threshold = float(await db.get_setting("alert_threshold", "30"))
        prices = await api.get_prices(tickers)
    except (CoinGeckoError, ValueError) as e:
        logger.warning("Проверка волатильности пропущена: %s", e)
        return

    now = datetime.now()
    for info in prices.values():
        if abs(info.change_24h) < threshold:
            continue
        # Анти-спам: по одной монете алертим не чаще одного раза за период cooldown
        last = _last_alert_at.get(info.ticker)
        if last is not None and now - last < ALERT_COOLDOWN:
            continue
        _last_alert_at[info.ticker] = now

        direction = "рост" if info.change_24h > 0 else "падение"
        emoji = "🚀" if info.change_24h > 0 else "📉"

        # Собираем держателей актива и текущую стоимость позиции каждого в $
        holders = await db.get_holders_by_ticker(info.ticker)
        if holders:
            holders_str = ", ".join(
                f"{esc(h['investor_name'])} (${fmt_usd(h['amount'] * info.price_usd)})"
                for h in holders
            )
        else:
            holders_str = "—"

        # Rich-алерт: заголовок-триггер + цитата с ценой и держателями
        html = (
            f"<h3>🚨 {emoji} {esc(info.ticker)}: {direction} {info.change_24h:+.1f}% за 24ч</h3>"
            f"<blockquote>Текущая цена: <b>${fmt_usd(info.price_usd)}</b><br>"
            f"Лежит у: {holders_str}"
            "<cite>Источник: CoinGecko</cite></blockquote>"
        )
        try:
            await send_rich_message(bot, chat_id, html)
            logger.info("Алерт по %s (%+.1f%%) отправлен", info.ticker, info.change_24h)
        except Exception:
            logger.exception("Ошибка при отправке алерта по %s", info.ticker)


def reschedule_report(scheduler: AsyncIOScheduler, hours: int) -> None:
    """Меняет интервал сводного отчета на лету (вызывается из меню настроек)."""
    scheduler.reschedule_job(REPORT_JOB_ID, trigger="interval", hours=hours)
    logger.info("Интервал сводного отчета изменен: каждые %d ч", hours)


async def setup_scheduler(bot: Bot, db: Database, api: CoinGeckoClient,
                          config: Config) -> AsyncIOScheduler:
    """Создает и запускает планировщик с обеими фоновыми задачами."""
    scheduler = AsyncIOScheduler()

    report_hours = int(await db.get_setting("report_freq_hours", "24"))
    scheduler.add_job(
        send_daily_report,
        trigger="interval",
        hours=report_hours,
        id=REPORT_JOB_ID,
        args=(bot, db, api, config),
    )
    scheduler.add_job(
        check_volatility,
        trigger="interval",
        minutes=ALERT_CHECK_MINUTES,
        id=ALERT_JOB_ID,
        args=(bot, db, api, config),
    )

    scheduler.start()
    logger.info("Планировщик запущен: отчет каждые %d ч, проверка волатильности каждые %d мин",
                report_hours, ALERT_CHECK_MINUTES)
    return scheduler
