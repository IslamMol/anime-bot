"""Клиент Kodik API (ссылки на плеер с русской озвучкой). Нужен KODIK_TOKEN с kodik.info."""
import httpx

SEARCH_URL = "https://kodikapi.com/search"


def to_player_url(link: str) -> str:
    if not link:
        return ""
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("http"):
        return link
    return "https://" + link.lstrip("/")


async def find_by_shikimori(shikimori_id: int, token: str) -> dict | None:
    if not token:
        return None
    params = {"token": token, "shikimori_id": shikimori_id, "with_material_data": "true"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(SEARCH_URL, params=params)
        r.raise_for_status()
        data = r.json().get("results") or []
        return data[0] if data else None


async def find_by_title(title: str, token: str) -> dict | None:
    if not token:
        return None
    params = {"token": token, "title": title, "types": "anime-serial,anime", "with_material_data": "true"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(SEARCH_URL, params=params)
        r.raise_for_status()
        data = r.json().get("results") or []
        return data[0] if data else None
