"""Клиент AniLiberty (ex AniLibria). Без токена. Русская озвучка + прямые HLS-ссылки."""
import asyncio

import httpx

BASE = "https://anilibria.top/api/v1"


def poster_url(path: str) -> str:
    if not path:
        return ""
    if path.startswith("http"):
        return path
    return f"https://anilibria.top{path}"


def title_of(r: dict) -> str:
    name = r.get("name") or {}
    return name.get("main") or name.get("english") or "Без названия"


def best_hls(ep: dict) -> str:
    return ep.get("hls_1080") or ep.get("hls_720") or ep.get("hls_480") or ""


async def search_releases(query: str, limit: int = 5) -> list[dict]:
    params = {"f[search]": query, "page": 1, "limit": limit}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{BASE}/anime/catalog/releases", params=params)
        r.raise_for_status()
        return r.json().get("data") or []


async def get_release(release_id: int | str, with_episodes: bool = True) -> dict:
    # метаданные и серии тянем параллельно — иначе карточка ждет 2 запроса подряд
    async with httpx.AsyncClient(timeout=20) as c:
        if not with_episodes:
            r = await c.get(f"{BASE}/anime/releases/{release_id}")
            r.raise_for_status()
            meta = r.json()
            return meta["data"] if isinstance(meta, dict) and isinstance(meta.get("data"), dict) else meta
        r_meta, r_eps = await asyncio.gather(
            c.get(f"{BASE}/anime/releases/{release_id}"),
            c.get(f"{BASE}/anime/releases/{release_id}", params={"include": "episodes"}),
        )
        r_meta.raise_for_status()
        r_eps.raise_for_status()
        meta = r_meta.json()
        # API отдает data-обертку в части ответов — разворачиваем
        if isinstance(meta, dict) and "data" in meta and isinstance(meta["data"], dict):
            meta = meta["data"]
        ej = r_eps.json()
        eps = ej.get("episodes") if isinstance(ej, dict) else None
        meta["episodes"] = eps or []
        return meta


async def get_latest(limit: int = 5) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{BASE}/anime/releases/latest", params={"limit": limit})
        r.raise_for_status()
        j = r.json()
        # /latest отдает голый list, а /catalog — {"data": [...]}
        if isinstance(j, list):
            return j
        data = j.get("data") if isinstance(j, dict) else None
        return data if isinstance(data, list) else []


async def get_new_2026(limit: int = 5) -> list[dict]:
    """Новинки 2026: онгоинги этого года по рейтингу."""
    params = {
        "f[years][from_year]": 2026,
        "f[years][to_year]": 2026,
        "f[publish_statuses]": "IS_ONGOING",
        "f[sorting]": "RATING_DESC",
        "page": 1,
        "limit": limit,
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{BASE}/anime/catalog/releases", params=params)
        r.raise_for_status()
        return r.json().get("data") or []


async def get_episode_count(release_id: int | str) -> int:
    """Сколько серий доступно в озвучке (для уведомлений о новых сериях)."""
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{BASE}/anime/releases/{release_id}", params={"include": "episodes"})
        r.raise_for_status()
        j = r.json()
        eps = j.get("episodes") if isinstance(j, dict) else None
        return len(eps) if isinstance(eps, list) else 0


async def get_random() -> dict | None:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{BASE}/anime/releases/random")
        r.raise_for_status()
        j = r.json()
        if isinstance(j, dict) and isinstance(j.get("data"), dict):
            return j["data"]
        if isinstance(j, dict) and "id" in j:
            return j
        if isinstance(j, list) and j:
            return j[0]
        return None
