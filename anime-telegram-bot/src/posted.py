"""Журнал опубликованных в канал постов: простой JSON-сет ID.

Зачем отдельно от SQLite: GitHub Actions каждый запуск стартует с чистой
машины, и SQLite-база не переживает перезапуск. А этот JSON лежит в репо,
Actions коммитит его обратно — и ни один релиз не постится дважды.
Локально бот продолжает пользоваться SQLite (там же еще и избранное).
"""
import json
import os


def load_posted_ids(path: str) -> set[int]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {int(x) for x in data} if isinstance(data, list) else set()
    except (FileNotFoundError, ValueError, TypeError):
        return set()


def save_posted_ids(path: str, ids: set[int]) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=1)
        f.write("\n")
