"""SQLite: избранное + уже опубликованные в канал посты."""
import aiosqlite
SCHEMA = """
CREATE TABLE IF NOT EXISTS favs (user_id INTEGER, anime_id INTEGER, title TEXT, PRIMARY KEY (user_id, anime_id));
CREATE TABLE IF NOT EXISTS posted (anime_id INTEGER PRIMARY KEY);
"""


async def init_db(path: str) -> None:
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def add_fav(path: str, user_id: int, anime_id: int, title: str) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute("INSERT OR IGNORE INTO favs VALUES (?, ?, ?)", (user_id, anime_id, title))
        await db.commit()


async def list_favs(path: str, user_id: int) -> list[tuple]:
    async with aiosqlite.connect(path) as db:
        cur = await db.execute("SELECT anime_id, title FROM favs WHERE user_id=?", (user_id,))
        return await cur.fetchall()


async def is_fav(path: str, user_id: int, anime_id: int) -> bool:
    async with aiosqlite.connect(path) as db:
        cur = await db.execute("SELECT 1 FROM favs WHERE user_id=? AND anime_id=?", (user_id, anime_id))
        return await cur.fetchone() is not None


async def remove_fav(path: str, user_id: int, anime_id: int) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute("DELETE FROM favs WHERE user_id=? AND anime_id=?", (user_id, anime_id))
        await db.commit()


async def is_posted(path: str, anime_id: int) -> bool:
    async with aiosqlite.connect(path) as db:
        cur = await db.execute("SELECT 1 FROM posted WHERE anime_id=?", (anime_id,))
        return await cur.fetchone() is not None


async def mark_posted(path: str, anime_id: int) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute("INSERT OR IGNORE INTO posted VALUES (?)", (anime_id,))
        await db.commit()
