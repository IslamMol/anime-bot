"""Клиент Shikimori API (метаданные: поиск, онгоинги). Без ключа."""
import urllib.parse

import httpx

BASE = "https://shikimori.one/api"
HEADERS = {"User-Agent": "anime-telegram-bot/1.0"}


def image_url(path: str) -> str:
    if not path:
        return ""
    if path.startswith("http"):
        return path
    return f"https://shikimori.one{path}"


async def search_anime(query: str, limit: int = 5) -> list[dict]:
    params = {"search": query, "limit": limit, "order": "ranked", "censored": "true"}
    async with httpx.AsyncClient(timeout=15, headers=HEADERS) as c:
        r = await c.get(f"{BASE}/animes", params=params)
        r.raise_for_status()
        return r.json()


async def get_ongoings(limit: int = 10) -> list[dict]:
    params = {"status": "ongoing", "order": "ranked", "limit": limit, "censored": "true"}
    async with httpx.AsyncClient(timeout=15, headers=HEADERS) as c:
        r = await c.get(f"{BASE}/animes", params=params)
        r.raise_for_status()
        return r.json()


async def get_anime(anime_id: int) -> dict:
    async with httpx.AsyncClient(timeout=15, headers=HEADERS) as c:
        r = await c.get(f"{BASE}/animes/{anime_id}")
        r.raise_for_status()
        return r.json()


def title_of(a: dict) -> str:
    return a.get("russian") or a.get("name") or "Без названия"


def short_caption(a: dict) -> str:
    score = a.get("score", "?")
    kind = a.get("kind", "?")
    eps = a.get("episodes", "?")
    status = a.get("status", "")
    return f"{title_of(a)}\n{kind} • ep: {eps} • ★ {score} • {status}"


def webapp_link(base: str, kodik_url: str, title: str) -> str:
    q = urllib.parse.urlencode({"kodik": kodik_url, "title": title})
    return f"{base}index.html?{q}"
