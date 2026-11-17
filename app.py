
import os
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify
from db import get_db_connection

load_dotenv()

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "development-key-change-before-deployment"
)

logging.basicConfig(level=logging.INFO)


@app.get("/")
def home():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>NotePilot | AI Learning Companion</title>
        <style>
            * { box-sizing: border-box; }

            body {
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                font-family: Arial, sans-serif;
                background: #101426;
                color: #f4f5fb;
            }

            main {
                width: min(620px, 90%);
                padding: 40px;
                border: 1px solid #343b59;
                border-radius: 20px;
                background: #1a2038;
            }

            h1 { color: #a99bff; font-size: 36px; }
            p { color: #d1d5e5; line-height: 1.7; }
            a { color: #c6bdff; margin-right: 16px; }
        </style>
    </head>
    <body>
        <main>
            <h1>NotePilot</h1>
            <p>Welcome to your AI-powered learning companion.</p>
            <p>Your application server is running successfully.</p>
            <a href="/health">Health Check</a>
            <a href="/db-check">Database Check</a>
        </main>
    </body>
    </html>
    """


@app.get("/health")
def health_check():
    return jsonify(
        status="ok",
        application="NotePilot",
        timestamp=datetime.now(timezone.utc).isoformat()
    ), 200


@app.get("/db-check")
def database_check():
    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE() AS database_name")
            result = cursor.fetchone()

        return jsonify(
            status="connected",
            database=result["database_name"]
        ), 200

    except Exception:
        app.logger.exception("Database connection failed")

        return jsonify(
            status="not_connected",
            message="Check MySQL and database configuration."
        ), 503

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "1").lower()
        in {"1", "true", "yes"}
    )
