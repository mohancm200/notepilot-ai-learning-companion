
import os
import json
import logging
import urllib.request
import urllib.error
import socket

from datetime import datetime, timezone
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    render_template,
    session,
    redirect,
    url_for,
    request,
    flash
)

from db import get_db_connection
from auth import auth
from admin import admin
from ask import ask


# ==========================================================
# CONFIGURATION
# ==========================================================

load_dotenv()

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "development-key-change-before-deployment"
)

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

logging.basicConfig(level=logging.INFO)
logger = app.logger


# ==========================================================
# REGISTER BLUEPRINTS
# ==========================================================

app.register_blueprint(auth)
app.register_blueprint(admin)
app.register_blueprint(ask)


# ==========================================================
# GEMINI CONFIGURATION
# ==========================================================

GEMINI_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
    "gemini-flash-latest"
]

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/"
    "v1beta/models/{model}:generateContent"
)


# ==========================================================
# LOGIN DECORATORS
# ==========================================================

def login_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login_page"))

        return func(*args, **kwargs)

    return wrapper


def student_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login_page"))

        if session.get("role") != "user":
            return redirect("/admin/")

        return func(*args, **kwargs)

    return wrapper


# ==========================================================
# GEMINI API REQUEST
# ==========================================================

def call_gemini(model, prompt):

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is missing from your .env file."
        )

    url = (
        GEMINI_API_URL.format(model=model)
        + "?key="
        + api_key
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json"
        }
    }

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:

        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

        candidates = result.get("candidates", [])

        if not candidates:
            raise ValueError("Gemini returned no candidates.")

        parts = candidates[0].get(
            "content", {}
        ).get("parts", [])

        if not parts:
            raise ValueError("Gemini returned an empty response.")

        generated_text = parts[0].get("text", "")

        if not generated_text:
            raise ValueError("Gemini returned empty text.")

        return generated_text

    except urllib.error.HTTPError as error:

        details = error.read().decode(
            "utf-8",
            errors="replace"
        )

        logger.error(
            "Gemini model %s returned HTTP %s. Response: %s",
            model,
            error.code,
            details
        )

        raise RuntimeError(
            f"Gemini HTTP {error.code}: {details}"
        )

    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout
    ) as error:

        logger.error(
            "Gemini model %s connection failed: %s",
            model,
            str(error)
        )

        raise RuntimeError(
            f"Gemini connection failed: {error}"
        )


# ==========================================================
# GENERATE AI NOTES
# ==========================================================

def generate_ai_content(source_text):

    prompt = f"""
You are NotePilot, an expert AI learning assistant.

Analyze the following study material and generate
useful and understandable study notes.

Return ONLY valid JSON using this structure:

{{
    "summary": "A clear and detailed summary",
    "key_points": [
        "Important point 1",
        "Important point 2",
        "Important point 3"
    ],
    "action_items": [
        "Revision task 1",
        "Practice task 2"
    ]
}}

Instructions:
1. Use simple language.
2. Preserve important technical terms.
3. Do not invent information.
4. Make the summary useful for college examinations.
5. Return valid JSON only.

STUDY MATERIAL:

{source_text}
"""

    errors = []

    for model in GEMINI_MODELS:

        try:

            logger.info("Trying Gemini model: %s", model)

            generated_text = call_gemini(model, prompt)
            generated_text = generated_text.strip()

            if generated_text.startswith("```"):
                generated_text = (
                    generated_text
                    .replace("```json", "")
                    .replace("```", "")
                    .strip()
                )

            result = json.loads(generated_text)

            if not isinstance(result.get("summary"), str):
                raise ValueError("Invalid summary returned by AI.")

            if not isinstance(result.get("key_points"), list):
                raise ValueError("Invalid key points returned by AI.")

            if not isinstance(result.get("action_items"), list):
                raise ValueError("Invalid action items returned by AI.")

            logger.info(
                "Notes generated successfully using %s",
                model
            )

            return result

        except Exception as error:

            logger.error(
                "Gemini model %s failed: %s",
                model,
                str(error)
            )

            errors.append(f"{model}: {str(error)}")

    logger.error(
        "All Gemini models failed: %s",
        "; ".join(errors)
    )

    raise ValueError(
        "AI note generation failed. Check the VS Code terminal."
    )


