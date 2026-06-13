"""Изолированный асинхронный клиент CoinGecko API.

Поиск монет больше НЕ ходит в API: список монет кэшируется в локальной БД
(таблица coins), а цены запрашиваются точечно по coin id через /coins/markets
(с динамикой за 24ч и 7д). Кэш цен — на PRICE_CACHE_TTL секунд.
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp

logger = logging.getLogger(__name__)

BASE_URL = "https://api.coingecko.com/api/v3"
PRICE_CACHE_TTL = 180          # кэш цен: 3 минуты
MARKETS_PAGE_SIZE = 250        # максимум монет в одном /coins/markets
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


@dataclass
class PriceInfo:
    """Цена монеты и её динамика."""
    ticker: str            # отображаемый ключ (символ или coin id)
    price_usd: float
    change_24h: float      # изменение за 24ч, %
    change_7d: float = 0.0  # изменение за 7д, %


class CoinGeckoError(Exception):
    """Ошибка при обращении к CoinGecko API."""


class CoinGeckoClient:
    def __init__(self, api_key: str = ""):
        self._api_key = api_key
        self._session: aiohttp.ClientSession | None = None
        # Кэш рыночных данных: coin_id -> (PriceInfo, timestamp)
        self._market_cache: dict[str, tuple[PriceInfo, float]] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        """Лениво создаёт aiohttp-сессию (нельзя создавать вне event loop)."""
        if self._session is None or self._session.closed:
            headers = {}
            if self._api_key:
                headers["x-cg-demo-api-key"] = self._api_key
            self._session = aiohttp.ClientSession(headers=headers, timeout=REQUEST_TIMEOUT)
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _request(self, path: str, params: dict):
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

    # ---------- Список монет (для локального кэша) ----------

    async def fetch_coins_list(self) -> list[tuple[str, str, str]]:
        """Скачивает полный список монет и оставляет только (id, symbol, name).

        Возвращает список кортежей (coin_id, symbol_lower, name). Прочие
        метаданные отбрасываются для экономии памяти.
        """
        data = await self._request("/coins/list", {})
        coins: list[tuple[str, str, str]] = []
        for item in data:
            coin_id = item.get("id")
            symbol = item.get("symbol")
            name = item.get("name")
            if coin_id and symbol and name:
                coins.append((coin_id, symbol.lower(), name))
        return coins

    # ---------- Цены по coin id ----------

    async def get_market(self, coin_ids: list[str]) -> dict[str, PriceInfo]:
        """Возвращает рыночные данные по списку coin id (цена + динамика 24ч/7д).

        Свежие значения берутся из кэша; недостающие догружаются батчами
        через /coins/markets. Ключ результата — coin id.
        """
        coin_ids = list(dict.fromkeys(coin_ids))  # уникализируем, сохраняя порядок
        now = time.monotonic()
        result: dict[str, PriceInfo] = {}
        stale: list[str] = []
        for cid in coin_ids:
            cached = self._market_cache.get(cid)
            if cached is not None and now - cached[1] < PRICE_CACHE_TTL:
                result[cid] = cached[0]
            else:
                stale.append(cid)

        # Догружаем недостающие батчами по MARKETS_PAGE_SIZE
        for i in range(0, len(stale), MARKETS_PAGE_SIZE):
            batch = stale[i:i + MARKETS_PAGE_SIZE]
            data = await self._request(
                "/coins/markets",
                {
                    "vs_currency": "usd",
                    "ids": ",".join(batch),
                    "per_page": str(MARKETS_PAGE_SIZE),
                    "page": "1",
                    "price_change_percentage": "24h,7d",
                },
            )
            for item in data:
                cid = item.get("id")
                price = item.get("current_price")
                if cid is None or price is None:
                    continue
                info = PriceInfo(
                    ticker=cid,
                    price_usd=float(price),
                    change_24h=float(item.get("price_change_percentage_24h_in_currency") or 0.0),
                    change_7d=float(item.get("price_change_percentage_7d_in_currency") or 0.0),
                )
                self._market_cache[cid] = (info, now)
                result[cid] = info

        return result

    async def find_date_for_price(self, coin_id: str, target_price: float) -> str | None:
        """Находит ПОСЛЕДНЮЮ дату за год, когда монета стоила примерно target_price.

        Берёт график цен за 365 дней (/coins/{id}/market_chart) и выбирает точку
        с минимальным отклонением; при равном отклонении — более позднюю.
        Возвращает дату ДД.ММ.ГГГГ или None.
        """
        if not coin_id:
            return None
        data = await self._request(
            f"/coins/{coin_id}/market_chart",
            {"vs_currency": "usd", "days": "365"},
        )
        prices = data.get("prices", [])
        if not prices:
            return None
        best_ts = None
        best_diff = float("inf")
        for ts, price in prices:
            diff = abs(price - target_price)
            if diff <= best_diff:  # <= даёт более позднюю точку при равенстве
                best_diff = diff
                best_ts = ts
        dt = datetime.fromtimestamp(best_ts / 1000, tz=timezone.utc)
        return dt.strftime("%d.%m.%Y")
