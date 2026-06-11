import time
import asyncio
import aiohttp
from config import COINGECKO_API_KEY, PRICE_CACHE_TTL

# Маппинг тикеров → CoinGecko ID (расширяй по необходимости)
TICKER_TO_ID: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "TRX": "tron",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LTC": "litecoin",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "XLM": "stellar",
    "ETC": "ethereum-classic",
    "ZEC": "zcash",
    "DASH": "dash",
    "NEAR": "near",
    "FTM": "fantom",
    "ALGO": "algorand",
    "VET": "vechain",
    "ICP": "internet-computer",
    "FIL": "filecoin",
    "SAND": "the-sandbox",
    "MANA": "decentraland",
    "AAVE": "aave",
    "CRO": "crypto-com-chain",
    "SHIB": "shiba-inu",
    "TON": "the-open-network",
    "ARB": "arbitrum",
    "OP": "optimism",
    "SUI": "sui",
    "APT": "aptos",
    "INJ": "injective-protocol",
    "SEI": "sei-network",
    "WLD": "worldcoin-wld",
    "PEPE": "pepe",
    "FLOKI": "floki",
    "BONK": "bonk",
    "JUP": "jupiter-exchange-solana",
    "W": "wormhole",
    "ENA": "ethena",
    "EIGEN": "eigenlayer",
}

BASE_URL = "https://api.coingecko.com/api/v3"
PRO_BASE_URL = "https://pro-api.coingecko.com/api/v3"


class PriceCache:
    """Простой in-memory кэш с TTL."""

    def __init__(self, ttl: int = PRICE_CACHE_TTL):
        self._ttl = ttl
        self._data: dict[str, tuple[dict, float]] = {}  # key → (data, timestamp)
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> dict | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry and time.monotonic() - entry[1] < self._ttl:
                return entry[0]
            return None

    async def set(self, key: str, value: dict) -> None:
        async with self._lock:
            self._data[key] = (value, time.monotonic())

    async def invalidate(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)


class CoinGeckoService:
    """Асинхронный клиент CoinGecko с кэшированием."""

    def __init__(self):
        self._cache = PriceCache()
        self._session: aiohttp.ClientSession | None = None

    def _base(self) -> str:
        return PRO_BASE_URL if COINGECKO_API_KEY else BASE_URL

    def _headers(self) -> dict:
        if COINGECKO_API_KEY:
            return {"x-cg-pro-api-key": COINGECKO_API_KEY}
        return {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers())
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def ticker_to_id(self, ticker: str) -> str | None:
        return TICKER_TO_ID.get(ticker.upper())

    async def get_prices(self, tickers: list[str]) -> dict[str, dict]:
        """
        Возвращает словарь {ticker: {price, change_24h}} для списка тикеров.
        Использует кэш; запрос к API делается только для тикеров с устаревшим кэшем.
        """
        result: dict[str, dict] = {}
        missing_ids: list[str] = []
        id_to_ticker: dict[str, str] = {}

        for ticker in tickers:
            cached = await self._cache.get(ticker.upper())
            if cached:
                result[ticker.upper()] = cached
            else:
                cg_id = self.ticker_to_id(ticker)
                if cg_id:
                    missing_ids.append(cg_id)
                    id_to_ticker[cg_id] = ticker.upper()
                else:
                    result[ticker.upper()] = {"price": 0.0, "change_24h": 0.0, "error": "unknown"}

        if missing_ids:
            fetched = await self._fetch_prices(missing_ids)
            for cg_id, data in fetched.items():
                ticker = id_to_ticker.get(cg_id, cg_id)
                result[ticker] = data
                await self._cache.set(ticker, data)

        return result

    async def _fetch_prices(self, coin_ids: list[str]) -> dict[str, dict]:
        """Делает один запрос к /simple/price для списка ID."""
        url = f"{self._base()}/simple/price"
        params = {
            "ids": ",".join(coin_ids),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        }
        try:
            session = await self._get_session()
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                raw: dict = await resp.json()
        except Exception as exc:
            # При ошибке возвращаем нули для всех запрошенных монет
            return {cid: {"price": 0.0, "change_24h": 0.0, "error": str(exc)} for cid in coin_ids}

        result: dict[str, dict] = {}
        for cid in coin_ids:
            entry = raw.get(cid, {})
            result[cid] = {
                "price": entry.get("usd", 0.0),
                "change_24h": entry.get("usd_24h_change", 0.0),
            }
        return result


# Глобальный экземпляр сервиса
coingecko = CoinGeckoService()
