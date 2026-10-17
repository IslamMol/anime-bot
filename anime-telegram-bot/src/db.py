"""SQLite: избранное + журнал постов + очередь на уведомления."""
from contextlib import asynccontextmanager

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS favs (user_id INTEGER, anime_id INTEGER, title TEXT, PRIMARY KEY (user_id, anime_id));
CREATE TABLE IF NOT EXISTS posted (anime_id INTEGER PRIMARY KEY);
"""


@asynccontextmanager
async def connect(path: str):
    """Соединение с WAL: без него бот и парсер ловят «database is locked»."""
    db = await aiosqlite.connect(path)
    try:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA busy_timeout=5000")
        yield db
    finally:
        await db.close()


async def init_db(path: str) -> None:
    async with connect(path) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def add_fav(path: str, user_id: int, anime_id: int, title: str) -> None:
    async with connect(path) as db:
        await db.execute("INSERT OR IGNORE INTO favs VALUES (?, ?, ?)", (user_id, anime_id, title))
        await db.commit()


async def list_favs(path: str, user_id: int) -> list[tuple]:
    async with connect(path) as db:
        cur = await db.execute("SELECT anime_id, title FROM favs WHERE user_id=?", (user_id,))
        return await cur.fetchall()


async def is_fav(path: str, user_id: int, anime_id: int) -> bool:
    async with connect(path) as db:
        cur = await db.execute("SELECT 1 FROM favs WHERE user_id=? AND anime_id=?", (user_id, anime_id))
        return await cur.fetchone() is not None


async def remove_fav(path: str, user_id: int, anime_id: int) -> None:
    async with connect(path) as db:
        await db.execute("DELETE FROM favs WHERE user_id=? AND anime_id=?", (user_id, anime_id))
        await db.commit()


async def is_posted(path: str, anime_id: int) -> bool:
    async with connect(path) as db:
        cur = await db.execute("SELECT 1 FROM posted WHERE anime_id=?", (anime_id,))
        return await cur.fetchone() is not None


async def mark_posted(path: str, anime_id: int) -> None:
    async with connect(path) as db:
        await db.execute("INSERT OR IGNORE INTO posted VALUES (?)", (anime_id,))
        await db.commit()
