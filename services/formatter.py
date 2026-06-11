from services.coingecko import coingecko


async def build_portfolio_text(investor_name: str, positions: list[dict]) -> str:
    """Формирует текстовую сводку портфеля инвестора с актуальными ценами."""
    if not positions:
        return f"👤 <b>{investor_name}</b>\n\nПортфель пуст."

    tickers = [p["asset_ticker"] for p in positions]
    prices = await coingecko.get_prices(tickers)

    lines: list[str] = [f"👤 <b>{investor_name}</b>\n"]
    total = 0.0

    for pos in positions:
        ticker = pos["asset_ticker"]
        amount = pos["amount"]
        info = prices.get(ticker, {})
        price = info.get("price", 0.0)
        change = info.get("change_24h", 0.0)
        value = price * amount

        change_emoji = "📈" if change >= 0 else "📉"
        change_str = f"{change:+.2f}%"
        error_note = " ⚠️" if "error" in info else ""

        lines.append(
            f"  <b>{ticker}</b>{error_note}: {amount:g} × ${price:,.4f} = <b>${value:,.2f}</b>  "
            f"{change_emoji} {change_str}"
        )
        total += value

    lines.append(f"\n💰 <b>Итого: ${total:,.2f}</b>")
    return "\n".join(lines)


async def build_full_report(all_positions: list[dict]) -> str:
    """Формирует полный отчёт по всем инвесторам."""
    if not all_positions:
        return "📋 Нет данных о портфелях."

    tickers = list({p["asset_ticker"] for p in all_positions})
    prices = await coingecko.get_prices(tickers)

    # Группируем по инвестору
    investors: dict[str, list[dict]] = {}
    for pos in all_positions:
        investors.setdefault(pos["investor_name"], []).append(pos)

    lines: list[str] = ["📋 <b>Общий отчёт по портфелям</b>\n"]
    grand_total = 0.0

    for name, positions in investors.items():
        total = 0.0
        inv_lines: list[str] = []
        for pos in positions:
            ticker = pos["asset_ticker"]
            amount = pos["amount"]
            price = prices.get(ticker, {}).get("price", 0.0)
            value = price * amount
            change = prices.get(ticker, {}).get("change_24h", 0.0)
            change_str = f"{change:+.2f}%"
            inv_lines.append(f"    {ticker}: {amount:g} → <b>${value:,.2f}</b> ({change_str})")
            total += value

        lines.append(f"👤 <b>{name}</b> — ${total:,.2f}")
        lines.extend(inv_lines)
        grand_total += total

    lines.append(f"\n🏦 <b>Суммарно: ${grand_total:,.2f}</b>")
    return "\n".join(lines)


async def build_analytics_top(all_positions: list[dict], top_n: int = 5) -> tuple[str, str]:
    """Возвращает тексты топа роста и топа падения среди уникальных тикеров портфелей."""
    if not all_positions:
        return "Нет данных.", "Нет данных."

    tickers = list({p["asset_ticker"] for p in all_positions})
    prices = await coingecko.get_prices(tickers)

    sorted_by_change = sorted(
        [(t, prices[t]) for t in tickers if t in prices and "error" not in prices[t]],
        key=lambda x: x[1]["change_24h"],
        reverse=True,
    )

    def format_row(ticker: str, info: dict) -> str:
        return (
            f"  <b>{ticker}</b>: ${info['price']:,.4f}  "
            f"({info['change_24h']:+.2f}%)"
        )

    top_growth = sorted_by_change[:top_n]
    top_drop = sorted_by_change[-top_n:][::-1]

    growth_text = "📈 <b>Топ роста за 24ч</b>\n" + (
        "\n".join(format_row(t, i) for t, i in top_growth) if top_growth else "Нет данных."
    )
    drop_text = "📉 <b>Топ падения за 24ч</b>\n" + (
        "\n".join(format_row(t, i) for t, i in top_drop) if top_drop else "Нет данных."
    )
    return growth_text, drop_text
