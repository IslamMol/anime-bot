"""Журнал опубликованных в канал постов: простой JSON-сет ID.

Зачем отдельно от SQLite: GitHub Actions каждый запуск стартует с чистой
машины, и SQLite-база не переживает перезапуск. А этот JSON лежит в репо,
Actions коммитит его обратно — и ни один релиз не постится дважды.
Локально бот продолжает пользоваться SQLite (там же еще и избранное).
"""
from .storage import read_json, write_json_atomic


def load_posted_ids(path: str) -> set[int]:
    data = read_json(path, [])
    if not isinstance(data, list):
        return set()
    out: set[int] = set()
    for x in data:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out


def save_posted_ids(path: str, ids: set[int]) -> None:
    write_json_atomic(path, sorted(ids))


def load_tracked(path: str) -> dict[str, dict]:
    """Онгоинги под наблюдением: {"rid": {title, year, type, count}}.
    Отдельно от posted.json: тот — «что уже постили как новинку»,
    этот — «за какими сериями следим». Оба коммитятся обратно в Actions."""
    data = read_json(path, {})
    return data if isinstance(data, dict) else {}


def save_tracked(path: str, tracked: dict[str, dict]) -> None:
    write_json_atomic(path, tracked)
