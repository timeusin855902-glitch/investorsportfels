"""Фоновые задачи на APScheduler.

1. Сводный отчёт — раз в N часов: общий отчёт в аналитический чат + персональные
   отчёты по каждому инвестору в его форум-тему.
2. Алерты волатильности — каждые 15 минут: при сильном движении монеты алерт
   уходит в аналитический чат и персонально в темы держателей этой монеты.
3. Обновление локального кэша монет CoinGecko — раз в 24 часа.
"""
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Config
from app.database import Database
from app.services.coingecko import CoinGeckoClient, CoinGeckoError
from app.services.market import prices_for
from app.services.reports import build_personal_report, build_summary_report, fmt_usd
from app.services.rich import RichMessageError, create_forum_topic, esc, send_rich_message

logger = logging.getLogger(__name__)

REPORT_JOB_ID = "daily_report"
ALERT_JOB_ID = "volatility_alerts"
COINS_JOB_ID = "coins_refresh"
ALERT_CHECK_MINUTES = 15
COINS_REFRESH_HOURS = 24
ALERT_COOLDOWN = timedelta(hours=4)  # не чаще одного алерта по монете за этот период

# Время последнего алерта по каждой монете (в памяти процесса)
_last_alert_at: dict[str, datetime] = {}


async def _get_analytics_chat_id(db: Database, config: Config) -> int | None:
    """Чат для общих отчётов/алертов: значение из настроек приоритетнее .env."""
    raw = await db.get_setting("analytics_chat_id")
    if raw.strip().lstrip("-").isdigit():
        return int(raw)
    return config.analytics_chat_id


async def _get_forum_chat_id(db: Database) -> int | None:
    """Форум-супергруппа, в которой создаются персональные темы инвесторов."""
    raw = await db.get_setting("forum_chat_id")
    return int(raw) if raw.strip().lstrip("-").isdigit() else None


async def ensure_topic(bot: Bot, db: Database, forum_chat_id: int,
                       investor_id: int, name: str, thread_id) -> int | None:
    """Возвращает id темы инвестора, создавая её при необходимости."""
    if thread_id is not None:
        return int(thread_id)
    try:
        new_id = await create_forum_topic(bot, forum_chat_id, name)
    except RichMessageError as e:
        logger.warning("Не удалось создать тему для инвестора %s: %s", name, e)
        return None
    await db.set_investor_thread(investor_id, new_id)
    logger.info("Создана тема '%s' (thread_id=%s) для инвестора %s", name, new_id, investor_id)
    return new_id


# ---------------------------------------------------------------------------
# Регулярные отчёты
# ---------------------------------------------------------------------------

async def send_daily_report(bot: Bot, db: Database, api: CoinGeckoClient,
                            config: Config) -> None:
    """Общий отчёт в аналитический чат + персональные отчёты в темы инвесторов."""
    chat_id = await _get_analytics_chat_id(db, config)
    if chat_id is not None:
        try:
            html = await build_summary_report(db, api, title="🗞 Регулярный отчёт по портфелям")
            await send_rich_message(bot, chat_id, html)
            logger.info("Сводный отчёт отправлен в чат %s", chat_id)
        except Exception:
            logger.exception("Ошибка при отправке сводного отчёта")

    # Персональные отчёты в форум-темы инвесторов
    forum_chat_id = await _get_forum_chat_id(db)
    if forum_chat_id is None:
        return
    for inv in await db.get_investors():
        thread = await ensure_topic(bot, db, forum_chat_id, inv["id"], inv["name"], inv["thread_id"])
        if thread is None:
            continue
        try:
            html = await build_personal_report(db, api, inv["id"])
            await send_rich_message(bot, forum_chat_id, html, message_thread_id=thread)
        except Exception:
            logger.exception("Ошибка при отправке персонального отчёта инвестору %s", inv["id"])


# ---------------------------------------------------------------------------
# Алерты волатильности
# ---------------------------------------------------------------------------

