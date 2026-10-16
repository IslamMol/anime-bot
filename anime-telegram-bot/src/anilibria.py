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


def best_poster(release: dict, kind: str = "big") -> str:
    """Та же цепочка fallback'ов, что в JS-плеере (posterOf).
    Поле src есть не всегда — без этого посты уходят без картинки."""
    p = release.get("poster") or {}
    o = p.get("optimized") or {}
    if kind == "big":
        src = o.get("src") or p.get("src") or ""
    else:
        src = o.get("preview") or o.get("thumbnail") or p.get("preview") or p.get("thumbnail") or p.get("src") or ""
    return poster_url(src)


def title_of(r: dict) -> str:
    name = r.get("name") or {}
    return name.get("main") or name.get("english") or "Без названия"


def best_hls(ep: dict) -> str:
    return ep.get("hls_1080") or ep.get("hls_720") or ep.get("hls_480") or ""


async def search_releases(query: str, limit: int = 5, page: int = 1) -> list[dict]:
    params = {"f[search]": query, "page": page, "limit": limit}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{BASE}/anime/catalog/releases", params=params)
        r.raise_for_status()
        return r.json().get("data") or []


async def get_top(limit: int = 5) -> list[dict]:
    """Топ по рейтингу — как витрина «Топ» в приложении."""
    params = {"f[sorting]": "RATING_DESC", "page": 1, "limit": limit}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{BASE}/anime/catalog/releases", params=params)
        r.raise_for_status()
        return r.json().get("data") or []


_GENRES_CACHE: dict = {"at": 0.0, "items": []}


async def get_genres() -> list[dict]:
    """Справочник жанров [{id, name}]. Проверено: 35 штук."""
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{BASE}/anime/genres")
        r.raise_for_status()
        j = r.json()
        items = j.get("data") if isinstance(j, dict) else j
        return [g for g in (items or []) if isinstance(g, dict) and g.get("name")]


async def genre_name(gid: int) -> str:
    """Имя жанра с часовым кэшем — чтобы не дергать API на каждой странице."""
    import time

    now = time.monotonic()
    if now - _GENRES_CACHE["at"] > 3600 or not _GENRES_CACHE["items"]:
        try:
            _GENRES_CACHE["items"] = await get_genres()
        except Exception:
            pass
        _GENRES_CACHE["at"] = now
    for g in _GENRES_CACHE["items"]:
        if g.get("id") == gid:
            return g.get("name") or ""
    return ""


async def get_filtered(genre_id: int = 0, status: str = "all", year: int = 0,
                       limit: int = 8, page: int = 1) -> list[dict]:
    """Каталог с фильтрами. Зеркалит параметры из WebApp:
    f[genres], f[publish_statuses]=IS_ONGOING, f[years], f[sorting]."""
    params: dict = {"f[sorting]": "RATING_DESC", "page": page, "limit": limit}
    if genre_id:
        params["f[genres]"] = genre_id
    if status == "ongoing":
        params["f[publish_statuses]"] = "IS_ONGOING"
    if year:
        params["f[years][from_year]"] = year
        params["f[years][to_year]"] = year
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
