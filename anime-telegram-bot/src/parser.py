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
from .posted import load_posted_ids, load_tracked, save_posted_ids, save_tracked
from .subs import load_counts, load_subs, save_counts


def esc(s: object) -> str:
    return html.escape(str(s) if s is not None else "", quote=False)


def clamp_html(s: str, limit: int = 1000) -> str:
    """Обрезка под лимит Telegram без разрыва HTML-тега или сущности.

    Если резать вслепую, на границе может остаться «&am» или «<b» —
    Telegram отвечает «can't parse entities» и пост не уходит.
    """
    if len(s) <= limit:
        return s
    cut = s[:limit]
    amp = cut.rfind("&")
    if amp != -1 and ";" not in cut[amp:]:
        cut = cut[:amp]
    lt = cut.rfind("<")
    if lt != -1 and ">" not in cut[lt:]:
        cut = cut[:lt]
    return cut.rstrip()


def _watch_kb(cfg, rid: int):
    if not cfg.bot_username:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="▶ Смотреть в боте",
        url=f"https://t.me/{cfg.bot_username}?start=libria_{rid}",
    )]])


def _tags_for(item: dict) -> str:
    tags = ["#аниме", "#русскаяозвучка"]
    type_tag = {"TV": "#сериал", "movie": "#полнометражка", "OVA": "#ova", "ONA": "#ona", "special": "#спешл"}.get((item.get("type") or {}).get("value", ""))
    if type_tag:
        tags.append(type_tag)
    tags.append("#онгоинг" if item.get("is_ongoing") else "#новинка")
    return " ".join(tags)


async def post_new(limit: int) -> int:
    cfg = load_config()
    if not cfg.bot_token or not cfg.channel_id:
        raise SystemExit("Заполни BOT_TOKEN и CHANNEL_ID в .env")
    os.makedirs(os.path.dirname(cfg.db_path) or ".", exist_ok=True)
    await init_db(cfg.db_path)
    posted_ids = load_posted_ids(cfg.posted_path)
    tracked = load_tracked(cfg.tracked_path)
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    posted = 0
    failed = 0
    try:
        for r in await anilibria.get_latest(limit):
            rid = r["id"]
            if rid in posted_ids:
                continue
            title = anilibria.title_of(r)
            img = anilibria.best_poster(r)
            desc = (r.get("description") or "")[:350]
            year = r.get("year", "")
            genres = ", ".join((g.get("name") or "") for g in (r.get("genres") or [])[:3] if g.get("name"))
            deep = f"https://t.me/{cfg.bot_username}?start=libria_{rid}" if cfg.bot_username else None
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶ Смотреть в боте", url=deep)]]) if deep else None
            ep_no = (r.get("latest_ep") or {}).get("ordinal")
            head = f"🆕 <b>{esc(title)} ({esc(year)})</b>"
            if ep_no:
                head += f" — вышла серия {ep_no}"
            lines = [head]
            if genres:
                lines.append(f"<i>{esc(genres)}</i>")
            if desc:
                lines.append("")
                lines.append(esc(desc))
            lines.append("")
            lines.append(_tags_for(r))
            text = clamp_html("\n".join(lines))
            try:
                if img:
                    await bot.send_photo(cfg.channel_id, img, caption=text, reply_markup=kb)
                else:
                    await bot.send_message(cfg.channel_id, text, reply_markup=kb)
            except Exception as e:
                # один проблемный релиз не должен ронять остальные и терять журнал
                failed += 1
                print(f"Post failed for {rid}: {e}")
                continue
            posted_ids.add(rid)
            # пишем журнал сразу после успешного поста: если упадем на следующем
            # релизе, уже отправленное не уйдет в канал второй раз
            save_posted_ids(cfg.posted_path, posted_ids)
            # онгоинг ставим под наблюдение (молча): серии проверим ниже
            if r.get("is_ongoing"):
                if not ep_no:
                    try:
                        ep_no = await anilibria.get_episode_count(rid)
                    except Exception:
                        ep_no = 0
                tracked[str(rid)] = {
                    "title": title, "year": year,
                    "type": (r.get("type") or {}).get("value", ""),
                    "count": ep_no or 0,
                }
            posted += 1
    finally:
        await bot.session.close()
        # журналы фиксируем всегда, в том числе при падении посередине
        save_posted_ids(cfg.posted_path, posted_ids)
        save_tracked(cfg.tracked_path, tracked)
    if failed:
        print(f"Failed posts: {failed}")
    try:
        ep_posts = await check_tracked(bot, cfg, tracked)
        print(f"Episode posts: {ep_posts}")
    except Exception as e:  # посты о сериях не должны ронять весь запуск
        print(f"Episodes check failed: {e}")
    save_tracked(cfg.tracked_path, tracked)
    try:
        notified = await check_subscriptions(bot, cfg)
        print(f"Notified: {notified}")
    except Exception as e:  # уведомления не должны ронять весь запуск
        print(f"Notify failed: {e}")
    return posted


async def check_tracked(bot: Bot, cfg, tracked: dict) -> int:
    """Посты «вышла серия» для отслеживаемых онгоингов. Один запрос на релиз:
    get_release отдает и флаг is_ongoing, и список серий."""
    made = 0
    for rid_str in list(tracked):
        try:
            rid = int(rid_str)
        except (TypeError, ValueError):
            tracked.pop(rid_str, None)
            continue
        try:
            r = await anilibria.get_release(rid)
        except Exception:
            continue  # API чихнул — попробуем в следующий раз
        if r.get("is_ongoing") is False:
            tracked.pop(rid_str, None)  # завершен — снимаем с наблюдения
            continue
        new_count = len(r.get("episodes") or [])
        # meta может быть пустым словарём или мусором из старого журнала:
        # setdefault + проверка типа, иначе апдейт count уходил в никуда
        meta = tracked.get(rid_str)
        if not isinstance(meta, dict):
            meta = {}
            tracked[rid_str] = meta
        old_count = int(meta.get("count") or 0)
        if new_count <= 0 or new_count <= old_count:
            meta["count"] = max(old_count, new_count)
            continue
        title = meta.get("title") or anilibria.title_of(r)
        year = meta.get("year", "")
        img = anilibria.best_poster(r)
        kb = _watch_kb(cfg, rid)
        text = (
            f"📺 <b>{esc(title)} ({esc(year)})</b> — вышла серия {new_count}\n\n"
            + _tags_for({"type": {"value": meta.get("type", "")}, "is_ongoing": True})
        )
        try:
            if img:
                await bot.send_photo(cfg.channel_id, img, caption=clamp_html(text), reply_markup=kb)
            else:
                await bot.send_message(cfg.channel_id, clamp_html(text), reply_markup=kb)
        except Exception:
            continue
        meta["count"] = new_count
        # фиксируем сразу: иначе после падения на следующем релизе
        # эта же серия уйдет в канал повторно
        save_tracked(cfg.tracked_path, tracked)
        made += 1
    return made


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
