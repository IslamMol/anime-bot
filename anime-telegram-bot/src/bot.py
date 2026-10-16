"""Бот-каталог: поиск по AniLiberty (русская озвучка, без токена), новинки 2026, избранное."""
import asyncio
import html
import logging
import urllib.parse

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultPhoto,
    InputTextMessageContent,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from . import anilibria, animego, shikimori, subs
from .config import BASE_DIR, load_config
from .db import add_fav, init_db, is_fav, list_favs, remove_fav
from .parser import post_new as parser_post_new
from .posted import load_posted_ids

router = Router()
cfg = load_config()

BTN_SEARCH = "🔍 Найти аниме"
BTN_NEW = "🆕 Новинки 2026"
BTN_RANDOM = "🎲 Случайное"
BTN_FAVS = "⭐ Избранное"
BTN_APP = "📱 Приложение"
BTN_HELP = "❓ Помощь"
BTN_CANCEL = "✖ Отмена"
BTN_FILTER = "🎛 Фильтры"

PAGE_SIZE = 8
GENRES_PER_PAGE = 10
FILTER_YEARS = [2026, 2025, 2024, 0]


def esc(s: object) -> str:
    return html.escape(str(s or ""), quote=False)


class SearchStates(StatesGroup):
    waiting_query = State()


