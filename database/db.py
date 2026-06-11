import aiosqlite
from config import DEFAULT_VOLATILITY_THRESHOLD, DEFAULT_REPORT_HOUR, DEFAULT_REPORT_MINUTE

DB_PATH = "portfolio.db"


async def init_db() -> None:
    """Инициализация БД и создание таблиц при первом запуске."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS investors (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS portfolios (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                investor_id    INTEGER NOT NULL REFERENCES investors(id) ON DELETE CASCADE,
                asset_ticker   TEXT    NOT NULL,
                amount         REAL    NOT NULL DEFAULT 0,
                UNIQUE(investor_id, asset_ticker)
            )
        """)

        # Таблица настроек хранит пары ключ-значение
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Вставляем дефолтные настройки, если их ещё нет
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("volatility_threshold", str(DEFAULT_VOLATILITY_THRESHOLD)),
        )
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("report_hour", str(DEFAULT_REPORT_HOUR)),
        )
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("report_minute", str(DEFAULT_REPORT_MINUTE)),
        )

        await db.commit()


# ---------------------------------------------------------------------------
# Helpers — настройки
# ---------------------------------------------------------------------------

async def get_setting(key: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Helpers — инвесторы
# ---------------------------------------------------------------------------

async def get_all_investors() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, name FROM investors ORDER BY name") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def add_investor(name: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT INTO investors (name) VALUES (?)", (name,))
        await db.commit()
        return cur.lastrowid


async def delete_investor(investor_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM investors WHERE id = ?", (investor_id,))
        await db.commit()


async def get_investor(investor_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, name FROM investors WHERE id = ?", (investor_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ---------------------------------------------------------------------------
# Helpers — активы портфеля
# ---------------------------------------------------------------------------

async def get_portfolio(investor_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, asset_ticker, amount FROM portfolios WHERE investor_id = ? ORDER BY asset_ticker",
            (investor_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def add_or_update_asset(investor_id: int, ticker: str, amount: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO portfolios (investor_id, asset_ticker, amount)
            VALUES (?, ?, ?)
            ON CONFLICT(investor_id, asset_ticker)
            DO UPDATE SET amount = excluded.amount
            """,
            (investor_id, ticker.upper(), amount),
        )
        await db.commit()


async def delete_asset(investor_id: int, ticker: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM portfolios WHERE investor_id = ? AND asset_ticker = ?",
            (investor_id, ticker.upper()),
        )
        await db.commit()


async def get_all_unique_tickers() -> list[str]:
    """Возвращает все уникальные тикеры из всех портфелей."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT DISTINCT asset_ticker FROM portfolios") as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]


async def get_all_portfolios() -> list[dict]:
    """Возвращает все позиции со именами инвесторов (для общего отчёта)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT i.name as investor_name, p.asset_ticker, p.amount
            FROM portfolios p
            JOIN investors i ON i.id = p.investor_id
            ORDER BY i.name, p.asset_ticker
            """
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
