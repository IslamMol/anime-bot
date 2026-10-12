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
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from . import anilibria, animego, shikimori
from .config import load_config
from .db import add_fav, init_db, list_favs

router = Router()
cfg = load_config()

BTN_SEARCH = "🔍 Найти аниме"
BTN_NEW = "🆕 Новинки 2026"
BTN_RANDOM = "🎲 Случайное"
BTN_FAVS = "⭐ Избранное"
BTN_APP = "📱 Приложение"
BTN_HELP = "❓ Помощь"
BTN_CANCEL = "✖ Отмена"


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
    rows.append([KeyboardButton(text=BTN_HELP)])
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
        "v": "8",
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


def kb_card(release: dict, alt_url: str | None = None) -> InlineKeyboardMarkup:
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
    rows.append([InlineKeyboardButton(text="⭐ В избранное", callback_data=f"fav:{rid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def do_search(msg: Message, query: str) -> None:
    try:
        res = await anilibria.search_releases(query, limit=5)
    except Exception:
        await msg.answer("Поиск временно недоступен, попробуй еще раз.", reply_markup=main_menu())
        return
    if not res:
        await msg.answer(f'По «{esc(query)}» ничего не нашел. Попробуй другое название.', reply_markup=main_menu())
        return
    if len(res) == 1:
        await send_card_by_libria(msg, res[0]["id"])
        return
    await msg.answer(f'По «{esc(query)}» нашел, выбери:', reply_markup=kb_search(res))


async def send_card_by_libria(msg: Message, release_id: int) -> None:
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
    img = anilibria.poster_url((r.get("poster") or {}).get("src", ""))
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
        if img:
            await msg.answer_photo(img, caption=caption[:1000], reply_markup=kb_card(r, alt_url))
        else:
            await msg.answer(caption[:1000], reply_markup=kb_card(r, alt_url))
    except Exception:
        await msg.answer("Не получилось отправить карточку, попробуй еще раз.", reply_markup=main_menu())


HELP_TEXT = (
    "Как пользоваться:\n"
    f"{BTN_APP} — мини-приложение: главная, поиск, избранное\n"
    f"{BTN_SEARCH} — напиши название, покажу карточки с плеером\n"
    f"{BTN_NEW} — топ онгоингов 2026 года\n"
    f"{BTN_RANDOM} — случайное аниме\n"
    f"{BTN_FAVS} — твое избранное\n\n"
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


@router.message(F.text == BTN_NEW)
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


@router.message(F.text == BTN_RANDOM)
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


@router.message(F.text == BTN_FAVS)
async def favs_btn(msg: Message) -> None:
    await favs_cmd(msg)


@router.message(Command("search"))
async def search_cmd(msg: Message, state: FSMContext) -> None:
    parts = msg.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        await do_search(msg, parts[1].strip())
        return
    await state.set_state(SearchStates.waiting_query)
    await msg.answer(
        "Напиши название аниме:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
            resize_keyboard=True,
        ),
    )


@router.message(F.text == BTN_SEARCH)
async def search_btn(msg: Message, state: FSMContext) -> None:
    await state.set_state(SearchStates.waiting_query)
    await msg.answer(
        "Напиши название аниме:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
            resize_keyboard=True,
        ),
    )


@router.message(StateFilter(SearchStates.waiting_query))
async def search_query(msg: Message, state: FSMContext) -> None:
    if msg.text == BTN_CANCEL:
        await state.clear()
        await msg.answer("Поиск отменен.", reply_markup=main_menu())
        return
    await state.clear()
    await do_search(msg, msg.text.strip())


@router.message(F.text.len() >= 2)
async def search_free(msg: Message) -> None:
    # свободный ввод тоже ищет — кнопки не обязательны
    await do_search(msg, msg.text.strip())


@router.callback_query(F.data.startswith("lib:"))
async def view(cb: CallbackQuery) -> None:
    await cb.answer()
    try:
        await send_card_by_libria(cb.message, int(cb.data.split(":")[1]))
    except Exception:
        await cb.message.answer("Не получилось загрузить, попробуй еще раз.", reply_markup=main_menu())


@router.callback_query(F.data.startswith("fav:"))
async def fav(cb: CallbackQuery) -> None:
    try:
        rid = int(cb.data.split(":")[1])
        r = await anilibria.get_release(rid, with_episodes=False)
        await add_fav(cfg.db_path, cb.from_user.id, rid, anilibria.title_of(r))
        await cb.answer("⭐ Добавил в избранное")
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
        BotCommand(command="random", description="Случайное"),
        BotCommand(command="favs", description="Избранное"),
        BotCommand(command="help", description="Помощь"),
    ])
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