async def check_volatility(bot: Bot, db: Database, api: CoinGeckoClient,
                           config: Config) -> None:
    """Проверяет изменения цен за 24ч и шлёт алерты при превышении порога."""
    chat_id = await _get_analytics_chat_id(db, config)
    forum_chat_id = await _get_forum_chat_id(db)
    if chat_id is None and forum_chat_id is None:
        return  # некуда слать

    tickers = await db.get_unique_tickers()
    if not tickers:
        return

    try:
        threshold = float(await db.get_setting("alert_threshold", "30"))
        prices = await prices_for(db, api, tickers)
    except (CoinGeckoError, ValueError) as e:
        logger.warning("Проверка волатильности пропущена: %s", e)
        return

    now = datetime.now()
    for ticker, info in prices.items():
        if abs(info.change_24h) < threshold:
            continue
        # Анти-спам: по одной монете не чаще раза в ALERT_COOLDOWN
        last = _last_alert_at.get(ticker)
        if last is not None and now - last < ALERT_COOLDOWN:
            continue
        _last_alert_at[ticker] = now

        direction = "рост" if info.change_24h > 0 else "падение"
        emoji = "🚀" if info.change_24h > 0 else "📉"
        head = f"🚨 {emoji} {esc(ticker)}: {direction} {info.change_24h:+.1f}% за 24ч"
        holders = await db.get_holders_by_ticker(ticker)

        # 1) Общий алерт в аналитический чат — с перечислением держателей
        if chat_id is not None:
            holders_str = ", ".join(
                f"{esc(h['investor_name'])} (${fmt_usd(h['amount'] * info.price_usd)})"
                for h in holders
            ) or "—"
            html = (
                f"<h3>{head}</h3>"
                f"<blockquote>Текущая цена: <b>${fmt_usd(info.price_usd)}</b><br>"
                f"Лежит у: {holders_str}<cite>CoinGecko</cite></blockquote>"
            )
            try:
                await send_rich_message(bot, chat_id, html)
            except Exception:
                logger.exception("Ошибка общего алерта по %s", ticker)

        # 2) Персональные алерты в темы держателей
        if forum_chat_id is not None:
            for h in holders:
                thread = await ensure_topic(
                    bot, db, forum_chat_id, h["investor_id"], h["investor_name"], h["thread_id"]
                )
                if thread is None:
                    continue
                value = h["amount"] * info.price_usd
                html = (
                    f"<h3>{head}</h3>"
                    f"<blockquote>Текущая цена: <b>${fmt_usd(info.price_usd)}</b><br>"
                    f"Ваша позиция: <b>${fmt_usd(value)}</b><cite>CoinGecko</cite></blockquote>"
                )
                try:
                    await send_rich_message(bot, forum_chat_id, html, message_thread_id=thread)
                except Exception:
                    logger.exception("Ошибка персонального алерта инвестору %s", h["investor_id"])

        logger.info("Алерт по %s (%+.1f%%) обработан", ticker, info.change_24h)


# ---------------------------------------------------------------------------
# Обновление кэша монет
# ---------------------------------------------------------------------------

async def refresh_coins(db: Database, api: CoinGeckoClient) -> None:
    """Скачивает список монет CoinGecko и полностью обновляет локальный кэш."""
    try:
        coins = await api.fetch_coins_list()
    except CoinGeckoError as e:
        logger.warning("Не удалось обновить кэш монет: %s", e)
        return
    if coins:
        count = await db.replace_coins(coins)
        logger.info("Кэш монет обновлён: %d монет", count)


def reschedule_report(scheduler: AsyncIOScheduler, hours: int) -> None:
    """Меняет интервал отчётов на лету (вызывается из меню настроек)."""
    scheduler.reschedule_job(REPORT_JOB_ID, trigger="interval", hours=hours)
    logger.info("Интервал отчётов изменён: каждые %d ч", hours)


async def setup_scheduler(bot: Bot, db: Database, api: CoinGeckoClient,
                          config: Config) -> AsyncIOScheduler:
    """Создаёт и запускает планировщик со всеми фоновыми задачами."""
    scheduler = AsyncIOScheduler()
    report_hours = int(await db.get_setting("report_freq_hours", "24"))

    scheduler.add_job(send_daily_report, "interval", hours=report_hours,
                      id=REPORT_JOB_ID, args=(bot, db, api, config))
    scheduler.add_job(check_volatility, "interval", minutes=ALERT_CHECK_MINUTES,
                      id=ALERT_JOB_ID, args=(bot, db, api, config))
    scheduler.add_job(refresh_coins, "interval", hours=COINS_REFRESH_HOURS,
                      id=COINS_JOB_ID, args=(db, api))

    scheduler.start()

    # Первичная загрузка кэша монет, если он пуст (не блокируя запуск при ошибке сети)
    if await db.count_coins() == 0:
        await refresh_coins(db, api)

    logger.info("Планировщик запущен: отчёты каждые %d ч, волатильность каждые %d мин, "
                "кэш монет каждые %d ч", report_hours, ALERT_CHECK_MINUTES, COINS_REFRESH_HOURS)
    return scheduler
