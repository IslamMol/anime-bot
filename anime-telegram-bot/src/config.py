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


def load_config() -> Config:
    raw_webapp = os.getenv("WEBAPP_URL", "").rstrip("/")
    raw_db = os.getenv("DB_PATH", "./data/bot.db")
    db_path = raw_db if os.path.isabs(raw_db) else str(BASE_DIR / raw_db)
    raw_posted = os.getenv("POSTED_PATH", "./data/posted.json")
    posted_path = raw_posted if os.path.isabs(raw_posted) else str(BASE_DIR / raw_posted)
    return Config(
        bot_token=os.getenv("BOT_TOKEN", ""),
        bot_username=os.getenv("BOT_USERNAME", ""),
        channel_id=os.getenv("CHANNEL_ID", ""),
        webapp_url=(raw_webapp + "/" if raw_webapp else ""),
        db_path=db_path,
        posted_path=posted_path,
    )
