import os

USER_BOT_TOKEN = os.environ["USER_BOT_TOKEN"]
ADMIN_BOT_TOKEN = os.environ["ADMIN_BOT_TOKEN"]
ADMIN_USER_ID = int(os.environ["ADMIN_USER_ID"])

DB_PATH = os.environ.get("DB_PATH", "data/bot.sqlite3")
PAGE_SIZE = 5
