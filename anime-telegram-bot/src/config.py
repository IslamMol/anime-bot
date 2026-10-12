"""Общая конфигурация из .env."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# корень проекта (папка с webapp/, src/, data/) — база всегда там,
# из какой бы папки ни запускали бота, иначе избранное «теряется»
BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    bot_token: str
    bot_username: str
    channel_id: str
    webapp_url: str
    db_path: str
    posted_path: str
    subs_path: str
    counts_path: str


def _join(base: Path, raw: str) -> str:
    return raw if os.path.isabs(raw) else str(base / raw)


def load_config() -> Config:
    raw_webapp = os.getenv("WEBAPP_URL", "").rstrip("/")
    return Config(
        bot_token=os.getenv("BOT_TOKEN", ""),
        bot_username=os.getenv("BOT_USERNAME", ""),
        channel_id=os.getenv("CHANNEL_ID", ""),
        webapp_url=(raw_webapp + "/" if raw_webapp else ""),
        db_path=_join(BASE_DIR, os.getenv("DB_PATH", "./data/bot.db")),
        posted_path=_join(BASE_DIR, os.getenv("POSTED_PATH", "./data/posted.json")),
        subs_path=_join(BASE_DIR, os.getenv("SUBS_PATH", "./data/subscriptions.json")),
        counts_path=_join(BASE_DIR, os.getenv("COUNTS_PATH", "./data/epcounts.json")),
    )
