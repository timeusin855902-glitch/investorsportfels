import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
COINGECKO_API_KEY: str = os.getenv("COINGECKO_API_KEY", "")
ANALYTICS_CHAT_ID: int = int(os.getenv("ANALYTICS_CHAT_ID", "0"))

# Список разрешённых пользователей (ID через запятую в .env)
_raw_users = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS: set[int] = {int(uid.strip()) for uid in _raw_users.split(",") if uid.strip()}

# Настройки по умолчанию
DEFAULT_VOLATILITY_THRESHOLD: float = 30.0  # % для алертов
DEFAULT_REPORT_HOUR: int = 9               # час отправки ежедневного отчёта (UTC)
DEFAULT_REPORT_MINUTE: int = 0

# Интервал проверки волатильности (минуты)
VOLATILITY_CHECK_INTERVAL: int = 20

# Время кэширования цен CoinGecko (секунды)
PRICE_CACHE_TTL: int = 120
