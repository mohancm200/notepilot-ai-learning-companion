
import os
import pymysql
from dotenv import load_dotenv

load_dotenv()


def get_db_connection():
    """Create and return a MySQL database connection."""

    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "notepilot_db"),
        connect_timeout=5,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
