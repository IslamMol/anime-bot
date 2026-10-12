"""Подписки на выход новых серий + счетчики серий. Два JSON в репо.

subscriptions.json: [{"user_id": int, "release_id": int, "title": str}]
epcounts.json: {"<release_id>": <доступно серий>}

Локальный бот пишет subscriptions.json при ⭐/убирании из избранного и пушит
в GitHub (best effort, фоном). Парсер в Actions читает подписки, сверяет
счетчики и шлет уведомления, а epcounts.json коммитит обратно.
"""
import json
import logging
import os
import subprocess

log = logging.getLogger("subs")


def load_subs(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        out = []
        for s in data if isinstance(data, list) else []:
            if isinstance(s, dict) and s.get("user_id") and s.get("release_id"):
                out.append({
                    "user_id": int(s["user_id"]),
                    "release_id": int(s["release_id"]),
                    "title": str(s.get("title") or ""),
                })
        return out
    except (FileNotFoundError, ValueError, TypeError):
        return []


def save_subs(path: str, subs: list[dict]) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    subs = sorted(subs, key=lambda s: (s["user_id"], s["release_id"]))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=1)
        f.write("\n")


def upsert_sub(path: str, user_id: int, release_id: int, title: str) -> None:
    subs = [s for s in load_subs(path) if not (s["user_id"] == user_id and s["release_id"] == release_id)]
    subs.append({"user_id": user_id, "release_id": release_id, "title": title})
    save_subs(path, subs)


def remove_sub(path: str, user_id: int, release_id: int) -> None:
    subs = [s for s in load_subs(path) if not (s["user_id"] == user_id and s["release_id"] == release_id)]
    save_subs(path, subs)


def load_counts(path: str) -> dict[str, int]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, TypeError, AttributeError):
        return {}


def save_counts(path: str, counts: dict[str, int]) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: int(v) for k, v in sorted(counts.items())}, f, ensure_ascii=False, indent=1)
        f.write("\n")


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