def main_menu() -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text=BTN_SEARCH), KeyboardButton(text=BTN_NEW)],
        [KeyboardButton(text=BTN_RANDOM), KeyboardButton(text=BTN_FAVS)],
    ]
    # кнопка запуска мини-приложения (главная, поиск, избранное)
    if cfg.webapp_url and "your-domain" not in cfg.webapp_url:
        rows.append([KeyboardButton(text=BTN_APP, web_app=WebAppInfo(url=cfg.webapp_url))])
    rows.append([KeyboardButton(text=BTN_FILTER), KeyboardButton(text=BTN_HELP)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выбери действие или напиши название…",
    )


def watch_url_for(release: dict, animego_url: str | None = None) -> str | None:
    # Заглушку your-domain считаем отсутствующей — Telegram такие URL отклоняет
    if not cfg.webapp_url or "your-domain" in cfg.webapp_url:
        return None
    sh = release.get("shikimori") or {}
    q = urllib.parse.urlencode({
        "v": "9",
        "release_id": release["id"],
        "title": anilibria.title_of(release),
        "shikimori_id": sh.get("id") or "",
        "total": release.get("episodes_total") or "",
        "animego": animego_url or "",
    })
    return f"{cfg.webapp_url}index.html?{q}"


def kb_search(results: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for r in results:
        year = f" ({r.get('year')})" if r.get("year") else ""
        rows.append([InlineKeyboardButton(
            text=(anilibria.title_of(r)[:36] + year),
            callback_data=f"lib:{r['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _shiki_id(r: dict) -> str:
    sh = r.get("shikimori") or {}
    return str(sh.get("id") or f"rel:{r.get('id')}")


def kb_search_grouped(groups: list[tuple[str, list[dict]]]) -> InlineKeyboardMarkup:
    """Одна кнопка на тайтл; если релизов несколько — счетчик озвучек."""
    rows = []
    for _key, items in groups:
        first = items[0]
        year = f" ({first.get('year')})" if first.get("year") else ""
        base = anilibria.title_of(first)[:32] + year
        if len(items) == 1:
            rows.append([InlineKeyboardButton(text=base, callback_data=f"lib:{first['id']}")])
        else:
            rows.append([InlineKeyboardButton(
                text=f"{base} — {len(items)} озвучки",
                callback_data=f"dubs:{first['id']}",
            )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_dubs(items: list[tuple[dict, int]], back_rid: int) -> InlineKeyboardMarkup:
    rows = []
    for r, n in items:
        label = f"{anilibria.title_of(r)[:28]} ({r.get('year', '?')}) • {n} сер."
        rows.append([InlineKeyboardButton(text=label, callback_data=f"lib:{r['id']}")])
    rows.append([InlineKeyboardButton(text="◀ Назад к поиску", callback_data=f"q:{back_rid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_card(release: dict, alt_url: str | None = None, in_fav: bool = False) -> InlineKeyboardMarkup:
    rid = release["id"]
    url = watch_url_for(release, alt_url)
    rows: list[list[InlineKeyboardButton]] = []
    if url:
        rows.append([InlineKeyboardButton(text="▶ Смотреть (WebApp)", url=url)])
    else:
        # Без WebApp: прямые ссылки на первые серии (открываются в браузере)
        eps = sorted(release.get("episodes") or [], key=lambda e: e.get("ordinal", 0))[:6]
        for ep in eps:
            hls = anilibria.best_hls(ep)
            if hls and hls.startswith("http"):
                rows.append([InlineKeyboardButton(text=f"▶ Серия {ep.get('ordinal')}", url=hls)])
        alias = release.get("alias")
        if alias:
            rows.append([InlineKeyboardButton(text="Открыть на сайте Anilibria", url=f"https://anilibria.top/title/{alias}")])
        # AnimeGO оставляем только как запасной вариант, когда WebApp-плеера нет.
        # Когда плеер есть — все серии и озвучки уже внутри, во вкладке «Все серии».
        if alt_url:
            rows.append([InlineKeyboardButton(text="🌐 Все серии + другие озвучки (AnimeGO)", url=alt_url)])
    if in_fav:
        rows.append([InlineKeyboardButton(text="💔 Убрать из избранного", callback_data=f"unfav:{rid}")])
    else:
        rows.append([InlineKeyboardButton(text="⭐ В избранное", callback_data=f"fav:{rid}")])
    if cfg.bot_username:
        share = "https://t.me/share/url?" + urllib.parse.urlencode({
            "url": f"https://t.me/{cfg.bot_username}?start=libria_{rid}",
            "text": anilibria.title_of(release),
        })
        rows.append([InlineKeyboardButton(text="📤 Поделиться", url=share)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_by_title(results: list[dict]) -> list[tuple[str, list[dict]]]:
    groups: dict[str, list[dict]] = {}
    for r in results:
        groups.setdefault(_shiki_id(r), []).append(r)
    return list(groups.items())


async def do_search(msg: Message, query: str, page: int = 1, state: FSMContext | None = None) -> None:
    try:
        res = await anilibria.search_releases(query, limit=PAGE_SIZE, page=page)
    except Exception:
        await msg.answer("Поиск временно недоступен, попробуй еще раз.", reply_markup=main_menu())
        return
    if not res:
        text = f'По «{esc(query)}» ничего не нашел. Попробуй другое название.' if page == 1 else "Это все результаты."
        await msg.answer(text, reply_markup=main_menu())
        return
    if state:
        try:
            await state.update_data(last_q=query)
        except Exception:
            pass
    groups = group_by_title(res)
    if page == 1 and len(groups) == 1 and len(groups[0][1]) == 1:
        await send_card_by_libria(msg, res[0]["id"], msg.from_user.id)
        return
    kb = kb_search_grouped(groups)
    if len(res) == PAGE_SIZE:
        kb.inline_keyboard.append([InlineKeyboardButton(text="Показать ещё", callback_data=f"more:{page + 1}")])
    suffix = "" if page == 1 else f" (стр. {page})"
    await msg.answer(f'По «{esc(query)}» нашел{suffix}, выбери:', reply_markup=kb)


async def send_card_by_libria(msg: Message, release_id: int, user_id: int | None = None) -> None:
    uid = user_id if user_id is not None else (msg.from_user.id if msg.from_user and not msg.from_user.is_bot else 0)
    try:
        r = await anilibria.get_release(release_id)
    except Exception:
        await msg.answer("Не получилось загрузить тайтл, попробуй еще раз.", reply_markup=main_menu())
        return
    title = anilibria.title_of(r)
    eps = r.get("episodes") or []
    avail = len(eps)
    total = r.get("episodes_total") or "?"
    year = r.get("year", "?")
    desc = (r.get("description") or "")[:300]
    img = anilibria.best_poster(r)
    if isinstance(total, int) and avail < total:
        avail_line = f"Доступно в озвучке Anilibria: {avail} из {total}"
    else:
        avail_line = f"Серий в озвучке Anilibria: {avail or total}"
    caption = f"<b>{esc(title)} ({esc(year)})</b>\n{esc(avail_line)}\n\n{esc(desc)}"
    # Ссылка AnimeGO для вкладке «Все серии» ищется лениво самим WebApp.
    # Здесь ищем только когда WebApp нет — иначе это лишний медленный запрос к animego.me.
    alt_url = None
    if not watch_url_for(r, None):
        try:
            alt = await animego.search_titles(title, limit=1)
            alt_url = alt[0]["url"] if alt else None
        except Exception:
            alt_url = None
    try:
        in_fav = await is_fav(cfg.db_path, uid, release_id) if uid else False
    except Exception:
        in_fav = False
    try:
        if img:
            await msg.answer_photo(img, caption=caption[:1000], reply_markup=kb_card(r, alt_url, in_fav))
        else:
            await msg.answer(caption[:1000], reply_markup=kb_card(r, alt_url, in_fav))
    except Exception:
        await msg.answer("Не получилось отправить карточку, попробуй еще раз.", reply_markup=main_menu())


HELP_TEXT = (
    "Как пользоваться:\n"
    f"{BTN_APP} — мини-приложение: главная, поиск, избранное\n"
    f"{BTN_SEARCH} — напиши название, покажу карточки с плеером\n"
    f"{BTN_NEW} — топ онгоингов 2026 года\n"
    f"{BTN_RANDOM} — случайное аниме\n"
    f"{BTN_FAVS} — твое избранное\n"
    f"{BTN_FILTER} — подборка по жанру, статусу и году\n"
    "/top — топ по рейтингу\n\n"
    "В карточке: Смотреть — плеер с сериями и сезонами, "
    "во вкладке «Все серии» — другие озвучки. Кнопка «В избранное» сохраняет тайтл."
)


@router.message(CommandStart())
async def start(msg: Message, state: FSMContext) -> None:
    await state.clear()
    parts = msg.text.split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    if arg.startswith("libria_"):
        try:
            await send_card_by_libria(msg, int(arg.replace("libria_", "")))
            return
        except ValueError:
            pass
    if arg.startswith("anime_"):
        # старый формат из Shikimori: пробуем найти по названию в Anilibria
        try:
            a = await shikimori.get_anime(int(arg.replace("anime_", "")))
            found = await anilibria.search_releases(shikimori.title_of(a), limit=3)
            if found:
                await send_card_by_libria(msg, found[0]["id"])
                return
        except Exception:
            pass
    await msg.answer(
        "Привет! Здесь аниме в русской озвучке.\nВыбери кнопку ниже или просто напиши название.",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def help_cmd(msg: Message) -> None:
    await msg.answer(HELP_TEXT, reply_markup=main_menu())


@router.message(F.text == BTN_HELP)
async def help_btn(msg: Message) -> None:
    await msg.answer(HELP_TEXT, reply_markup=main_menu())


@router.message(Command("new"))
async def new_cmd(msg: Message) -> None:
    await send_new(msg)


@router.message(F.text == BTN_NEW, F.chat.type == "private")
async def new_btn(msg: Message) -> None:
    await send_new(msg)


async def send_new(msg: Message) -> None:
    try:
        items = await anilibria.get_new_2026(5)
    except Exception:
        items = []
    if not items:
        await msg.answer("Не смог получить новинки.", reply_markup=main_menu())
        return
    await msg.answer("🆕 Новинки 2026 — онгоинги по рейтингу, выбери:", reply_markup=kb_search(items))


@router.message(Command("random"))
async def random_cmd(msg: Message) -> None:
    try:
        r = await anilibria.get_random()
    except Exception:
        r = None
    if not r:
        await msg.answer("Не получилось, попробуй еще раз.", reply_markup=main_menu())
        return
    await send_card_by_libria(msg, r["id"])


@router.message(F.text == BTN_RANDOM, F.chat.type == "private")
async def random_btn(msg: Message) -> None:
    await random_cmd(msg)


@router.message(Command("favs"))
async def favs_cmd(msg: Message) -> None:
    rows = await list_favs(cfg.db_path, msg.from_user.id)
    if not rows:
        await msg.answer("Избранное пусто. Открой карточку и нажми «В избранное».", reply_markup=main_menu())
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t[:40], callback_data=f"lib:{i}")] for i, t in rows
    ])
    await msg.answer("Избранное — нажми чтобы открыть:", reply_markup=kb)


@router.message(F.text == BTN_FAVS, F.chat.type == "private")
async def favs_btn(msg: Message) -> None:
    await favs_cmd(msg)


@router.message(Command("search"))
async def search_cmd(msg: Message, state: FSMContext) -> None:
    parts = msg.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        await do_search(msg, parts[1].strip(), state=state)
        return
    await state.set_state(SearchStates.waiting_query)
    await msg.answer(
        "Напиши название аниме:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
            resize_keyboard=True,
        ),
    )


@router.message(F.text == BTN_SEARCH, F.chat.type == "private")
async def search_btn(msg: Message, state: FSMContext) -> None:
    await state.set_state(SearchStates.waiting_query)
    await msg.answer(
        "Напиши название аниме:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
            resize_keyboard=True,
        ),
    )


@router.message(StateFilter(SearchStates.waiting_query), F.chat.type == "private")
async def search_query(msg: Message, state: FSMContext) -> None:
    if msg.text == BTN_CANCEL:
        await state.clear()
        await msg.answer("Поиск отменен.", reply_markup=main_menu())
        return
    await state.clear()
    await do_search(msg, msg.text.strip(), state=state)


@router.message(F.text.len() >= 2, F.chat.type == "private")
async def search_free(msg: Message, state: FSMContext) -> None:
    # свободный ввод тоже ищет — кнопки не обязательны.
    # в группах молчим: там работают только команды, иначе спам на каждое сообщение
    await do_search(msg, msg.text.strip(), state=state)


@router.callback_query(F.data.startswith("more:"))
async def more_results(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    try:
        page = int(cb.data.split(":")[1])
        data = await state.get_data()
        query = (data.get("last_q") or "").strip()
        if not query:
            await cb.message.answer("Поиск устарел, напиши название заново.", reply_markup=main_menu())
            return
        await do_search(cb.message, query, page=page, state=state)
    except Exception:
        await cb.message.answer("Не получилось загрузить, попробуй еще раз.", reply_markup=main_menu())


@router.callback_query(F.data.startswith("lib:"))
async def view(cb: CallbackQuery) -> None:
    await cb.answer()
    try:
        await send_card_by_libria(cb.message, int(cb.data.split(":")[1]), cb.from_user.id)
    except Exception:
        await cb.message.answer("Не получилось загрузить, попробуй еще раз.", reply_markup=main_menu())


@router.callback_query(F.data.startswith("dubs:"))
async def view_dubs(cb: CallbackQuery) -> None:
    """Все озвучки одного тайтла: ищем по названию, фильтруем по shikimori_id."""
    await cb.answer()
    try:
        rid = int(cb.data.split(":")[1])
        base = await anilibria.get_release(rid, with_episodes=False)
        sh = (base.get("shikimori") or {}).get("id")
        title = anilibria.title_of(base)
        found = await anilibria.search_releases(title, limit=10)
        items = [r for r in found if (r.get("shikimori") or {}).get("id") == sh] if sh else found[:5]
        if not items:
            items = [base]
        counts = await asyncio.gather(*[anilibria.get_episode_count(r["id"]) for r in items[:6]])
        await cb.message.answer(
            f"Озвучки: <b>{esc(title)}</b> — выбери:",
            reply_markup=kb_dubs(list(zip(items[:6], counts)), rid),
        )
    except Exception:
        await cb.message.answer("Не получилось загрузить озвучки.", reply_markup=main_menu())


@router.callback_query(F.data.startswith("q:"))
async def back_to_search(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    try:
        rid = int(cb.data.split(":")[1])
        base = await anilibria.get_release(rid, with_episodes=False)
        await do_search(cb.message, anilibria.title_of(base), state=state)
    except Exception:
        await cb.message.answer("Не получилось, попробуй еще раз.", reply_markup=main_menu())


@router.message(Command("top"))
async def top_cmd(msg: Message) -> None:
    try:
        items = await anilibria.get_top(5)
    except Exception:
        items = []
    if not items:
        await msg.answer("Не смог получить топ.", reply_markup=main_menu())
        return
    await msg.answer("🏆 Топ по рейтингу:", reply_markup=kb_search(items))


def _filter_label(genre_name: str, status: str, year: int) -> str:
    parts = [f"Жанр: {genre_name}"]
    parts.append("Онгоинги" if status == "ongoing" else "Все статусы")
    parts.append(str(year) if year else "Все годы")
    return " • ".join(parts)


async def do_filter(msg: Message, genre_id: int, status: str, year: int, page: int = 1) -> None:
    try:
        gname = await anilibria.genre_name(genre_id)
        res = await anilibria.get_filtered(genre_id, status, year, limit=PAGE_SIZE, page=page)
    except Exception:
        await msg.answer("Подборка недоступна, попробуй еще раз.", reply_markup=main_menu())
        return
    if not res and page == 1:
        await msg.answer("По такому фильтру ничего нет, попробуй шире.", reply_markup=main_menu())
        return
    if not res:
        await msg.answer("Это все результаты.", reply_markup=main_menu())
        return
    kb = kb_search(res)
    if len(res) == PAGE_SIZE:
        kb.inline_keyboard.append([InlineKeyboardButton(
            text="Показать ещё", callback_data=f"fmore:{genre_id}:{status}:{year}:{page + 1}",
        )])
    suffix = "" if page == 1 else f" (стр. {page})"
    await msg.answer(f"{esc(_filter_label(gname or '?', status, year))}{suffix}:", reply_markup=kb)


@router.message(Command("filter"))
async def filter_cmd(msg: Message) -> None:
    await send_genres(msg, 0)


@router.message(F.text == BTN_FILTER)
async def filter_btn(msg: Message) -> None:
    await send_genres(msg, 0)


async def send_genres(msg: Message, page: int = 0) -> None:
    try:
        genres = await anilibria.get_genres()
    except Exception:
        genres = []
    if not genres:
        await msg.answer("Жанры недоступны, попробуй позже.", reply_markup=main_menu())
        return
    total_pages = max(1, (len(genres) + GENRES_PER_PAGE - 1) // GENRES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    chunk = genres[page * GENRES_PER_PAGE:(page + 1) * GENRES_PER_PAGE]
    rows = [[InlineKeyboardButton(text=g["name"][:30], callback_data=f"fs:{g['id']}:all")] for g in chunk]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"fgenres:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"fgenres:{page + 1}"))
    if nav:
        rows.append(nav)
    await msg.answer(
        f"Выбери жанр ({page + 1}/{total_pages}):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("fgenres:"))
async def filter_genres_page(cb: CallbackQuery) -> None:
    await cb.answer()
    try:
        await cb.message.delete()
    except Exception:
        pass
    try:
        await send_genres(cb.message, int(cb.data.split(":")[1]))
    except Exception:
        await cb.message.answer("Не получилось, попробуй еще раз.", reply_markup=main_menu())


@router.callback_query(F.data.startswith("fs:"))
async def filter_status(cb: CallbackQuery) -> None:
    """Шаг 2: статус выхода для выбранного жанра."""
    await cb.answer()
    try:
        gid = int(cb.data.split(":")[1])
    except (ValueError, IndexError):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📡 Онгоинги", callback_data=f"fy:{gid}:ongoing:0")],
        [InlineKeyboardButton(text="📚 Все", callback_data=f"fy:{gid}:all:0")],
        [InlineKeyboardButton(text="◀ К жанрам", callback_data="fgenres:0")],
    ])
    try:
        await cb.message.edit_text("Какой статус?", reply_markup=kb)
    except Exception:
        await cb.message.answer("Какой статус?", reply_markup=kb)


@router.callback_query(F.data.startswith("fy:"))
async def filter_year(cb: CallbackQuery) -> None:
    """Шаг 3: год выхода."""
    await cb.answer()
    try:
        _, gid_s, status = cb.data.split(":")
        gid = int(gid_s)
    except (ValueError, IndexError):
        return
    rows = [[InlineKeyboardButton(text=str(y), callback_data=f"ff:{gid}:{status}:{y}")] for y in FILTER_YEARS if y]
    rows.append([InlineKeyboardButton(text="Все годы", callback_data=f"ff:{gid}:{status}:0")])
    rows.append([InlineKeyboardButton(text="◀ К жанрам", callback_data="fgenres:0")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    try:
        await cb.message.edit_text("Какой год?", reply_markup=kb)
    except Exception:
        await cb.message.answer("Какой год?", reply_markup=kb)


@router.callback_query(F.data.startswith("ff:"))
async def filter_results(cb: CallbackQuery) -> None:
    await cb.answer()
    try:
        _, gid_s, status, year_s = cb.data.split(":")
        await do_filter(cb.message, int(gid_s), status, int(year_s), page=1)
    except (ValueError, IndexError):
        return
    except Exception:
        await cb.message.answer("Не получилось, попробуй еще раз.", reply_markup=main_menu())


@router.callback_query(F.data.startswith("fmore:"))
async def filter_more(cb: CallbackQuery) -> None:
    await cb.answer()
    try:
        _, gid_s, status, year_s, page_s = cb.data.split(":")
        await do_filter(cb.message, int(gid_s), status, int(year_s), page=int(page_s))
    except (ValueError, IndexError):
        return
    except Exception:
        await cb.message.answer("Не получилось загрузить, попробуй еще раз.", reply_markup=main_menu())


def _is_admin(uid: int) -> bool:
    return bool(cfg.admin_ids) and uid in cfg.admin_ids


@router.message(Command("stats"))
async def stats_cmd(msg: Message) -> None:
    if not _is_admin(msg.from_user.id):
        await msg.answer("Нет доступа.", reply_markup=main_menu())
        return
    try:
        from .subs import load_counts, load_subs
        subs_list = load_subs(cfg.subs_path)
        counts = load_counts(cfg.counts_path)
        posted = load_posted_ids(cfg.posted_path)
        users = sorted({s["user_id"] for s in subs_list})
        releases = sorted({s["release_id"] for s in subs_list})
        await msg.answer(
            "📊 <b>Статистика</b>\n"
            f"Подписчиков: {len(users)}\n"
            f"Подписок всего: {len(subs_list)}\n"
            f"Отслеживается релизов: {len(releases)}\n"
            f"Постов в канале: {len(posted)}\n"
            f"Счётчиков серий: {len(counts)}",
            reply_markup=main_menu(),
        )
    except Exception:
        await msg.answer("Не смог собрать статистику.", reply_markup=main_menu())


@router.message(Command("post"))
async def post_cmd(msg: Message) -> None:
    if not _is_admin(msg.from_user.id):
        await msg.answer("Нет доступа.", reply_markup=main_menu())
        return
    parts = (msg.text or "").split()
    limit = 3
    if len(parts) > 1 and parts[1].isdigit():
        limit = max(1, min(int(parts[1]), 20))
    status = await msg.answer(f"Пощу свежие ({limit})…", reply_markup=main_menu())
    try:
        n = await parser_post_new(limit)
        await status.edit_text(f"Готово: постов {n}.")
    except Exception:
        try:
            await status.edit_text("Не получилось запостить.")
        except Exception:
            pass


@router.inline_query()
async def inline_search(inline: InlineQuery) -> None:
    """Поиск прямо из любого чата: @бот наруто. Карточки со кнопкой «Смотреть»."""
    q = (inline.query or "").strip()
    if len(q) < 2:
        await inline.answer(
            [], switch_pm_text="Напиши название аниме…",
            switch_pm_parameter="start", cache_time=5,
        )
        return
    try:
        res = await anilibria.search_releases(q, limit=10)
    except Exception:
        await inline.answer([], cache_time=5)
        return
    uname = cfg.bot_username
    out = []
    for r in res[:10]:
        rid = r["id"]
        title = anilibria.title_of(r)
        year = r.get("year") or "?"
        deep = f"https://t.me/{uname}?start=libria_{rid}"
        text = f"<b>{esc(title)} ({esc(year)})</b>\n\nСмотреть и все серии — в боте."
        kb = None
        watch = watch_url_for(r, None)
        if watch:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="▶ Смотреть", url=watch),
            ]])
        img = anilibria.best_poster(r, kind="preview")
        if img:
            out.append(InlineQueryResultPhoto(
                id=str(rid), photo_url=img, thumbnail_url=img,
                caption=text[:1000], parse_mode="HTML", reply_markup=kb,
                description=f"{year}",
            ))
        else:
            out.append(InlineQueryResultArticle(
                id=f"a{rid}", title=f"{title} ({year})",
                input_message_content=InputTextMessageContent(
                    message_text=text + f"\n{deep}", parse_mode="HTML",
                ),
                reply_markup=kb, description="Открыть в боте",
            ))
    await inline.answer(out, cache_time=300, is_personal=False)


def _sync_subs_bg() -> None:
    """Фоновая отправка subscriptions.json в GitHub. Никогда не роняет бота."""
    try:
        import asyncio as _aio

        async def _run() -> None:
            try:
                await _aio.to_thread(
                    subs.push_file_to_github, str(BASE_DIR), "anime-telegram-bot/data/subscriptions.json"
                )
            except Exception:
                pass

        try:
            loop = _aio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(_run())
    except Exception:
        pass


@router.callback_query(F.data.startswith("fav:"))
async def fav(cb: CallbackQuery) -> None:
    try:
        rid = int(cb.data.split(":")[1])
        r = await anilibria.get_release(rid, with_episodes=False)
        title = anilibria.title_of(r)
        await add_fav(cfg.db_path, cb.from_user.id, rid, title)
        try:
            subs.upsert_sub(cfg.subs_path, cb.from_user.id, rid, title)
        except Exception:
            pass
        _sync_subs_bg()
        await cb.answer("⭐ Добавил в избранное + включил уведомления о новых сериях")
    except Exception:
        await cb.answer("Не получилось, попробуй еще раз")


@router.callback_query(F.data.startswith("unfav:"))
async def unfav(cb: CallbackQuery) -> None:
    try:
        rid = int(cb.data.split(":")[1])
        await remove_fav(cfg.db_path, cb.from_user.id, rid)
        try:
            subs.remove_sub(cfg.subs_path, cb.from_user.id, rid)
        except Exception:
            pass
        _sync_subs_bg()
        await cb.answer("Убрал из избранного, уведомления выключены")
    except Exception:
        await cb.answer("Не получилось, попробуй еще раз")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not cfg.bot_token:
        raise SystemExit("Нет BOT_TOKEN. Скопируй .env.example в .env и заполни.")
    import os

    os.makedirs(os.path.dirname(cfg.db_path) or ".", exist_ok=True)
    await init_db(cfg.db_path)
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    await bot.set_my_commands([
        BotCommand(command="start", description="Меню"),
        BotCommand(command="new", description="Новинки 2026"),
        BotCommand(command="search", description="Найти аниме"),
        BotCommand(command="filter", description="Подборка по фильтрам"),
        BotCommand(command="top", description="Топ по рейтингу"),
        BotCommand(command="random", description="Случайное"),
        BotCommand(command="favs", description="Избранное"),
        BotCommand(command="help", description="Помощь"),
    ])
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
