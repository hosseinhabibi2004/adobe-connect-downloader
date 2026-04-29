from pathlib import Path
from zoneinfo import ZoneInfo

from decouple import config
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

TEMP_DIR = BASE_DIR.parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)

OUTPUT_DIR = BASE_DIR.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

TIMEZONE = ZoneInfo(config("TIMEZONE", default="UTC"))

REDIS_HOST = config("REDIS_HOST", default="localhost")
REDIS_PORT = config("REDIS_PORT", cast=int, default=6379)
REDIS_DB = config("REDIS_DB", cast=int, default=0)
