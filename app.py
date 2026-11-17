
import os
import json
import logging
import urllib.request
import urllib.error
import socket

from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify
)

from dotenv import load_dotenv
from db import get_db_connection
from auth import auth
from admin import admin

load_dotenv()

# --------------------------------------------------
# APPLICATION CONFIGURATION
# --------------------------------------------------

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

logging.basicConfig(level=logging.INFO)
logger = app.logger

app.register_blueprint(auth)
app.register_blueprint(admin)


# --------------------------------------------------
# GEMINI CONFIGURATION
# --------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

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


# --------------------------------------------------
# LOGIN DECORATORS
# --------------------------------------------------

def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login to continue.", "error")
            return redirect(url_for("login"))

        return func(*args, **kwargs)

    return wrapper


def student_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login to continue.", "error")
            return redirect(url_for("login"))

        if session.get("role") == "admin":
            return redirect("/admin/")

        return func(*args, **kwargs)

    return wrapper


# --------------------------------------------------
# GEMINI API REQUEST
# --------------------------------------------------

def call_gemini(model, prompt):

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is missing from your .env file."
        )

    url = (
        GEMINI_API_URL.format(model=model)
        + "?key="
        + GEMINI_API_KEY
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
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            response_data = response.read().decode("utf-8")
            result = json.loads(response_data)

        candidates = result.get("candidates", [])

        if not candidates:
            raise ValueError(
                "Gemini returned no response candidates."
            )

        parts = candidates[0].get("content", {}).get("parts", [])

        if not parts:
            raise ValueError(
                "Gemini returned an empty response."
            )

        generated_text = parts[0].get("text", "")

        if not generated_text:
            raise ValueError(
                "Gemini returned empty generated text."
            )

        return generated_text

    except urllib.error.HTTPError as error:

        # Read Google's actual error response.
        error_body = error.read().decode(
            "utf-8",
            errors="replace"
        )

        logger.error(
            "Gemini model %s returned HTTP %s. Response: %s",
            model,
            error.code,
            error_body
        )

        raise RuntimeError(
            f"Gemini HTTP {error.code}: {error_body}"
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
            f"Connection failed: {error}"
        )


# --------------------------------------------------
# GENERATE AI CONTENT WITH MODEL FALLBACK
# --------------------------------------------------

def generate_ai_content(source_text):

    prompt = f"""
You are NotePilot, an AI learning companion.

Analyze the following study material and generate useful
study notes for a college student.

Return ONLY valid JSON in this exact structure:

{{
    "summary": "A clear and detailed summary",
    "key_points": [
        "Important point 1",
        "Important point 2",
        "Important point 3"
    ],
    "action_items": [
        "Important concept to revise",
        "Practice question or activity"
    ]
}}

Rules:
1. Use simple and understandable language.
2. Preserve important technical terms.
3. Do not invent information not present in the material.
4. Make the summary useful for examination preparation.
5. Return valid JSON only.

STUDY MATERIAL:

{source_text}
"""

    errors = []

    for model in GEMINI_MODELS:

        try:
            logger.info("Trying Gemini model: %s", model)

            generated_text = call_gemini(model, prompt)

            # Remove Markdown code fences if returned.
            generated_text = generated_text.strip()

            if generated_text.startswith("```"):
                generated_text = generated_text.replace(
                    "```json", ""
                ).replace("```", "").strip()

            result = json.loads(generated_text)

            required_fields = [
                "summary",
                "key_points",
                "action_items"
            ]

            for field in required_fields:
                if field not in result:
                    raise ValueError(
                        f"Missing field: {field}"
                    )

            if not isinstance(result["key_points"], list):
                raise ValueError(
                    "key_points must be a list."
                )

            if not isinstance(result["action_items"], list):
                raise ValueError(
                    "action_items must be a list."
                )

            logger.info(
                "Successfully generated notes using %s",
                model
            )

            return result

        except Exception as error:

            error_message = str(error)

            logger.error(
                "Gemini model %s failed: %s",
                model,
                error_message
            )

            errors.append(
                f"{model}: {error_message}"
            )

    logger.error(
        "All Gemini models failed: %s",
        "; ".join(errors)
    )

    raise RuntimeError(
        "All available Gemini models failed. "
        "Check the VS Code terminal for the detailed API error."
    )


# --------------------------------------------------
# HOME PAGE
# --------------------------------------------------

@app.route("/")
def home():

    if "user_id" in session:

        if session.get("role") == "admin":
            return redirect("/admin/")

        return redirect("/dashboard")

    return render_template("auth.html")


# --------------------------------------------------
# LOGIN PAGE
# --------------------------------------------------

@app.route("/login")
def login():

    if "user_id" in session:

        if session.get("role") == "admin":
            return redirect("/admin/")

        return redirect("/dashboard")

    return render_template("auth.html")


# --------------------------------------------------
# STUDENT DASHBOARD
# --------------------------------------------------

@app.route("/dashboard")
@student_required
def dashboard():

    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:

            cursor.execute(
                "SELECT COUNT(*) AS total FROM notes WHERE user_id = %s",
                (session["user_id"],)
            )
            total_notes = cursor.fetchone()["total"]

            cursor.execute(
                "SELECT COUNT(*) AS total FROM quizzes WHERE user_id = %s",
                (session["user_id"],)
            )
            total_quizzes = cursor.fetchone()["total"]

            cursor.execute(
                "SELECT COUNT(*) AS total FROM flashcards WHERE user_id = %s",
                (session["user_id"],)
            )
            total_flashcards = cursor.fetchone()["total"]

            cursor.execute(
                """
                SELECT AVG(score) AS average_score
                FROM quiz_attempts
                WHERE user_id = %s
                """,
                (session["user_id"],)
            )
            result = cursor.fetchone()

            average_score = result["average_score"] or 0

        return render_template(
            "student_dashboard.html",
            user_name=session.get("user_name", "Student"),
            total_notes=total_notes,
            total_quizzes=total_quizzes,
            average_score=round(float(average_score), 2),
            total_flashcards=total_flashcards
        )

    except Exception:
        logger.exception("Student dashboard failed")
        flash("Unable to load dashboard.", "error")
        return render_template(
            "student_dashboard.html",
            user_name=session.get("user_name", "Student"),
            total_notes=0,
            total_quizzes=0,
            average_score=0,
            total_flashcards=0
        )

    finally:
        connection.close()


# --------------------------------------------------
# NOTES PAGE
# --------------------------------------------------

@app.route("/notes")
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

    except Exception:
        logger.exception("Loading notes failed")
        flash("Unable to load your notes.", "error")

        return render_template(
            "notes.html",
            notes=[]
        )

    finally:
        connection.close()


# --------------------------------------------------
# GENERATE NOTES
# --------------------------------------------------

@app.route("/notes/generate", methods=["POST"])
@student_required
def generate_notes():

    title = request.form.get("title", "").strip()
    source_text = request.form.get("source_text", "").strip()

    uploaded_file = request.files.get("study_file")

    # Read uploaded TXT file.
    if uploaded_file and uploaded_file.filename:

        if not uploaded_file.filename.lower().endswith(".txt"):
            flash(
                "Only TXT files are supported currently.",
                "error"
            )
            return redirect(url_for("notes"))

        try:
            file_content = uploaded_file.read().decode(
                "utf-8",
                errors="replace"
            )

            source_text = file_content.strip()

        except Exception:
            flash("Unable to read the uploaded file.", "error")
            return redirect(url_for("notes"))

    if not title:
        title = "Untitled Study Notes"

    if not source_text:
        flash("Please enter or upload study material.", "error")
        return redirect(url_for("notes"))

    if len(source_text) > 30000:
        flash(
            "Study material is too long. Maximum allowed is 30,000 characters.",
            "error"
        )
        return redirect(url_for("notes"))

    # Generate AI content.
    try:
        ai_result = generate_ai_content(source_text)

    except Exception as error:

        logger.exception("AI notes generation failed")

        flash(
            "AI note generation failed. Check the VS Code terminal for details.",
            "error"
        )

        return redirect(url_for("notes"))

    # Save generated notes in MySQL.
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO notes
                (
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

        flash("Your AI notes were generated successfully!", "success")

        return redirect(url_for("notes"))

    except Exception:

        connection.rollback()

        logger.exception("Saving generated notes failed")

        flash(
            "Notes were generated but could not be saved to the database.",
            "error"
        )

        return redirect(url_for("notes"))

    finally:
        connection.close()


# --------------------------------------------------
# VIEW INDIVIDUAL NOTE
# --------------------------------------------------

@app.route("/notes/<int:note_id>")
@student_required
def view_note(note_id):

    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT *
                FROM notes
                WHERE id = %s AND user_id = %s
                """,
                (note_id, session["user_id"])
            )

            note = cursor.fetchone()

        if not note:
            flash("Note not found.", "error")
            return redirect(url_for("notes"))

        try:
            note["key_points"] = json.loads(
                note["key_points"] or "[]"
            )
        except (TypeError, json.JSONDecodeError):
            note["key_points"] = []

        try:
            note["action_items"] = json.loads(
                note["action_items"] or "[]"
            )
        except (TypeError, json.JSONDecodeError):
            note["action_items"] = []

        return render_template(
            "note_detail.html",
            note=note
        )

    except Exception:
        logger.exception("Opening note failed")
        flash("Unable to open this note.", "error")
        return redirect(url_for("notes"))

    finally:
        connection.close()


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout")
def logout():

    session.clear()

    flash("You have been logged out.", "success")

    return redirect(url_for("login"))


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.route("/health")
def health():

    return jsonify({
        "status": "running",
        "application": "NotePilot",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


# --------------------------------------------------
# DATABASE CHECK
# --------------------------------------------------

@app.route("/db-check")
def db_check():

    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE() AS database_name")
            result = cursor.fetchone()

        return jsonify({
            "status": "connected",
            "database": result["database_name"]
        })

    except Exception as error:

        logger.exception("Database connection failed")

        return jsonify({
            "status": "error",
            "message": str(error)
        }), 500

    finally:
        if connection:
            connection.close()


# --------------------------------------------------
# FILE SIZE ERROR
# --------------------------------------------------

@app.errorhandler(413)
def file_too_large(error):

    flash("Uploaded file is too large. Maximum size is 5 MB.", "error")

    return redirect(url_for("notes"))


# --------------------------------------------------
# APPLICATION START
# --------------------------------------------------

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