# ==========================================================
# HOME PAGE
# ==========================================================

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
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>NotePilot</title>
        <style>
            body {
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                font-family: Arial, sans-serif;
                background: #101426;
                color: white;
            }
            main {
                padding: 40px;
                background: #1a2038;
                border: 1px solid #343b59;
                border-radius: 20px;
            }
            h1 { color: #a99bff; }
            a { color: #c6bdff; }
        </style>
    </head>
    <body>
        <main>
            <h1>NotePilot</h1>
            <p>Your AI-powered learning companion.</p>
            <a href="/login">Login / Register</a>
        </main>
    </body>
    </html>
    """


# ==========================================================
# LOGIN PAGE
# ==========================================================

@app.get("/login")
def login_page():

    if session.get("role") == "admin":
        return redirect("/admin/")

    if session.get("role") == "user":
        return redirect("/dashboard")

    return render_template("auth.html")


# ==========================================================
# STUDENT DASHBOARD
# ==========================================================

@app.get("/dashboard")
@student_required
def student_dashboard():

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM notes
                WHERE user_id = %s
                """,
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
                float(cursor.fetchone()["average_score"]),
                1
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

        return render_template(
            "student_dashboard.html",
            user_name=session.get("user_name", "Student"),
            total_notes=total_notes,
            total_quizzes=total_quizzes,
            average_score=average_score,
            total_flashcards=total_flashcards
        )

    finally:
        connection.close()


# ==========================================================
# NOTES PAGE
# ==========================================================

@app.get("/notes")
@student_required
def notes():

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT id, title, summary, created_at
                FROM notes
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (session["user_id"],)
            )

            notes_list = cursor.fetchall()

        return render_template(
            "notes.html",
            notes=notes_list
        )

    finally:
        connection.close()


# ==========================================================
# AJAX SEARCH AND FILTER SAVED NOTES
# ==========================================================

@app.get("/api/notes/search")
@student_required
def search_notes():

    search_query = request.args.get(
        "q", ""
    ).strip()

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT id, title, summary, created_at
                FROM notes
                WHERE user_id = %s
                  AND title LIKE %s
                ORDER BY created_at DESC
                """,
                (
                    session["user_id"],
                    f"%{search_query}%"
                )
            )

            results = cursor.fetchall()

        notes_data = []

        for note in results:

            created_at = note["created_at"]

            if created_at:
                created_at = str(created_at)
            else:
                created_at = ""

            summary = note.get("summary") or ""

            notes_data.append({
                "id": note["id"],
                "title": note["title"],
                "summary": summary[:250],
                "created_at": created_at
            })

        return jsonify({
            "success": True,
            "count": len(notes_data),
            "notes": notes_data
        }), 200

    except Exception:

        logger.exception("AJAX note search failed")

        return jsonify({
            "success": False,
            "error": "Unable to search notes."
        }), 500

    finally:
        connection.close()


# ==========================================================
# GENERATE NOTES
# ==========================================================

@app.post("/notes/generate")
@student_required
def generate_notes():

    title = request.form.get("title", "").strip()
    source_text = request.form.get("source_text", "").strip()
    uploaded_file = request.files.get("study_file")

    if uploaded_file and uploaded_file.filename:

        if not uploaded_file.filename.lower().endswith(".txt"):
            flash(
                "Currently, only TXT files are supported.",
                "error"
            )
            return redirect(url_for("notes"))

        try:
            source_text = uploaded_file.read().decode(
                "utf-8",
                errors="replace"
            ).strip()

        except Exception:
            flash("Unable to read this text file.", "error")
            return redirect(url_for("notes"))

    if not title:
        title = "Untitled Study Notes"

    if not source_text:
        flash(
            "Please enter or upload study material.",
            "error"
        )
        return redirect(url_for("notes"))

    if len(source_text) > 30000:
        flash(
            "Study material must be under 30,000 characters.",
            "error"
        )
        return redirect(url_for("notes"))

    try:
        ai_result = generate_ai_content(source_text)

    except Exception:
        logger.exception("AI notes generation failed")
        flash(
            "AI note generation failed. Check the VS Code terminal.",
            "error"
        )
        return redirect(url_for("notes"))

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO notes (
                    user_id,
                    title,
                    source_text,
                    summary,
                    key_points,
                    action_items,
                    word_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session["user_id"],
                    title,
                    source_text,
                    ai_result["summary"],
                    json.dumps(ai_result["key_points"]),
                    json.dumps(ai_result["action_items"]),
                    len(source_text.split())
                )
            )

        connection.commit()

        flash(
            "Your AI notes were generated successfully!",
            "success"
        )

        return redirect(url_for("notes"))

    except Exception:
        connection.rollback()
        logger.exception("Saving generated notes failed")
        flash(
            "Could not save your notes. Please try again.",
            "error"
        )
        return redirect(url_for("notes"))

    finally:
        connection.close()


# ==========================================================
# VIEW SAVED NOTE
# ==========================================================

@app.get("/notes/<int:note_id>")
@student_required
def view_note(note_id):

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    title,
                    source_text,
                    summary,
                    key_points,
                    action_items,
                    created_at
                FROM notes
                WHERE id = %s AND user_id = %s
                """,
                (note_id, session["user_id"])
            )

            note = cursor.fetchone()

        if not note:
            flash(
                "Note not found or you do not have access.",
                "error"
            )
            return redirect(url_for("notes"))

        for field in ("key_points", "action_items"):

            value = note.get(field)

            if isinstance(value, str):
                try:
                    note[field] = json.loads(value)
                except (ValueError, TypeError):
                    note[field] = []

            elif not isinstance(value, list):
                note[field] = []

        if note.get("source_text") is None:
            note["source_text"] = ""

        if note.get("summary") is None:
            note["summary"] = ""

        logger.info(
            "Opening note ID %s for user ID %s",
            note_id,
            session["user_id"]
        )

        return render_template(
            "note_detail.html",
            note=note
        )

    except Exception:
        logger.exception(
            "VIEW NOTE ERROR - Note ID: %s",
            note_id
        )
        flash(
            "Unable to open this note. Check the VS Code terminal.",
            "error"
        )
        return redirect(url_for("notes"))

    finally:

        if connection is not None:
            connection.close()


# ==========================================================
# LOGOUT
# ==========================================================

@app.get("/logout")
def logout_page():

    session.clear()
    return redirect(url_for("login_page"))


# ==========================================================
# HEALTH CHECK
# ==========================================================

@app.get("/health")
def health_check():

    return jsonify(
        status="ok",
        application="NotePilot",
        timestamp=datetime.now(timezone.utc).isoformat()
    ), 200


# ==========================================================
# DATABASE CHECK
# ==========================================================

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
        logger.exception("Database connection failed")
        return jsonify(status="not_connected"), 503

    finally:

        if connection is not None:
            connection.close()


# ==========================================================
# FILE SIZE ERROR
# ==========================================================

@app.errorhandler(413)
def file_too_large(error):

    return (
        "File is too large. Maximum upload size is 5 MB.",
        413
    )


# ==========================================================
# APPLICATION START
# ==========================================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "1").lower()
        in {"1", "true", "yes"}
    )
