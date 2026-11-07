from typing import Optional

import asyncpg


class Storage:
    """
    Simple Postgres/Supabase storage for chat ↔ wallet/tokens mapping.
    Schema suggestion:
        CREATE TABLE bot_links (
            chat_id BIGINT PRIMARY KEY,
            wallet TEXT NOT NULL,
            access_token TEXT,
            refresh_token TEXT,
            notify BOOLEAN DEFAULT FALSE
        );
    """

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool: Optional[asyncpg.pool.Pool] = None

    async def connect(self):
        self._pool = await asyncpg.create_pool(dsn=self.dsn, min_size=1, max_size=4)

    async def close(self):
        if self._pool:
            await self._pool.close()

    async def upsert_link(self, chat_id: int, wallet: str, access: str, refresh: str, notify: bool = False):
        query = """
        INSERT INTO bot_links (chat_id, wallet, access_token, refresh_token, notify)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (chat_id) DO UPDATE
            SET wallet = EXCLUDED.wallet,
                access_token = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                notify = COALESCE(EXCLUDED.notify, bot_links.notify)
        """
        async with self._pool.acquire() as conn:
            await conn.execute(query, chat_id, wallet, access, refresh, notify)

    async def get_link(self, chat_id: int) -> Optional[dict]:
        query = "SELECT chat_id, wallet, access_token, refresh_token, notify FROM bot_links WHERE chat_id = $1"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, chat_id)
        return dict(row) if row else None

    async def set_notify(self, chat_id: int, notify: bool):
        query = "UPDATE bot_links SET notify=$2 WHERE chat_id=$1"
        async with self._pool.acquire() as conn:
            await conn.execute(query, chat_id, notify)

    async def delete_link(self, chat_id: int):
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM bot_links WHERE chat_id=$1", chat_id)

    async def list_links(self) -> list[dict]:
        query = "SELECT chat_id, wallet, access_token, refresh_token, notify FROM bot_links"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query)
        return [dict(row) for row in rows]
