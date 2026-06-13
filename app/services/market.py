"""Получение цен по текущим позициям без поиска в API.

Тикеры (символы) сопоставляются с точными coin id из сохранённых сделок
(db.get_symbol_coin_map), после чего цены берутся точечно через /coins/markets.
Так мы не зависим от неоднозначного поиска по символу во время запроса.
"""
import dataclasses

from app.database import Database
from app.services.coingecko import CoinGeckoClient, PriceInfo


async def prices_for(db: Database, api: CoinGeckoClient,
                     tickers: list[str]) -> dict[str, PriceInfo]:
    """Возвращает рыночные данные по тикерам, ключ результата — тикер (символ).

    Тикеры без известного coin_id (например, мигрированные из старой схемы)
    в результат не попадают — цена по ним недоступна.
    """
    if not tickers:
        return {}
    symbol_to_id = await db.get_symbol_coin_map()
    wanted = {t: symbol_to_id[t] for t in tickers if t in symbol_to_id}

    # Для тикеров без сохранённого coin_id пробуем однозначное совпадение по кэшу
    missing = [t for t in tickers if t not in wanted]
    if missing:
        wanted.update(await db.resolve_symbols_unique(missing))

    if not wanted:
        return {}

    market = await api.get_market(list(set(wanted.values())))

    result: dict[str, PriceInfo] = {}
    for ticker, coin_id in wanted.items():
        info = market.get(coin_id)
        if info is not None:
            # Подменяем ключ на тикер для отображения
            result[ticker] = dataclasses.replace(info, ticker=ticker)
    return result
