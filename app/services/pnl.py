"""Расчёт прибыли/убытка (P&L) и сборка rich-таблиц для раздела «Прибыль/Убыток».

Модель расчёта по каждому активу:
    avg_buy     = сумма(цена×кол-во покупок) / сумма(кол-во покупок)   — средняя цена входа
    remaining   = куплено − продано                                    — текущий остаток
    realized    = выручка с продаж − avg_buy × проданное_кол-во        — реализованный P&L
    unrealized  = (текущая_цена − avg_buy) × remaining                 — нереализованный P&L

Если средняя цена входа неизвестна (avg_buy = 0, например после миграции
старых данных) — P&L по позиции помечается как «н/д».
"""
import logging
from dataclasses import dataclass, field

from app.database import Database
from app.database.db import EPS
from app.services.coingecko import CoinGeckoClient, CoinGeckoError
from app.services.reports import fmt_change, fmt_usd
from app.services.rich import esc, render_table

logger = logging.getLogger(__name__)


@dataclass
class AssetPnL:
    """Сводка P&L по одному активу инвестора."""
    ticker: str
    avg_buy: float
    remaining: float
    realized: float
    unrealized: float
    current_price: float | None
    has_cost: bool  # известна ли цена входа (avg_buy > 0)

    @property
    def total(self) -> float:
        return self.realized + self.unrealized

    @property
    def unrealized_pct(self) -> float | None:
        """Процент изменения открытой позиции относительно цены входа."""
        if not self.has_cost or self.current_price is None:
            return None
        return (self.current_price / self.avg_buy - 1) * 100


@dataclass
class InvestorPnL:
    """Агрегированный P&L по инвестору."""
    assets: list[AssetPnL] = field(default_factory=list)

    @property
    def realized(self) -> float:
        return sum(a.realized for a in self.assets)

    @property
    def unrealized(self) -> float:
        return sum(a.unrealized for a in self.assets)

    @property
    def total(self) -> float:
        return self.realized + self.unrealized


def _aggregate(transactions, prices) -> InvestorPnL:
    """Сворачивает список сделок инвестора в P&L по каждому активу."""
    # Группируем сделки по тикеру
    by_ticker: dict[str, dict[str, float]] = {}
    for tx in transactions:
        if tx["asset_ticker"] is None:
            continue
        agg = by_ticker.setdefault(
            tx["asset_ticker"],
            {"buy_qty": 0.0, "buy_cost": 0.0, "sell_qty": 0.0, "sell_rev": 0.0},
        )
        if tx["kind"] == "buy":
            agg["buy_qty"] += tx["amount"]
            agg["buy_cost"] += tx["price"] * tx["amount"]
        else:
            agg["sell_qty"] += tx["amount"]
            agg["sell_rev"] += tx["price"] * tx["amount"]

    result = InvestorPnL()
    for ticker, agg in sorted(by_ticker.items()):
        avg_buy = agg["buy_cost"] / agg["buy_qty"] if agg["buy_qty"] > EPS else 0.0
        has_cost = avg_buy > 0
        remaining = agg["buy_qty"] - agg["sell_qty"]
        realized = agg["sell_rev"] - avg_buy * agg["sell_qty"] if has_cost else 0.0

        info = prices.get(ticker)
        current_price = info.price_usd if info is not None else None
        if has_cost and current_price is not None and remaining > EPS:
            unrealized = (current_price - avg_buy) * remaining
        else:
            unrealized = 0.0

        result.assets.append(AssetPnL(
            ticker=ticker, avg_buy=avg_buy, remaining=max(remaining, 0.0),
            realized=realized, unrealized=unrealized,
            current_price=current_price, has_cost=has_cost,
        ))
    return result


