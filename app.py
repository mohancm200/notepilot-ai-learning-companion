
import os
import logging
from datetime import datetime, timezone
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, session, redirect, url_for

from db import get_db_connection
from auth import auth
from admin import admin

load_dotenv()

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "development-key-change-before-deployment"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

app.register_blueprint(auth)
app.register_blueprint(admin)

logging.basicConfig(level=logging.INFO)


def student_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))

        if session.get("role") != "user":
            return redirect("/admin/")

        return func(*args, **kwargs)
    return wrapper


@app.get("/")
def home():
    if session.get("role") == "admin":
        return redirect("/admin/")

    if session.get("role") == "user":
        return redirect("/dashboard")

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
            a { color: #c6bdff; }
        </style>
    </head>
    <body>
        <main>
            <h1>NotePilot</h1>
            <p>Welcome to your AI-powered learning companion.</p>
            <p>Learn smarter. Revise faster. Understand better.</p>
            <a href="/login">Login / Register</a>
        </main>
    </body>
    </html>
    """


@app.get("/login")
def login_page():
    if session.get("role") == "admin":
        return redirect("/admin/")

    if session.get("role") == "user":
        return redirect("/dashboard")

    return render_template("auth.html")


@app.get("/dashboard")
@student_required
def student_dashboard():
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS total FROM notes WHERE user_id = %s",
                (session["user_id"],)
            )
            total_notes = cursor.fetchone()["total"]

            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM quiz_attempts
                WHERE user_id = %s
                """,
                (session["user_id"],)
            )
            total_quizzes = cursor.fetchone()["total"]

            cursor.execute(
                """
                SELECT COALESCE(AVG(score), 0) AS average_score
                FROM quiz_attempts
                WHERE user_id = %s
                """,
                (session["user_id"],)
            )
            average_score = round(
                float(cursor.fetchone()["average_score"]), 1
            )

            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM flashcards f
                JOIN notes n ON n.id = f.note_id
                WHERE n.user_id = %s
                """,
                (session["user_id"],)
            )
            total_flashcards = cursor.fetchone()["total"]

        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>NotePilot | Student Dashboard</title>
            <style>
                * {{ box-sizing: border-box; }}
                body {{
                    margin: 0;
                    font-family: Arial, sans-serif;
                    background: #101426;
                    color: #f4f5fb;
                }}
                header {{
                    padding: 25px 5%;
                    background: #1a2038;
                    border-bottom: 1px solid #343b59;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }}
                h1 {{ color: #a99bff; margin: 0; }}
                main {{ padding: 35px 5%; }}
                .stats {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                    gap: 20px;
                }}
                .card {{
                    padding: 25px;
                    background: #1a2038;
                    border: 1px solid #343b59;
                    border-radius: 15px;
                }}
                .card p {{ color: #aeb5cc; }}
                .card h2 {{ color: #b4a6ff; font-size: 32px; }}
                .links {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                    gap: 15px;
                    margin-top: 30px;
                }}
                .links a {{
                    padding: 20px;
                    background: #252b48;
                    color: white;
                    text-decoration: none;
                    border-radius: 12px;
                }}
                .links a:hover {{ background: #37305f; }}
                button {{
                    background: #806ee8;
                    border: 0;
                    padding: 11px 18px;
                    color: white;
                    border-radius: 8px;
                    cursor: pointer;
                }}
            </style>
        </head>
        <body>
            <header>
                <h1>NotePilot</h1>
                <span>Welcome, {session["user_name"]}</span>
                <button onclick="logout()">Logout</button>
            </header>
            <main>
                <h2>Your Learning Dashboard</h2>
                <p>Track your learning and improve every day.</p>

                <section class="stats">
                    <div class="card">
                        <p>Notes Generated</p>
                        <h2>{total_notes}</h2>
                    </div>
                    <div class="card">
                        <p>Quizzes Attempted</p>
                        <h2>{total_quizzes}</h2>
                    </div>
                    <div class="card">
                        <p>Average Score</p>
                        <h2>{average_score}%</h2>
                    </div>
                    <div class="card">
                        <p>Flashcard Sets</p>
                        <h2>{total_flashcards}</h2>
                    </div>
                </section>

                <section class="links">
                    <a href="#">Generate Notes – Coming Soon</a>
                    <a href="#">Ask AI – Coming Soon</a>
                    <a href="#">My Library – Coming Soon</a>
                    <a href="#">Flashcards – Coming Soon</a>
                    <a href="#">Quiz Centre – Coming Soon</a>
                    <a href="#">Learning Analytics – Coming Soon</a>
                </section>
            </main>
            <script>
                async function logout() {{
                    await fetch("/auth/logout", {{method: "POST"}});
                    window.location.href = "/login";
                }}
            </script>
        </body>
        </html>
        """

    finally:
        connection.close()


@app.get("/logout")
def logout_page():
    session.clear()
    return redirect("/login")


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
