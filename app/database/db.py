"""Асинхронный слой работы с SQLite через aiosqlite.

Таблицы:
    investors  — инвесторы (id, name)
    portfolios — активы инвесторов (id, investor_id, asset_ticker, amount)
    settings   — настройки бота в формате ключ-значение
    admins     — дополнительные админы, добавленные через меню (помимо ALLOWED_USERS из .env)
"""
import aiosqlite

# Значения настроек по умолчанию (записываются при первом запуске)
DEFAULT_SETTINGS = {
    "report_freq_hours": "24",   # частота ежедневного отчета (в часах)
    "alert_threshold": "30",     # порог пампа/дампа для алертов (в процентах)
    "analytics_chat_id": "",     # чат для отчетов (переопределяет .env, задается из меню)
}


class Database:
    """Обертка над aiosqlite с методами для всех операций бота."""

    def __init__(self, path: str):
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("База данных не инициализирована — вызовите init()")
        return self._conn

    async def init(self) -> None:
        """Открывает соединение и создает таблицы, если их еще нет."""
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        # Включаем каскадное удаление по внешним ключам
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS investors (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS portfolios (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                investor_id  INTEGER NOT NULL REFERENCES investors(id) ON DELETE CASCADE,
                asset_ticker TEXT NOT NULL,
                amount       REAL NOT NULL,
                UNIQUE (investor_id, asset_ticker)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            );
            """
        )
        # Заполняем настройки значениями по умолчанию (без перезаписи существующих)
        for key, value in DEFAULT_SETTINGS.items():
            await self._conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
        await self._conn.commit()

    async def close(self) -> None:
        """Закрывает соединение с БД."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ---------- Инвесторы ----------

    async def add_investor(self, name: str) -> int:
        cursor = await self.conn.execute("INSERT INTO investors (name) VALUES (?)", (name,))
        await self.conn.commit()
        return cursor.lastrowid

    async def get_investors(self) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute("SELECT id, name FROM investors ORDER BY name")
        return list(await cursor.fetchall())

    async def get_investor(self, investor_id: int) -> aiosqlite.Row | None:
        cursor = await self.conn.execute(
            "SELECT id, name FROM investors WHERE id = ?", (investor_id,)
        )
        return await cursor.fetchone()

    async def delete_investor(self, investor_id: int) -> None:
        """Удаляет инвестора; его активы удаляются каскадно (FK ON DELETE CASCADE)."""
        await self.conn.execute("DELETE FROM investors WHERE id = ?", (investor_id,))
        await self.conn.commit()

    # ---------- Портфели ----------

    async def add_asset(self, investor_id: int, ticker: str, amount: float) -> None:
        """Добавляет актив. Если тикер уже есть у инвестора — количество суммируется."""
        await self.conn.execute(
            """
            INSERT INTO portfolios (investor_id, asset_ticker, amount)
            VALUES (?, ?, ?)
            ON CONFLICT (investor_id, asset_ticker)
            DO UPDATE SET amount = amount + excluded.amount
            """,
            (investor_id, ticker.upper(), amount),
        )
        await self.conn.commit()

    async def get_portfolio(self, investor_id: int) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute(
            "SELECT id, asset_ticker, amount FROM portfolios "
            "WHERE investor_id = ? ORDER BY asset_ticker",
            (investor_id,),
        )
        return list(await cursor.fetchall())

    async def get_asset(self, asset_id: int) -> aiosqlite.Row | None:
        cursor = await self.conn.execute(
            "SELECT id, investor_id, asset_ticker, amount FROM portfolios WHERE id = ?",
            (asset_id,),
        )
        return await cursor.fetchone()

    async def update_asset_amount(self, asset_id: int, amount: float) -> None:
        await self.conn.execute(
            "UPDATE portfolios SET amount = ? WHERE id = ?", (amount, asset_id)
        )
        await self.conn.commit()

    async def delete_asset(self, asset_id: int) -> None:
        await self.conn.execute("DELETE FROM portfolios WHERE id = ?", (asset_id,))
        await self.conn.commit()

    async def get_unique_tickers(self) -> list[str]:
        """Все уникальные тикеры из всех портфелей (для аналитики и алертов)."""
        cursor = await self.conn.execute(
            "SELECT DISTINCT asset_ticker FROM portfolios ORDER BY asset_ticker"
        )
        return [row["asset_ticker"] for row in await cursor.fetchall()]

    async def get_all_holdings(self) -> list[aiosqlite.Row]:
        """Все позиции всех инвесторов одним запросом (для сводных отчетов)."""
        cursor = await self.conn.execute(
            """
            SELECT i.id AS investor_id, i.name AS investor_name,
                   p.asset_ticker, p.amount
            FROM investors i
            LEFT JOIN portfolios p ON p.investor_id = i.id
            ORDER BY i.name, p.asset_ticker
            """
        )
        return list(await cursor.fetchall())

    # ---------- Настройки ----------

    async def get_setting(self, key: str, default: str = "") -> str:
        cursor = await self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row["value"] if row is not None else default

    async def set_setting(self, key: str, value: str) -> None:
        await self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self.conn.commit()

    # ---------- Админы ----------

    async def get_admins(self) -> set[int]:
        cursor = await self.conn.execute("SELECT user_id FROM admins")
        return {row["user_id"] for row in await cursor.fetchall()}

    async def add_admin(self, user_id: int) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,)
        )
        await self.conn.commit()

    async def remove_admin(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await self.conn.commit()
