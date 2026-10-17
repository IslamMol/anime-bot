"""Подписки на выход новых серий + счетчики серий. Два JSON в репо.

subscriptions.json: [{"user_id": int, "release_id": int, "title": str}]
epcounts.json: {"<release_id>": <доступно серий>}

Локальный бот пишет subscriptions.json при ⭐/убирании из избранного и пушит
в GitHub (best effort, фоном). Парсер в Actions читает подписки, сверяет
счетчики и шлет уведомления, а epcounts.json коммитит обратно.
"""
import logging
import subprocess

from .storage import read_json, write_json_atomic

log = logging.getLogger("subs")


def load_subs(path: str) -> list[dict]:
    data = read_json(path, [])
    out = []
    for s in data if isinstance(data, list) else []:
        if isinstance(s, dict) and s.get("user_id") and s.get("release_id"):
            try:
                out.append({
                    "user_id": int(s["user_id"]),
                    "release_id": int(s["release_id"]),
                    "title": str(s.get("title") or ""),
                })
            except (TypeError, ValueError):
                continue
    return out


def save_subs(path: str, subs: list[dict]) -> None:
    subs = sorted(subs, key=lambda s: (s["user_id"], s["release_id"]))
    write_json_atomic(path, subs)


def upsert_sub(path: str, user_id: int, release_id: int, title: str) -> None:
    subs = [s for s in load_subs(path) if not (s["user_id"] == user_id and s["release_id"] == release_id)]
    subs.append({"user_id": user_id, "release_id": release_id, "title": title})
    save_subs(path, subs)


def remove_sub(path: str, user_id: int, release_id: int) -> None:
    subs = [s for s in load_subs(path) if not (s["user_id"] == user_id and s["release_id"] == release_id)]
    save_subs(path, subs)


def load_counts(path: str) -> dict[str, int]:
    data = read_json(path, {})
    if not isinstance(data, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in data.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def save_counts(path: str, counts: dict[str, int]) -> None:
    write_json_atomic(path, {k: int(v) for k, v in sorted(counts.items())})


def push_file_to_github(repo_dir: str, rel_path: str, timeout: int = 90) -> bool:
    """Коммит + пуш одного файла. Best effort: при любой ошибке просто False."""
    try:
        def run(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                ["git", *args], cwd=repo_dir, capture_output=True,
                text=True, timeout=timeout,
            )
        if run("rev-parse", "--git-dir").returncode != 0:
            return False
        run("add", rel_path)
        chk = run("diff", "--cached", "--quiet")
        if chk.returncode == 0:
            return True  # менять нечего
        run("config", "user.name", "anime-bot")
        run("config", "user.email", "anime-bot@localhost")
        if run("commit", "-m", f"chore: update {rel_path} [skip ci]").returncode != 0:
            return False
        if run("push").returncode != 0:
            # remote ушел вперед (Actions закоммитил) — подтягиваемся и повторяем
            run("pull", "--rebase")
            if run("push").returncode != 0:
                return False
        return True
    except Exception as e:  # noqa: BLE001 — фоновая задача, падать нельзя
        log.warning("git sync failed: %s", e)
        return False
