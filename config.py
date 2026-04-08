from dotenv import load_dotenv
import os

load_dotenv()

def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Отсутствует обязательная переменная окружения: {key}")
    return value

def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default)

DISCORD_TOKEN: str = _require("DISCORD_TOKEN")
GUILD_ID: int = int(_require("GUILD_ID"))
WELCOME_CHANNEL_ID: int = int(_optional("WELCOME_CHANNEL_ID", "0")) or None