async def build_investor_pnl(db: Database, api: CoinGeckoClient, investor_id: int) -> str:
    """Rich-таблица P&L по каждому активу конкретного инвестора + итог."""
    investor = await db.get_investor(investor_id)
    if investor is None:
        return "<p>⚠️ Инвестор не найден.</p>"

    transactions = await db.get_transactions(investor_id)
    if not transactions:
        return (f"<h3>💹 P&amp;L: {esc(investor['name'])}</h3>"
                "<p>Нет ни одной сделки. Добавьте активы с ценой входа.</p>")

    tickers = list({t["asset_ticker"] for t in transactions})
    try:
        prices = await api.get_prices(tickers)
    except CoinGeckoError as e:
        logger.warning("Ошибка CoinGecko при расчёте P&L: %s", e)
        prices = {}

    pnl = _aggregate(transactions, prices)

    # Таблица: Токен | Ср.вход | Остаток | Тек.цена | P&L % | P&L $
    rows: list[list[str]] = []
    for a in pnl.assets:
        if not a.has_cost:
            rows.append([a.ticker, "н/д", _q(a.remaining), "—", "н/д", "н/д"])
            continue
        price_str = fmt_usd(a.current_price) if a.current_price is not None else "—"
        pct = a.unrealized_pct
        pct_str = fmt_change(pct) if pct is not None else "—"
        rows.append([
            a.ticker,
            fmt_usd(a.avg_buy),
            _q(a.remaining),
            price_str,
            pct_str,
            _pnl(a.total),
        ])

    table = render_table(
        ["Токен", "Ср.вход", "Остаток", "Тек.цена", "P&L %", "P&L $"],
        rows,
    )

    parts = [
        f"<h3>💹 P&amp;L: {esc(investor['name'])}</h3>",
        table,
        f"<p>✅ Реализованный: <b>{_pnl(pnl.realized)}</b></p>",
        f"<p>📊 Нереализованный: <b>{_pnl(pnl.unrealized)}</b></p>",
        f"<p>💰 <b>Итого P&amp;L: {_pnl(pnl.total)}</b></p>",
    ]
    return "".join(parts)


async def build_pnl_summary(db: Database, api: CoinGeckoClient) -> str:
    """Сводная rich-таблица P&L по всем инвесторам (раздел «Прибыль/Убыток»)."""
    rows_tx = await db.get_all_transactions()
    if not rows_tx:
        return "<p>Инвесторы пока не добавлены.</p>"

    # Группируем сделки по инвестору
    by_investor: dict[str, list] = {}
    tickers: set[str] = set()
    for row in rows_tx:
        by_investor.setdefault(row["investor_name"], [])
        if row["asset_ticker"] is not None:
            by_investor[row["investor_name"]].append(row)
            tickers.add(row["asset_ticker"])

    prices = {}
    if tickers:
        try:
            prices = await api.get_prices(list(tickers))
        except CoinGeckoError as e:
            logger.warning("Ошибка CoinGecko при сводном P&L: %s", e)

    rows: list[list[str]] = []
    grand_total = 0.0
    for name, txs in by_investor.items():
        pnl = _aggregate(txs, prices)
        grand_total += pnl.total
        rows.append([name, _pnl(pnl.realized), _pnl(pnl.unrealized), _pnl(pnl.total)])

    table = render_table(
        ["Инвестор", "Реализ.", "Нереализ.", "Итого"],
        rows,
    )
    return (
        "<h3>💹 Прибыль/Убыток — сводка</h3>"
        + table
        + f"<p>💰 <b>Суммарный P&amp;L: {_pnl(grand_total)}</b></p>"
        + "<p>👇 Выберите инвестора для детализации по активам.</p>"
    )


# ---------------------------------------------------------------------------
# Локальные форматтеры
# ---------------------------------------------------------------------------

def _pnl(value: float) -> str:
    """P&L со знаком и маркером направления, например «+1,250.00 $»."""
    sign = "+" if value >= 0 else "-"
    return f"{sign}{fmt_usd(abs(value))} $"


def _q(value: float) -> str:
    """Количество монет без хвостовых нулей."""
    return f"{value:,.8f}".rstrip("0").rstrip(".")
