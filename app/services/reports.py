"""Формирование контента в формате Rich Messages (Bot API 10.1).

Все тексты собираются в расширенном rich-HTML: заголовки <h3>, нативные
таблицы <table>, абзацы <p>. Отправляются через app.services.rich
(методы sendRichMessage / editMessageText с rich_message).
"""
import logging

from app.database import Database
from app.services.coingecko import CoinGeckoClient, CoinGeckoError
from app.services.rich import esc, render_table

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Форматтеры значений (без символа $ — он добавляется в подписи колонок/итогов)
# ---------------------------------------------------------------------------

def fmt_usd(value: float) -> str:
    """Сумма в долларах: крупные — 2 знака, мелкие — до 6."""
    if value >= 1 or value == 0:
        return f"{value:,.2f}"
    return f"{value:.6f}"


def fmt_amount(value: float) -> str:
    """Количество монет без хвостовых нулей."""
    return f"{value:,.8f}".rstrip("0").rstrip(".")


def fmt_change(change: float) -> str:
    """Изменение за 24ч со знаком, например «+4.20%» или «-1.50%»."""
    return f"{change:+.2f}%"


# ---------------------------------------------------------------------------
# Карточка инвестора
# ---------------------------------------------------------------------------

async def build_investor_card(db: Database, api: CoinGeckoClient, investor_id: int) -> str:
    """Rich-карточка инвестора: заголовок + таблица активов + итоговый баланс."""
    investor = await db.get_investor(investor_id)
    if investor is None:
        return "<p>⚠️ Инвестор не найден (возможно, был удалён).</p>"

    assets = await db.get_portfolio(investor_id)
    header = f"<h3>📊 Портфель инвестора: {esc(investor['name'])}</h3>"

    if not assets:
        return f"{header}<p>Портфель пуст. Добавьте первый актив 👇</p>"

    tickers = [a["asset_ticker"] for a in assets]
    try:
        prices = await api.get_prices(tickers)
    except CoinGeckoError as e:
        logger.warning("Ошибка CoinGecko при построении карточки: %s", e)
        prices = {}

    # Строки таблицы: Токен | Кол-во | Курс ($) | Всего ($)
    rows: list[list[str]] = []
    total = 0.0
    for asset in assets:
        ticker, amount = asset["asset_ticker"], asset["amount"]
        info = prices.get(ticker)
        if info is None:
            rows.append([ticker, fmt_amount(amount), "—", "—"])
            continue
        position_value = amount * info.price_usd
        total += position_value
        rows.append([
            ticker,
            fmt_amount(amount),
            fmt_usd(info.price_usd),
            fmt_usd(position_value),
        ])

    table = render_table(["Токен", "Кол-во", "Курс ($)", "Всего ($)"], rows)

    parts = [header, table, f"<p>💰 <b>Общий баланс: {fmt_usd(total)} $</b></p>"]
    if len(prices) < len(tickers):
        parts.append("<p>⚠️ Часть цен недоступна, баланс может быть неполным.</p>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Топ роста / падения
# ---------------------------------------------------------------------------

async def build_top_movers(db: Database, api: CoinGeckoClient, gainers: bool) -> str:
    """Rich-таблица топа роста (gainers=True) или падения за 24ч."""
    tickers = await db.get_unique_tickers()
    if not tickers:
        return "<p>В портфелях пока нет ни одной монеты.</p>"

    try:
        prices = await api.get_prices(tickers)
    except CoinGeckoError as e:
        return f"<p>⚠️ Не удалось получить данные: {esc(e)}</p>"

    if not prices:
        return "<p>⚠️ Не удалось получить цены ни по одной монете.</p>"

    movers = sorted(prices.values(), key=lambda p: p.change_24h, reverse=gainers)[:10]
    title = "📈 Топ роста за 24ч" if gainers else "📉 Топ падения за 24ч"

    rows = [
        [info.ticker, fmt_change(info.change_24h), fmt_usd(info.price_usd)]
        for info in movers
    ]
    table = render_table(["Токен", "Изм. 24ч", "Курс ($)"], rows)
    return f"<h3>{title}</h3>{table}"


# ---------------------------------------------------------------------------
# Сводный отчёт по всем инвесторам
# ---------------------------------------------------------------------------

async def build_summary_report(
    db: Database, api: CoinGeckoClient, title: str = "📋 Общий отчёт"
) -> str:
    """Rich-сводка: таблица Инвестор | Баланс ($) | Изм. 24ч (%) + общий итог."""
    holdings = await db.get_all_holdings()
    if not holdings:
        return "<p>Инвесторы пока не добавлены.</p>"

    tickers = list({h["asset_ticker"] for h in holdings if h["asset_ticker"]})
    prices = {}
    if tickers:
        try:
            prices = await api.get_prices(tickers)
        except CoinGeckoError as e:
            logger.warning("Ошибка CoinGecko при построении сводки: %s", e)

    # Агрегируем балансы по инвесторам (порядок dict == ORDER BY name из SQL)
    agg: dict[str, dict[str, float]] = {}
    grand_total = 0.0
    grand_total_yesterday = 0.0

    for row in holdings:
        stats = agg.setdefault(row["investor_name"], {"total": 0.0, "yesterday": 0.0})
        if row["asset_ticker"] is None:
            continue  # инвестор без активов — попадёт в таблицу с нулевым балансом
        info = prices.get(row["asset_ticker"])
        if info is None:
            continue  # цена недоступна — позицию не учитываем
        value = row["amount"] * info.price_usd
        stats["total"] += value
        grand_total += value
        # Стоимость сутки назад восстанавливаем из текущей цены и изменения за 24ч
        if info.change_24h > -100:
            yesterday = value / (1 + info.change_24h / 100)
            stats["yesterday"] += yesterday
            grand_total_yesterday += yesterday

    rows: list[list[str]] = []
    for name, stats in agg.items():
        if stats["yesterday"] > 0:
            change_str = fmt_change((stats["total"] / stats["yesterday"] - 1) * 100)
        else:
            change_str = "—"
        rows.append([name, fmt_usd(stats["total"]), change_str])

    table = render_table(["Инвестор", "Баланс ($)", "Изм. 24ч (%)"], rows)

    parts = [f"<h3>{esc(title)}</h3>", table,
             f"<p>💰 <b>Суммарный баланс: {fmt_usd(grand_total)} $</b></p>"]
    if grand_total_yesterday > 0:
        day_change = (grand_total / grand_total_yesterday - 1) * 100
        parts.append(f"<p>📊 <b>Динамика за 24ч: {fmt_change(day_change)}</b></p>")
    return "".join(parts)
