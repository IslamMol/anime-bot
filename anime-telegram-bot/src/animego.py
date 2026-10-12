"""Поиск страниц тайтлов на AnimeGO (все серии + много озвучек). Без токена, обычный HTML-парсинг."""
import re

import httpx

BASE = "https://animego.me"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# <a ... href="/anime/slug" ...><img ... alt="Название">
RE_ITEM = re.compile(r'href="(/anime/[a-z0-9\-]+)"[^>]*>\s*<img[^>]+alt="([^"]{2,120})"', re.I)


async def search_titles(query: str, limit: int = 3) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True) as c:
            r = await c.get(f"{BASE}/search/all", params={"q": query})
            r.raise_for_status()
            out, seen = [], set()
            for href, title in RE_ITEM.findall(r.text):
                if href in seen:
                    continue
                seen.add(href)
                out.append({"title": title.strip(), "url": BASE + href})
                if len(out) >= limit:
                    break
            return out
    except Exception:
        return []
