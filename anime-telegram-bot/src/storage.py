"""Безопасная запись JSON-файлов.

Два процесса (бот и GitHub Actions) пишут одни и те же журналы, поэтому
обычный `open(path, "w")` может оставить полупустой файл, если процесс
убьют в момент записи. Пишем во временный файл рядом и подменяем атомарно:
читатель увидит либо старую версию, либо новую, но никогда — обрезанную.
"""
import json
import os
import tempfile


def read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError, TypeError):
        return default


def write_json_atomic(path: str, data, indent: int = 1) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=folder or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # атомарно в пределах одной файловой системы
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
