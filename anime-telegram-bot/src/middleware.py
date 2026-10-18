"""Антифлуд: не даем одному человеку завалить внешние API и Telegram.

Считаем события в скользящем окне. Лимит мягкий: обычный человек, который
листает результаты и жмет кнопки, в него не упирается, а скрипт — упирается.
"""
import time
from collections import defaultdict, deque

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

THROTTLE_TEXT = "Слишком часто. Подожди пару секунд."


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, limit: int = 12, window: float = 10.0) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[int, deque[float]] = defaultdict(deque)
        self._warned: dict[int, float] = {}

    def _prune(self, now: float) -> None:
        # чтобы словари не росли бесконечно на большом числе пользователей
        if len(self._hits) < 2000:
            return
        for uid in [u for u, q in self._hits.items() if not q or now - q[-1] > self.window]:
            self._hits.pop(uid, None)
        # _warned чистим вместе с _hits, иначе он тихо растет по всем, кого предупреждали
        for uid, ts in [i for i in self._warned.items() if now - i[1] > self.window]:
            self._warned.pop(uid, None)

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        uid = getattr(user, "id", None)
        if uid is None:
            return await handler(event, data)

        now = time.monotonic()
        q = self._hits[uid]
        while q and now - q[0] > self.window:
            q.popleft()

        if len(q) >= self.limit:
            # предупреждаем один раз за окно, иначе сам ответ станет флудом
            last = self._warned.get(uid, 0.0)
            if now - last > self.window:
                self._warned[uid] = now
                # важно ответить на callback, иначе у клиента крутится «часики»
                if isinstance(event, CallbackQuery):
                    await event.answer(THROTTLE_TEXT, show_alert=False)
                else:
                    answer = getattr(event, "answer", None)
                    if answer is not None:
                        await answer(THROTTLE_TEXT)
            elif isinstance(event, CallbackQuery):
                await event.answer()  # закрыть «часики» молча
            return None

        q.append(now)
        self._prune(now)
        return await handler(event, data)
