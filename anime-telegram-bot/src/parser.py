"""Автопостинг новинок AniLibria в канал. Запуск: python -m src.parser --limit 5"""
import argparse
import asyncio
import html
import os

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import anilibria
from .config import load_config
from .db import init_db
from .posted import load_posted_ids, save_posted_ids
from .subs import load_counts, load_subs, save_counts


def esc(s: object) -> str:
    return html.escape(str(s or ""), quote=False)


async def post_new(limit: int) -> int:
    cfg = load_config()
    if not cfg.bot_token or not cfg.channel_id:
        raise SystemExit("Заполни BOT_TOKEN и CHANNEL_ID в .env")
    os.makedirs(os.path.dirname(cfg.db_path) or ".", exist_ok=True)
    await init_db(cfg.db_path)
    posted_ids = load_posted_ids(cfg.posted_path)
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    posted = 0
    try:
        for r in await anilibria.get_latest(limit):
            rid = r["id"]
            if rid in posted_ids:
                continue
            title = anilibria.title_of(r)
            img = anilibria.poster_url((r.get("poster") or {}).get("src", ""))
            desc = (r.get("description") or "")[:350]
            year = r.get("year", "")
            genres = ", ".join((g.get("name") or "") for g in (r.get("genres") or [])[:3] if g.get("name"))
            deep = f"https://t.me/{cfg.bot_username}?start=libria_{rid}" if cfg.bot_username else None
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶ Смотреть в боте", url=deep)]]) if deep else None
            lines = [f"🆕 <b>{esc(title)} ({esc(year)})</b>"]
            if genres:
                lines.append(f"<i>{esc(genres)}</i>")
            if desc:
                lines.append("")
                lines.append(esc(desc))
            lines.append("")
            lines.append("#аниме #новинка #русскаяозвучка")
            text = "\n".join(lines)
            if img:
                await bot.send_photo(cfg.channel_id, img, caption=text[:1000], reply_markup=kb)
            else:
                await bot.send_message(cfg.channel_id, text[:1000], reply_markup=kb)
            posted_ids.add(rid)
            posted += 1
    finally:
        await bot.session.close()
    # журнал пишем один раз в конце — и локально так безопаснее (не будет
    # полузаписанного состояния, если упадем посередине)
    save_posted_ids(cfg.posted_path, posted_ids)
    try:
        notified = await check_subscriptions(bot, cfg)
        print(f"Notified: {notified}")
    except Exception as e:  # уведомления не должны ронять весь запуск
        print(f"Notify failed: {e}")
    return posted


async def check_subscriptions(bot: Bot, cfg) -> int:
    """Сверяет счетчики серий по подпискам, шлет «вышла новая серия».

    Первый замер только запоминается (без уведомлений), чтобы не заспамить
    всех при первом запуске.
    """
    subs = load_subs(cfg.subs_path)
    if not subs:
        return 0
    counts = load_counts(cfg.counts_path)
    by_release: dict[int, list[int]] = {}
    titles: dict[int, str] = {}
    for s in subs:
        by_release.setdefault(s["release_id"], []).append(s["user_id"])
        titles.setdefault(s["release_id"], s.get("title") or "")
    notified = 0
    deep_base = f"https://t.me/{cfg.bot_username}" if cfg.bot_username else ""
    for rid, user_ids in by_release.items():
        try:
            new_count = await anilibria.get_episode_count(rid)
        except Exception:
            continue
        old = counts.get(str(rid))
        counts[str(rid)] = new_count
        if old is None or new_count <= old or new_count <= 0:
            continue
        title = titles.get(rid) or f"релиз {rid}"
        kb = None
        if deep_base:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="▶ Смотреть",
                    url=f"{deep_base}?start=libria_{rid}",
                )
            ]])
        for uid in sorted(set(user_ids)):
            try:
                await bot.send_message(
                    uid,
                    f"🔔 <b>Новая серия!</b> «{esc(title)}» — вышла серия {new_count}.",
                    reply_markup=kb,
                )
                notified += 1
            except Exception:
                continue  # юзер заблокировал бота — пропускаем
    save_counts(cfg.counts_path, counts)
    return notified


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=5)
    args = p.parse_args()
    n = asyncio.run(post_new(args.limit))
    print(f"Posted: {n}")


if __name__ == "__main__":
    main()
