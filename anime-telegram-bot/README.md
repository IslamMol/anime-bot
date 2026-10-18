# Anime Telegram Bot — канал + каталог + WebApp (без токенов для видео)

Видео: AniLiberty API (`anilibria.top`, русская озвучка Anilibria, прямые HLS). Токен не нужен.
Метаданные: AniLibria (каталог/релизы/серии). Shikimori — только для диплинков
`/start anime_<id>` и блока «связанные сезоны» в WebApp; остальное работает без него.

## 1. Получи ключи
- `@BotFather` → `/newbot` → `BOT_TOKEN`, `BOT_USERNAME`
- Создай канал, добавь бота в админы → `CHANNEL_ID` через `@getmyid_bot`
- KODIK НЕ НУЖЕН: сайт kodik.info закрыт (домен истек в 2023), регистрация недоступна. Бот работает без него.

## 2. Запуск
```powershell
cd anime-telegram-bot
pip install -r requirements.txt
copy .env.example .env
notepad .env
python -m src.bot
```

## 3. Автопостинг новинок
```powershell
python -m src.parser --limit 5
```

## 3.1. Уведомления о новых сериях
- ⭐ в карточке подписывает на тайтл, 💔 — отписывает. Подписки лежат в
  `data/subscriptions.json`.
- Парсер каждый запуск сверяет число серий с `data/epcounts.json` и шлет
  «🔔 Новая серия!» в личку подписчикам. Первый замер молча запоминается,
  чтобы не заспамить всех при включении.
- `data/tracked.json` — онгоинги под наблюдением: парсер сам добавляет их при
  посте новинки, а когда релиз завершается — убирает.
- Actions коммитит обратно `posted.json`, `tracked.json` и `epcounts.json`.

### Чтобы подписки доезжали до Actions
Бот при ⭐ коммитит `data/subscriptions.json` в GitHub (лучше запускать его
из клона репозитория — тогда файл попадает в ветку, которую видит Actions;
если папка не git-репозиторий, в логе будет предупреждение и подписки
останутся только локально).
В файле есть `user_id` — это персональные данные. Держи репозиторий приватным.

### Планировщик — ровно один
`anime-parser.yml` крутит парсер каждые 6 часов в Actions. Файлы в `deploy/`
(systemd timer на VPS) — альтернатива, а не дополнение: если включить оба,
один и тот же релиз может уйти в канал дважды.

## 4. WebApp
Залей `webapp/` на https-хостинг, URL впиши в `WEBAPP_URL`.
Плеер сам тянет серии через `anilibria.top/api/v1` и играет HLS через hls.js.

## Структура
- `src/bot.py` — поиск, карточки, /new, избранное
- `src/anilibria.py` — поиск/релизы/серии без токена
- `src/parser.py` — новинки в канал
- `webapp/index.html` — каталог серий + видеоплеер

## Свой сервер (когда будет)
Приложение ходит в сеть только через `getJSON`/`cj` в `webapp/index.html`.
Чтобы воткнуть свой бэкенд вместо публичных API, достаточно отдавать те же JSON-формы:
- `GET /anime/releases/latest?limit=N` → `{data: [release...]}` или `[...]`
- `GET /anime/catalog/releases?f[search]=..&f[years][from_year]=..&f[publish_statuses]=IS_ONGOING&f[sorting]=RATING_DESC&f[genres]=ids&page=N&limit=M` → `{data: [release...]}`
- `GET /anime/releases/{id}` → `release` (поля: id, name{main,english}, poster{src,optimized}, year, type{value,description}, season{description}, age_rating{label}, description, episodes_total, is_ongoing, shikimori{id,rating}, alias)
- `GET /anime/releases/{id}?include=episodes` → `{episodes: [{ordinal, hls_480, hls_720, hls_1080}]}`
- `GET /anime/releases/{id}?include=genres` → `{genres: [{name}]}`
- `GET /anime/genres` → `{data: [{id, name}]}`
- `GET /anime/releases/random` → `release`
- Позиция просмотра сейчас хранится локально (`pos:{release_id}`), синк на сервер — следующим шагом.
