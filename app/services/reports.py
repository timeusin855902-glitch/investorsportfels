"""Формирование текстов: карточка инвестора, сводные отчеты, топы роста/падения."""
import logging

from app.database import Database
from app.services.coingecko import CoinGeckoClient, CoinGeckoError

logger = logging.getLogger(__name__)


def fmt_usd(value: float) -> str:
    """Форматирует сумму в долларах: крупные — 2 знака, мелкие — до 6."""
    if value >= 1:
        return f"${value:,.2f}"
    return f"${value:.6f}"


def fmt_amount(value: float) -> str:
    """Форматирует количество монет без лишних нулей."""
    return f"{value:,.8f}".rstrip("0").rstrip(".")


def fmt_change(change: float) -> str:
    """Форматирует изменение за 24ч со знаком и эмодзи-направлением."""
    arrow = "🟢" if change >= 0 else "🔴"
    return f"{arrow} {change:+.2f}%"


async def build_investor_card(db: Database, api: CoinGeckoClient, investor_id: int) -> str:
    """Текст карточки инвестора: активы, цены, стоимость позиций и общий баланс."""
    investor = await db.get_investor(investor_id)
    if investor is None:
        return "⚠️ Инвестор не найден (возможно, был удален)."

    assets = await db.get_portfolio(investor_id)
    lines = [f"👤 <b>{investor['name']}</b>\n"]

    if not assets:
        lines.append("Портфель пуст. Добавьте первый актив 👇")
        return "\n".join(lines)

    tickers = [a["asset_ticker"] for a in assets]
    try:
        prices = await api.get_prices(tickers)
    except CoinGeckoError as e:
        logger.warning("Ошибка CoinGecko при построении карточки: %s", e)
        prices = {}

    total = 0.0
    for asset in assets:
        ticker, amount = asset["asset_ticker"], asset["amount"]
        info = prices.get(ticker)
        if info is None:
            lines.append(f"• <b>{ticker}</b> — {fmt_amount(amount)} шт (цена недоступна)")
            continue
        position_value = amount * info.price_usd
        total += position_value
        lines.append(
            f"• <b>{ticker}</b> — {fmt_amount(amount)} шт × {fmt_usd(info.price_usd)} "
            f"= <b>{fmt_usd(position_value)}</b> ({fmt_change(info.change_24h)})"
        )

    lines.append(f"\n💰 <b>Общий баланс: {fmt_usd(total)}</b>")
    if len(prices) < len(tickers):
        lines.append("\n⚠️ Часть цен недоступна, баланс может быть неполным.")
    return "\n".join(lines)


async def build_top_movers(db: Database, api: CoinGeckoClient, gainers: bool) -> str:
    """Топ роста (gainers=True) или падения (gainers=False) за 24ч по монетам из портфелей."""
    tickers = await db.get_unique_tickers()
    if not tickers:
        return "В портфелях пока нет ни одной монеты."

    try:
        prices = await api.get_prices(tickers)
    except CoinGeckoError as e:
        return f"⚠️ Не удалось получить данные: {e}"

    if not prices:
        return "⚠️ Не удалось получить цены ни по одной монете."

    # Сортируем по изменению за 24ч в нужном направлении
    movers = sorted(prices.values(), key=lambda p: p.change_24h, reverse=gainers)
    title = "📈 <b>Топ роста за 24ч</b>" if gainers else "📉 <b>Топ падения за 24ч</b>"
    lines = [title + "\n"]
    for i, info in enumerate(movers[:10], start=1):
        lines.append(
            f"{i}. <b>{info.ticker}</b>: {fmt_change(info.change_24h)} — {fmt_usd(info.price_usd)}"
        )
    return "\n".join(lines)


async def build_summary_report(db: Database, api: CoinGeckoClient, title: str = "📋 <b>Общий отчет</b>") -> str:
    """Сводка по всем инвесторам: состав портфелей, балансы, динамика за день."""
    holdings = await db.get_all_holdings()
    if not holdings:
        return "Инвесторы пока не добавлены."

    tickers = list({h["asset_ticker"] for h in holdings if h["asset_ticker"]})
    prices = {}
    if tickers:
        try:
            prices = await api.get_prices(tickers)
        except CoinGeckoError as e:
            logger.warning("Ошибка CoinGecko при построении сводки: %s", e)

    lines = [title + "\n"]
    grand_total = 0.0
    grand_total_yesterday = 0.0
    current_investor = None

    for row in holdings:
        if row["investor_name"] != current_investor:
            # Начинается блок нового инвестора
            current_investor = row["investor_name"]
            lines.append(f"\n👤 <b>{current_investor}</b>")

        if row["asset_ticker"] is None:
            lines.append("   — портфель пуст")
            continue

        info = prices.get(row["asset_ticker"])
        if info is None:
            lines.append(f"   • {row['asset_ticker']}: {fmt_amount(row['amount'])} шт (цена недоступна)")
            continue

        value = row["amount"] * info.price_usd
        grand_total += value
        # Восстанавливаем стоимость сутки назад из текущей цены и изменения за 24ч
        if info.change_24h > -100:
            grand_total_yesterday += value / (1 + info.change_24h / 100)
        lines.append(
            f"   • {row['asset_ticker']}: {fmt_amount(row['amount'])} шт = "
            f"{fmt_usd(value)} ({fmt_change(info.change_24h)})"
        )

    lines.append(f"\n💰 <b>Суммарный баланс: {fmt_usd(grand_total)}</b>")
    if grand_total_yesterday > 0:
        day_change = (grand_total / grand_total_yesterday - 1) * 100
        lines.append(f"📊 Динамика за 24ч: {fmt_change(day_change)}")
    return "\n".join(lines)
