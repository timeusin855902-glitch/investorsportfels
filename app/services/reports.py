"""Формирование контента в формате Rich Messages (Bot API 10.1).

Все тексты собираются в расширенном rich-HTML: заголовки <h3>, нативные
таблицы <table>, абзацы <p>. Отправляются через app.services.rich
(методы sendRichMessage / editMessageText с rich_message).
"""
import logging

from app.database import Database
from app.services.coingecko import CoinGeckoClient, CoinGeckoError
from app.services.market import prices_for
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
        prices = await prices_for(db, api, tickers)
    except CoinGeckoError as e:
        logger.warning("Ошибка CoinGecko при построении карточки: %s", e)
        prices = {}

    # Считаем стоимость каждой позиции и сортируем по убыванию стоимости.
    # Позиции без доступной цены отправляем в конец списка.
    items: list[tuple[str, float, float | None]] = []  # (тикер, кол-во, стоимость|None)
    for asset in assets:
        info = prices.get(asset["asset_ticker"])
        value = asset["amount"] * info.price_usd if info is not None else None
        items.append((asset["asset_ticker"], asset["amount"], value))
    items.sort(key=lambda x: x[2] if x[2] is not None else float("-inf"), reverse=True)

    # Строки таблицы: Токен | Кол-во | Курс ($) | Всего ($)
    rows: list[list[str]] = []
    total = 0.0
    for ticker, amount, value in items:
        info = prices.get(ticker)
        if info is None or value is None:
            rows.append([ticker, fmt_amount(amount), "—", "—"])
            continue
        total += value
        rows.append([
            ticker,
            fmt_amount(amount),
            fmt_usd(info.price_usd),
            fmt_usd(value),
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
        prices = await prices_for(db, api, tickers)
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
    """Монето-центричный отчёт: монеты по убыванию динамики за 24ч.

    Колонки: Монета | Δ24ч % | Сумма $ (по всем инвесторам) | Инвесторы (доля %).
    В 4-й колонке у каждого инвестора в скобках — его доля в общем количестве
    данного актива среди всех инвесторов.
    """
    holdings = await db.get_all_holdings()

    # Группируем остатки по тикеру: общий объём + список держателей
    per_ticker: dict[str, dict] = {}
    for row in holdings:
        if row["asset_ticker"] is None:
            continue
        bucket = per_ticker.setdefault(
            row["asset_ticker"], {"total_amount": 0.0, "holders": []}
        )
        bucket["total_amount"] += row["amount"]
        bucket["holders"].append((row["investor_name"], row["amount"]))

    if not per_ticker:
        return f"<h3>{esc(title)}</h3><p>В портфелях пока нет активов.</p>"

    try:
        prices = await prices_for(db, api, list(per_ticker))
    except CoinGeckoError as e:
        logger.warning("Ошибка CoinGecko при построении отчёта: %s", e)
        prices = {}

    # Готовим данные строк: (тикер, изменение, стоимость, строка держателей)
    rows_data: list[tuple[str, float | None, float | None, str]] = []
    grand_total = 0.0
    for ticker, bucket in per_ticker.items():
        info = prices.get(ticker)
        change = info.change_24h if info is not None else None
        total_value = bucket["total_amount"] * info.price_usd if info is not None else None
        if total_value is not None:
            grand_total += total_value

        # Держатели по убыванию доли, в скобках — процент от общего количества актива
        holders = sorted(bucket["holders"], key=lambda h: h[1], reverse=True)
        total_amount = bucket["total_amount"]
        holders_str = ", ".join(
            f"{name} ({(amount / total_amount * 100) if total_amount > 0 else 0:.0f}%)"
            for name, amount in holders
        )
        rows_data.append((ticker, change, total_value, holders_str))

    # Сортируем монеты по убыванию динамики за 24ч (монеты без цены — в конец)
    rows_data.sort(
        key=lambda r: r[1] if r[1] is not None else float("-inf"), reverse=True
    )

    table_rows = [
        [
            ticker,
            fmt_change(change) if change is not None else "—",
            fmt_usd(value) if value is not None else "—",
            holders_str,
        ]
        for ticker, change, value, holders_str in rows_data
    ]
    table = render_table(
        ["Монета", "Δ24ч %", "Сумма $", "Инвесторы (доля)"],
        table_rows,
        aligns=["left", "right", "right", "left"],
    )

    return (
        f"<h3>{esc(title)}</h3>"
        + table
        + f"<p>💰 <b>Суммарно по всем активам: {fmt_usd(grand_total)} $</b></p>"
    )


# ---------------------------------------------------------------------------
# Персональный отчёт инвестора (в его форум-тему)
# ---------------------------------------------------------------------------

async def build_personal_report(db: Database, api: CoinGeckoClient, investor_id: int) -> str:
    """Личный отчёт инвестора: Монета | Сумма $ | Δ24ч | Δ7д (без количества монет)."""
    investor = await db.get_investor(investor_id)
    if investor is None:
        return "<p>⚠️ Инвестор не найден.</p>"

    assets = await db.get_portfolio(investor_id)
    header = f"<h3>📈 Отчёт по портфелю: {esc(investor['name'])}</h3>"
    if not assets:
        return f"{header}<p>Портфель пуст.</p>"

    tickers = [a["asset_ticker"] for a in assets]
    try:
        prices = await prices_for(db, api, tickers)
    except CoinGeckoError as e:
        logger.warning("Ошибка CoinGecko при персональном отчёте: %s", e)
        prices = {}

    # Считаем стоимость позиций и сортируем по убыванию динамики за 24ч
    data: list[tuple[str, float | None, float | None, float | None]] = []
    total = 0.0
    for asset in assets:
        info = prices.get(asset["asset_ticker"])
        if info is None:
            data.append((asset["asset_ticker"], None, None, None))
            continue
        value = asset["amount"] * info.price_usd
        total += value
        data.append((asset["asset_ticker"], value, info.change_24h, info.change_7d))

    data.sort(key=lambda r: r[2] if r[2] is not None else float("-inf"), reverse=True)

    rows = [
        [
            ticker,
            fmt_usd(value) if value is not None else "—",
            fmt_change(c24) if c24 is not None else "—",
            fmt_change(c7) if c7 is not None else "—",
        ]
        for ticker, value, c24, c7 in data
    ]
    table = render_table(
        ["Монета", "Сумма $", "Δ24ч", "Δ7д"], rows,
        aligns=["left", "right", "right", "right"],
    )
    return f"{header}{table}<p>💰 <b>Итого: {fmt_usd(total)} $</b></p>"
