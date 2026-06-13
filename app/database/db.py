"""Асинхронный слой работы с SQLite через aiosqlite.

Модель данных построена на сделках (lots), чтобы вести точки входа и считать P&L:
    investors    — инвесторы (id, name)
    transactions — сделки: покупки и продажи активов
                   (id, investor_id, asset_ticker, kind['buy'|'sell'], price, amount, date)
    settings     — настройки бота (ключ-значение)
    admins       — админы, добавленные через меню (помимо ALLOWED_USERS из .env)

Текущий остаток актива = сумма покупок − сумма продаж (считается на лету).
"""
import aiosqlite

# Порог сравнения вещественных остатков (борьба с погрешностью float)
EPS = 1e-9

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
        """Открывает соединение, создает таблицы и переносит данные старой схемы."""
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS investors (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                investor_id  INTEGER NOT NULL REFERENCES investors(id) ON DELETE CASCADE,
                asset_ticker TEXT NOT NULL,
                kind         TEXT NOT NULL CHECK (kind IN ('buy', 'sell')),
                price        REAL NOT NULL,   -- цена за 1 монету в USD
                amount       REAL NOT NULL,   -- количество монет в сделке
                date         TEXT NOT NULL    -- дата сделки в формате ДД.ММ.ГГГГ
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
        for key, value in DEFAULT_SETTINGS.items():
            await self._conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
        await self._conn.commit()
        await self._migrate_legacy_portfolios()

    async def _migrate_legacy_portfolios(self) -> None:
        """Переносит остатки из старой таблицы portfolios (если она была) в transactions.

        Старая схема хранила только текущее количество без цены входа. Переносим
        каждый остаток как покупку с ценой 0 (неизвестна) — остатки сохранятся,
        а P&L по таким позициям будет помечен как «н/д» (нулевая цена входа).
        """
        cursor = await self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='portfolios'"
        )
        if await cursor.fetchone() is None:
            return  # старой таблицы нет — миграция не нужна

        # Переносим только если transactions ещё пуста (миграция выполняется один раз)
        cursor = await self.conn.execute("SELECT COUNT(*) AS c FROM transactions")
        if (await cursor.fetchone())["c"] > 0:
            return

        cursor = await self.conn.execute(
            "SELECT investor_id, asset_ticker, amount FROM portfolios WHERE amount > 0"
        )
        rows = await cursor.fetchall()
        for row in rows:
            await self.conn.execute(
                "INSERT INTO transactions "
                "(investor_id, asset_ticker, kind, price, amount, date) "
                "VALUES (?, ?, 'buy', 0, ?, '—')",
                (row["investor_id"], row["asset_ticker"], row["amount"]),
            )
        await self.conn.commit()

    async def close(self) -> None:
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

    async def find_investor_by_name(self, name: str) -> aiosqlite.Row | None:
        """Ищет инвестора по точному имени (для выбора reply-кнопкой)."""
        cursor = await self.conn.execute(
            "SELECT id, name FROM investors WHERE name = ? ORDER BY id LIMIT 1", (name,)
        )
        return await cursor.fetchone()

    async def delete_investor(self, investor_id: int) -> None:
        """Удаляет инвестора; его сделки удаляются каскадно (FK ON DELETE CASCADE)."""
        await self.conn.execute("DELETE FROM investors WHERE id = ?", (investor_id,))
        await self.conn.commit()

    # ---------- Сделки (покупки / продажи) ----------

    async def add_transaction(self, investor_id: int, ticker: str, kind: str,
                              price: float, amount: float, date: str) -> None:
        """Добавляет сделку (kind = 'buy' или 'sell')."""
        await self.conn.execute(
            "INSERT INTO transactions "
            "(investor_id, asset_ticker, kind, price, amount, date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (investor_id, ticker.upper(), kind, price, amount, date),
        )
        await self.conn.commit()

    async def get_transactions(self, investor_id: int) -> list[aiosqlite.Row]:
        """Все сделки инвестора в хронологическом порядке."""
        cursor = await self.conn.execute(
            "SELECT asset_ticker, kind, price, amount, date FROM transactions "
            "WHERE investor_id = ? ORDER BY id",
            (investor_id,),
        )
        return list(await cursor.fetchall())

    async def get_portfolio(self, investor_id: int) -> list[aiosqlite.Row]:
        """Текущие позиции инвестора (тикер + остаток), только с остатком > 0."""
        cursor = await self.conn.execute(
            """
            SELECT asset_ticker,
                   SUM(CASE kind WHEN 'buy' THEN amount ELSE -amount END) AS amount
            FROM transactions
            WHERE investor_id = ?
            GROUP BY asset_ticker
            HAVING amount > ?
            ORDER BY asset_ticker
            """,
            (investor_id, EPS),
        )
        return list(await cursor.fetchall())

    async def remaining_amount(self, investor_id: int, ticker: str) -> float:
        """Текущий остаток конкретного актива у инвестора."""
        cursor = await self.conn.execute(
            """
            SELECT SUM(CASE kind WHEN 'buy' THEN amount ELSE -amount END) AS amount
            FROM transactions WHERE investor_id = ? AND asset_ticker = ?
            """,
            (investor_id, ticker.upper()),
        )
        row = await cursor.fetchone()
        return float(row["amount"]) if row and row["amount"] is not None else 0.0

    async def delete_asset(self, investor_id: int, ticker: str) -> None:
        """Полностью удаляет актив у инвестора (все его сделки)."""
        await self.conn.execute(
            "DELETE FROM transactions WHERE investor_id = ? AND asset_ticker = ?",
            (investor_id, ticker.upper()),
        )
        await self.conn.commit()

    async def get_unique_tickers(self) -> list[str]:
        """Тикеры с положительным остатком по всем портфелям (для аналитики/алертов)."""
        cursor = await self.conn.execute(
            """
            SELECT asset_ticker FROM transactions
            GROUP BY asset_ticker
            HAVING SUM(CASE kind WHEN 'buy' THEN amount ELSE -amount END) > ?
            ORDER BY asset_ticker
            """,
            (EPS,),
        )
        return [row["asset_ticker"] for row in await cursor.fetchall()]

    async def get_holders_by_ticker(self, ticker: str) -> list[aiosqlite.Row]:
        """Инвесторы, держащие данный актив, и их остатки (по убыванию остатка)."""
        cursor = await self.conn.execute(
            """
            SELECT i.name AS investor_name,
                   SUM(CASE t.kind WHEN 'buy' THEN t.amount ELSE -t.amount END) AS amount
            FROM investors i
            JOIN transactions t ON t.investor_id = i.id
            WHERE t.asset_ticker = ?
            GROUP BY i.id
            HAVING amount > ?
            ORDER BY amount DESC
            """,
            (ticker.upper(), EPS),
        )
        return list(await cursor.fetchall())

    async def get_all_holdings(self) -> list[aiosqlite.Row]:
        """Текущие остатки всех инвесторов (для сводных отчетов).

        Инвесторы без активов попадают в результат с NULL-тикером.
        """
        cursor = await self.conn.execute(
            """
            SELECT i.id AS investor_id, i.name AS investor_name,
                   t.asset_ticker,
                   SUM(CASE t.kind WHEN 'buy' THEN t.amount ELSE -t.amount END) AS amount
            FROM investors i
            LEFT JOIN transactions t ON t.investor_id = i.id
            GROUP BY i.id, t.asset_ticker
            HAVING amount IS NULL OR amount > ?
            ORDER BY i.name, t.asset_ticker
            """,
            (EPS,),
        )
        return list(await cursor.fetchall())

    async def get_all_transactions(self) -> list[aiosqlite.Row]:
        """Все сделки всех инвесторов (для сводного P&L по разделу «Прибыль/Убыток»)."""
        cursor = await self.conn.execute(
            """
            SELECT i.id AS investor_id, i.name AS investor_name,
                   t.asset_ticker, t.kind, t.price, t.amount
            FROM investors i
            LEFT JOIN transactions t ON t.investor_id = i.id
            ORDER BY i.name
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
