"""Изолированный асинхронный клиент CoinGecko API с кэшированием.

Особенности:
    - Резолвинг тикера (BTC) в coin id CoinGecko (bitcoin) через /search,
      результат кэшируется навсегда (на время жизни процесса).
    - Цены и изменение за 24ч запрашиваются батчем через /simple/price
      и кэшируются на PRICE_CACHE_TTL секунд, чтобы не упираться в rate limit
      при частой навигации по меню.
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp

logger = logging.getLogger(__name__)

BASE_URL = "https://api.coingecko.com/api/v3"
PRICE_CACHE_TTL = 180  # кэш цен: 3 минуты
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)


@dataclass
class PriceInfo:
    """Цена монеты и ее динамика за 24 часа."""
    ticker: str
    price_usd: float
    change_24h: float  # в процентах, например +5.2 или -12.7


class CoinGeckoError(Exception):
    """Ошибка при обращении к CoinGecko API."""


class CoinGeckoClient:
    def __init__(self, api_key: str = ""):
        self._api_key = api_key
        self._session: aiohttp.ClientSession | None = None
        # Кэш соответствия тикер -> coin id (например, "BTC" -> "bitcoin")
        self._id_cache: dict[str, str] = {}
        # Кэш цен: тикер -> (PriceInfo, timestamp)
        self._price_cache: dict[str, tuple[PriceInfo, float]] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        """Лениво создает aiohttp-сессию (нельзя создавать вне event loop)."""
        if self._session is None or self._session.closed:
            headers = {}
            if self._api_key:
                # Заголовок для бесплатного Demo-плана CoinGecko
                headers["x-cg-demo-api-key"] = self._api_key
            self._session = aiohttp.ClientSession(headers=headers, timeout=REQUEST_TIMEOUT)
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _request(self, path: str, params: dict) -> dict:
        """GET-запрос к API с обработкой ошибок и rate limit."""
        session = await self._get_session()
        try:
            async with session.get(f"{BASE_URL}{path}", params=params) as resp:
                if resp.status == 429:
                    raise CoinGeckoError("Превышен лимит запросов CoinGecko, попробуйте позже")
                if resp.status != 200:
                    raise CoinGeckoError(f"CoinGecko вернул статус {resp.status}")
                return await resp.json()
        except aiohttp.ClientError as e:
            raise CoinGeckoError(f"Сетевая ошибка при запросе к CoinGecko: {e}") from e

    async def resolve_ticker(self, ticker: str) -> str | None:
        """Преобразует тикер (BTC) в coin id (bitcoin).

        Использует /search: результаты отсортированы по капитализации,
        поэтому при совпадении символов берется самая крупная монета.
        Возвращает None, если монета не найдена.
        """
        ticker = ticker.upper().strip()
        if ticker in self._id_cache:
            return self._id_cache[ticker]

        data = await self._request("/search", {"query": ticker})
        coins = data.get("coins", [])
        # Сначала ищем точное совпадение символа, иначе монета не найдена
        for coin in coins:
            if coin.get("symbol", "").upper() == ticker:
                self._id_cache[ticker] = coin["id"]
                return coin["id"]
        return None

    async def find_date_for_price(self, ticker: str, target_price: float) -> str | None:
        """Находит ПОСЛЕДНЮЮ дату за год, когда монета стоила примерно target_price.

        Берет график цен за 365 дней (/coins/{id}/market_chart) и выбирает точку
        с минимальным отклонением от целевой цены; при равном отклонении —
        более позднюю (список отсортирован по времени по возрастанию).
        Возвращает дату в формате ДД.ММ.ГГГГ или None, если данных нет.
        """
        coin_id = await self.resolve_ticker(ticker)
        if not coin_id:
            return None

        data = await self._request(
            f"/coins/{coin_id}/market_chart",
            {"vs_currency": "usd", "days": "365"},
        )
        prices = data.get("prices", [])  # список пар [timestamp_ms, price]
        if not prices:
            return None

        best_ts = None
        best_diff = float("inf")
        for ts, price in prices:
            diff = abs(price - target_price)
            # <= гарантирует выбор более поздней точки при равном отклонении
            if diff <= best_diff:
                best_diff = diff
                best_ts = ts

        dt = datetime.fromtimestamp(best_ts / 1000, tz=timezone.utc)
        return dt.strftime("%d.%m.%Y")

    async def get_prices(self, tickers: list[str]) -> dict[str, PriceInfo]:
        """Возвращает цены и динамику 24ч для списка тикеров.

        Свежие значения берутся из кэша; недостающие запрашиваются
        одним батч-запросом к /simple/price.
        """
        tickers = [t.upper() for t in tickers]
        now = time.monotonic()
        result: dict[str, PriceInfo] = {}
        stale: list[str] = []

        # Раздаем то, что есть в кэше и не протухло
        for ticker in tickers:
            cached = self._price_cache.get(ticker)
            if cached is not None and now - cached[1] < PRICE_CACHE_TTL:
                result[ticker] = cached[0]
            else:
                stale.append(ticker)

        if not stale:
            return result

        # Резолвим тикеры в coin id (нерезолвящиеся тикеры просто пропускаем)
        ticker_to_id: dict[str, str] = {}
        for ticker in stale:
            try:
                coin_id = await self.resolve_ticker(ticker)
            except CoinGeckoError:
                logger.warning("Не удалось зарезолвить тикер %s", ticker)
                continue
            if coin_id:
                ticker_to_id[ticker] = coin_id

        if not ticker_to_id:
            return result

        data = await self._request(
            "/simple/price",
            {
                "ids": ",".join(ticker_to_id.values()),
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
        )

        for ticker, coin_id in ticker_to_id.items():
            coin_data = data.get(coin_id)
            if not coin_data or "usd" not in coin_data:
                continue
            info = PriceInfo(
                ticker=ticker,
                price_usd=float(coin_data["usd"]),
                change_24h=float(coin_data.get("usd_24h_change") or 0.0),
            )
            self._price_cache[ticker] = (info, now)
            result[ticker] = info

        return result
